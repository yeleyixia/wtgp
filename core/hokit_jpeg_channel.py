# -*- coding: utf-8 -*-
"""
HoKit 同款 JPEG 截图流通道

原理（与 HoKit 的 JpegCastingChannel 一致）：
  1. 把 agent.so（uitest 扩展）推送到 /data/local/tmp/agent.so
  2. 启动 `uitest start-daemon singleness`（守护进程自动加载 agent.so）
  3. hdc fport 把本地端口转发到设备 localabstract:uitest_socket
  4. 走 UITest RPC 协议发送 startCaptureScreen 请求（module=com.ohos.devicetest.hypiumApiHelper）
  5. agent 持续用 Rosen DisplayManager 截图 + libjpeg 编码，把 JPEG 帧推回

实测（华为畅享 90 Pro Max / OpenHarmony 6.1.1.125）：
  scale=0.5 时稳定约 7 fps（画面静止也能持续出帧）
  scale=0.99 时只有约 0.4 fps（截图+JPEG 编码耗时约 2.5s/张）

注：agent.so 来自 HoKit 安装目录（resources/assets/tools/so），原文件是
AES-256-CBC 加密的，本项目资源目录里存放的是解密后的明文 ELF。
替换/升级时可用同款密钥解密新版，或后续自研同协议扩展替代。
"""

import json
import os
import random
import socket
import struct
import subprocess
import threading
import time
from typing import Optional


MSG_HEAD = b"_uitestkit_rpc_message_head_"
MSG_TAIL = b"_uitestkit_rpc_message_tail_"
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"

DAEMON_PATH = "/data/local/tmp/agent.so"
DAEMON_CMD = "uitest start-daemon singleness"
ABSTRACT_SOCKET = "uitest_socket"
UITEST_TCP_PORT = 8012


def _resource_base() -> str:
    """定位本项目 resources 目录（兼容开发模式与打包模式）。"""
    candidates = []
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), "resources"))
    if getattr(__import__("sys"), "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(__import__("sys").executable))
        candidates.append(os.path.join(exe_dir, "resources"))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


def pick_agent_so(abi: str, protocol_v2: bool) -> Optional[str]:
    """根据 ABI 与协议版本选择本地 agent.so 路径。"""
    base = os.path.join(_resource_base(), "tools", "so")
    candidates = []
    if abi and ("arm64" in abi or "aarch64" in abi):
        candidates.append(os.path.join(base, "arm64-v8a", "agent_v2.so" if protocol_v2 else "agent_v1.so"))
    candidates.append(os.path.join(base, "x86_64", "agent.so"))
    candidates.append(os.path.join(base, "arm64-v8a", "agent_v2.so"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


class HokitJpegChannel:
    """管理 agent 推送、daemon、端口转发与 JPEG 帧接收。"""

    def __init__(self, hdc_path: str, device_id: str, scale: float = 0.5):
        self.hdc_path = hdc_path
        self.device_id = device_id
        self.scale = scale
        self.local_port = 0
        self._forward_target = ""
        self._sock: Optional[socket.socket] = None
        self._buf = b""
        self._lock = threading.Lock()
        self._started = False

    # ---------------- 基础工具 ----------------
    def _run_hdc(self, args, timeout=15):
        cmd = [self.hdc_path] + args
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            r = subprocess.run(
                cmd, capture_output=True, timeout=timeout,
                creationflags=creationflags,
            )
            return r.returncode, r.stdout.decode("utf-8", "replace").strip(), r.stderr.decode("utf-8", "replace").strip()
        except Exception as e:
            return -1, "", str(e)

    def _shell(self, cmd, timeout=15):
        return self._run_hdc(["shell", cmd], timeout=timeout)

    def _device_abi(self) -> str:
        code, out, _ = self._shell("param get const.product.cpu.abilist")
        return out or ""

    def _device_protocol_v2(self) -> bool:
        code, out, _ = self._shell("uitest --version", timeout=20)
        # HoKit 判定: 版本 > 6.0.2.1 使用 v2
        try:
            ver = out.strip().split()[-1]
            parts = [int(x) for x in ver.split(".")]
            return parts >= [6, 0, 2, 1] if len(parts) >= 3 else True
        except Exception:
            return True

    def _daemon_running(self) -> bool:
        """检测 uitest daemon 是否在跑（避免 pgrep 自匹配误判）。"""
        code, out, _ = self._shell('ps -ef | grep "uitest start-daemon" | grep -v grep', timeout=10)
        return bool(out.strip())

    def _agent_daemon_running(self) -> bool:
        """检测 agent 专属 daemon 是否在跑。

        agent daemon 命令为 `uitest start-daemon singleness`（无
        --extension-name，默认加载 agent.so），因此命令行不含
        scrcpy_server.so 的 daemon 均视为 agent 的。
        """
        code, out, _ = self._shell('ps -ef | grep "uitest start-daemon" | grep -v grep', timeout=10)
        for line in out.splitlines():
            if "scrcpy_server.so" in line:
                continue  # 是 h264 通道的 daemon
            return True
        return False

    def _kill_other_daemons(self):
        """杀掉非 agent 的 uitest daemon（singleness 单实例冲突修复）。

        `uitest start-daemon singleness` 全局单实例：残留 scrcpy_server.so
        的 daemon 时，agent.so 启动会被复用旧 daemon，uitest_socket
        不出现导致等待超时。仅杀含 scrcpy_server.so 的 daemon，
        agent 自身的（无 extension / agent.so）保留复用。
        """
        _, out, _ = self._shell('ps -ef | grep "uitest start-daemon" | grep -v grep', timeout=10)
        killed = False
        for line in out.splitlines():
            if "scrcpy_server.so" not in line:
                continue  # agent 自己的 daemon，保留
            # ps -ef 固定列：第 2 列恒为 PID（POSIX），首列 USER 可能是
            # 数字 UID（OpenHarmony app uid 10000 常见），不能按"第一个
            # 数字字段"取。取 parts[1] 并回查 /proc/<pid>/cmdline 复核
            # 确为 uitest daemon 才杀，防误杀任意进程。
            parts = line.split()
            if len(parts) < 2 or not parts[1].isdigit():
                continue
            pid = int(parts[1])
            if pid <= 1:
                continue
            _, cl, _ = self._shell(f"cat /proc/{pid}/cmdline 2>/dev/null", timeout=5)
            if "uitest" not in (cl or ""):
                continue  # /proc 复核不匹配，跳过
            self._shell(f"kill -9 {pid}", timeout=10)
            killed = True
        if killed:
            time.sleep(0.3)

    def _wait_uitest_socket(self, v2: bool, timeout: float = 8.0) -> bool:
        """等待设备端 uitest_socket 抽象套接字就绪。"""
        target = "uitest" if v2 else f":{8012}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if v2:
                _, out, _ = self._shell("cat /proc/net/unix | grep uitest", timeout=10)
                if out.strip():
                    return True
            else:
                _, out, _ = self._shell("netstat -tln | grep 8012", timeout=10)
                if out.strip():
                    return True
            time.sleep(0.2)
        return False

    # ---------------- 生命周期 ----------------
    def start(self) -> bool:
        """推送 agent、启动 daemon、建立转发并开始截图流。"""
        abi = self._device_abi()
        v2 = self._device_protocol_v2()
        local_so = pick_agent_so(abi, v2)
        if not local_so:
            raise RuntimeError("未找到 agent.so 资源文件，请检查 resources/tools/so 目录")

        # 1) 推送 agent（每次覆盖推送，600KB 约 40ms，避免版本残留问题）
        rc, _, err = self._run_hdc(["file", "send", local_so, DAEMON_PATH], timeout=30)
        if rc != 0:
            raise RuntimeError(f"推送 agent.so 失败: {err}")
        self._shell("chmod 755 " + DAEMON_PATH)

        # 2) 确保 daemon 归属本通道（singleness 单实例冲突修复），复用或启动
        self._kill_other_daemons()
        if not self._agent_daemon_running():
            self._shell(DAEMON_CMD, timeout=20)
            time.sleep(1.0)
            if not self._agent_daemon_running():
                raise RuntimeError("uitest start-daemon 启动失败")

        # 2.5) 等待 RPC 套接字就绪（失败自愈：杀 daemon 重启一次再等，
        # 覆盖"旧 daemon 内存中仍是旧 agent.so"的资源升级场景）
        if not self._wait_uitest_socket(self._device_protocol_v2()):
            _, out, _ = self._shell('ps -ef | grep "uitest start-daemon" | grep -v grep', timeout=10)
            for line in out.splitlines():
                # ps -ef 固定列：第 2 列恒为 PID；回查 /proc 复核确为 uitest daemon
                parts = line.split()
                if len(parts) < 2 or not parts[1].isdigit():
                    continue
                pid = int(parts[1])
                if pid <= 1:
                    continue
                _, cl, _ = self._shell(f"cat /proc/{pid}/cmdline 2>/dev/null", timeout=5)
                if "uitest" not in (cl or ""):
                    continue
                self._shell(f"kill -9 {pid}", timeout=10)
            time.sleep(0.5)
            self._shell(DAEMON_CMD, timeout=20)
            time.sleep(1.0)
            if not self._wait_uitest_socket(self._device_protocol_v2()):
                raise RuntimeError("等待 uitest_socket 超时")

        # 3) 端口转发
        if not self._forward():
            raise RuntimeError("端口转发失败")

        # 4) 建立连接并请求截图流（先 stop 再 start，与 HoKit 一致）
        ok = self._open_stream()
        if not ok:
            self._remove_forward()
            raise RuntimeError("建立截图流失败")
        self._started = True
        return True

    def _forward(self) -> bool:
        v2 = self._device_protocol_v2()
        target = f"localabstract:{ABSTRACT_SOCKET}" if v2 else f"tcp:{UITEST_TCP_PORT}"
        for _ in range(2):
            port = random.randint(20000, 50000)
            rc, out, err = self._run_hdc(
                ["fport", f"tcp:{port}", target],
                timeout=15,
            )
            if rc == 0 and "OK" in out.upper():
                if self.local_port and self._forward_target:
                    self._run_hdc(
                        ["fport", "rm", f"tcp:{self.local_port}", self._forward_target],
                        timeout=10,
                    )
                self.local_port = port
                self._forward_target = target
                return True
        return False

    def _remove_forward(self):
        if self.local_port and self._forward_target:
            self._run_hdc(
                ["fport", "rm", f"tcp:{self.local_port}", self._forward_target],
                timeout=10,
            )
        self.local_port = 0
        self._forward_target = ""

    # ---------------- RPC 请求 ----------------
    @staticmethod
    def _build_request(api: str, **args) -> bytes:
        payload = {
            "module": "com.ohos.devicetest.hypiumApiHelper",
            "method": "Captures",
            "params": {"api": api, "args": args},
        }
        body = json.dumps(payload).encode("utf-8")
        sid = random.randint(0, 0xFFFFFFFF)
        return MSG_HEAD + struct.pack(">II", sid, len(body)) + body + MSG_TAIL

    def _open_stream(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(3)
            self._sock.connect(("127.0.0.1", self.local_port))
            # 与 HoKit 一致：先 stop，稍等，再 start
            self._sock.sendall(self._build_request("stopCaptureScreen"))
            time.sleep(0.2)
            self._sock.sendall(self._build_request(
                "startCaptureScreen",
                options={"displayId": 0, "scale": self.scale},
            ))
            return True
        except Exception:
            try:
                if self._sock:
                    self._sock.close()
            except Exception:
                pass
            self._sock = None
            return False

    # ---------------- 帧读取 ----------------
    def read_frame(self, timeout: float = 2.0) -> Optional[bytes]:
        """返回一帧完整 JPEG 数据；超时返回 None。"""
        if not self._sock:
            return None
        deadline = time.time() + timeout
        self._sock.settimeout(max(0.1, timeout))
        while time.time() < deadline:
            # 先看看缓冲区里有没有完整帧
            frame, consumed = self._extract_jpeg(self._buf)
            if frame is not None:
                self._buf = self._buf[consumed:]
                return frame
            # 收数据
            try:
                data = self._sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return None
            if not data:
                return None
            self._buf += data
        # 最后再查一次
        frame, consumed = self._extract_jpeg(self._buf)
        if frame is not None:
            self._buf = self._buf[consumed:]
        return frame

    def _extract_jpeg(self, buf: bytes):
        """从缓冲提取一帧 JPEG，兼容裸流与 UITest 协议包两种封装。"""
        # 裸 JPEG 流：FFD8 ... FFD9
        idx = buf.find(JPEG_SOI)
        if idx != -1:
            eoi = buf.find(JPEG_EOI, idx + 2)
            if eoi != -1:
                return buf[idx:eoi + 2], eoi + 2
        # 协议包封装：HEAD + sid(4) + len(4) + body + TAIL
        hidx = buf.find(MSG_HEAD)
        if hidx != -1 and hidx <= 64:
            if len(buf) >= hidx + len(MSG_HEAD) + 8:
                ln = struct.unpack(">I", buf[hidx + len(MSG_HEAD) + 4:hidx + len(MSG_HEAD) + 8])[0]
                total = hidx + len(MSG_HEAD) + 8 + ln + len(MSG_TAIL)
                if len(buf) >= total:
                    body = buf[hidx + len(MSG_HEAD) + 8: hidx + len(MSG_HEAD) + 8 + ln]
                    if body.startswith(JPEG_SOI) and JPEG_EOI in body:
                        eoi = body.find(JPEG_EOI)
                        return body[:eoi + 2], total
                    # 协议包（JSON 响应等）直接消费掉
                    return None, total
        return None, 0

    def stop(self):
        try:
            if self._sock:
                try:
                    self._sock.sendall(self._build_request("stopCaptureScreen"))
                except Exception:
                    pass
                try:
                    self._sock.close()
                except Exception:
                    pass
        finally:
            self._sock = None
            self._remove_forward()
            self._started = False

    @property
    def started(self) -> bool:
        return self._started

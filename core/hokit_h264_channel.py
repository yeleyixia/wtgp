# -*- coding: utf-8 -*-
"""
HoKit 同款 H.264 投屏通道（scrcpy_server.so + gRPC 流）

原理（与 HoKit 的 H264CastingChannel 一致）：
  1. 把解密后的 scrcpy_server.so 推送到 /data/local/tmp/scrcpy_server.so
  2. 启动 `uitest start-daemon singleness --extension-name scrcpy_server.so
     -scale X -frameRate F -bitRate B -p 9958 ...`
  3. hdc fport 转发到设备 localabstract:scrcpy_grpc_socket（协议 v2）
     （旧协议为 tcp:9958）
  4. gRPC：先调 onEnd 复位，再 onStart 拉流；帧数据在
     ReplyMessage.payload["data"].val_bytes（Annex-B H.264）
  5. 画面静止时编码器不产帧：用 uinput 鼠标微移"软刺激"保持编码器活跃

实测（华为畅享 90 Pro Max / OpenHarmony 6.1.1.125）：
  scale=2(50%) + frameRate=30 + bitrate=10MB/s 时流畅可用的 H.264 流，
  HoKit 在该设备上即以此模式运行（日志: 模式: h264, 分辨率 564x1222）。

注意：scrcpy_server.so 来自 HoKit 安装目录，原文件为 AES-256-CBC 加密，
本项目 resources 中存放解密后的明文 ELF。
"""

import os
import queue
import random
import subprocess
import threading
import time
from typing import Optional

import grpc

try:
    from core.hokit_grpc import scrcpy_pb2 as pb2
    from core.hokit_grpc import scrcpy_pb2_grpc as pb2_grpc
except ImportError:
    pb2 = None
    pb2_grpc = None


SCRCPY_PORT = 9958
REMOTE_SO = "/data/local/tmp/scrcpy_server.so"
ABSTRACT_SOCKET = "scrcpy_grpc_socket"


def _resource_base() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(here), "resources"),
    ]
    if getattr(__import__("sys"), "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(__import__("sys").executable))
        candidates.append(os.path.join(exe_dir, "resources"))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


def _so_md5(path: str) -> str:
    """计算本地 so 文件 MD5（带缓存）。"""
    try:
        import hashlib
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def pick_screencopy_so(abi: str, protocol_v2: bool) -> Optional[str]:
    """按 ABI 与协议版本选择本地 scrcpy_server.so（兼容接口，返回首选）。"""
    cands = pick_screencopy_so_candidates(abi, protocol_v2)
    return cands[0][0] if cands else None


def pick_screencopy_so_candidates(abi: str, protocol_v2: bool):
    """
    按 ABI 与协议版本返回全部可用 scrcpy_server.so 候选（HoKit 同款多版本回退）。

    返回 [(path, md5), ...]，优先级：
      1. 本 ABI 目录下协议对应版本（v2/v1）
      2. 本 ABI 目录下另一协议版本（回退）
      3. x86_64 兜底
    """
    base = os.path.join(_resource_base(), "tools", "so")
    dirs = []
    if abi and ("arm64" in abi or "aarch64" in abi):
        dirs.append("arm64-v8a")
    dirs.append("x86_64")
    wanted = "screencopy_v2.so" if protocol_v2 else "screencopy_v1.so"
    fallback = "screencopy_v1.so" if protocol_v2 else "screencopy_v2.so"
    paths = []
    for d in dirs:
        dpath = os.path.join(base, d)
        for name in (wanted, fallback, "screencopy.so"):
            p = os.path.join(dpath, name)
            if os.path.isfile(p) and p not in paths:
                paths.append(p)
    return [(p, _so_md5(p)) for p in paths]


# 模块级成功缓存（HoKit successfulSoCache）：key = "<abi目录>_<v1|v2>"
_SUCCESSFUL_SO_CACHE: dict = {}


class HokitH264Channel:
    """管理 scrcpy_server.so 推送、daemon、gRPC 拉流与软刺激。"""

    def __init__(
        self,
        hdc_path: str,
        device_id: str,
        scale: int = 2,          # HoKit 语义: 1=100%, 2=50%
        frame_rate: int = 30,
        bitrate_mbps: int = 10,
        screen_id: int = 0,
        repeat_interval: int = 16,  # repeatInterval ms：编码器重复发送间隔（16=60FPS，33=30FPS）
    ):
        self.hdc_path = hdc_path
        self.device_id = device_id
        self.scale = max(1, int(scale))
        self.frame_rate = max(5, min(120, int(frame_rate)))
        self.bitrate_mbps = max(1, int(bitrate_mbps))
        self.screen_id = max(0, int(screen_id))  # clamp（安全审查 LOW：防拼入 shell）
        self.repeat_interval = max(8, min(100, int(repeat_interval)))
        self.local_port = 0
        self._forward_target = ""
        self._grpc_channel = None
        self._stub = None
        self._stream = None
        self._q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=64)
        self._feeder = None
        self._started = False

    # ---------------- 基础工具 ----------------
    def _run_hdc(self, args, timeout=15):
        cmd = [self.hdc_path] + args
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            r = subprocess.run(
                cmd, capture_output=True, timeout=timeout, creationflags=creationflags,
            )
            return r.returncode, r.stdout.decode("utf-8", "replace").strip(), r.stderr.decode("utf-8", "replace").strip()
        except Exception as e:
            return -1, "", str(e)

    def _shell(self, cmd, timeout=15):
        return self._run_hdc(["shell", cmd], timeout=timeout)

    def _device_abi(self) -> str:
        _, out, _ = self._shell("param get const.product.cpu.abilist")
        return out or ""

    def _device_protocol_v2(self) -> bool:
        _, out, _ = self._shell("uitest --version", timeout=20)
        try:
            ver = out.strip().split()[-1]
            parts = [int(x) for x in ver.split(".")]
            return parts >= [6, 0, 2, 1] if len(parts) >= 3 else True
        except Exception:
            return True

    def _scrcpy_running(self) -> bool:
        """检测 scrcpy daemon 是否在跑（避免 pgrep 自匹配误判）。"""
        _, out, _ = self._shell('ps -ef | grep scrcpy_server.so | grep -v grep', timeout=10)
        for line in out.splitlines():
            if "uitest" in line and "scrcpy_server.so" in line:
                return True
        return False

    def _kill_other_daemons(self):
        """杀掉非本通道的 uitest daemon（singleness 单实例冲突修复）。

        设备端 `uitest start-daemon singleness` 全局单实例：若残留
        agent.so（或其它 extension）的 daemon，scrcpy_server.so 启动时
        会被 singleness 复用旧 daemon 而失败。启动前确保 daemon 归属本通道。
        """
        _, out, _ = self._shell('ps -ef | grep "uitest start-daemon" | grep -v grep', timeout=10)
        killed = False
        for line in out.splitlines():
            if "scrcpy_server.so" in line:
                continue  # 自己的 daemon，保留（复用）
            # ps -ef 固定列：第 2 列恒为 PID（POSIX），首列 USER 可能是
            # 数字 UID；取 parts[1] 并回查 /proc/<pid>/cmdline 复核确为
            # uitest daemon 才杀，防误杀任意进程。
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
            killed = True
        # 仅在有清理动作时等待（避免无谓的数百 ms 延迟）
        if killed:
            time.sleep(0.3)

    def _kill_scrcpy_daemons(self):
        """杀掉所有 scrcpy daemon（kill -9，避免 pkill 权限问题）。"""
        _, out, _ = self._shell('ps -ef | grep scrcpy_server.so | grep -v grep', timeout=10)
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
        time.sleep(0.3)

    # ---------------- 生命周期 ----------------
    def start(self) -> bool:
        if pb2 is None or pb2_grpc is None:
            raise RuntimeError("缺少 grpc/protobuf 依赖，请安装 grpcio")
        abi = self._device_abi()
        v2 = self._device_protocol_v2()
        candidates = pick_screencopy_so_candidates(abi, v2)
        if not candidates:
            raise RuntimeError("未找到 scrcpy_server.so 资源，请检查 resources/tools/so 目录")

        key = self._cache_key(abi, v2)
        last_err = None

        # 1) 设备已有 so 且 MD5 与本地候选匹配 → 直接启动（免推送，秒开）
        dev_md5 = self._device_so_md5()
        if dev_md5:
            for path, md5 in candidates:
                if md5 == dev_md5:
                    if self._try_daemon(v2):
                        _SUCCESSFUL_SO_CACHE[key] = md5
                        return self._finish_start(v2)
                    break  # 设备文件能匹配但启动失败，走推送流程

        # 2) 成功缓存优先，逐个推送 + 启动（HoKit successfulSoCache 逻辑）
        ordered = sorted(candidates, key=lambda c: c[1] != _SUCCESSFUL_SO_CACHE.get(key))
        for path, md5 in ordered:
            try:
                self._push_so(path)
                if self._try_daemon(v2):
                    _SUCCESSFUL_SO_CACHE[key] = md5
                    return self._finish_start(v2)
            except RuntimeError as e:
                last_err = e
        raise RuntimeError(f"所有 scrcpy_server.so 均启动失败: {last_err}")

    def _finish_start(self, v2: bool) -> bool:
        """daemon 就绪后的收尾：端口转发 → gRPC 拉流 → 唤醒/刺激。"""
        if not self._forward(v2):
            raise RuntimeError("端口转发失败")
        self._connect_grpc(v2)
        self._kick_start()
        self._started = True
        # 与 HoKit 一致：启动后唤醒屏幕并微移鼠标触发编码器出帧
        self.wake()
        self.stimulate()
        return True

    def _cache_key(self, abi: str, v2: bool) -> str:
        d = "arm64-v8a" if (abi and ("arm64" in abi or "aarch64" in abi)) else "x86_64"
        return f"{d}_{'v2' if v2 else 'v1'}"

    def _device_so_md5(self) -> str:
        """查询设备端已存在的 scrcpy_server.so MD5（不存在返回空串）。"""
        _, out, _ = self._shell(f"md5sum {REMOTE_SO} 2>/dev/null", timeout=10)
        parts = out.split()
        if parts and len(parts[0]) == 32:
            return parts[0].lower()
        return ""

    def _push_so(self, local_so: str):
        """推送并安装指定 so（先清理旧 daemon 与旧文件，避免占用）。"""
        self._kill_scrcpy_daemons()
        self._shell(f"rm -f {REMOTE_SO}", timeout=10)
        rc, _, err = self._run_hdc(["file", "send", local_so, REMOTE_SO], timeout=30)
        if rc != 0:
            rc, _, err = self._run_hdc(["file", "send", local_so, REMOTE_SO], timeout=30)
        if rc != 0:
            raise RuntimeError(f"推送 scrcpy_server.so 失败: {err}")
        self._shell("chmod 755 " + REMOTE_SO)

    def _try_daemon(self, v2: bool) -> bool:
        """确保 daemon 在跑且 RPC 套接字就绪；失败则自愈重启一次。"""
        # IDR 间隔：下限 1000ms。IDR 越密集，参考链异常时恢复越快、
        # 滑动结束后画面越快回到完全清晰（带宽代价可接受）。
        iframe = max(1000, round(60000 / self.frame_rate))
        params = (
            f"-scale {self.scale} -frameRate {self.frame_rate} "
            f"-bitRate {self.bitrate_mbps * 1024 * 1024} -p {SCRCPY_PORT} "
            f"-screenId {self.screen_id} -encodeType 0 "
            f"-iFrameInterval {iframe} -repeatInterval {self.repeat_interval}"
        )
        # 确保 daemon 归属本通道（singleness 单实例冲突修复）
        self._kill_other_daemons()
        if not self._scrcpy_running():
            cmd = f"uitest start-daemon singleness --extension-name scrcpy_server.so {params}"
            self._shell(cmd, timeout=20)
            for _ in range(40):
                if self._scrcpy_running():
                    break
                time.sleep(0.2)
            if not self._scrcpy_running():
                return False

        # 等待 RPC 套接字就绪（过早建转发会错过首包，导致空流）
        if not self._wait_rpc_socket(v2):
            # 自愈：重启一次 daemon 再等
            self._kill_scrcpy_daemons()
            self._shell(
                f"uitest start-daemon singleness --extension-name scrcpy_server.so {params}",
                timeout=20,
            )
            if not self._wait_rpc_socket(v2):
                return False
        return True

    def _wait_rpc_socket(self, v2: bool, timeout: float = 8.0) -> bool:
        """等待设备端 RPC 套接字出现（协议 v2 为抽象套接字，v1 为 tcp:9958）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if v2:
                _, out, _ = self._shell("cat /proc/net/unix | grep scrcpy", timeout=10)
                if out.strip():
                    return True
            else:
                _, out, _ = self._shell("netstat -tln | grep 9958", timeout=10)
                if out.strip():
                    return True
            time.sleep(0.2)
        return False

    def _forward(self, v2: bool) -> bool:
        target = f"localabstract:{ABSTRACT_SOCKET}" if v2 else f"tcp:{SCRCPY_PORT}"
        for _ in range(2):
            port = random.randint(20000, 50000)
            rc, out, _ = self._run_hdc(["fport", f"tcp:{port}", target], timeout=15)
            if rc == 0 and "OK" in out.upper():
                # 记录当前规则，供 stop() 时删除
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

    def _connect_grpc(self, v2: bool):
        host = "127.0.0.1"
        self._grpc_channel = grpc.insecure_channel(
            f"{host}:{self.local_port}",
            options=[
                ("grpc.max_receive_message_length", 10 * 1024 * 1024),
                ("grpc.max_send_message_length", 10 * 1024 * 1024),
                ("grpc.keepalive_time_ms", 2147483647),
                ("grpc.keepalive_permit_without_calls", 0),
            ],
        )
        self._stub = pb2_grpc.ScrcpyServiceStub(self._grpc_channel)
        # onEnd 复位编码器（HoKit connect 流程）
        try:
            self._stub.onEnd(pb2.Empty(), timeout=2)
        except Exception:
            pass
        self._stream = self._stub.onStart(pb2.Empty())
        self._feeder = threading.Thread(target=self._feed, daemon=True)
        self._feeder.start()

    def _feed(self):
        try:
            for msg in self._stream:
                try:
                    pv = msg.payload.get("data")
                except Exception:
                    pv = None
                if pv is not None and pv.WhichOneof("values") == "val_bytes":
                    data = pv.val_bytes
                    # 帧元数据（scrcpy demuxer 格式）：flags 高 2 位 = CONFIG/KEY_FRAME
                    # 必须随 data 传递，否则 PacketMerger 无法识别 config 包缓存
                    # SPS/PPS，解码缺参数集导致 0 帧（e2e/实机诊断确认）。
                    flags = 0
                    fv = msg.payload.get("flags")
                    if fv is not None and fv.WhichOneof("values") == "val_int":
                        flags = int(fv.val_int)
                    if data:
                        try:
                            self._q.put((bytes(data), flags), timeout=0.5)
                        except queue.Full:
                            # 丢旧保新：队满时弹出最旧包，保留最新（低延迟优先）
                            try:
                                self._q.get_nowait()
                                self._q.put((bytes(data), flags), timeout=0.5)
                            except Exception:
                                pass
        except Exception:
            pass
        finally:
            try:
                self._q.put(None, timeout=0.5)
            except queue.Full:
                pass

    def qsize(self) -> int:
        """当前积压包数（供上层做 burst 跳帧决策）。"""
        return self._q.qsize()

    def drain_to_latest(self, keep: int = 1) -> Optional[tuple]:
        """
        排空积压队列，只保留最新包（burst 跳帧）。

        返回 (data, pts_flags) 或 None。
        """
        try:
            while self._q.qsize() > keep:
                self._q.get_nowait()
            if self._q.empty():
                return None
            return self._q.get_nowait()
        except Exception:
            return None

    def take_available(self, max_n: int = 512) -> list:
        """
        按顺序取走当前积压的全部包（**不丢包**，保持 GOP 顺序）。

        与 drain_to_latest 的"丢旧保新"相反：上层要逐包送解码器
        维持参考链（丢 P 帧 = 残影），只是中间包不做像素转换。

        :param max_n: 单次最多取走的包数（安全上限）
        :return: [(data, pts_flags), ...]；若遇到流结束哨兵 None，
                 将哨兵放回队列（让主循环下次 read_packet 感知）并停止。
        """
        items = []
        try:
            while len(items) < max_n:
                item = self._q.get_nowait()
                if item is None:
                    # 流结束哨兵：放回，主循环下轮 read_packet 拿到后退出
                    try:
                        self._q.put_nowait(None)
                    except Exception:
                        pass
                    break
                items.append(item)
        except Exception:  # queue.Empty 等
            pass
        return items

    def _wait_data(self, timeout: float) -> bool:
        """等待队列中出现数据。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._q.qsize() > 0:
                return True
            time.sleep(0.1)
        return False

    def _restart_stream(self):
        """取消当前流并重新 onEnd → onStart（对应 HoKit restartStream）。"""
        try:
            if self._stream is not None:
                self._stream.cancel()
        except Exception:
            pass
        # 先等旧 feeder 退出（其 finally 可能 put(None) 终止哨兵），
        # 再排空队列，避免哨兵残留在重启后的流中导致 read_packet 返回 None
        if self._feeder is not None:
            self._feeder.join(timeout=2)
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        try:
            self._stub.onEnd(pb2.Empty(), timeout=2)
        except Exception:
            pass
        self._stream = self._stub.onStart(pb2.Empty())
        self._feeder = threading.Thread(target=self._feed, daemon=True)
        self._feeder.start()

    def _kick_start(self):
        """初次拉流激活：刺激 + IDR；若仍无数据则重启流一次。"""
        try:
            self.stimulate()
            self.request_idr()
        except Exception:
            pass
        if not self._wait_data(1.5):
            try:
                self._restart_stream()
                self.stimulate()
                self.request_idr()
            except Exception:
                pass
            self._wait_data(1.5)

    # ---------------- 对外接口 ----------------
    def read_packet(self, timeout: float = 2.0) -> Optional[tuple]:
        """取一包 H.264 数据（可能含多帧 NAL）。

        返回 (data, pts_flags)：pts_flags 高位含 CONFIG/KEY_FRAME 标志，
        供 PacketMerger 缓存/合并 SPS/PPS（缺失则解码 0 帧）。
        超时但流仍在返回 b""（falsy，消费端按无数据处理）；
        流结束返回 None。
        """
        try:
            item = self._q.get(timeout=timeout)
        except queue.Empty:
            return b""  # 超时但流仍在
        if item is None:
            self._started = False
        return item

    def request_idr(self):
        """请求设备立即输出 IDR 关键帧（不打断当前流）。"""
        if self._stub is None:
            return
        try:
            self._stub.onRequestIDRFrame(pb2.Empty(), timeout=2)
        except Exception:
            pass

    def stimulate(self):
        """uinput 鼠标微移，触发画面变化让编码器产帧。"""
        a = random.randint(1, 10)
        b = random.randint(1, 10)
        c = random.randint(1, 10)
        d = random.randint(1, 10)
        self._shell(f"uinput -M -m {a} {b} {c} {d} 300", timeout=10)

    def wake(self):
        self._shell("power-shell wakeup", timeout=10)

    def stop(self):
        self._started = False
        try:
            if self._stream is not None:
                try:
                    self._stream.cancel()
                except Exception:
                    pass
                self._stream = None
        except Exception:
            pass
        if self._feeder is not None:
            self._feeder.join(timeout=2)
            self._feeder = None
        if self._stub is not None:
            try:
                self._stub.onEnd(pb2.Empty(), timeout=2)
            except Exception:
                pass
            self._stub = None
        if self._grpc_channel is not None:
            try:
                self._grpc_channel.close()
            except Exception:
                pass
            self._grpc_channel = None
        self._remove_forward()
        # 与 HoKit 一致：会话结束主动清理 scrcpy daemon
        try:
            self._kill_scrcpy_server()
        except Exception:
            pass

    def _kill_scrcpy_server(self):
        self._kill_scrcpy_daemons()

    @property
    def started(self) -> bool:
        return self._started

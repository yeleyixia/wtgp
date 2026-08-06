import subprocess
import os
import shutil
import re
import sys
import time
from typing import List, Optional, Tuple
from PySide6.QtCore import QThread, Signal, QObject


def find_base_dir() -> str:
    """自动检测项目根目录，兼容开发模式和多种打包器"""
    candidates = []

    # PyInstaller
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates.append(sys._MEIPASS)

    # Nuitka / 其他打包器：sys.executable 所在目录（onefile 临时解压目录）
    candidates.append(os.path.dirname(sys.executable))

    # sys.argv[0] 所在目录（原始 exe 路径）
    candidates.append(os.path.dirname(os.path.abspath(sys.argv[0])))

    # 开发模式
    candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    for path in candidates:
        if path and os.path.isdir(os.path.join(path, "resources", "tools", "hdc")):
            return path
    return candidates[-1]


BASE_DIR = find_base_dir()
TOOLS_DIR = os.path.join(BASE_DIR, "resources", "tools")


def find_hdc() -> str:
    hdc_paths = [
        os.path.join(TOOLS_DIR, "hdc", "hdc.exe"),
        os.path.join(TOOLS_DIR, "hdc", "hdc"),
    ]
    for path in hdc_paths:
        if os.path.exists(path):
            return path
    system_hdc = shutil.which("hdc")
    if system_hdc:
        return system_hdc
    return "hdc"


class HDCClient(QObject):
    device_found = Signal(str, str)
    device_lost = Signal(str)
    devices_updated = Signal(list)
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hdc_path = find_hdc()
        self._devices: dict = {}

    def run_hdc(self, args: List[str], timeout: int = 10) -> Tuple[int, str, str]:
        cmd = [self.hdc_path] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except FileNotFoundError:
            return -1, "", "HDC not found"
        except Exception as e:
            return -1, "", str(e)

    def list_devices(self) -> List[Tuple[str, str]]:
        code, stdout, stderr = self.run_hdc(["list", "targets"])
        if code != 0:
            self.log_message.emit(f"HDC list error: {stderr}")
            return []

        devices = []
        for line in stdout.split("\n"):
            line = line.strip()
            if not line or line.startswith("["):
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))
            elif len(parts) == 1:
                devices.append((parts[0], "device"))

        self.devices_updated.emit(devices)
        return devices

    def get_device_info(self, device_id: str) -> dict:
        """获取 HarmonyOS 设备详细信息（HoKit 同款合并命令：一次 shell 拉全部字段）。

        单条 shell 内用 `echo __marker__` 标记分隔各字段，避免逐个
        `param get` 子进程开销（设备轮询时明显更快）。"""
        info = {"id": device_id, "status": "device"}

        # HoKit DeviceInfoProvider.PARAM_KEYS 同款：key → marker
        markers = [
            ("const.product.name", "name"),
            ("const.product.model", "model"),
            ("const.product.software.version", "swver"),
            ("const.product.cpu.abilist", "abi"),
            ("const.product.devicetype", "devtype"),
            ("const.ohos.apiversion", "apiver"),
        ]
        parts = []
        for key, marker in markers:
            parts.append(f"echo __{marker}__")
            parts.append(f"param get {key}")
        parts.append("echo __udid__")
        parts.append("bm get -u")
        parts.append("echo __end__")
        cmd = "; ".join(parts)

        code, stdout, stderr = self.run_hdc(
            ["-t", device_id, "shell", cmd],
            timeout=15,
        )
        sections = {}
        if code == 0 and stdout:
            marker = None
            lines = (stdout or "").splitlines()
            for line in lines:
                s = line.strip()
                if s.startswith("__") and s.endswith("__") and s[2:-2] in (
                        "name", "model", "swver", "abi", "devtype", "apiver", "udid", "end"):
                    marker = s[2:-2]
                    sections[marker] = []
                elif marker is not None and marker != "end":
                    if s and not s.lower() in ("error", "false", "none", "null"):
                        sections[marker].append(s)
                    else:
                        sections[marker].append("")

        def _sec(marker: str) -> str:
            return "\n".join(sections.get(marker, [])).strip()

        name = _sec("name")
        if not name:
            name = ""
        if name.startswith("HUAWEI "):
            name = name[7:]  # HoKit 同款：去掉 HUAWEI 前缀
        if name:
            info["name"] = name
            info["name_short"] = name

        model = _sec("model")
        if model:
            info["model"] = model
            info.setdefault("name", model)
            info.setdefault("name_short", model)

        version = _sec("swver")
        if not version:
            version = ""
        # 版本号提取（HoKit 同款：取 x.y.z.w 部分）
        import re as _re
        vm = _re.search(r"(\d+\.\d+\.\d+\.\d+)", version)
        if vm:
            version = vm.group(1)
        if version:
            info["version"] = version

        abi = _sec("abi")
        if abi:
            info["abi"] = abi
        devtype = _sec("devtype")
        if devtype:
            info["devtype"] = devtype
        apiver = _sec("apiver")
        if apiver:
            info["apiver"] = apiver

        udid = _sec("udid")
        if udid:
            # bm get -u 输出类似 "udid of current device is :\n<64位hex>"，提取 hex
            import re as _re2
            m = _re2.search(r"[0-9A-Fa-f]{32,64}", udid)
            if m:
                udid = m.group(0)
            if udid and not udid.startswith("{"):
                info["udid"] = udid

        # 分辨率：优先使用 hidumper 获取渲染分辨率
        code, stdout, stderr = self.run_hdc(
            ["-t", device_id, "shell", "hidumper", "-s", "RenderService", "-a", "screen"],
            timeout=8,
        )
        if code == 0 and stdout:
            # 匹配 "render resolution=1128x2444"
            res_match = re.search(r"render resolution=(\d+)x(\d+)", stdout)
            if res_match:
                info["resolution"] = f"{res_match.group(1)}x{res_match.group(2)}"
            else:
                # 回退到 physical resolution
                res_match = re.search(r"physical resolution=(\d+)x(\d+)", stdout)
                if res_match:
                    info["resolution"] = f"{res_match.group(1)}x{res_match.group(2)}"

        # 若 hidumper 未获取到，回退到 wm size
        if "resolution" not in info:
            code, stdout, stderr = self.run_hdc(
                ["-t", device_id, "shell", "wm", "size"], timeout=5
            )
            if code == 0 and stdout:
                size_match = re.search(r"(\d+)x(\d+)", stdout)
                if size_match:
                    info["resolution"] = f"{size_match.group(1)}x{size_match.group(2)}"

        # 电量：bms dump Battery
        try:
            code, stdout, stderr = self.run_hdc(
                ["-t", device_id, "shell", "bms", "dump", "Battery"], timeout=5
            )
            if code == 0 and stdout:
                battery_match = re.search(r"level:\s*(\d+)", stdout)
                if battery_match:
                    info["battery"] = int(battery_match.group(1))
        except Exception:
            pass

        return info

    def connect_device(self, ip: str, port: int = 5555) -> bool:
        code, stdout, stderr = self.run_hdc(["tconn", f"{ip}:{port}"])
        return code == 0

    def disconnect_device(self, device_id: str) -> bool:
        code, stdout, stderr = self.run_hdc(["tdconn", device_id])
        return code == 0

    def send_touch(self, device_id: str, x: int, y: int, action: str) -> bool:
        if action == "down":
            code, _, _ = self.run_hdc(["-t", device_id, "shell", "uinput", "-T", "-d", str(x), str(y)])
        elif action == "move":
            code, _, _ = self.run_hdc(["-t", device_id, "shell", "uinput", "-T", "-m", str(x), str(y), str(x), str(y)])
        else:
            code, _, _ = self.run_hdc(["-t", device_id, "shell", "uinput", "-T", "-u", str(x), str(y)])
        return code == 0

    def send_key(self, device_id: str, key_code: int) -> bool:
        key_map = {
            2007: "276",
            2003: "102",
            2049: "254",
            2076: "116",
            2058: "115",
            2059: "114",
            2060: "113",
        }
        key_name = key_map.get(key_code, str(key_code))
        self.run_hdc(["-t", device_id, "shell", "uinput", "-K", "-d", key_name])
        time.sleep(0.02)
        code, _, _ = self.run_hdc(["-t", device_id, "shell", "uinput", "-K", "-u", key_name])
        return code == 0

    def send_swipe(self, device_id: str, x: int, y: int, delta_y: int) -> bool:
        end_y = max(0, y - delta_y)
        # uinput -T -g 要求 press_time >= 500ms 且 total_time - press_time >= 500ms
        code, _, _ = self.run_hdc([
            "-t", device_id, "shell", "uinput", "-T", "-g",
            str(x), str(y), str(x), str(end_y), "500", "1000"
        ])
        return code == 0

    def wake_screen(self, device_id: str) -> bool:
        code, stdout, stderr = self.run_hdc([
            "-t", device_id, "shell", "powerctrl", "wakeup"
        ])
        return code == 0

    def take_screenshot(self, device_id: str, save_path: str) -> bool:
        remote_path = "/data/local/tmp/screenshot.jpeg"
        code, stdout, stderr = self.run_hdc([
            "-t", device_id, "shell", "snapshot_display", "-f", remote_path
        ])
        if code != 0:
            return False

        code, stdout, stderr = self.run_hdc([
            "-t", device_id, "file", "recv", remote_path, save_path
        ])
        if code != 0:
            return False

        self.run_hdc(["-t", device_id, "shell", "rm", remote_path])
        return True

    def get_screen_size(self, device_id: str) -> Tuple[int, int]:
        # 优先使用 hidumper 获取渲染分辨率
        code, stdout, stderr = self.run_hdc(
            ["-t", device_id, "shell", "hidumper", "-s", "RenderService", "-a", "screen"],
            timeout=8,
        )
        if code == 0 and stdout:
            res_match = re.search(r"render resolution=(\d+)x(\d+)", stdout)
            if res_match:
                return int(res_match.group(1)), int(res_match.group(2))
            res_match = re.search(r"physical resolution=(\d+)x(\d+)", stdout)
            if res_match:
                return int(res_match.group(1)), int(res_match.group(2))
        # 回退：wm size
        code, stdout, stderr = self.run_hdc(["-t", device_id, "shell", "wm", "size"])
        if code == 0:
            match = re.search(r"(\d+)x(\d+)", stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
        # 最终回退：通过 snapshot_display 输出解析分辨率
        code, stdout, stderr = self.run_hdc([
            "-t", device_id, "shell", "snapshot_display", "-f", "/data/local/tmp/_probe.jpeg"
        ])
        if code == 0:
            w_match = re.search(r"width:\s*(\d+)", stdout)
            h_match = re.search(r"height:\s*(\d+)", stdout)
            if w_match and h_match:
                self.run_hdc(["-t", device_id, "shell", "rm", "/data/local/tmp/_probe.jpeg"])
                return int(w_match.group(1)), int(h_match.group(1))
            # 解析失败也清理探测文件，避免设备端残留
            self.run_hdc(["-t", device_id, "shell", "rm", "/data/local/tmp/_probe.jpeg"])
        return 1080, 2400


class DeviceMonitor(QThread):
    device_changed = Signal(list)

    def __init__(self, hdc_client: HDCClient, parent=None):
        super().__init__(parent)
        self.hdc = hdc_client
        self._running = True

    def run(self):
        while self._running:
            devices = self.hdc.list_devices()
            self.device_changed.emit(devices)
            self.msleep(2000)

    def stop(self):
        self._running = False
        self.wait(3000)

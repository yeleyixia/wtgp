#!/usr/bin/env python3
"""为投个屏 - 功能测试脚本
测试 HDC 截图、输入、设备信息等核心功能
"""
import subprocess
import time
import os
import sys

HDC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "tools", "hdc", "hdc.exe")

def run_hdc(args, timeout=10):
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    cmd = [HDC_PATH] + args
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace',
                            timeout=timeout, creationflags=creationflags)
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def test_device_list():
    """测试1: 设备发现"""
    code, stdout, stderr = run_hdc(["list", "targets"])
    assert code == 0, f"HDC list targets failed: {stderr}"
    devices = [l.strip() for l in stdout.split("\n") if l.strip() and not l.startswith("[")]
    assert len(devices) > 0, "No devices found"
    print(f"[PASS] 设备发现: {devices}")
    return devices[0]

def test_device_info(device_id):
    """测试2: 设备信息"""
    params = [
        ("const.product.name", "名称"),
        ("const.product.model", "型号"),
        ("const.ohos.fullname", "版本"),
    ]
    for param, label in params:
        code, stdout, _ = run_hdc(["-t", device_id, "shell", "param", "get", param])
        assert code == 0 and stdout, f"Failed to get {param}"
        print(f"[PASS] {label}: {stdout}")

def test_screen_size(device_id):
    """测试3: 屏幕分辨率"""
    import re
    code, stdout, _ = run_hdc(["-t", device_id, "shell", "hidumper", "-s", "RenderService", "-a", "screen"], timeout=8)
    assert code == 0, "hidumper failed"
    match = re.search(r"render resolution=(\d+)x(\d+)", stdout)
    assert match, f"Cannot parse resolution from: {stdout[:200]}"
    print(f"[PASS] 分辨率: {match.group(1)}x{match.group(2)}")

def test_screenshot(device_id):
    """测试4: 截图功能"""
    remote = "/data/local/tmp/test_func.jpeg"
    code, stdout, _ = run_hdc(["-t", device_id, "shell", "snapshot_display", "-f", remote])
    assert code == 0, f"Screenshot failed: {stdout}"
    assert "success" in stdout, f"Screenshot not successful: {stdout}"

    # 验证文件存在
    code, stdout, _ = run_hdc(["-t", device_id, "shell", "ls", "-la", remote])
    assert code == 0 and ".jpeg" in stdout, "Screenshot file not found"

    # 下载到本地
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_screenshot.jpeg")
    code, _, _ = run_hdc(["-t", device_id, "file", "recv", remote, local])
    assert code == 0, "File recv failed"
    assert os.path.exists(local), "Local file not created"
    size = os.path.getsize(local)
    assert size > 10000, f"Screenshot too small: {size} bytes"
    print(f"[PASS] 截图: {size} bytes")

    # 清理
    run_hdc(["-t", device_id, "shell", "rm", remote])
    try:
        os.remove(local)
    except Exception:
        pass

def test_touch(device_id):
    """测试5: 触摸点击"""
    code, stdout, _ = run_hdc(["-t", device_id, "shell", "uinput", "-T", "-c", "564", "1222"])
    assert code == 0, f"Touch click failed: {stdout}"
    print(f"[PASS] 触摸点击: (564, 1222)")

def test_key(device_id):
    """测试6: 按键"""
    code, _, _ = run_hdc(["-t", device_id, "shell", "uinput", "-K", "-d", "276"])
    assert code == 0, "Key down failed"
    time.sleep(0.05)
    code, _, _ = run_hdc(["-t", device_id, "shell", "uinput", "-K", "-u", "276"])
    assert code == 0, "Key up failed"
    print(f"[PASS] 按键: 276 (电源键)")

def test_battery(device_id):
    """测试7: 电池信息"""
    import re
    code, stdout, _ = run_hdc(["-t", device_id, "shell", "hidumper", "-s", "BatteryService", "-a", "-i"], timeout=8)
    assert code == 0, "BatteryService hidumper failed"
    match = re.search(r"capacity:\s*(\d+)", stdout)
    assert match, f"Cannot parse battery capacity"
    print(f"[PASS] 电池: {match.group(1)}%")

def test_memory(device_id):
    """测试8: 内存信息"""
    import re
    code, stdout, _ = run_hdc(["-t", device_id, "shell", "cat", "/proc/meminfo"])
    assert code == 0, "meminfo failed"
    total = re.search(r"MemTotal:\s+(\d+)", stdout)
    avail = re.search(r"MemAvailable:\s+(\d+)", stdout)
    assert total and avail, "Cannot parse meminfo"
    used_mb = (int(total.group(1)) - int(avail.group(1))) / 1024
    print(f"[PASS] 内存: {used_mb:.0f} MB used")

def test_file_list(device_id):
    """测试9: 文件列表"""
    code, stdout, _ = run_hdc(["-t", device_id, "shell", "ls", "/data/local/tmp/"])
    assert code == 0, "ls failed"
    files = [l for l in stdout.split("\n") if l.strip()]
    assert len(files) > 0, "No files found"
    print(f"[PASS] 文件列表: {len(files)} items")

def test_base64_screenshot(device_id):
    """测试10: Base64截图管道"""
    import base64
    remote = "/data/local/tmp/sc_b64.jpeg"
    cmd = f"snapshot_display -f {remote} 2>/dev/null && echo B64_START && base64 {remote}"
    code, stdout, _ = run_hdc(["-t", device_id, "shell", cmd], timeout=10)
    assert code == 0, "Base64 screenshot failed"
    idx = stdout.find("B64_START")
    assert idx >= 0, "B64_START marker not found"
    b64_data = stdout[idx + len("B64_START"):].strip().replace("\n", "").replace("\r", "").replace(" ", "")
    assert len(b64_data) > 64, f"Base64 data too short: {len(b64_data)}"
    jpeg_bytes = base64.b64decode(b64_data)
    assert jpeg_bytes[:2] == b'\xff\xd8', "Invalid JPEG header"
    print(f"[PASS] Base64截图: {len(jpeg_bytes)} bytes JPEG")

if __name__ == "__main__":
    print("=" * 50)
    print("为投个屏 - 功能测试")
    print("=" * 50)
    print()

    try:
        device_id = test_device_list()
        print()
        test_device_info(device_id)
        print()
        test_screen_size(device_id)
        print()
        test_screenshot(device_id)
        print()
        test_touch(device_id)
        print()
        test_key(device_id)
        print()
        test_battery(device_id)
        print()
        test_memory(device_id)
        print()
        test_file_list(device_id)
        print()
        test_base64_screenshot(device_id)
        print()
        print("=" * 50)
        print("全部测试通过!")
        print("=" * 50)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

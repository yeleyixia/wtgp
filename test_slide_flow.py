# -*- coding: utf-8 -*-
"""
主动滑动 + 窗口同步监测：量化操作流畅度

- 设备端通过 hdc uinput 执行真实滑动序列（down → 10 个 move → up）
- 同步以 ~10Hz 抓取投屏窗口画面，记录每帧时间戳与差异
- 输出：滑动期间画面变化率(估算 FPS)、首帧变化延迟、总变化量

用法: python test_slide_flow.py [device_id]
"""
import sys
import os
import time
import json
import subprocess
import ctypes
from ctypes import wintypes
import numpy as np
from PIL import ImageGrab

ROOT = os.path.dirname(os.path.abspath(__file__))
HDC = os.path.join(ROOT, "resources", "tools", "hdc", "hdc.exe")
DEVICE = sys.argv[1] if len(sys.argv) > 1 else "6UNBB26324009125"

user32 = ctypes.windll.user32


def find_window(title_part):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if title_part in buf.value and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return found


def get_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def hdc_shell(cmd, timeout=15):
    try:
        r = subprocess.run(
            [HDC, "-t", DEVICE, "shell", cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode, r.stdout
    except Exception as e:
        return -1, str(e)


def swipe(x1, y1, x2, y2, steps=12, duration=0.35):
    """设备端真实滑动（uinput down/move/up 序列）"""
    hdc_shell(f"uinput -T -d {x1} {y1}")
    n = max(steps, 2)
    for i in range(1, n):
        x = x1 + (x2 - x1) * i // n
        y = y1 + (y2 - y1) * i // n
        hdc_shell(f"uinput -T -m {x} {y}")
        time.sleep(duration / n)
    hdc_shell(f"uinput -T -u {x2} {y2}")


def main():
    wins = find_window("为投个屏")
    if not wins:
        print("[slide] ❌ 未找到投屏窗口", flush=True)
        return 1
    hwnd = wins[0]
    print(f"[slide] 窗口 hwnd={hwnd} 开始 3 轮滑动测试...", flush=True)

    # 预取一帧作基线
    bbox = get_rect(hwnd)
    prev = np.asarray(ImageGrab.grab(bbox).convert("RGB").resize((48, 96)),
                      dtype=np.float32)

    for round_i in range(3):
        # 等画面稳定（静止基线）
        time.sleep(2.0)
        bbox = get_rect(hwnd)
        base = np.asarray(ImageGrab.grab(bbox).convert("RGB").resize((48, 96)),
                          dtype=np.float32)

        t0 = time.time()
        changed_frames = 0
        first_change_lag = None
        samples = 0
        # 滑动 + 采样并行
        import threading
        stop = {"done": False}
        results = []

        def sampler():
            prev_s = base.copy()
            while not stop["done"]:
                try:
                    b = get_rect(hwnd)
                    cur = np.asarray(ImageGrab.grab(b).convert("RGB").resize((48, 96)),
                                     dtype=np.float32)
                    diff = float(np.abs(cur - prev_s).mean())
                    now = time.time() - t0
                    results.append((now, diff))
                    prev_s = cur
                except Exception:
                    pass
                time.sleep(0.09)

        th = threading.Thread(target=sampler, daemon=True)
        th.start()

        # 设备端滑动（一轮 3 次快速滑动）
        for k in range(3):
            swipe(560, 1800, 560, 600, steps=12, duration=0.3)

        time.sleep(0.8)
        stop["done"] = True
        th.join(timeout=2)

        # 分析
        active = [(ts, d) for ts, d in results if d > 1.5]
        total_change = sum(d for _, d in results)
        if active:
            first_change_lag = active[0][0]
            # 变化率：活动时段内采样变化次数 / 时长
            span = active[-1][0] - active[0][0]
            rate = len(active) / max(span, 0.001)
        else:
            span = 0.0
            rate = 0.0
        print(f"[slide] 轮{round_i+1}: 变化帧={len(active)}/{len(results)} "
              f"总变化量={total_change:.1f} "
              f"首变延迟={('%.2fs' % first_change_lag) if first_change_lag is not None else '无变化'}"
              f" 活动跨度={span:.2f}s 变化率≈{rate:.1f}/s", flush=True)
        if first_change_lag is not None and first_change_lag > 1.5:
            print(f"[slide]    ⚠️ 首变延迟 {first_change_lag:.2f}s —— 操作响应偏慢", flush=True)

    print("[slide] 完成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

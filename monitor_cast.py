# -*- coding: utf-8 -*-
"""
投屏窗口实时监测工具

用法: python monitor_cast.py [duration_sec]
- 查找标题含"为投个屏"的投屏窗口
- 循环抓取窗口画面，分析:
  1. 活动检测: 相邻采样差异 -> 画面变化频率(估算 FPS)
  2. 残影检测: 窗口边缘黑边区域颜色稳定性(应保持深色背景)
  3. 卡顿检测: 活动期间帧更新间隔(>250ms 计为一次卡顿)
- 每 2 秒输出一行状态(JSON)到 stdout; Ctrl+C 停止
"""
import sys
import os
import time
import json
import ctypes
from ctypes import wintypes
import numpy as np
from PIL import ImageGrab

user32 = ctypes.windll.user32


def find_window(title_part):
    """按标题子串查找窗口句柄（递归枚举顶层窗口）"""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if title_part in buf.value and user32.IsWindowVisible(hwnd):
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def get_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    print(f"[monitor] 查找投屏窗口（标题含'为投个屏'）...", flush=True)
    wins = find_window("为投个屏")
    if not wins:
        print("[monitor] ❌ 未找到投屏窗口，请先启动投屏", flush=True)
        return 1
    hwnd, title = wins[0]
    print(f"[monitor] 找到窗口: '{title}' hwnd={hwnd}", flush=True)

    # 上一采样缩略图（64x128 灰度，快）
    prev = None
    prev_time = 0.0
    prev_corners = None
    last_change = 0.0
    changes = 0
    stalls = 0
    fps_est = 0.0
    corner_drift_max = 0.0
    corner_bright_max = 0.0
    last_report = time.time()
    t0 = time.time()

    while time.time() - t0 < duration:
        try:
            bbox = get_rect(hwnd)
            if bbox[2] - bbox[0] < 50 or bbox[3] - bbox[1] < 50:
                time.sleep(0.5)
                continue
            img = ImageGrab.grab(bbox)
            arr = np.asarray(img.convert("L"), dtype=np.float32)
            if arr.size == 0:
                continue
            small = np.asarray(img.convert("RGB").resize((64, 128)), dtype=np.float32)
            now = time.time()

            if prev is not None:
                # 活动检测：差异 > 阈值（缩略图均差）
                diff = float(np.abs(small - prev).mean())
                if diff > 1.5:
                    changes += 1
                    gap = now - last_change
                    if last_change > 0 and gap > 0.25:
                        stalls += 1  # 卡顿：变化间隔 > 250ms
                    last_change = now
                # 残影参考：窗口四角 6x6 区域亮度（KeepAspectRatio 下
                # 角部最可能为背景黑边；画面占满时角部为画面内容）
                h, w = arr.shape
                corners = [
                    arr[2:8, 2:8].mean(),
                    arr[2:8, w-8:w-2].mean(),
                    arr[h-8:h-2, 2:8].mean(),
                    arr[h-8:h-2, w-8:w-2].mean(),
                ]
                # 四角亮度最大与最小之差：画面内容（高对比）vs 纯黑边（接近）
                corner_spread = max(corners) - min(corners)
                corner_bright = max(corners)
                # 相邻采样间四角区域变化（残影会随帧更新残留旧内容）
                if prev_corners is not None:
                    corner_drift = max(
                        abs(corners[i] - prev_corners[i]) for i in range(4)
                    )
                else:
                    corner_drift = 0.0
                prev_corners = corners
                # 帧率估算：最近 2s 变化次数
                if now - last_report >= 2.0:
                    window = now - last_report
                    fps_est = changes / max(window, 0.001)
                    corner_drift_max = max(corner_drift_max, corner_drift)
                    corner_bright_max = max(corner_bright_max, corner_bright)
                    report = {
                        "t": round(now - t0, 1),
                        "fps_est": round(fps_est, 1),
                        "changes": changes,
                        "stalls": stalls,
                        "corner_bright": round(float(corner_bright), 0),
                        "corner_drift": round(float(corner_drift), 1),
                        "activity": "变化中" if now - last_change < 1.0 else "静止",
                    }
                    print(f"[monitor] {json.dumps(report, ensure_ascii=False)}", flush=True)
                    changes = 0
                    last_report = now
            prev = small
            prev_time = now
            time.sleep(0.1)  # 10Hz 采样
        except Exception as e:
            print(f"[monitor] 采样异常: {e}", flush=True)
            time.sleep(1.0)

    # 汇总
    print(f"[monitor] 结束: 卡顿={stalls} 角部漂移峰值={corner_drift_max:.1f} "
          f"角部亮度峰值={corner_bright_max:.0f} 总时长={time.time()-t0:.1f}s", flush=True)
    print("[monitor] 角部漂移大 = 窗口边缘有内容变化（可能是画面占满或残影）；"
          "角部稳定且为深色 = 正常黑边", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

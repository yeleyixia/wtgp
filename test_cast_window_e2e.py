# -*- coding: utf-8 -*-
"""独立投屏窗口真机端到端：启动投屏 → 帧到达/帧率 → 触控 → 关闭"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

app = QApplication.instance() or QApplication(sys.argv)

DEVICE_ID = "6UNBB26324009125"
from core.hdc_cast_service import HDCCastService
from core.input_manager import InputManager
from core.audio_manager import AudioManager
from ui.cast_window import CastWindow

svc = HDCCastService()
win = CastWindow(svc, svc, InputManager(), AudioManager())

# 让 UI 事件循环跑起来的定时器
app_timer = QTimer()
app_timer.start(50)

results = {}

def check_frames():
    results["frames"] = getattr(results, "frames", 0) + 1
    results["last_frame"] = win.phone_screen._frame is not None
    results["fps_text"] = win.title_bar.fps_label.text()

t0 = time.time()
win.start_casting(DEVICE_ID)
print(f"[e2e] 启动投屏返回（{time.time()-t0:.2f}s）")
assert win._is_casting, "投屏未启动"
print(f"[e2e] 独立窗口已显示: {win.isVisible()}")

# 事件循环运行 ~15s，期间统计帧
deadline = time.time() + 15
frame_ticks = 0
while time.time() < deadline:
    app.processEvents()
    if win.phone_screen._frame is not None:
        frame_ticks += 1
    time.sleep(0.02)

# 打开设置页并持续滚动制造画面变化，统计真实帧率
svc.run_hdc(["-t", DEVICE_ID, "shell",
             "aa start -b com.huawei.hmos.settings -a com.huawei.hmos.settings.MainAbility"], timeout=10)
time.sleep(1.0)

def _scroll():
    svc.run_hdc(["-t", DEVICE_ID, "shell", "uinput -T -d 564 1700"], timeout=10)
    for i in range(1, 5):
        y = 1700 + (700 - 1700) * i // 4
        svc.run_hdc(["-t", DEVICE_ID, "shell", f"uinput -T -m 564 1700 564 {y} 10"], timeout=10)
        time.sleep(0.08)
    svc.run_hdc(["-t", DEVICE_ID, "shell", "uinput -T -u 564 700"], timeout=10)

frames_seen = 0
versions = set()
t_end = time.time() + 6
last_scroll = time.time()
while time.time() < t_end:
    app.processEvents()
    if time.time() - last_scroll >= 1.0:
        _scroll()
        last_scroll = time.time()
    if win.phone_screen._frame is not None:
        frames_seen += 1
        versions.add(svc.frame_version)
    time.sleep(0.02)

print(f"[e2e] 15s 内画布有帧的 tick 数: {frame_ticks}")
print(f"[e2e] 6s 滚动变化期: 渲染 tick={frames_seen}, 帧版本数={len(versions)}")
fps_text = win.title_bar.fps_label.text()
print(f"[e2e] 标题栏帧率: {fps_text}")

# 触控：发一次滑动（scrcpy 语义）
print("[e2e] 发送触控滑动...")
win._hdc_cast.send_touch(564, 1700, 0)
for y in range(1650, 799, -100):
    win._hdc_cast.send_touch(564, y, 2)
win._hdc_cast.send_touch(564, 800, 1)
time.sleep(1.0)
app.processEvents()

# 关闭
win.close()
app.processEvents()
print("[e2e] 窗口已关闭")

ok = frame_ticks > 100 and len(versions) > 10
print(f"[e2e] {'✅ 独立窗口投屏端到端正常' if ok else '❌ 帧数不足'}")
print(f"[e2e] 总结: 画布tick={frame_ticks}, 变化期帧版本={len(versions)}, 标题栏={fps_text}")
return_code = 0 if ok else 1
app_timer.stop()
sys.exit(return_code)

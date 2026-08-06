# -*- coding: utf-8 -*-
"""独立投屏窗口冒烟测试：布局/接线/信号"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

from core.hdc_cast_service import HDCCastService
from core.input_manager import InputManager
from core.audio_manager import AudioManager
from ui.cast_window import CastWindow

svc = HDCCastService()
im = InputManager()
am = AudioManager()
win = CastWindow(svc, svc, im, am)
win.show()
app.processEvents()

print(f"[win] 窗口尺寸: {win.width()}x{win.height()}")
assert win.width() > 300 and win.height() > 500, "窗口尺寸异常"

# 1. 标题栏
assert win.title_bar.title_label is not None
assert win.title_bar.fps_label.text() == "-- FPS"
print(f"[win] 标题栏 OK: {win.title_bar.title_label.text()} / {win.title_bar.fps_label.text()}")

# 2. 画布 + 工具栏
assert win.phone_screen is not None
assert win.toolbar is not None
print(f"[win] 画布+工具栏 OK")

# 3. 工具栏按键接线验证：模拟按钮点击 → 对应槽执行
sent_keys = []
win._send_key = lambda k: sent_keys.append(k)
for btn, expected in [
    (win.toolbar.back_clicked, 2007),
    (win.toolbar.home_clicked, 2003),
    (win.toolbar.recent_clicked, 2049),
    (win.toolbar.power_clicked, 2076),
    (win.toolbar.scroll_up_clicked, 2068),       # 新增：上滚 PageUp
]:
    btn.emit()
app.processEvents()
assert sent_keys == [2007, 2003, 2049, 2076, 2068], f"按键信号接线异常: {sent_keys}"
print(f"[win] 工具栏按键接线 OK: {sent_keys}")

# 4. FPS 更新
win._on_fps_updated(60)
assert win.toolbar.fps_label.text().find("60") >= 0 or "60" in win.toolbar.fps_label.text()
print(f"[win] FPS 更新 OK: {win.toolbar.fps_label.text()}")

# 5. 帧拉取（模拟一帧）
import numpy as np
frame = np.zeros((600, 300, 3), dtype=np.uint8)
win.phone_screen.set_frame(frame)
win.phone_screen.set_resolution(1128, 2444)
app.processEvents()
assert win.phone_screen._frame is not None
print(f"[win] 帧渲染 OK: {win.phone_screen._frame.shape}")

# 6. HoKit 同款新增按钮接线验证：触发对应信号不会被异常吞掉
print("[win] 验证 HoKit 同款新增按钮接线…")
# 用 monkey-patch 包裹每个 handler，确保 emit 后被调用
called = {}
orig_toggle_mode = win._toggle_cast_mode
orig_open_apps = win._open_app_drawer
orig_toggle_pinned = win._toggle_window_pinned
orig_toggle_fs = win._toggle_fullscreen
orig_brightness = win._show_brightness_dialog
win._toggle_cast_mode = lambda: called.setdefault("layers", True)
win._open_app_drawer = lambda: called.setdefault("apps", True)
win._toggle_window_pinned = lambda: called.setdefault("window", True)
win._toggle_fullscreen = lambda: called.setdefault("fullscreen", True)
win._show_brightness_dialog = lambda: called.setdefault("brightness", True)
win.toolbar.layers_clicked.emit()
win.toolbar.apps_clicked.emit()
win.toolbar.window_clicked.emit()
win.toolbar.fullscreen_clicked.emit()
win.toolbar.brightness_clicked.emit()
app.processEvents()
expected_called = {"layers", "apps", "window", "fullscreen", "brightness"}
assert expected_called.issubset(called.keys()), f"HoKit 新按钮接线缺失: {called}"
print(f"[win] HoKit 同款按钮接线 OK: {sorted(called.keys())}")

# 7. 关闭清理
win.close()
app.processEvents()
print("\n[win] ✅ 独立投屏窗口冒烟测试全部通过（含 HoKit 同款 6 个新按钮）")

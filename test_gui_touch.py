# -*- coding: utf-8 -*-
"""GUI 触控注入测试：QTest 模拟鼠标拖动 → 验证滑动命令序列"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, QPoint
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

# 避免模态弹窗阻塞测试：替换为打印
QMessageBox.warning = staticmethod(lambda *a, **kw: print("[dlg] warning:", a[1] if len(a) > 1 else a))
QMessageBox.critical = staticmethod(lambda *a, **kw: print("[dlg] critical:", a[1] if len(a) > 1 else a))
QMessageBox.information = staticmethod(lambda *a, **kw: print("[dlg] info:", a[1] if len(a) > 1 else a))

app = QApplication.instance() or QApplication(sys.argv)

DEVICE_ID = "6UNBB26324009125"
from core.hdc_cast_service import HDCCastService
from core.input_manager import InputManager
from core.audio_manager import AudioManager
from ui.cast_window import CastWindow

svc = HDCCastService()
win = CastWindow(svc, svc, InputManager(), AudioManager())
print("[gui-touch] 启动投屏...")
win.start_casting(DEVICE_ID)
print(f"[gui-touch] start_casting 返回, is_casting={win._is_casting}")
time.sleep(3)
app.processEvents()

# 设置画布分辨率（模拟真实投屏画面尺寸）
win.phone_screen.set_resolution(1128, 2444)
win.phone_screen.resize(300, 650)
win.phone_screen.set_frame(
    __import__("numpy").zeros((2444, 1128, 3), dtype="uint8")
)
app.processEvents()

# 记录 send_fn 收到的命令（monkeypatch ControlQueue）
sent = []
orig = svc._control_queue._send_fn
svc._control_queue._send_fn = lambda cmd: (sent.append(cmd) or True)

# 在画布中心按下并拖动（模拟鼠标滑动）
center = win.phone_screen.rect().center()
start = QPoint(center.x(), int(center.y() * 0.7))
end = QPoint(center.x(), int(center.y() * 0.3))

print(f"[gui-touch] 画布 rect={win.phone_screen.rect()}")
print(f"[gui-touch] 按下 ({start.x()},{start.y()}) → 拖动 → 释放 ({end.x()},{end.y()})")
t0 = time.time()
QTest.mousePress(win.phone_screen, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
app.processEvents()
# 多步 move
y = start.y()
step = (end.y() - start.y()) // 8
for i in range(8):
    y += step
    QTest.mouseMove(win.phone_screen, QPoint(start.x(), y), 30)
    app.processEvents()
    time.sleep(0.03)
QTest.mouseRelease(win.phone_screen, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
app.processEvents()
time.sleep(1.0)  # 等待 ControlQueue 发送完成
svc._control_queue._send_fn = orig

print(f"[gui-touch] 发送命令批数: {len(sent)}")
for s in sent[:6]:
    print(f"  {s[:120]}")
all_cmds = "; ".join(sent)
has_down = "uinput -T -d " in all_cmds
has_move = "-m " in all_cmds
has_up = "uinput -T -u " in all_cmds
print(f"[gui-touch] down={has_down} move={has_move} up={has_up}")
win.close()
app.processEvents()

if has_down and has_move and has_up:
    print("[gui-touch] ✅ GUI 鼠标拖动 → 完整滑动命令序列")
    sys.exit(0)
print("[gui-touch] ❌ 滑动命令缺失（GUI 链路问题）")
sys.exit(1)

# -*- coding: utf-8 -*-
"""端到端滑动验证：GUI 鼠标拖动 → 设备端画面实际变化 + 批数/延迟"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

QMessageBox.warning = staticmethod(lambda *a, **kw: print("[dlg] warning:", a[1] if len(a) > 1 else a))
QMessageBox.critical = staticmethod(lambda *a, **kw: print("[dlg] critical:", a[1] if len(a) > 1 else a))
QMessageBox.information = staticmethod(lambda *a, **kw: print("[dlg] info:", a[1] if len(a) > 1 else a))

app = QApplication.instance() or QApplication(sys.argv)

DEVICE_ID = "6UNBB26324009125"
HDC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "tools", "hdc", "hdc.exe")
from core.hdc_cast_service import HDCCastService
from core.input_manager import InputManager
from core.audio_manager import AudioManager
from ui.cast_window import CastWindow
import subprocess
import numpy as np
import cv2


def snap(path):
    subprocess.run([HDC, "-t", DEVICE_ID, "shell", f"snapshot_display -f {path}"],
                   capture_output=True, timeout=10)


def recv(remote, local):
    subprocess.run([HDC, "-t", DEVICE_ID, "file", "recv", remote, local],
                   capture_output=True, timeout=10)


svc = HDCCastService()
win = CastWindow(svc, svc, InputManager(), AudioManager())
print("[e2e-touch] 启动投屏...")
win.start_casting(DEVICE_ID)
print(f"[e2e-touch] is_casting={win._is_casting}")
time.sleep(4)
app.processEvents()

win.phone_screen.set_resolution(1128, 2444)
win.phone_screen.resize(360, 650)
win.phone_screen.set_frame(np.zeros((2444, 1128, 3), dtype="uint8"))
app.processEvents()

# 打开设置页（滑动有画面变化）
svc.run_hdc(["-t", DEVICE_ID, "shell",
             "aa start -b com.huawei.hmos.settings -a com.huawei.hmos.settings.MainAbility"], timeout=10)
time.sleep(2.0)
app.processEvents()

# 滑动前截图
snap("/data/local/tmp/et_before.jpeg")
time.sleep(0.5)

# 记录批命令
sent = []
orig = svc._control_queue._send_fn
svc._control_queue._send_fn = lambda cmd: (sent.append(cmd) or orig(cmd))

# GUI 拖动（模拟鼠标滑动）
center = win.phone_screen.rect().center()
start = QPoint(center.x(), int(center.y() * 0.75))
end = QPoint(center.x(), int(center.y() * 0.25))
t0 = time.time()
QTest.mousePress(win.phone_screen, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
app.processEvents()
y = start.y()
step = (end.y() - start.y()) // 8
for i in range(8):
    y += step
    QTest.mouseMove(win.phone_screen, QPoint(start.x(), y), 20)
    app.processEvents()
    time.sleep(0.02)
QTest.mouseRelease(win.phone_screen, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
app.processEvents()
send_dur = time.time() - t0
svc._control_queue._send_fn = orig

# 等待命令全部发到设备 + 画面更新
time.sleep(1.5)
snap("/data/local/tmp/et_after.jpeg")
time.sleep(0.3)

# 对比画面
recv("/data/local/tmp/et_before.jpeg", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reverse", "et_before.jpeg"))
recv("/data/local/tmp/et_after.jpeg", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reverse", "et_after.jpeg"))
a = cv2.imread(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reverse", "et_before.jpeg"))
b = cv2.imread(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reverse", "et_after.jpeg"))
if a is None or b is None:
    print("[e2e-touch] ❌ 截图读取失败")
else:
    diff = np.abs(a.astype(int) - b.astype(int)).mean()
    pct = (np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 10).mean()
    print(f"[e2e-touch] 画面变化: 平均差异={diff:.1f}, 变化占比={pct:.2%}")

print(f"[e2e-touch] 发送耗时={send_dur:.2f}s, 命令批数={len(sent)}")
for s in sent[:4]:
    print(f"  {s[:110]}")
all_cmds = "; ".join(sent)
print(f"[e2e-touch] down={'uinput -T -d ' in all_cmds} move={'-m ' in all_cmds} up={'uinput -T -u ' in all_cmds}")

win.close()
app.processEvents()
if pct > 0.05:
    print("[e2e-touch] ✅ GUI 拖动 → 设备画面实际滑动")
    sys.exit(0)
print("[e2e-touch] ❌ 设备画面未变化")
sys.exit(1)

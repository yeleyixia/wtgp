# -*- coding: utf-8 -*-
"""HoKit 同款侧边按钮真机端到端测试。

流程：启动投屏 → 验证帧到达 → 逐一点击 HoKit 同款侧边按钮验证信号接线
与后端处理 → 退出。

用 QTimer + app.exec() 驱动事件循环，保证脚本正常退出。
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt

app = QApplication.instance() or QApplication(sys.argv)

DEVICE_ID = os.environ.get("CAST_DEVICE", "6UNBB26324009125")

from core.hdc_cast_service import HDCCastService
from core.input_manager import InputManager
from core.audio_manager import AudioManager
from ui.cast_window import CastWindow

svc = HDCCastService()
im = InputManager()
am = AudioManager()
win = CastWindow(svc, svc, im, am)

results = {"frames": 0, "fps_text": "-- FPS", "errors": []}
phase = {"name": "start", "index": 0}
sent_keys = []

# 记录通过 _send_key 发送的键码（不真发到设备，避免干扰）
win._send_key = lambda k: sent_keys.append(k)

# 需要验证信号触发 → 键码的按钮
BUTTON_KEY_TESTS = [
    ("scroll_up_clicked", 2068),   # 上滚 PageUp
    ("home_clicked", 2003),
    ("recent_clicked", 2049),
    ("power_clicked", 2076),
    ("back_clicked", 2007),
]

# 需要验证 signal 触发但走非 send_key 路径的按钮
BUTTON_NONKEY_TESTS = [
    "layers_clicked",    # 分层（需 hdc 在投屏中，切换会重启，这里只验证接线无异常）
    "window_clicked",    # 悬浮窗（改窗口 flags，无害）
    "fullscreen_clicked",# 全屏（改窗口状态，无害）
    "brightness_clicked",# 亮度（会弹对话框，跳过实际 exec，只验证接线）
]

called_nonkey = {}


def step_start():
    """阶段1：启动投屏，等待帧到达"""
    global phase
    print("[e2e] 启动投屏…", flush=True)
    win.start_casting(DEVICE_ID)
    print(f"[e2e] is_casting={win._is_casting}", flush=True)
    if not win._is_casting:
        results["errors"].append("投屏未启动")
        app.quit()
        return
    phase = {"name": "wait_frames", "index": 0}


def step_wait_frames():
    """阶段2：等待帧到达并统计"""
    global phase
    if win.phone_screen._frame is not None:
        results["frames"] += 1
        results["fps_text"] = win.title_bar.fps_label.text()
    phase["index"] += 1
    # 等约 2 秒（每 tick 20ms）
    if phase["index"] >= 100:
        print(f"[e2e] 帧到达 ticks={results['frames']}, FPS={results['fps_text']}", flush=True)
        if results["frames"] == 0:
            results["errors"].append("未接收到任何帧")
        phase = {"name": "test_keys", "index": 0}


def step_test_keys():
    """阶段3：逐一点击导航类按钮，验证 send_key"""
    global phase
    i = phase["index"]
    if i < len(BUTTON_KEY_TESTS):
        name, key = BUTTON_KEY_TESTS[i]
        sent_keys.clear()
        getattr(win.toolbar, name).emit()
        app.processEvents()
        if sent_keys != [key]:
            results["errors"].append(f"{name} 期望键码 {key}, 实际 {sent_keys}")
        else:
            print(f"[e2e]   {name} -> 键码 {key} ✅", flush=True)
        phase["index"] += 1
        return
    phase = {"name": "test_nonkey", "index": 0}


def step_test_nonkey():
    """阶段4：验证非 send_key 类按钮接线（不 exec 亮度对话框）"""
    global phase
    i = phase["index"]
    if i < len(BUTTON_NONKEY_TESTS):
        name = BUTTON_NONKEY_TESTS[i]
        # 对 brightness 做打桩，避免弹出阻塞对话框
        if name == "brightness_clicked":
            win._show_brightness_dialog = lambda: called_nonkey.setdefault(name, True)
        try:
            getattr(win.toolbar, name).emit()
            app.processEvents()
            if name == "brightness_clicked":
                if not called_nonkey.get(name):
                    results["errors"].append(f"{name} 未触发")
                else:
                    print(f"[e2e]   {name} 触发 ✅", flush=True)
            else:
                print(f"[e2e]   {name} 触发 ✅", flush=True)
        except Exception as e:
            results["errors"].append(f"{name} 异常: {e}")
        phase["index"] += 1
        return
    phase = {"name": "finish", "index": 0}


def step_finish():
    """阶段5：关闭投屏，汇总结果"""
    print(f"[e2e] 关闭投屏…", flush=True)
    win.close()
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    print("[e2e] 关闭完成", flush=True)
    app.quit()


timer = QTimer()
timer.setInterval(20)
timer.timeout.connect(step_start)

# 分阶段用不同定时器回调
def _on_tick():
    p = phase["name"]
    if p == "start":
        step_start()
    elif p == "wait_frames":
        step_wait_frames()
    elif p == "test_keys":
        step_test_keys()
    elif p == "test_nonkey":
        step_test_nonkey()
    elif p == "finish":
        step_finish()


timer.timeout.connect(_on_tick)
timer.start()

# 5 秒看门狗
QTimer.singleShot(15000, app.quit)

app.exec()

print("\n===== 汇总 =====", flush=True)
print(f"帧到达 ticks: {results['frames']}", flush=True)
print(f"标题栏 FPS: {results['fps_text']}", flush=True)
if results["errors"]:
    print("❌ 存在错误:", flush=True)
    for e in results["errors"]:
        print(f"   - {e}", flush=True)
    sys.exit(1)
else:
    print("✅ HoKit 同款侧边按钮真机端到端测试全部通过", flush=True)
    sys.exit(0)

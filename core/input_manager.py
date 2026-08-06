import threading
import time
import ctypes
import sys
from typing import Optional, Dict, Callable, List
from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QClipboard


class InputManager(QObject):
    text_input = Signal(str)
    key_event = Signal(int, str)
    clipboard_changed = Signal(str)
    combo_key = Signal(list, int)

    MODIFIER_SHIFT = 1
    MODIFIER_CTRL = 2
    MODIFIER_ALT = 4
    MODIFIER_META = 8

    KEY_MAP = {
        "backspace": 2055,
        "tab": 2056,
        "enter": 2057,
        "escape": 2063,
        "space": 2062,
        "pageup": 2068,
        "pagedown": 2069,
        "home": 2073,
        "end": 2074,
        "left": 2072,
        "up": 2070,
        "right": 2071,
        "down": 2075,
        "insert": 2064,
        "delete": 2065,
        "f1": 2079, "f2": 2080, "f3": 2081, "f4": 2082,
        "f5": 2083, "f6": 2084, "f7": 2085, "f8": 2086,
        "f9": 2087, "f10": 2088, "f11": 2089, "f12": 2090,
        "caps_lock": 2061,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cast_engine = None
        self._clipboard: QClipboard = None
        self._last_clipboard_text = ""
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.setInterval(500)
        self._clipboard_timer.timeout.connect(self._check_clipboard)
        self._ime_state = {
            "shift": False,
            "ctrl": False,
            "alt": False,
            "caps_lock": False,
        }
        self._clipboard_sync_enabled = True
        self._hid_mode = False
        self._hid_sensitivity = 5
        self._init_clipboard()

    def _init_clipboard(self):
        app = QGuiApplication.instance()
        if app:
            self._clipboard = app.clipboard()
            self._clipboard.dataChanged.connect(self._on_clipboard_changed)
            self._clipboard_timer.start()

    def set_cast_engine(self, engine):
        self._cast_engine = engine

    def set_clipboard_sync(self, enabled: bool):
        """开启/关闭剪贴板同步"""
        self._clipboard_sync_enabled = enabled
        if enabled:
            self._clipboard_timer.start()
        else:
            self._clipboard_timer.stop()

    def set_hid_mode(self, enabled: bool):
        """开启/关闭 HID 键鼠模式"""
        self._hid_mode = enabled

    def set_hid_sensitivity(self, sensitivity: int):
        """设置 HID 鼠标灵敏度 (1-10)"""
        self._hid_sensitivity = max(1, min(10, sensitivity))

    @property
    def hid_mode(self) -> bool:
        return self._hid_mode

    @property
    def hid_sensitivity(self) -> int:
        return self._hid_sensitivity

    def _on_clipboard_changed(self):
        if self._clipboard and self._clipboard_sync_enabled:
            text = self._clipboard.text()
            if text and text != self._last_clipboard_text:
                self._last_clipboard_text = text
                self.sync_clipboard_to_device(text)

    def _check_clipboard(self):
        if self._clipboard and self._clipboard_sync_enabled:
            text = self._clipboard.text()
            if text and text != self._last_clipboard_text:
                self._last_clipboard_text = text
                self.sync_clipboard_to_device(text)

    def sync_clipboard_to_device(self, text: str):
        if self._cast_engine:
            self._cast_engine.send_clipboard(text)
            self.clipboard_changed.emit(text)

    def sync_clipboard_from_device(self, text: str):
        if self._clipboard and text != self._last_clipboard_text:
            self._last_clipboard_text = text
            self._clipboard.setText(text)

    def send_text(self, text: str):
        if self._cast_engine:
            self._cast_engine.send_text(text)
            self.text_input.emit(text)

    def send_key(self, key_name: str):
        key_code = self.KEY_MAP.get(key_name.lower())
        if key_code and self._cast_engine:
            self._cast_engine.send_key(key_code)
            self.key_event.emit(key_code, key_name)

    def send_combo(self, modifiers: List[str], key_name: str):
        modifier_map = {
            "shift": self.MODIFIER_SHIFT,
            "ctrl": self.MODIFIER_CTRL,
            "alt": self.MODIFIER_ALT,
            "meta": self.MODIFIER_META,
        }
        modifier_bits = []
        for m in modifiers:
            if m.lower() in modifier_map:
                modifier_bits.append(modifier_map[m.lower()])

        key_code = self.KEY_MAP.get(key_name.lower(), 0)
        if self._cast_engine:
            # HarmonyOS uinput 不支持 PC 风格修饰键组合
            # Ctrl+V 等通过剪贴板同步处理；其他组合直接发送按键
            if "ctrl" in modifiers and key_name.lower() == "v":
                self._handle_paste()
            elif key_code:
                self._cast_engine.send_key(key_code)
            self.combo_key.emit(modifier_bits, key_code)

    def handle_keypress(self, event):
        key = event.key()
        text = event.text()
        modifiers = event.modifiers()

        # Ctrl+字母组合键：Ctrl 按下时 Qt 的 event.text() 返回控制字符
        # （如 Ctrl+C -> '\x03'），不满足 isprintable()，会被下面的分支拦截，
        # 因此必须先在这里按 event.key() 处理。
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_C:
                self._handle_copy()
                return True
            if key == Qt.Key.Key_V:
                self._handle_paste()
                return True
            if key == Qt.Key.Key_X:
                self._handle_cut()
                return True
            if key == Qt.Key.Key_A:
                self._handle_select_all()
                return True
            if key == Qt.Key.Key_Z:
                # 撤销组合键：HarmonyOS uinput 不支持 PC 风格修饰键组合，
                # 这里只上报组合事件（设备端按键由调用方另行处理）
                self.combo_key.emit([self.MODIFIER_CTRL], 0)
                return True

        special_map = {
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Escape: "escape",
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_PageUp: "pageup",
            Qt.Key.Key_PageDown: "pagedown",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Insert: "insert",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_F1: "f1", Qt.Key.Key_F2: "f2", Qt.Key.Key_F3: "f3",
            Qt.Key.Key_F4: "f4", Qt.Key.Key_F5: "f5", Qt.Key.Key_F6: "f6",
            Qt.Key.Key_F7: "f7", Qt.Key.Key_F8: "f8", Qt.Key.Key_F9: "f9",
            Qt.Key.Key_F10: "f10", Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
        }

        if key in special_map:
            modifiers = event.modifiers()
            mod_list = []
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                mod_list.append("ctrl")
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                mod_list.append("shift")
            if modifiers & Qt.KeyboardModifier.AltModifier:
                mod_list.append("alt")

            if mod_list:
                self.send_combo(mod_list, special_map[key])
            else:
                self.send_key(special_map[key])
            return True

        if text and text.isprintable():
            mod_list = []
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                mod_list.append("ctrl")

            if mod_list:
                # 到达这里的组合键基本是 Ctrl+Shift+字母 等未单独处理的场景，
                # 直接按普通文本发送
                self.send_text(text)
            else:
                self.send_text(text)
            return True

        return False

    def _handle_copy(self):
        pass

    def _handle_paste(self):
        if self._clipboard:
            text = self._clipboard.text()
            if text:
                self.send_text(text)

    def _handle_cut(self):
        pass

    def _handle_select_all(self):
        self.send_combo(["ctrl"], "a")


class ClipboardSync(QObject):
    clipboard_updated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._clipboard: QClipboard = None
        self._last_text = ""
        self._enabled = False
        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll_clipboard)

    def start(self):
        app = QGuiApplication.instance()
        if app:
            self._clipboard = app.clipboard()
            self._clipboard.dataChanged.connect(self._on_data_changed)
            self._last_text = self._clipboard.text()
            self._timer.start()
            self._enabled = True

    def stop(self):
        self._timer.stop()
        self._enabled = False
        if self._clipboard:
            self._clipboard.dataChanged.disconnect(self._on_data_changed)

    def _on_data_changed(self):
        if self._clipboard:
            text = self._clipboard.text()
            if text != self._last_text:
                self._last_text = text
                self.clipboard_updated.emit(text)

    def _poll_clipboard(self):
        if self._clipboard:
            text = self._clipboard.text()
            if text != self._last_text:
                self._last_text = text
                self.clipboard_updated.emit(text)

    def set_clipboard_text(self, text: str):
        if self._clipboard and text != self._last_text:
            self._last_text = text
            self._clipboard.blockSignals(True)
            self._clipboard.setText(text)
            self._clipboard.blockSignals(False)
            self.clipboard_updated.emit(text)

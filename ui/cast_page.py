import numpy as np
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QSize, QPoint
from PySide6.QtGui import QPainter, QColor, QPixmap, QImage, QFont, QKeyEvent

from core.hdc_cast_service import HDCCastService
from core.input_manager import InputManager
from core.audio_manager import AudioManager
from core.cast_config import get_config_manager, CastConfig
from ui.cast_config_dialog import CastConfigDialog


class PhoneScreen(QFrame):
    """投屏画面控件 — 借鉴 scrcpy 的最新帧优先 + 快速渲染策略"""
    touch_event = Signal(int, int, str)
    key_event_signal = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("phoneScreen")
        self.setMinimumSize(360, 640)
        self._frame = None
        self._resolution = (1080, 2400)
        self._device_rect = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # 抗撕裂关键属性：
        # - WA_OpaquePaintEvent：控件告诉 Qt 自己完全覆盖背景，Qt 不会
        #   先 fill 自身背景再 paint，可直接画在父背景上，避免一帧的
        #   残留 + 半透明叠加看起来像花屏
        # - WA_StaticContents：尺寸固定的内容区合并 update 区域，减少
        #   多次跨帧重绘重叠（解决 scroll up/down 时连续 paint 的痕迹）
        # - WA_PaintOnScreen：直接画到屏幕，避免双缓冲场景下前后缓冲
        #   被同时触摸造成的扫描线撕裂
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents, True)

        # 渲染缓存：避免每帧重复 QPixmap 创建+缩放
        self._cached_pixmap = None       # 缓存的缩放后 pixmap
        self._cached_frame_id = -1       # 对应的帧 ID
        self._cached_size = (0, 0)       # 对应的控件尺寸
        self._cached_src_shape = None    # 源 frame shape（防止 shape 变了缓存错乱）
        self._frame_counter = 0          # 帧计数器（用于帧 ID）
        self._pending_frame = None       # 待渲染的最新帧（丢弃中间帧）

    def set_frame(self, frame: np.ndarray):
        """最新帧优先：只保留最新帧，丢弃中间未渲染的帧。

        注意：必须深拷贝。推帧线程持有并持续覆盖 numpy 数组（_latest_frame
        单变量 + 旧数组 GC 释放），若直接引用原 buffer，paintEvent 里
        QImage 会悬挂（dangling pointer）→ 绘制读到已释放/被复用的内存，
        表现为全屏残影/花屏。拷贝后 GUI 侧数据与推帧线程完全隔离。
        """
        self._pending_frame = frame.copy()
        self.update()

    def set_resolution(self, width: int, height: int):
        self._resolution = (width, height)

    def paintEvent(self, event):
        # 关闭 Antialiasing / Smooth pixmap transform —— BGR888 大色块
        # 平滑没用且会拖慢 paint；用 FastTransformation 缩放，无伪影
        # 默认 RenderHint（None）。Qt 在跨线程 buffer copy 时
        # SmoothTransformation 容易引入扫描线错位，是残影的主因。
        painter = QPainter(self)
        # 不要用 SmoothTransformation / Antialiasing 渲染 BGR 大位图

        # 如果有待渲染帧，消费它
        if self._pending_frame is not None:
            self._frame = self._pending_frame
            self._pending_frame = None
            self._frame_counter += 1

        if self._frame is not None:
            h, w, ch = self._frame.shape
            cur_size = (self.width(), self.height())
            src_shape = (h, w, ch)

            # 1) 先用纯黑覆盖整个控件（不留任何旧像素）。
            # WA_OpaquePaintEvent 让 Qt 不会再做背景合成，但我们仍显式
            # fillRect 一遍，挡住 KeepAspectRatio 黑边区域可能漏出的
            # 上一帧底色。
            painter.fillRect(self.rect(), Qt.GlobalColor.black)

            # 2) 缓存命中：源数据形状 + 控件尺寸都未变 + 是当前帧
            if (self._cached_pixmap is not None
                    and self._cached_frame_id == self._frame_counter
                    and self._cached_size == cur_size
                    and self._cached_src_shape == src_shape):
                scaled = self._cached_pixmap
            else:
                bytes_per_line = ch * w
                fmt = QImage.Format.Format_BGR888 if ch == 3 else QImage.Format.Format_RGB888
                # QImage 不复制 self._frame.data（仅引用），self._frame
                # 是 set_frame 深拷贝来的独立 numpy，painter.end 前不会被
                # 推帧线程覆写（本帧生命周期内）。
                q_img = QImage(
                    self._frame.data, w, h, bytes_per_line, fmt
                )
                # QPixmap.fromImage：会深拷贝到 pixmap 内部 buffer，scaled
                # 也深拷贝。缓存的 pixmap 与 self._frame 完全独立。
                pixmap = QPixmap.fromImage(q_img)
                # FastTransformation：抗扫描线撕裂比 SmoothTransformation
                # 强很多；缩放比仍 < 1 时（cast 50% 截图到 360px 渲染）
                # 视觉差异肉眼难辨。
                scaled = pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation
                )
                self._cached_pixmap = scaled
                self._cached_frame_id = self._frame_counter
                self._cached_size = cur_size
                self._cached_src_shape = src_shape

            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            self._device_rect = (x, y, scaled.width(), scaled.height())
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(self.rect(), QColor("#FAFAFA"))
            painter.setPen(QColor("#99A2B1"))
            painter.setFont(QFont("Microsoft YaHei", 14))
            text_rect = self.rect().adjusted(20, 20, -20, -20)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "等待投屏画面...")

        painter.end()

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self._map_to_device(event.position().x(), event.position().y())
            if pos:
                self.touch_event.emit(pos[0], pos[1], "down")

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            pos = self._map_to_device(event.position().x(), event.position().y())
            if pos:
                self.touch_event.emit(pos[0], pos[1], "move")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self._map_to_device(event.position().x(), event.position().y())
            if pos:
                self.touch_event.emit(pos[0], pos[1], "up")

    def keyPressEvent(self, event: QKeyEvent):
        modifiers = event.modifiers()
        mod_list = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            mod_list.append("ctrl")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            mod_list.append("shift")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            mod_list.append("alt")

        # Ctrl+字母组合键：Ctrl 按下时 event.text() 是控制字符（不可打印），
        # 必须在这里按 event.key() 处理
        key = event.key()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            combo_map = {
                Qt.Key.Key_C: "copy",
                Qt.Key.Key_V: "paste",
                Qt.Key.Key_X: "cut",
                Qt.Key.Key_A: "select_all",
                Qt.Key.Key_Z: "undo",
            }
            if key in combo_map:
                self.key_event_signal.emit("combo", {"combo": combo_map[key]})
                event.accept()
                return

        key_map = {
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Escape: "escape",
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_F1: "f1", Qt.Key.Key_F2: "f2",
            Qt.Key.Key_F3: "f3", Qt.Key.Key_F4: "f4",
            Qt.Key.Key_F5: "f5", Qt.Key.Key_F6: "f6",
            Qt.Key.Key_F7: "f7", Qt.Key.Key_F8: "f8",
            Qt.Key.Key_F9: "f9", Qt.Key.Key_F10: "f10",
            Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
        }

        if key in key_map:
            self.key_event_signal.emit(key_map[key], {"modifiers": mod_list})
            event.accept()
        elif event.text() and event.text().isprintable():
            self.key_event_signal.emit("text", {
                "text": event.text(),
                "modifiers": mod_list
            })
            event.accept()
        else:
            super().keyPressEvent(event)

    def _map_to_device(self, x: float, y: float):
        if self._frame is None or not self._device_rect:
            return None
        dx, dy, dw, dh = self._device_rect
        w, h = self._resolution

        if x < dx or x > dx + dw or y < dy or y > dy + dh:
            return None

        device_x = int((x - dx) / dw * w)
        device_y = int((y - dy) / dh * h)
        return device_x, device_y


class CastToolbar(QFrame):
    """右侧侧边工具栏（按用户指定功能清单，共 12 个按钮）。

    自上而下：截图 · 录屏 | 全屏 · 旋转 · 常亮 | 音量+ · 音量- · 静音 |
    返回 · 主页 · 多任务 · 电源
    （用户给定的自下而上顺序：电源、多任务、主页、返回、静音、音量-、
    音量+、屏幕常亮、屏幕旋转、全屏、开始录屏、截图）
    """
    rotate_clicked = Signal()
    screen_awake_clicked = Signal()
    vol_up_clicked = Signal()
    vol_down_clicked = Signal()
    mute_clicked = Signal()
    back_clicked = Signal()
    home_clicked = Signal()
    recent_clicked = Signal()
    power_clicked = Signal()
    screenshot_clicked = Signal()
    record_clicked = Signal()
    fullscreen_clicked = Signal()   # 全屏（切换全屏显示）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolbar")
        self.setStyleSheet(
            "QFrame#toolbar { background-color: #FFFFFF;"
            "border: 1px solid #E5E8EB; border-radius: 12px; }"
        )
        self._record_btn = None
        self._mute_btn = None
        self._fullscreen_btn = None
        self._screen_awake_btn = None
        self._rotate_btn = None

        layout = QVBoxLayout(self)
        # 紧凑内边距和间距
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(7)

        self.fps_label = QLabel("0 FPS")
        self.fps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fps_label.setStyleSheet(
            "font-family: Consolas, Monaco, monospace; font-size: 11px; font-weight: 700; color: #FFFFFF;"
            "background-color: #007DFF;"
            "border-radius: 999px; padding: 5px 6px;"
        )
        layout.addWidget(self.fps_label)

        self.bitrate_label = QLabel("0 Mbps")
        self.bitrate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bitrate_label.setStyleSheet("font-size: 9px; color: #99A2B1; font-weight: 700;")
        layout.addWidget(self.bitrate_label)

        # 注：按钮用中文文字标签（emoji 在部分 Windows 字体下渲染为空白）
        # ── 截图 / 录屏 ──
        self._add_btn(layout, "截图", "截图", self.screenshot_clicked)
        self._record_btn = self._add_btn(layout, "录屏", "开始录屏", self.record_clicked, checkable=True)

        self._add_divider(layout)

        # ── 全屏 / 旋转 / 常亮 ──
        self._fullscreen_btn = self._add_btn(
            layout, "全屏", "全屏显示", self.fullscreen_clicked, checkable=True
        )
        self._rotate_btn = self._add_btn(layout, "旋转", "屏幕旋转", self.rotate_clicked)
        self._screen_awake_btn = self._add_btn(
            layout, "常亮", "屏幕常亮（再点关闭）", self.screen_awake_clicked, checkable=True
        )

        self._add_divider(layout)

        # ── 音量+ / 音量- / 静音 ──
        self._add_btn(layout, "音+", "音量+", self.vol_up_clicked)
        self._add_btn(layout, "音-", "音量-", self.vol_down_clicked)
        self._mute_btn = self._add_btn(layout, "静音", "静音", self.mute_clicked, checkable=True)

        self._add_divider(layout)

        # ── 返回 / 主页 / 多任务 / 电源 ──
        self._add_btn(layout, "返回", "返回", self.back_clicked)
        self._add_btn(layout, "主页", "主页", self.home_clicked)
        self._add_btn(layout, "任务", "多任务", self.recent_clicked)
        self._add_btn(layout, "电源", "电源", self.power_clicked)

        layout.addStretch()

    def _add_btn(self, layout, icon, tooltip, signal, checkable=False):
        btn = QPushButton(icon)
        btn.setObjectName("toolBtn")
        # 紧凑按钮尺寸，避免挤压
        btn.setFixedSize(42, 42)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setCheckable(checkable)
        btn.setStyleSheet(
            # padding:0 必须写：全局 QPushButton 有 padding:10px 20px，
            # 会把 42x42 按钮的文字区挤到 2px，文字裁切不可见（空白按钮根因）
            "QPushButton#toolBtn { background-color: #F5F5F5; border: 1px solid #E5E8EB; border-radius: 8px;"
            "color: #5A6370; font-size: 12px; font-weight: 600; padding: 0px; }"
            "QPushButton#toolBtn:hover { background-color: #E6F0FF; color: #007DFF; border-color: #80BFFF; }"
            "QPushButton#toolBtn:pressed { background-color: #CCE5FF; }"
            "QPushButton#toolBtn:checked { background-color: #007DFF; color: #FFFFFF; border: none; }"
        )
        btn.clicked.connect(signal.emit)
        layout.addWidget(btn)
        return btn

    def _add_divider(self, layout):
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #E5E8EB; margin: 4px 6px;")
        layout.addWidget(divider)

    def update_fps(self, fps: int):
        self.fps_label.setText(f"{fps} FPS")

    def update_bitrate(self, bitrate: int):
        self.bitrate_label.setText(f"{bitrate} Mbps")

    def set_recording(self, recording: bool):
        if self._record_btn:
            self._record_btn.setText("停止" if recording else "录屏")
            self._record_btn.setChecked(recording)

    def set_muted(self, muted: bool):
        if self._mute_btn:
            self._mute_btn.setText("静音")
            self._mute_btn.setChecked(muted)

    def set_fullscreen(self, fullscreen: bool):
        """同步全屏按钮的勾选态（外部切换全屏后回传）"""
        if self._fullscreen_btn:
            self._fullscreen_btn.setChecked(fullscreen)
            self._fullscreen_btn.setText("全屏")

    def set_screen_awake(self, awake: bool):
        """同步屏幕常亮按钮的勾选态"""
        if self._screen_awake_btn:
            self._screen_awake_btn.setChecked(awake)

    def set_rotate(self, rotated: bool):
        if self._rotate_btn:
            self._rotate_btn.setChecked(rotated)


class CastPage(QWidget):
    def __init__(self, hdc_client, parent=None):
        super().__init__(parent)
        self.hdc = hdc_client
        self._hdc_cast: HDCCastService = None
        self._input_mgr: InputManager = None
        self._audio_mgr: AudioManager = None
        self._current_device = None
        self._is_casting = False
        self._is_recording = False
        self._record_frames = []
        self._record_start_time = 0
        self._share_token = None
        self._sharing = False
        self._web_server = None
        self._last_share_push = 0.0
        self._mode_h264 = False
        self._max_fps = 60
        self._mouse_follow = True
        # 配置管理器
        self._cfg_mgr = get_config_manager()

        # 最新帧拉取定时器：投屏服务采用"单槽缓冲 + 按需拉取"模式，
        # 不再每帧发射 frame_received 信号，因此 UI 需要定时主动拉取。
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(16)  # ~60 FPS 拉取（原 33ms/30FPS，降低画面滞后）
        self._frame_timer.timeout.connect(self._poll_latest_frame)
        self._last_frame_version = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header - 紧凑高度避免挤压
        header_widget = QWidget()
        header_widget.setStyleSheet("background-color: #FFFFFF; border-bottom: 1px solid #E5E8EB;")
        header_widget.setMaximumHeight(64)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(18, 10, 18, 10)
        header.setSpacing(10)

        self.back_btn = QPushButton("← 返回")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setFixedHeight(36)
        self.back_btn.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #99A2B1; border: 1.5px solid #E5E8EB;"
            "border-radius: 8px; padding: 6px 18px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background-color: #E6F0FF; color: #007DFF; border-color: #80BFFF; }"
        )
        self.back_btn.clicked.connect(self._go_back)
        header.addWidget(self.back_btn)

        self.device_label = QLabel("未连接设备")
        self.device_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #182431;")
        header.addWidget(self.device_label, 1)

        self.conn_badge = QLabel("● 未连接")
        self.conn_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.conn_badge.setStyleSheet(
            "font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: 999px;"
            "background-color: #F5F5F5; color: #99A2B1;"
        )
        header.addWidget(self.conn_badge)

        self.settings_btn = QPushButton("⚙️")
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setStyleSheet(
            "QPushButton { background: #F5F5F5; border: 1px solid #E5E8EB; border-radius: 8px;"
            "color: #99A2B1; font-size: 16px; }"
            "QPushButton:hover { background: #E6F0FF; color: #007DFF; border-color: #80BFFF; }"
        )
        self.settings_btn.clicked.connect(self._show_settings)
        header.addWidget(self.settings_btn)

        layout.addWidget(header_widget)

        # Body - 紧凑外边距
        body_widget = QWidget()
        body_widget.setStyleSheet("background-color: #F1F3F5;")
        body_layout = QHBoxLayout(body_widget)
        body_layout.setContentsMargins(20, 16, 20, 16)
        body_layout.setSpacing(16)

        phone_container = QWidget()
        phone_layout = QVBoxLayout(phone_container)
        phone_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        phone_layout.setContentsMargins(0, 0, 0, 0)

        self.phone_screen = PhoneScreen()
        self.phone_screen.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.phone_screen.touch_event.connect(self._on_touch_event)
        self.phone_screen.key_event_signal.connect(self._on_key_event)

        phone_layout.addWidget(self.phone_screen)
        body_layout.addWidget(phone_container, 1)

        # 工具栏 - 紧凑宽度
        self.toolbar = CastToolbar()
        self.toolbar.setFixedWidth(64)
        self.toolbar.rotate_clicked.connect(self._rotate_screen)
        self.toolbar.screen_awake_clicked.connect(self._toggle_screen_awake)
        self.toolbar.vol_up_clicked.connect(self._volume_up)
        self.toolbar.vol_down_clicked.connect(self._volume_down)
        self.toolbar.mute_clicked.connect(self._toggle_mute)
        self.toolbar.back_clicked.connect(self._go_back_key)
        self.toolbar.home_clicked.connect(self._go_home)
        self.toolbar.recent_clicked.connect(self._recent_apps)
        self.toolbar.power_clicked.connect(self._power_key)
        self.toolbar.screenshot_clicked.connect(self._take_screenshot)
        self.toolbar.record_clicked.connect(self._toggle_record)
        self.toolbar.fullscreen_clicked.connect(self._toggle_fullscreen)

        body_layout.addWidget(self.toolbar, 0)
        layout.addWidget(body_widget, 1)

        self._settings_panel = None

    def set_hdc_cast_service(self, service: HDCCastService):
        self._hdc_cast = service
        self._hdc_cast.frame_received.connect(self._on_frame_received)
        self._hdc_cast.connection_status.connect(self._on_connection_status)
        self._hdc_cast.error_occurred.connect(self._on_error)
        self._hdc_cast.fps_updated.connect(self._on_fps_updated)

    def set_input_manager(self, input_mgr: InputManager):
        self._input_mgr = input_mgr

    def set_audio_manager(self, audio_mgr: AudioManager):
        self._audio_mgr = audio_mgr

    def start_casting(self, device_id: str):
        self._current_device = device_id
        short_id = device_id[:12] if len(device_id) > 12 else device_id
        self.device_label.setText(f"设备: {short_id}")
        self._set_connection_status("connecting", "● 连接中")

        if self._hdc_cast:
            # 1) 从配置管理器读取记住的配置（若无则返回默认值）
            cfg: CastConfig = self._cfg_mgr.get(device_id)
            # 2) 应用到服务端（先设置参数，再连接/启动）
            self._hdc_cast.set_capture_mode(cfg.capture_mode)
            self._hdc_cast.set_max_fps(cfg.fps)
            self._hdc_cast.set_bitrate(cfg.bitrate_mbps)
            self._hdc_cast.set_scale(cfg.scale_pct)
            self._hdc_cast.set_screen_id(cfg.screen_id)
            # 同步到页面状态变量
            self._mode_h264 = cfg.is_h264
            self._max_fps = cfg.fps

            success = self._hdc_cast.connect_device(device_id)
            if success:
                self._set_connection_status("connected", "● 已连接")
                self._hdc_cast.start_casting(mode=cfg.cast_engine_mode)
                self._is_casting = True
                info = self._hdc_cast.get_device_info()
                resolution = self._hdc_cast._resolution
                self.phone_screen.set_resolution(*resolution)
                self._start_audio_capture()
                self._frame_timer.start()
            else:
                self._set_connection_status("error", "● 连接失败")
                QMessageBox.warning(self, "连接失败", f"无法连接到设备 {device_id}")
        else:
            self._set_connection_status("connected", "● 已连接 (模拟)")
            self._is_casting = True
            self._start_mock_casting()

    def stop_casting(self):
        self._frame_timer.stop()
        self._stop_sharing()
        if self._hdc_cast:
            self._hdc_cast.stop_casting()
        self._stop_audio_capture()
        self._is_casting = False
        self._current_device = None
        self.phone_screen._frame = None
        self.phone_screen.update()

    def _poll_latest_frame(self):
        """按需拉取服务端最新帧（兼容单槽缓冲模式）"""
        if not self._hdc_cast:
            return
        try:
            version = self._hdc_cast.frame_version
            if version == self._last_frame_version:
                return
            frame = self._hdc_cast.get_latest_frame()
            if frame is None:
                return
            self._last_frame_version = version
            self._on_frame_received(frame)
        except Exception:
            pass

    def _start_mock_casting(self):
        import threading
        self._mock_running = True

        def mock_loop():
            t = 0
            while self._mock_running:
                t += 0.016
                frame = np.zeros((2400, 1080, 3), dtype=np.uint8)
                frame[:] = np.array([245, 247, 250], dtype=np.uint8)
                for i in range(8):
                    y_pos = int(300 + i * 250 + np.sin(t * 2 + i * 0.5) * 40)
                    x_pos = int(200 + np.cos(t * 1.5 + i * 0.3) * 60)
                    if 0 < y_pos < 2350 and 0 < x_pos < 1030:
                        color = np.array([
                            int(59 + 40 * np.sin(t + i)),
                            int(130 + 40 * np.cos(t + i * 2)),
                            int(246 + 30 * np.sin(t + i * 3))
                        ], dtype=np.uint8)
                        frame[y_pos:y_pos+60, x_pos:x_pos+60] = color
                self._on_frame_received(frame)
                self.toolbar.update_fps(int(60 + 10 * np.sin(t)))
                time.sleep(0.016)

        self._mock_thread = threading.Thread(target=mock_loop, daemon=True)
        self._mock_thread.start()

    def _go_back(self):
        if hasattr(self, '_mock_running'):
            self._mock_running = False
        self.stop_casting()
        main_window = self.window()
        if hasattr(main_window, 'stack'):
            main_window.stack.setCurrentIndex(0)

    def _on_frame_received(self, frame: np.ndarray):
        self.phone_screen.set_frame(frame)
        if self._is_recording:
            if len(self._record_frames) < 1800:
                self._record_frames.append(frame.copy())
        if self._sharing and self._web_server is not None and self._current_device:
            now = time.time()
            # 限制推送频率约 15 FPS，避免编码开销拖慢本地投屏
            if now - self._last_share_push >= 0.066:
                self._last_share_push = now
                try:
                    import cv2
                    ok, buf = cv2.imencode(".jpg", frame, [
                        cv2.IMWRITE_JPEG_QUALITY, 80
                    ])
                    if ok:
                        self._web_server.update_device_frame(
                            self._current_device, buf.tobytes()
                        )
                except Exception:
                    pass

    def _on_connection_status(self, status: str):
        status_map = {
            "connected": ("connected", "● 投屏中"),
            "casting": ("connected", "● 投屏中"),
            "connecting": ("connecting", "● 连接中"),
            "disconnected": ("disconnected", "● 已断开"),
            "error": ("disconnected", "● 错误"),
        }
        cls, text = status_map.get(status, ("disconnected", "● 未知"))
        self._set_connection_status(cls, text)

    def _on_fps_updated(self, fps: int):
        self.toolbar.update_fps(fps)

    def _on_error(self, error: str):
        QMessageBox.warning(self, "连接错误", str(error))

    def _set_connection_status(self, status_class: str, text: str):
        self.conn_badge.setText(text)
        color_map = {
            "connected": "#007DFF",
            "connecting": "#007DFF",
            "disconnected": "#99A2B1",
        }
        bg_map = {
            "connected": "#E6F0FF",
            "connecting": "#E6F0FF",
            "disconnected": "#F5F5F5",
        }
        c = color_map.get(status_class, "#99A2B1")
        b = bg_map.get(status_class, "#F5F5F5")
        self.conn_badge.setStyleSheet(
            f"font-size: 13px; font-weight: 600; padding: 5px 14px; border-radius: 999px;"
            f"background-color: {b}; color: {c};"
        )

    def _on_touch_event(self, x: int, y: int, action: str):
        if self._hdc_cast and self._current_device:
            # scrcpy 语义：ACTION_DOWN=0, ACTION_UP=1, ACTION_MOVE=2
            action_map = {"down": 0, "up": 1, "move": 2}
            self._hdc_cast.send_touch(x, y, action_map.get(action, 0))

    def _on_key_event(self, event_type: str, data: dict):
        if self._input_mgr:
            if event_type == "combo":
                combo = data.get("combo")
                if combo == "paste":
                    from PySide6.QtGui import QGuiApplication
                    clipboard = QGuiApplication.clipboard()
                    if clipboard is not None:
                        text = clipboard.text()
                        if text:
                            self._input_mgr.send_text(text)
            elif event_type == "text":
                text = data.get("text", "")
                self._input_mgr.send_text(text)
            elif event_type in InputManager.KEY_MAP:
                modifiers = data.get("modifiers", [])
                if modifiers:
                    self._input_mgr.send_combo(modifiers, event_type)
                else:
                    self._input_mgr.send_key(event_type)

    def _send_key(self, key_code: int):
        if self._hdc_cast and self._current_device:
            self._hdc_cast.send_key(key_code)

    def _rotate_screen(self):
        pass

    def _toggle_screen_awake(self):
        if self._hdc_cast and self._current_device:
            self._hdc_cast.run_hdc(["-t", self._current_device, "shell", "powerctrl", "wakeup"])

    def _volume_up(self):
        if self._audio_mgr:
            self._audio_mgr.set_volume(min(100, self._audio_mgr.get_volume() + 10))
        self._send_key(2058)

    def _volume_down(self):
        if self._audio_mgr:
            self._audio_mgr.set_volume(max(0, self._audio_mgr.get_volume() - 10))
        self._send_key(2059)

    def _toggle_mute(self):
        if self._audio_mgr:
            self._audio_mgr.set_muted(not self._audio_mgr.is_muted())
            self.toolbar.set_muted(self._audio_mgr.is_muted())
        self._send_key(2060)

    # ---------- HoKit 同款新增按钮处理 ----------
    def _toggle_cast_mode(self):
        """分层（Layers）：JPEG 截图 ↔ H.264 流之间热切换。"""
        if not self._hdc_cast or not self._current_device:
            QMessageBox.warning(self, "提示", "请先开始投屏")
            return
        cur = getattr(self._hdc_cast, "_capture_mode", "screenshot")
        if cur == "stream":
            new_mode = "screenshot"
            new_engine = "screenshot"
        else:
            new_mode = "stream"
            new_engine = "stream"
        try:
            self._hdc_cast.set_capture_mode("jpeg" if new_mode == "screenshot" else "h264")
            self._hdc_cast.stop_casting()
            ok = self._hdc_cast.start_casting(mode=new_engine)
            if not ok and new_mode == "stream":
                QMessageBox.warning(
                    self, "切换失败",
                    "H.264 模式不可用，已自动降级为截图模式。"
                )
                self._hdc_cast.set_capture_mode("jpeg")
                self._hdc_cast.start_casting(mode="screenshot")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"切换投屏模式异常: {e}")

    def _open_app_drawer(self):
        """应用（Apps）：拉起 HarmonyOS 桌面应用列表。"""
        if not self._hdc_cast or not self._current_device:
            QMessageBox.warning(self, "提示", "请先开始投屏")
            return
        candidates = [
            "aa start -b com.huawei.hmos.launcher -a com.huawei.hmos.launcher.MainAbility",
            "aa start -b com.huawei.hmos.launcher",
            "am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER",
        ]
        for cmd in candidates:
            try:
                code, _, _ = self._hdc_cast.run_hdc(
                    ["-t", self._current_device, "shell"] + cmd.split()
                )
                if code == 0:
                    return
            except Exception:
                continue
        QMessageBox.warning(self, "失败", "无法启动应用列表，请手动在设备端操作。")

    def _toggle_window_pinned(self):
        """切换窗口置顶（当前无按钮接线，预留）。"""
        from PySide6.QtCore import Qt as _Qt
        win = self.window()
        if win is None:
            return
        flags = win.windowFlags()
        if flags & _Qt.WindowType.WindowStaysOnTopHint:
            win.setWindowFlags(flags & ~_Qt.WindowType.WindowStaysOnTopHint)
        else:
            win.setWindowFlags(flags | _Qt.WindowType.WindowStaysOnTopHint)
        win.show()

    def _toggle_fullscreen(self):
        """全屏（Fullscreen）：切换 Qt 全屏状态。"""
        win = self.window()
        if win is None:
            return
        if win.isFullScreen():
            win.showNormal()
            self.toolbar.set_fullscreen(False)
        else:
            win.showFullScreen()
            self.toolbar.set_fullscreen(True)

    def _show_brightness_dialog(self):
        """亮度（Brightness）：弹出亮度调节滑块，通过 hdc shell 设置设备屏幕亮度。"""
        if not self._hdc_cast or not self._current_device:
            QMessageBox.warning(self, "提示", "请先开始投屏")
            return
        try:
            current = 128
            code, out, _ = self._hdc_cast.run_hdc([
                "-t", self._current_device, "shell",
                "settings get system screen_brightness"
            ])
            if code == 0 and out.strip().isdigit():
                current = max(0, min(255, int(out.strip())))
        except Exception:
            current = 128

        from PySide6.QtWidgets import QDialog, QSlider, QDialogButtonBox, QVBoxLayout, QLabel
        dlg = QDialog(self)
        dlg.setWindowTitle("亮度调节")
        dlg.setFixedWidth(280)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 16)
        info = QLabel(f"当前亮度: {current} / 255")
        info.setStyleSheet("font-size: 13px; color: #182431; font-weight: 600;")
        lay.addWidget(info)

        slider = QSlider(Qt.Orientation.Horizontal, dlg)
        slider.setRange(0, 255)
        slider.setValue(current)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(32)
        slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 6px; background: #E5E8EB; border-radius: 3px; }"
            "QSlider::handle:horizontal { width: 18px; height: 18px; margin: -6px 0;"
            "background: #007DFF; border-radius: 9px; }"
        )
        lay.addWidget(slider)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        lay.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        def _on_change(v):
            info.setText(f"当前亮度: {v} / 255")
        slider.valueChanged.connect(_on_change)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            value = slider.value()
            try:
                self._hdc_cast.run_hdc([
                    "-t", self._current_device, "shell",
                    f"settings put system screen_brightness {value}"
                ])
            except Exception as e:
                QMessageBox.warning(self, "提示", f"亮度设置失败: {e}")

    def _scroll_up(self):
        """上滚（ScrollUp）：发送 PageUp 键。"""
        self._send_key(2068)

    def _go_back_key(self):
        self._send_key(2007)

    def _go_home(self):
        self._send_key(2003)

    def _recent_apps(self):
        self._send_key(2049)

    def _power_key(self):
        self._send_key(2076)

    def _take_screenshot(self):
        if self.phone_screen._frame is None:
            QMessageBox.warning(self, "提示", "没有可截图的画面")
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        default_path = f"screenshot_{timestamp}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存截图", default_path, "PNG 图片 (*.png)"
        )
        if path:
            frame = self.phone_screen._frame
            h, w, ch = frame.shape
            q_img = QImage(
                frame.tobytes(), w, h, ch * w,
                # 帧数据是 OpenCV 的 BGR 顺序，直接用 BGR888 保存，
                # 否则红蓝通道互换
                QImage.Format.Format_BGR888
            )
            q_img.save(path, "PNG")
            QMessageBox.information(self, "成功", f"截图已保存到:\n{path}")

    def _toggle_record(self):
        if self._is_recording:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        self._is_recording = True
        self._record_frames = []
        self._record_start_time = time.time()
        self.toolbar.set_recording(True)

    def _stop_record(self):
        self._is_recording = False
        self.toolbar.set_recording(False)
        duration = time.time() - self._record_start_time
        frame_count = len(self._record_frames)

        if frame_count == 0:
            QMessageBox.warning(self, "提示", "没有录制到任何帧")
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        default_path = f"recording_{timestamp}.mp4"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存录屏", default_path, "MP4 视频 (*.mp4)"
        )
        if path:
            try:
                import cv2
                fps = max(1, frame_count / max(duration, 0.1))
                h, w = self._record_frames[0].shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                writer = cv2.VideoWriter(path, fourcc, min(fps, 30), (w, h))
                for frame in self._record_frames:
                    # 帧本来就是 BGR（OpenCV 解码输出），VideoWriter 期望 BGR，
                    # 直接写入即可，不要再做颜色转换
                    writer.write(frame)
                writer.release()
                QMessageBox.information(
                    self, "成功",
                    f"录屏已保存到:\n{path}\n帧数: {frame_count}, 时长: {duration:.1f}s"
                )
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")

        self._record_frames = []

    def _share_device(self):
        if self._sharing:
            self._stop_sharing()
            QMessageBox.information(self, "提示", "网页投屏已停止")
            return

        if not self._current_device:
            QMessageBox.warning(self, "提示", "请先开始投屏")
            return

        try:
            from core.web_cast_server import WebCastServer
            if self._web_server is None:
                self._web_server = WebCastServer(host="0.0.0.0", port=8080)
                self._web_server.frame_broadcast.connect(self._on_web_control)
            self._web_server.start()
            self._web_server.register_device(self._current_device, {
                "id": self._current_device,
                "name": self.device_label.text(),
            })
            token_info = self._web_server.permission_manager.create_share_token(
                self._current_device, "full_control", expiry_hours=24
            )
            self._share_token = token_info["token"]
            self._sharing = True
            self._last_share_push = 0.0
            QMessageBox.information(
                self, "网页投屏已开启",
                f"在浏览器中打开以下链接即可观看/控制设备（24 小时内有效）：\n\n"
                f"{token_info['url']}"
            )
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"网页投屏启动失败:\n{str(e)}")

    def _stop_sharing(self):
        self._sharing = False
        self._share_token = None
        if self._web_server is not None:
            try:
                self._web_server.stop()
            except Exception:
                pass
            self._web_server = None

    def _on_web_control(self, payload: bytes):
        """处理来自网页端的控制指令（触控 / 按键 / 剪贴板）"""
        try:
            import json
            data = json.loads(payload.decode("utf-8"))
            control = data.get("control")
            if control is None:
                return
            action = control.get("action")
            if not self._hdc_cast or not self._current_device:
                return

            if action == "touch":
                x = int(control.get("x", 0))
                y = int(control.get("y", 0))
                self._hdc_cast.send_tap(x, y)
            else:
                key_map = {
                    "back": 2007,
                    "home": 2003,
                    "recent": 2049,
                    "power": 2076,
                    "volume_up": 2058,
                    "volume_down": 2059,
                    "mute": 2060,
                }
                code = key_map.get(action)
                if code is not None:
                    self._hdc_cast.send_key(code)
        except Exception:
            pass

    # ----------------- 投屏设置（使用独立弹窗） -----------------
    def _show_settings(self):
        """打开投屏配置弹窗（使用独立 CastConfigDialog，不会导致崩溃）"""
        device_id = self._current_device or "default"
        dlg = CastConfigDialog(device_id, self)
        if dlg.exec() == CastConfigDialog.DialogCode.Accepted:
            # 配置已保存到 CastConfigManager
            # 如果正在投屏，提示用户需要重启才能生效（避免在 UI 线程中 stop+start 导致崩溃）
            if self._is_casting and self._current_device:
                cfg = dlg.result_config
                self._show_config_saved_tip(cfg)

    def _show_config_saved_tip(self, cfg: CastConfig):
        """显示非阻塞提示，告知配置已保存，重启投屏后生效"""
        msg = f"配置已保存：{cfg.capture_mode.upper()} / {cfg.fps} FPS"
        if cfg.remember:
            msg += "（已记住此配置）"
        msg += "\n将在下次开始投屏时生效"

        tip = QLabel(msg, self)
        tip.setStyleSheet(
            "background: rgba(24, 36, 49, 0.92); color: #FFFFFF;"
            "padding: 12px 24px; border-radius: 10px; font-size: 13px; font-weight: 600;"
        )
        tip.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        tip.adjustSize()
        gp = self.settings_btn.mapToGlobal(self.settings_btn.rect().center())
        tip.move(gp.x() - tip.width() // 2, gp.y() + 28)
        tip.show()
        QTimer.singleShot(3000, tip.close)

    def _start_audio_capture(self):
        if self._audio_mgr:
            try:
                self._audio_mgr.start_capture()
            except Exception:
                pass

    def _stop_audio_capture(self):
        if self._audio_mgr:
            self._audio_mgr.stop_capture()

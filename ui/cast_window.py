# -*- coding: utf-8 -*-
"""
独立投屏窗口（复刻 HoKit ScreencastWindow 布局）

- 无边框独立顶层窗口，自绘标题栏（设备名 + 实时帧率 + 最小化/关闭）
- 中央 PhoneScreen 投屏画布（可自由拖拽调整窗口大小）
- 右侧 CastToolbar 侧边工具栏（HoKit 同款）：
  FPS · 截图 · 录屏 · 分层 · 应用 · 悬浮窗 · 全屏 · 亮度 ·
  音量+ · 音量- · 静音 · 上滚 · 主页 · 多任务 · 电源
  额外保留：旋转、常亮、返回、网页分享
- 帧渲染定时器 16ms（60 FPS 上限，相对主窗口内嵌页 33ms/30FPS 减半延迟）
"""
import os
import time

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QImage, QPixmap, QFont, QColor, QPainter, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QMessageBox, QFileDialog, QDialog, QSlider, QDialogButtonBox,
)

from ui.cast_page import PhoneScreen, CastToolbar
from core.cast_config import get_config_manager


class _TitleBar(QFrame):
    """自绘标题栏：设备名 + 帧率 + 置顶/最小化/最大化/关闭/收起工具栏

    按钮顺序（从左到右，用户指定）：
    窗口置顶 · 最小化 · 最大化 · 关闭 · 收起右侧工具栏
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("castWinTitle")
        # 浅色标题栏：用户反馈深色黑条上操作按钮看不清
        self.setStyleSheet(
            "QFrame#castWinTitle { background: #FFFFFF; border: none;"
            "  border-bottom: 1px solid #E5E8EB; }"
            "QLabel { color: #182431; background: transparent; }"
        )
        self.setFixedHeight(44)
        self._drag_pos = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(8)

        self.title_label = QLabel("为投个屏")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #182431;")
        lay.addWidget(self.title_label)

        self.fps_label = QLabel("-- FPS")
        self.fps_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; font-weight: 700; color: #00A870;"
        )
        lay.addWidget(self.fps_label)
        lay.addStretch(1)

        # 统一按钮样式：浅色底 + 边框 + 中文文字，清晰可见
        btn_qss = (
            "QPushButton { background: #F5F5F5; color: #5A6370; border: 1px solid #E5E8EB;"
            "  border-radius: 6px; font-size: 12px; font-weight: 600; padding: 0px; }"
            "QPushButton:hover { background: #E6F0FF; color: #007DFF; border-color: #80BFFF; }"
            "QPushButton#closeBtn:hover { background: #E81123; color: #FFFFFF; border-color: #E81123; }"
            "QPushButton#pinBtn:checked { background: #007DFF; color: #FFFFFF; border-color: #007DFF; }"
        )

        # 窗口置顶（checkable，勾选=置顶）
        self.pin_btn = QPushButton("置顶")
        self.pin_btn.setObjectName("pinBtn")
        self.pin_btn.setFixedSize(44, 28)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("窗口置顶")
        self.pin_btn.setStyleSheet(btn_qss)
        lay.addWidget(self.pin_btn)

        min_btn = QPushButton("最小化")
        min_btn.setFixedSize(56, 28)
        min_btn.setToolTip("最小化")
        min_btn.setStyleSheet(btn_qss)
        min_btn.clicked.connect(lambda: self.window().showMinimized())
        lay.addWidget(min_btn)

        self.max_btn = QPushButton("最大化")
        self.max_btn.setFixedSize(56, 28)
        self.max_btn.setToolTip("最大化")
        self.max_btn.setStyleSheet(btn_qss)
        lay.addWidget(self.max_btn)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(44, 28)
        close_btn.setToolTip("关闭投屏")
        close_btn.setStyleSheet(btn_qss)
        close_btn.clicked.connect(lambda: self.window().close())
        lay.addWidget(close_btn)

        self.collapse_btn = QPushButton("收起")
        self.collapse_btn.setFixedSize(44, 28)
        self.collapse_btn.setToolTip("收起右侧工具栏")
        self.collapse_btn.setStyleSheet(btn_qss)
        lay.addWidget(self.collapse_btn)

    def set_pinned(self, pinned: bool):
        """同步置顶按钮勾选态"""
        self.pin_btn.setChecked(pinned)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class CastWindow(QWidget):
    """独立投屏窗口"""

    def __init__(self, hdc_client, hdc_cast, input_mgr, audio_mgr, parent=None):
        super().__init__(parent)
        self._hdc_client = hdc_client
        self._hdc_cast = hdc_cast
        self._input_mgr = input_mgr
        self._audio_mgr = audio_mgr

        self._current_device = None
        self._is_casting = False
        self._last_frame_version = -1

        # 录制状态（流式写临时文件，避免内存累积）
        self._is_recording = False
        self._record_writer = None
        self._record_tmp = None
        self._record_start_time = 0.0

        self.setWindowTitle("为投个屏 - 投屏")
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet("QWidget#castWinRoot { background: #11151C; }")
        self.resize(460, 880)

        self._build_ui()

        # 帧拉取定时器：16ms ≈ 60 FPS 渲染上限
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(16)
        self._frame_timer.timeout.connect(self._poll_latest_frame)

        # 服务信号
        if self._hdc_cast is not None:
            self._hdc_cast.fps_updated.connect(self._on_fps_updated)
            self._hdc_cast.error_occurred.connect(self._on_error)

    # ---------- UI ----------
    def _build_ui(self):
        root = QFrame()
        root.setObjectName("castWinRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(root)

        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.title_bar = _TitleBar()
        lay.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        lay.addLayout(body, 1)

        # 中央画布
        self.phone_screen = PhoneScreen()
        self.phone_screen.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        body.addWidget(self.phone_screen, 1)

        # 右侧工具栏
        self.toolbar = CastToolbar()
        body.addWidget(self.toolbar, 0, Qt.AlignmentFlag.AlignRight)

        # 接线
        self.phone_screen.touch_event.connect(self._on_touch_event)
        self.phone_screen.key_event_signal.connect(self._on_key_event)
        self.toolbar.rotate_clicked.connect(self._rotate_screen)
        self.toolbar.screen_awake_clicked.connect(self._toggle_screen_awake)
        self.toolbar.vol_up_clicked.connect(self._volume_up)
        self.toolbar.vol_down_clicked.connect(self._volume_down)
        self.toolbar.mute_clicked.connect(self._toggle_mute)
        self.toolbar.back_clicked.connect(lambda: self._send_key(2007))
        self.toolbar.home_clicked.connect(lambda: self._send_key(2003))
        self.toolbar.recent_clicked.connect(lambda: self._send_key(2049))
        self.toolbar.power_clicked.connect(lambda: self._send_key(2076))
        self.toolbar.screenshot_clicked.connect(self._take_screenshot)
        self.toolbar.record_clicked.connect(self._toggle_record)
        self.toolbar.fullscreen_clicked.connect(self._toggle_fullscreen)

        # 标题栏：置顶 / 最大化 / 收起工具栏
        self.title_bar.pin_btn.clicked.connect(self._toggle_window_pinned)
        self.title_bar.max_btn.clicked.connect(self._toggle_maximized)
        self.title_bar.collapse_btn.clicked.connect(self._toggle_toolbar)

    # ---------- 投屏生命周期 ----------
    def start_casting(self, device_id: str):
        """启动投屏（读取设备记忆配置并应用）。

        幂等：若服务已在投屏且目标设备相同，直接复用（show + 置顶），
        避免双击/重复触发把正在运行的投屏停掉（共享 HDCCastService 实例）。
        """
        if not self._hdc_cast:
            return
        if getattr(self._hdc_cast, "_running", False):
            if self._current_device == device_id and self._is_casting:
                self.show()
                self.raise_()
                self.activateWindow()
                return
            # 服务被其它入口占用（如内嵌投屏页）→ 提示先停止
            QMessageBox.warning(
                self, "提示",
                "设备正在其它窗口投屏中，请先停止当前投屏再试。"
            )
            return
        self._current_device = device_id
        self.title_bar.title_label.setText(f"为投个屏 · {device_id[:12]}")
        try:
            cfg = get_config_manager().get_or_create(device_id)
        except Exception:
            cfg = None

        try:
            if cfg is not None:
                self._hdc_cast.apply_cast_config(cfg)
                mode = cfg.cast_engine_mode
            else:
                mode = "agent_jpeg"
            ok = self._hdc_cast.connect_device(device_id)
            if not ok:
                QMessageBox.warning(self, "连接失败", f"无法连接设备 {device_id}")
                self.close()
                return
            res = self._hdc_cast.get_device_screen_size()
            self.phone_screen.set_resolution(*res)
            success = self._hdc_cast.start_casting(mode=mode)
            if not success:
                QMessageBox.warning(self, "提示", "投屏启动失败，请检查设备连接")
                self.close()
                return
        except Exception as e:
            QMessageBox.critical(self, "错误", f"投屏启动异常: {str(e)}")
            self.close()
            return

        self._is_casting = True
        self._frame_timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

    def stop_casting(self):
        self._frame_timer.stop()
        self._is_casting = False
        if self._hdc_cast is not None:
            try:
                self._hdc_cast.stop_casting()
            except Exception:
                pass

    def closeEvent(self, event):
        # 录制中关闭：释放 writer 并清理临时文件
        if self._is_recording:
            self._is_recording = False
            if self._record_writer is not None:
                try:
                    self._record_writer.release()
                except Exception:
                    pass
                self._record_writer = None
            if self._record_tmp and os.path.exists(self._record_tmp):
                try:
                    os.remove(self._record_tmp)
                except Exception:
                    pass
                self._record_tmp = None
        self.stop_casting()
        super().closeEvent(event)

    # ---------- 帧流 ----------
    def _poll_latest_frame(self):
        """按帧版本号去重拉取最新帧（与服务端单槽缓冲配合）"""
        if not self._hdc_cast or not self._is_casting:
            return
        try:
            version = self._hdc_cast.frame_version
            if version == self._last_frame_version:
                return
            frame = self._hdc_cast.get_latest_frame()
            if frame is None:
                return
            self._last_frame_version = version
            self.phone_screen.set_frame(frame)
            if self._is_recording:
                self._write_record_frame(frame)
        except Exception:
            pass

    def _on_fps_updated(self, fps: int):
        self.toolbar.update_fps(fps)
        self.title_bar.fps_label.setText(f"{fps} FPS")

    def _on_error(self, error: str):
        self.toolbar.update_fps(0)
        self.title_bar.fps_label.setText("-- FPS")

    # ---------- 输入 ----------
    def _on_touch_event(self, x: int, y: int, action: str):
        if self._hdc_cast and self._current_device:
            # scrcpy 语义：ACTION_DOWN=0, ACTION_UP=1, ACTION_MOVE=2
            action_map = {"down": 0, "up": 1, "move": 2}
            self._hdc_cast.send_touch(x, y, action_map.get(action, 0))

    def _on_key_event(self, event_type: str, data: dict):
        if not self._input_mgr:
            return
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
            self._input_mgr.send_text(data.get("text", ""))
        elif event_type in self._input_mgr.KEY_MAP:
            modifiers = data.get("modifiers", [])
            if modifiers:
                self._input_mgr.send_combo(modifiers, event_type)
            else:
                self._input_mgr.send_key(event_type)

    def _send_key(self, key_code: int):
        if self._hdc_cast and self._current_device:
            self._hdc_cast.send_key(key_code)

    # ---------- 工具栏动作 ----------
    def _rotate_screen(self):
        pass  # 设备端旋转由系统控制，预留

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

    # ---------- 标题栏动作 ----------
    def _toggle_window_pinned(self):
        """窗口置顶：以标题栏"置顶"按钮勾选态为准。"""
        from PySide6.QtCore import Qt as _Qt
        win = self.window()
        if win is None:
            return
        pinned = self.title_bar.pin_btn.isChecked()
        flags = win.windowFlags()
        if pinned:
            win.setWindowFlags(flags | _Qt.WindowType.WindowStaysOnTopHint)
        else:
            win.setWindowFlags(flags & ~_Qt.WindowType.WindowStaysOnTopHint)
        win.show()  # setWindowFlags 后需要重新 show 才会生效

    def _toggle_maximized(self):
        """最大化 / 还原窗口。

        用 windowState 位判断并显式 setWindowState 切换 ——
        showNormal() 在无边框窗口上偶发第一次点击不生效（状态与
        显示不同步），显式设置 WindowNoState 可保证一次点击必然还原。
        """
        win = self.window()
        if win is None:
            return
        state = win.windowState()
        if state & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen):
            win.setWindowState(Qt.WindowState.WindowNoState)
        else:
            win.setWindowState(state | Qt.WindowState.WindowMaximized)
        # 按钮文字随状态切换，含义更清楚
        maxed = bool(win.windowState() & Qt.WindowState.WindowMaximized)
        self.title_bar.max_btn.setText("还原" if maxed else "最大化")

    def _toggle_toolbar(self):
        """收起 / 展开右侧工具栏。"""
        visible = self.toolbar.isVisible()
        self.toolbar.setVisible(not visible)
        self.title_bar.collapse_btn.setText("收起" if visible else "展开")
        self.title_bar.collapse_btn.setToolTip(
            "收起右侧工具栏" if visible else "展开右侧工具栏"
        )

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

    def _take_screenshot(self):
        if self.phone_screen._frame is None:
            QMessageBox.warning(self, "提示", "没有可截图的画面")
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存截图", f"screenshot_{timestamp}.png", "PNG 图片 (*.png)"
        )
        if path:
            frame = self.phone_screen._frame
            h, w, ch = frame.shape
            q_img = QImage(
                frame.tobytes(), w, h, ch * w, QImage.Format.Format_BGR888
            )
            q_img.save(path, "PNG")
            QMessageBox.information(self, "成功", f"截图已保存到:\n{path}")

    def _toggle_record(self):
        if self._is_recording:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self):
        import tempfile
        self._is_recording = True
        self._record_start_time = time.time()
        self._record_writer = None  # cv2.VideoWriter，收到首帧时初始化（需尺寸）
        # mkstemp 独占创建唯一临时文件（避免可预测路径的符号链接/覆写攻击面）
        fd, self._record_tmp = tempfile.mkstemp(
            suffix=".mp4", prefix="weitouping_rec_"
        )
        os.close(fd)
        self.toolbar.set_recording(True)

    def _write_record_frame(self, frame):
        """录制帧流式写入临时文件（避免内存累积：1800 帧全分辨率可达 GB 级）"""
        try:
            import cv2
            if self._record_writer is None:
                h, w = frame.shape[:2]
                self._record_writer = cv2.VideoWriter(
                    self._record_tmp, cv2.VideoWriter_fourcc(*'mp4v'), 30, (w, h)
                )
            self._record_writer.write(frame)  # BGR 帧直接写
        except Exception:
            pass

    def _stop_record(self):
        self._is_recording = False
        self.toolbar.set_recording(False)
        duration = time.time() - self._record_start_time
        writer = self._record_writer
        self._record_writer = None
        if writer is not None:
            try:
                writer.release()
            except Exception:
                pass
        if not self._record_tmp or not os.path.exists(self._record_tmp) \
                or os.path.getsize(self._record_tmp) == 0:
            QMessageBox.warning(self, "提示", "没有录制到任何帧")
            if self._record_tmp and os.path.exists(self._record_tmp):
                try:
                    os.remove(self._record_tmp)
                except Exception:
                    pass
            self._record_tmp = None
            return
        import shutil
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存录屏", f"recording_{timestamp}.mp4", "MP4 视频 (*.mp4)"
        )
        if path:
            try:
                shutil.move(self._record_tmp, path)
                QMessageBox.information(
                    self, "成功",
                    f"录屏已保存到:\n{path}\n时长: {duration:.1f}s"
                )
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")
        else:
            try:
                os.remove(self._record_tmp)
            except Exception:
                pass
        self._record_tmp = None

    # ---------- 窗口事件 ----------
    def keyPressEvent(self, event):
        if self.phone_screen is not None:
            self.phone_screen.keyPressEvent(event)
            return
        super().keyPressEvent(event)

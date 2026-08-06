"""
投屏配置独立弹窗
- 可在投屏前（设备列表页）或投屏中（投屏页）调用
- 只操作 CastConfigManager，不直接操作 HDCCastService，避免 UI 线程阻塞
- 保存后返回 CastConfig，由调用方决定是否热重启投屏
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QCheckBox, QWidget
)
from PySide6.QtCore import Qt, Signal

from core.cast_config import get_config_manager, CastConfig


# ---------- 自定义控件：模式卡片 ----------
class ModeCardFrame(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = False
        self._check_label = None
        self.set_selected(False)

    def set_selected(self, value: bool):
        self._selected = value
        if value:
            self.setStyleSheet(
                "QFrame#modeCard { background: #F0F7FF; border: 2px solid #007DFF; border-radius: 12px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#modeCard { background: #FFFFFF; border: 1.5px solid #E5E8EB; border-radius: 12px; }"
                "QFrame#modeCard:hover { border-color: #80BFFF; background: #FAFBFC; }"
            )
        if self._check_label:
            self._check_label.setVisible(value)

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ---------- 投屏配置弹窗 ----------
class CastConfigDialog(QDialog):
    """
    独立投屏配置弹窗。
    使用方式:
        dlg = CastConfigDialog(device_id, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg = dlg.result_config  # 获取保存后的 CastConfig
    """

    def __init__(self, device_id: str, parent=None,
                 on_saved: callable = None):
        """
        :param device_id: 目标设备 ID
        :param parent: 父控件
        :param on_saved: 保存成功后的回调，签名：(CastConfig) -> None
        """
        super().__init__(parent)
        self._device_id = device_id
        self._on_saved = on_saved
        self._cfg_mgr = get_config_manager()

        # 读取当前配置
        self._cfg = self._cfg_mgr.get_or_create(device_id)

        # 弹窗属性
        self.setWindowTitle(f"投屏配置 - {device_id}")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Popup
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(480, 620)

        # 控件引用（供保存时读取）
        self._dlg_mode = self._cfg.capture_mode
        self._dlg_mode_jpeg_card = None
        self._dlg_mode_h264_card = None
        self._dlg_screen_combo = None
        self._dlg_fps_combo = None
        self._dlg_bitrate_combo = None
        self._dlg_scale_combo = None
        self._dlg_remember_check = None

        self._build_ui()

    # ---------- UI 构建 ----------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        root = QFrame()
        root.setObjectName("castCfgRoot")
        root.setStyleSheet(
            "QFrame#castCfgRoot { background: #FFFFFF; border: 1px solid #E5E8EB; border-radius: 16px; }"
        )
        outer.addWidget(root)

        v = QVBoxLayout(root)
        v.setContentsMargins(28, 20, 28, 20)
        v.setSpacing(0)

        # === 标题栏 ===
        head = QHBoxLayout()
        device_name = self._device_id
        if len(device_name) > 20:
            device_name = device_name[:20] + "..."
        title = QLabel(f"投屏配置 - {device_name}")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #182431;")
        head.addWidget(title, 1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #99A2B1; border: none;"
            "font-size: 16px; border-radius: 14px; }"
            "QPushButton:hover { background: #F1F3F5; color: #007DFF; }"
        )
        close_btn.clicked.connect(self.close)
        head.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)
        v.addSpacing(16)

        # === 投屏模式（按用户要求只保留两种：图片传输 / 视频传输） ===
        v.addWidget(self._build_section_label("投屏模式"))
        v.addSpacing(8)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)

        # 历史配置若为 agent_jpeg（入口已下线），归一为 h264 显示
        if self._dlg_mode not in ("jpeg", "h264"):
            self._dlg_mode = "h264"

        jpeg_card = self._build_mode_card(
            "🖼️", "JPEG", "图片流传输，兼容性好",
            selected=(self._dlg_mode == "jpeg")
        )
        jpeg_card.clicked.connect(lambda: self._on_mode_pick("jpeg"))
        mode_row.addWidget(jpeg_card, 1)

        h264_card = self._build_mode_card(
            "🎬", "H.264", "视频流传输，低延迟",
            selected=(self._dlg_mode == "h264")
        )
        h264_card.clicked.connect(lambda: self._on_mode_pick("h264"))
        mode_row.addWidget(h264_card, 1)

        v.addLayout(mode_row)
        self._dlg_mode_jpeg_card = jpeg_card
        self._dlg_mode_h264_card = h264_card

        v.addSpacing(20)

        # === 显示设置 ===
        v.addWidget(self._build_section_label("显示设置"))
        v.addSpacing(10)

        r1 = QHBoxLayout()
        r1.setSpacing(14)
        v.addLayout(r1)
        r1.addWidget(self._build_combo_field(
            "屏幕 ID", [str(i) for i in range(5)],
            str(self._cfg.screen_id), "screen"
        ), 1)
        # 服务端帧率上限已放开到 120 FPS（H.264 通道支持 5-120）
        r1.addWidget(self._build_combo_field(
            "帧率", [f"{f} fps" for f in (15, 30, 45, 60, 90, 120)],
            f"{self._cfg.fps} fps", "fps"
        ), 1)

        v.addSpacing(14)

        r2 = QHBoxLayout()
        r2.setSpacing(14)
        v.addLayout(r2)

        bitrate_opts = ["2 MB/s", "5 MB/s", "8 MB/s", "10 MB/s", "15 MB/s",
                        "20 MB/s", "30 MB/s", "50 MB/s", "80 MB/s"]
        default_br = f"{self._cfg.bitrate_mbps} MB/s"
        if default_br not in bitrate_opts:
            bitrate_opts.append(default_br)
        r2.addWidget(self._build_combo_field(
            "码率", bitrate_opts, default_br, "bitrate", h264_only=True
        ), 1)

        scale_opts = [f"{s}%" for s in (25, 33, 50, 67, 75, 100)]
        default_sc = f"{self._cfg.scale_pct}%"
        if default_sc not in scale_opts:
            scale_opts.append(default_sc)
        r2.addWidget(self._build_combo_field(
            "缩放", scale_opts, default_sc, "scale"
        ), 1)

        # 编码节奏（H.264 性能档位，repeatInterval ms）：33=HoKit 同款，16=高性能，8=极速
        perf_opts = ["标准 (33ms)", "高性能 (16ms)", "极速 (8ms)"]
        perf_map = {"标准 (33ms)": 33, "高性能 (16ms)": 16, "极速 (8ms)": 8}
        default_perf = "高性能 (16ms)"
        for _k, _v in perf_map.items():
            if _v == self._cfg.repeat_interval:
                default_perf = _k
                break
        self._perf_label = QLabel("编码节奏")
        self._perf_label.setStyleSheet("color:#99A2B1;font-size:12px;")
        self._perf_combo = QComboBox()
        self._perf_combo.addItems(perf_opts)
        self._perf_combo.setCurrentText(default_perf)
        self._perf_combo.setEnabled(False)  # 默认跟随 H.264 开关
        r2.addWidget(self._perf_label, 1)
        r2.addWidget(self._perf_combo, 1)
        self._perf_map = perf_map

        v.addSpacing(20)

        # 分隔线
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #E5E8EB;")
        v.addWidget(divider)
        v.addSpacing(14)

        # === 记住此配置 ===
        remember_row = QHBoxLayout()
        icon_lbl = QLabel("💾")
        icon_lbl.setFixedSize(24, 24)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 16px;")
        remember_row.addWidget(icon_lbl, 0)

        rlbl = QLabel("记住此配置")
        rlbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #182431;")
        remember_row.addWidget(rlbl, 1)

        self._dlg_remember_check = QCheckBox()
        self._dlg_remember_check.setChecked(self._cfg.remember)
        self._dlg_remember_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dlg_remember_check.setStyleSheet("""
            QCheckBox::indicator { width: 36px; height: 20px; border-radius: 10px;
                background: #C4C6CC; }
            QCheckBox::indicator:checked { background: #007DFF; }
            QCheckBox::indicator::before { content: ''; width: 16px; height: 16px;
                border-radius: 8px; background: white;
                position: relative; top: 2px; left: 2px; }
            QCheckBox::indicator:checked::before { left: 18px; }
        """)
        remember_row.addWidget(self._dlg_remember_check, 0, Qt.AlignmentFlag.AlignRight)
        v.addLayout(remember_row)

        v.addStretch()

        # === 按钮 ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(44)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            "QPushButton { background: #FFFFFF; color: #99A2B1; border: 1.5px solid #E5E8EB;"
            "border-radius: 10px; font-size: 14px; font-weight: 700; }"
            "QPushButton:hover { background: #E6F0FF; color: #007DFF; border-color: #80BFFF; }"
        )
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn, 1)

        save_btn = QPushButton("保存配置")
        save_btn.setFixedHeight(44)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            "QPushButton { background: #007DFF; color: #FFFFFF; border: none;"
            "border-radius: 10px; font-size: 14px; font-weight: 700; }"
            "QPushButton:hover { background: #0066CC; }"
            "QPushButton:pressed { background: #0052D9; }"
        )
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn, 1)

        v.addLayout(btn_row)

        # 初始化字段启用状态
        self._update_h264_fields(self._cfg.is_h264)

    # ---------- UI 辅助构建 ----------
    def _build_section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #99A2B1;")
        return lbl

    def _build_mode_card(self, icon_text: str, title: str, subtitle: str,
                         selected: bool = False) -> ModeCardFrame:
        card = ModeCardFrame()
        card.setObjectName("modeCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        icon = QLabel(icon_text)
        icon.setFixedSize(28, 28)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 22px;")
        top.addWidget(icon, 0)
        top.addStretch(1)
        check = QLabel("✓")
        check.setObjectName("modeCardCheck")
        check.setFixedSize(20, 20)
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check.setStyleSheet(
            "color: #FFFFFF; background: #007DFF; border-radius: 10px;"
            "font-size: 12px; font-weight: 900;"
        )
        top.addWidget(check, 0)
        layout.addLayout(top)

        t = QLabel(title)
        t.setStyleSheet("font-size: 16px; font-weight: 700; color: #182431;")
        layout.addWidget(t)

        s = QLabel(subtitle)
        s.setWordWrap(True)  # 小字完整显示，不截断
        s.setStyleSheet(
            "font-size: 12px; color: #99A2B1; font-weight: 500;"
            "line-height: 1.4;"
        )
        layout.addWidget(s)

        card._check_label = check
        card.set_selected(selected)
        return card

    def _build_combo_field(self, label_text: str, options: list, current: str,
                           field: str, h264_only: bool = False) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        head = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #99A2B1;")
        head.addWidget(lbl, 1)
        if h264_only:
            tag = QLabel("仅 H.264")
            tag.setStyleSheet(
                "font-size: 10px; font-weight: 700; color: #FF8F1F;"
                "background: #FFF4E6; padding: 2px 8px; border-radius: 999px;"
            )
            head.addWidget(tag, 0)
        lay.addLayout(head)

        combo = QComboBox()
        combo.addItems(options)
        idx = combo.findText(current)
        if idx < 0:
            idx = 0
        combo.setCurrentIndex(idx)
        combo.setFixedHeight(44)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.setStyleSheet("""
            QComboBox { background: #FFFFFF; border: 1.5px solid #E5E8EB; border-radius: 10px;
                padding: 0 14px; color: #182431; font-size: 14px; font-weight: 600; }
            QComboBox:hover { border-color: #80BFFF; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView { background: #FFFFFF; border: 1px solid #E5E8EB;
                border-radius: 8px; padding: 6px; selection-background-color: #E6F0FF;
                selection-color: #007DFF; }
        """)

        # 绑定引用
        if field == "screen":
            self._dlg_screen_combo = combo
        elif field == "fps":
            self._dlg_fps_combo = combo
        elif field == "bitrate":
            self._dlg_bitrate_combo = combo
        elif field == "scale":
            self._dlg_scale_combo = combo
        lay.addWidget(combo)
        return wrap

    # ---------- 交互逻辑 ----------
    def _on_mode_pick(self, mode: str):
        self._dlg_mode = mode
        is_h264 = (mode == "h264")
        if self._dlg_mode_jpeg_card:
            self._dlg_mode_jpeg_card.set_selected(mode == "jpeg")
        if self._dlg_mode_h264_card:
            self._dlg_mode_h264_card.set_selected(mode == "h264")
        self._update_h264_fields(is_h264)

    def _update_h264_fields(self, is_h264: bool):
        """切换 H.264 only 字段启用状态"""
        if self._dlg_bitrate_combo:
            self._dlg_bitrate_combo.setEnabled(is_h264)
        if getattr(self, "_perf_combo", None):
            self._perf_combo.setEnabled(is_h264)
        if getattr(self, "_perf_label", None):
            self._perf_label.setEnabled(is_h264)

    def _on_save(self):
        """保存配置到 CastConfigManager，不操作投屏服务"""
        def _combo_int(combo: QComboBox, suffix: str, default: int) -> int:
            if combo is None:
                return default
            txt = combo.currentText().replace(suffix, "").strip()
            try:
                return int(float(txt))
            except Exception:
                return default

        mode = self._dlg_mode
        screen_id = _combo_int(self._dlg_screen_combo, "", 0)
        fps = _combo_int(self._dlg_fps_combo, "fps", 30)
        bitrate = _combo_int(self._dlg_bitrate_combo, "MB/s", 30)
        scale = _combo_int(self._dlg_scale_combo, "%", 50)
        repeat = 16
        if getattr(self, "_perf_combo", None) is not None:
            repeat = self._perf_map.get(self._perf_combo.currentText(), 16)
        remember = bool(self._dlg_remember_check.isChecked()) if self._dlg_remember_check else False

        cfg = CastConfig(
            capture_mode=mode,
            fps=fps,
            bitrate_mbps=bitrate,
            scale_pct=scale,
            screen_id=screen_id,
            repeat_interval=repeat,
            remember=remember,
        )

        # 写入配置管理器（持久化到磁盘）
        self._cfg_mgr.set(self._device_id, cfg, save=True)
        self._cfg = cfg

        # 设置结果配置，供外部读取
        self.result_config = cfg

        # 回调通知
        if self._on_saved:
            try:
                self._on_saved(cfg)
            except Exception:
                pass

        self.accept()

    @property
    def result_config(self) -> CastConfig:
        """保存后可读取的配置对象"""
        if not hasattr(self, '_result_config'):
            return self._cfg
        return self._result_config

    @result_config.setter
    def result_config(self, value: CastConfig):
        self._result_config = value

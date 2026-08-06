"""
设备投屏页面 - 严格参考参考图1设计
- 顶部：标题 + 副标题 + 右侧刷新/WiFi连接按钮
- 设备卡片列表：手机图标 + 名称型号 + 在线徽章 + 三列参数 + 开始投屏/投屏配置按钮
- 底部：大尺寸涟漪装饰
- 严格使用 ys/xys/images 中的 Element_* 设计元素
"""
import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, QSize, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QLinearGradient, QBrush, QPixmap

from ui.cast_config_dialog import CastConfigDialog


def _base_dir():
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _img_dir():
    """图片素材目录"""
    return os.path.join(_base_dir(), "ys", "xys", "images")


def _load_el(name: str) -> QPixmap:
    """加载设计元素（Element_*.png）"""
    p = os.path.join(_img_dir(), name)
    if os.path.exists(p):
        pm = QPixmap(p)
        if not pm.isNull():
            return pm
    return QPixmap()


class HeroPillDecor(QWidget):
    """头部装饰 - 使用 Element_01.png (设备投屏 3D pill)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedHeight(80)
        self._pm = _load_el("Element_01.png")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            target_h = self.height()
            target_w = self._pm.width() * target_h // max(self._pm.height(), 1)
            scaled = self._pm.scaled(target_w, target_h,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            p.setOpacity(0.18)
            p.drawPixmap(self.width() - scaled.width() - 10, 0, scaled)
            p.setOpacity(1.0)
        p.end()


class _VerticalRibbon(QWidget):
    """垂直装饰条 - 使用 Element_09 或 Element_20"""
    def __init__(self, element_name: str, opacity: float = 0.5, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pm = _load_el(element_name)
        self._opacity = opacity

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(),
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.setOpacity(self._opacity)
            p.drawPixmap(x, y, scaled)
            p.setOpacity(1.0)
        p.end()


# ========== 涟漪装饰 ==========
class RippleDecor(QWidget):
    """底部大涟漪装饰 - 使用 Element_18.png"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pm = _load_el("Element_18.png")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if not self._pm.isNull():
            # 居中偏下显示，足够大但留白
            target_w = int(min(w, h) * 0.85)
            target_h = self._pm.height() * target_w // max(self._pm.width(), 1)
            if target_h > int(h * 0.85):
                target_h = int(h * 0.85)
                target_w = self._pm.width() * target_h // max(self._pm.height(), 1)
            scaled = self._pm.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            x = (w - target_w) // 2
            y = h - target_h + 10
            p.setOpacity(0.6)
            p.drawPixmap(x, y, scaled)
            p.setOpacity(1.0)
        else:
            cx, cy = w * 0.5, h * 0.92
            for i in range(8):
                r = 30 + i * 52
                alpha = 22 - i * 2.6
                if alpha <= 0:
                    break
                p.setPen(QPen(QColor(0, 125, 255, int(alpha)), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# ========== 设备卡片 ==========
class DeviceCard(QFrame):
    """设备卡片 - 严格参考参考图1设备卡片样式"""
    cast_requested = Signal(str)
    config_requested = Signal(str)

    def __init__(self, device_info: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("deviceCard")
        self.setStyleSheet(
            "QFrame#deviceCard { background-color: #FFFFFF; border-radius: 12px;"
            "border: 1px solid #E5E8EB; }"
            "QFrame#deviceCard:hover { border-color: #80BFFF; }"
        )
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Preferred)
        self.device_id = device_info.get("id", "")
        self.device_info = device_info
        self._init_config_btn = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(20)

        # ===== 左侧：手机图标 =====
        icon_f = QFrame()
        icon_f.setFixedSize(QSize(64, 64))
        icon_f.setStyleSheet(
            "QFrame { background-color: #E6F0FF; border-radius: 12px;"
            "border: 1px solid #CCE5FF; }"
        )
        il = QVBoxLayout(icon_f)
        il.setContentsMargins(0, 0, 0, 0)
        # 使用 Element_14 作为设备图标（如果没有则用 Element_07）
        ipm = _load_el("Element_14.png")
        if ipm.isNull():
            ipm = _load_el("Element_07.png")
        if not ipm.isNull():
            l = QLabel()
            l.setPixmap(ipm.scaled(38, 38, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            l = QLabel("📱")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet("font-size: 28px;")
        il.addWidget(l)
        layout.addWidget(icon_f, 0, Qt.AlignmentFlag.AlignVCenter)

        # ===== 中部：设备信息 + 参数 =====
        info_col = QVBoxLayout()
        info_col.setSpacing(8)
        info_col.setContentsMargins(0, 0, 0, 0)

        # 第一行：设备名 + 型号
        name = QLabel(device_info.get("name", "HarmonyOS 设备"))
        name.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #182431; letter-spacing: 0.2px;"
        )
        info_col.addWidget(name)

        model_lbl = QLabel(f"型号：{device_info.get('model', '--')}")
        model_lbl.setStyleSheet("font-size: 12px; color: #99A2B1; font-weight: 600;")
        info_col.addWidget(model_lbl)

        # 第二行：参数列（设备名称 / 版本号 / 分辨率）
        param_row = QHBoxLayout()
        param_row.setSpacing(36)
        param_row.setContentsMargins(0, 6, 0, 0)

        params = [
            ("设备名称", device_info.get("name_short", "16dp")),
            ("版本号", device_info.get("version", "6.1.0.125(SP15C00E126R2P4)")),
            ("分辨率", device_info.get("resolution", "--")),
        ]
        for title, val in params:
            pf = QFrame()
            pf.setStyleSheet("QFrame { background: transparent; }")
            pl = QVBoxLayout(pf)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(4)
            t = QLabel(title)
            t.setStyleSheet(
                "font-size: 11px; color: #99A2B1; font-weight: 700; letter-spacing: 0.3px;"
            )
            v = QLabel(val)
            v.setStyleSheet("font-size: 13px; color: #182431; font-weight: 700;")
            v.setWordWrap(True)
            pl.addWidget(t)
            pl.addWidget(v)
            param_row.addWidget(pf, 0)

        param_row.addStretch()
        param_wrap = QWidget()
        param_wrap.setLayout(param_row)
        info_col.addWidget(param_wrap)

        info_wrap = QWidget()
        info_wrap.setLayout(info_col)
        info_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(info_wrap, 1)

        # ===== 右侧：在线状态 + 开始投屏按钮 =====
        right_col = QVBoxLayout()
        right_col.setSpacing(14)
        right_col.setContentsMargins(0, 0, 0, 0)

        # 在线徽章
        status_f = QFrame()
        status_f.setStyleSheet(
            "QFrame { background-color: #E6F0FF; border: 1px solid #80BFFF;"
            "border-radius: 999px; }"
        )
        sl = QHBoxLayout(status_f)
        sl.setContentsMargins(12, 5, 12, 5)
        sl.setSpacing(4)
        dot = QLabel("●")
        dot.setStyleSheet("color: #007DFF; font-size: 10px; background: transparent; border: none;")
        sl.addWidget(dot)
        st = QLabel("在线")
        st.setStyleSheet(
            "font-size: 12px; font-weight: 700; color: #007DFF; background: transparent; border: none;"
        )
        sl.addWidget(st)
        right_col.addWidget(status_f, 0, Qt.AlignmentFlag.AlignRight)

        right_col.addStretch()

        # 开始投屏按钮
        self.cast_btn = QPushButton("开始投屏")
        self.cast_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cast_btn.setStyleSheet(
            "QPushButton { background-color: #007DFF; color: #FFFFFF; border: none;"
            "border-radius: 999px; padding: 12px 32px; font-weight: 700; font-size: 14px; }"
            "QPushButton:hover { background-color: #0066CC; }"
            "QPushButton:pressed { background-color: #0052D9; }"
        )
        self.cast_btn.clicked.connect(lambda: self.cast_requested.emit(self.device_id))
        right_col.addWidget(self.cast_btn, 0, Qt.AlignmentFlag.AlignRight)

        # 投屏配置按钮
        self.config_btn = QPushButton("投屏配置")
        self.config_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.config_btn.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #5A6370; border: 1.5px solid #E5E8EB;"
            "border-radius: 999px; padding: 10px 24px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #E6F0FF; color: #007DFF; border-color: #80BFFF; }"
            "QPushButton:pressed { background-color: #CCE5FF; }"
        )
        self.config_btn.clicked.connect(lambda: self.config_requested.emit(self.device_id))
        right_col.addWidget(self.config_btn, 0, Qt.AlignmentFlag.AlignRight)

        right_wrap = QWidget()
        right_wrap.setLayout(right_col)
        layout.addWidget(right_wrap, 0)


# ========== 设备投屏页面 ==========
class DevicePage(QWidget):
    """设备投屏页面 - 严格参考参考图1设计"""
    start_cast_requested = Signal(str)

    def __init__(self, hdc_client, parent=None):
        super().__init__(parent)
        self.hdc = hdc_client
        self._build_ui()
        # 启动时自动拉取真实设备列表
        QTimer.singleShot(120, self._refresh_devices)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)

        # ===== 顶部 Header =====
        header = QHBoxLayout()
        header.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        page_title = QLabel("设备投屏")
        page_title.setStyleSheet(
            "font-size: 26px; font-weight: 700; color: #182431; letter-spacing: 0.3px;"
        )
        title_col.addWidget(page_title)
        page_sub = QLabel("连接 HarmonyOS 设备并开始投屏")
        page_sub.setStyleSheet("font-size: 13px; color: #99A2B1; font-weight: 500;")
        title_col.addWidget(page_sub)
        title_wrap = QWidget()
        title_wrap.setLayout(title_col)
        title_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(title_wrap, 1)

        # 右侧按钮组
        self.refresh_btn = QPushButton("🔄  刷新")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #182431;"
            "border: 1.5px solid #E5E8EB; border-radius: 8px; padding: 9px 20px;"
            "font-size: 13px; font-weight: 700; }"
            "QPushButton:hover { background-color: #E6F0FF; color: #007DFF; border-color: #80BFFF; }"
            "QPushButton:pressed { background-color: #CCE5FF; }"
        )
        self.refresh_btn.setFixedHeight(40)
        self.refresh_btn.clicked.connect(self._refresh_devices)
        header.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignBottom)

        self.connect_btn = QPushButton("📶  WiFi 连接")
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.setStyleSheet(
            "QPushButton { background-color: #007DFF; color: #FFFFFF; border: none;"
            "border-radius: 8px; padding: 9px 22px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #0066CC; }"
            "QPushButton:pressed { background-color: #0052D9; }"
        )
        self.connect_btn.setFixedHeight(40)
        self.connect_btn.clicked.connect(self._wifi_connect_dialog)
        header.addWidget(self.connect_btn, 0, Qt.AlignmentFlag.AlignBottom)

        hw = QWidget()
        hw.setLayout(header)
        root.addWidget(hw)

        # Element_01 装饰（在内容区上方右侧）
        self._hero_pill = HeroPillDecor()
        self._hero_pill.setParent(self)
        self._hero_pill.move(10, 10)
        self._hero_pill.setFixedWidth(160)
        root.addWidget(self._hero_pill)

        # ===== 主体滚动区域（卡片 + 涟漪） =====
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }"
            "QScrollBar::handle:vertical { background: #C4C6CC; border-radius: 4px; min-height: 40px; }"
            "QScrollBar::handle:vertical:hover { background: #99A2B1; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
        )

        sc_content = QWidget()
        sc_content.setStyleSheet("background: transparent;")
        sc_l = QVBoxLayout(sc_content)
        sc_l.setContentsMargins(0, 0, 0, 0)
        sc_l.setSpacing(14)

        # 设备列表容器
        self._device_list_widget = QWidget()
        self._dl_lay = QVBoxLayout(self._device_list_widget)
        self._dl_lay.setContentsMargins(0, 0, 0, 0)
        self._dl_lay.setSpacing(12)
        sc_l.addWidget(self._device_list_widget, 0)

        # 涟漪区域 - 使用专门的涟漪装饰
        ripple_container = QFrame()
        ripple_container.setStyleSheet("QFrame { background: transparent; border: none; }")
        ripple_container.setMinimumHeight(280)
        ripple_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rl = QVBoxLayout(ripple_container)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addStretch()
        self._ripple = RippleDecor(ripple_container)
        sc_l.addWidget(ripple_container, 1)

        scroll.setWidget(sc_content)
        root.addWidget(scroll, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_ripple') and self._ripple:
            parent = self._ripple.parentWidget()
            if parent:
                self._ripple.setGeometry(0, 0, parent.width(), parent.height())

    # ===== 业务接口 =====
    def _refresh_devices(self):
        devices = []
        try:
            if self.hdc:
                devices = self.hdc.list_devices() or []
        except Exception:
            devices = []
        self._render_devices(devices)

    def _wifi_connect_dialog(self):
        ip, ok = QInputDialog.getText(self, "WiFi 连接", "请输入设备 IP 地址:")
        if ok and ip.strip():
            ip = ip.strip()
            try:
                success = bool(self.hdc.connect_device(ip))
            except Exception:
                success = False
            if success:
                QMessageBox.information(self, "连接成功", f"已连接设备 {ip}")
                # 刷新设备列表，让新设备出现在卡片中
                QTimer.singleShot(500, self._refresh_devices)
            else:
                QMessageBox.warning(
                    self, "连接失败",
                    f"无法连接 {ip}\n请确认设备已开启无线调试，"
                    "且 IP/端口（默认 5555）正确。"
                )

    def _render_devices(self, devices):
        """渲染设备列表 - 显示真实的 HDC 设备，不再使用样例数据"""
        # 清空旧卡片
        while self._dl_lay.count():
            it = self._dl_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        if not devices:
            self._dl_lay.addWidget(self._build_empty_state(), 1)
            return

        # 遍历真实设备：devices 为 (device_id, status) 列表
        for device_id, status in devices:
            dev_info = {
                "id": device_id,
                "status": status or "device",
            }
            # 从 HDC 拉取设备详细参数（HarmonyOS 专用参数名）
            try:
                if self.hdc and hasattr(self.hdc, "get_device_info"):
                    info = self.hdc.get_device_info(device_id) or {}
                    if info:
                        dev_info.update(info)
            except Exception:
                pass

            # 字段兼容：补齐 DeviceCard 期望的字段
            name = dev_info.get("name") or dev_info.get("model") or "HarmonyOS 设备"
            dev_info.setdefault("name", name)
            dev_info.setdefault("name_short", name)
            dev_info.setdefault("model", dev_info.get("model", "--"))
            dev_info.setdefault("version", dev_info.get("version", "--"))
            dev_info.setdefault("resolution", dev_info.get("resolution", "--"))

            card = DeviceCard(dev_info)
            card.cast_requested.connect(self._on_start_cast)
            card.config_requested.connect(self._on_open_config)
            self._dl_lay.addWidget(card)

        self._dl_lay.addStretch()

    def _build_empty_state(self) -> QWidget:
        """空态：未检测到设备"""
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        l = QVBoxLayout(wrap)
        l.setContentsMargins(0, 40, 0, 40)
        l.setSpacing(14)

        # 中心图标：使用 Element_07 作为设备连接示意图标
        icon_f = QFrame()
        icon_f.setFixedSize(QSize(120, 120))
        icon_f.setStyleSheet(
            "QFrame { background-color: #E6F0FF; border-radius: 60px; }"
        )
        il = QVBoxLayout(icon_f)
        il.setContentsMargins(0, 0, 0, 0)
        pm = _load_el("Element_07.png")
        if not pm.isNull():
            lbl = QLabel()
            lbl.setPixmap(pm.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            lbl = QLabel("📱")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 56px;")
        il.addWidget(lbl)
        iwrap = QHBoxLayout()
        iwrap.addStretch()
        iwrap.addWidget(icon_f)
        iwrap.addStretch()
        l.addLayout(iwrap)

        tip1 = QLabel("未检测到 HarmonyOS 设备")
        tip1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip1.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #182431; letter-spacing: 0.3px;"
        )
        l.addWidget(tip1)

        tip2 = QLabel("请使用 USB 数据线连接设备，并确保已开启 开发者选项 + USB 调试")
        tip2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip2.setWordWrap(True)
        tip2.setStyleSheet("font-size: 13px; color: #99A2B1; padding: 0 40px;")
        l.addWidget(tip2)

        l.addStretch()
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return wrap

    def _on_start_cast(self, device_id: str):
        self.start_cast_requested.emit(device_id)

    def _on_open_config(self, device_id: str):
        """打开投屏配置弹窗（投屏前即可设置）"""
        dlg = CastConfigDialog(device_id, self)
        dlg.exec()

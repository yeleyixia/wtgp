import os
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QStackedWidget, QStatusBar,
    QFrame, QLineEdit, QSizePolicy, QPushButton, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, QSize, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QIcon, QFont, QLinearGradient, QPainterPath

from core.hdc_client import HDCClient
from core.hdc_cast_service import HDCCastService
from core.input_manager import InputManager
from core.audio_manager import AudioManager
from ui.device_page import DevicePage
from ui.cast_page import CastPage
from ui.extensions_page import ExtensionsPage
from ui.settings_page import SettingsPage
from ui.performance_page import PerformancePage
from ui.toolbox_page import ToolboxPage


def get_base_dir() -> str:
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(name: str) -> str:
    base_dir = get_base_dir()
    candidates = [
        os.path.join(base_dir, "ys", "xys", "images", name),
        os.path.join(base_dir, "resources", "images", name),
        os.path.join(base_dir, "resources", name),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ys", "xys", "images", name),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def load_element_pixmap(name: str) -> QPixmap:
    path = get_resource_path(name)
    if path:
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            return pixmap
    return QPixmap()


# ========== 设计元素：涟漪装饰（参考 Element_18） ==========
class RippleDecor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._element_pixmap = load_element_pixmap("Element_18.png")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if not self._element_pixmap.isNull():
            pix_w = min(int(w * 0.55), int(h * 0.55), 340)
            pix_h = self._element_pixmap.height() * pix_w // max(self._element_pixmap.width(), 1)
            if pix_h > h * 0.55:
                pix_h = int(h * 0.55)
                pix_w = self._element_pixmap.width() * pix_h // max(self._element_pixmap.height(), 1)
            x = w - pix_w + 40
            y = h - pix_h + 40
            painter.setOpacity(0.55)
            painter.drawPixmap(int(x), int(y), self._element_pixmap.scaled(
                pix_w, pix_h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
            painter.setOpacity(1.0)
        else:
            cx, cy = w * 0.86, h * 0.94
            for i in range(7):
                radius = 22 + i * 44
                alpha = 18 - i * 2.3
                if alpha <= 0:
                    break
                painter.setPen(QPen(QColor(0, 125, 255, int(alpha)), 1.3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), radius, radius)
            cx2, cy2 = w * 0.06, h * 0.82
            for i in range(4):
                radius = 14 + i * 20
                alpha = 10 - i * 2
                if alpha <= 0:
                    break
                painter.setPen(QPen(QColor(77, 166, 255, int(alpha)), 0.8))
                painter.drawEllipse(QPointF(cx2, cy2), radius, radius)
        painter.end()


# ========== 状态指示器（参考 Element_19） ==========
class StatusDots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._status = 0
        self._element_pixmap = load_element_pixmap("Element_19.png")
        self.setMinimumSize(QSize(34, 10))

    def set_status(self, status: int):
        self._status = status
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._element_pixmap.isNull():
            scaled = self._element_pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled
            )
        else:
            dot_size = 8
            spacing = 12
            total_width = dot_size * 3 + spacing * 2
            start_x = (self.width() - total_width) / 2
            y = (self.height() - dot_size) / 2
            colors = [QColor(196, 198, 204), QColor(0, 184, 31), QColor(0, 125, 255)]
            for i in range(3):
                x = start_x + i * (dot_size + spacing)
                color = colors[min(self._status, 2)] if i <= self._status else QColor(196, 198, 204)
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QRectF(x, y, dot_size, dot_size))
        painter.end()


# ========== 导航列表项 ==========
class NavItemWidget(QWidget):
    clicked = Signal()

    def __init__(self, icon_text: str, label: str, element_name: str = "", parent=None):
        super().__init__(parent)
        self._selected = False
        self._label = label
        self._element_pixmap = load_element_pixmap(element_name) if element_name else QPixmap()

        self.setObjectName("navItemWidget")
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 14, 6)
        layout.setSpacing(12)

        # 渐变圆形图标容器
        icon_container = QFrame()
        icon_container.setObjectName("navIconCircle")
        icon_container.setFixedSize(QSize(36, 36))
        icon_container.setStyleSheet(
            "QFrame#navIconCircle { background-color: #007DFF; border-radius: 18px; border: none; }"
        )
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        if not self._element_pixmap.isNull():
            scaled_pixmap = self._element_pixmap.scaled(
                22, 22, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._icon_label = QLabel()
            self._icon_label.setPixmap(scaled_pixmap)
        else:
            self._icon_label = QLabel(icon_text)
            self._icon_label.setStyleSheet("font-size: 15px; color: #FFFFFF;")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(self._icon_label)
        layout.addWidget(icon_container, 0)

        self._text_label = QLabel(label)
        self._text_label.setObjectName("navItemText")
        self._text_label.setStyleSheet(
            "QLabel#navItemText { font-size: 14px; font-weight: 600; color: #182431; background: transparent; }"
        )
        layout.addWidget(self._text_label, 1)

        self._dot_indicator = QLabel()
        self._dot_indicator.setObjectName("navDot")
        self._dot_indicator.setFixedSize(8, 8)
        self._dot_indicator.setStyleSheet(
            "background-color: #C4C6CC; border-radius: 4px;"
        )
        layout.addWidget(self._dot_indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_style(False)

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_style(selected)

    def _apply_style(self, selected: bool):
        if selected:
            self.setStyleSheet(
                "QWidget#navItemWidget { background-color: #007DFF; border-radius: 8px; }"
            )
            self._text_label.setStyleSheet(
                "QLabel#navItemText { font-size: 14px; font-weight: 700; color: #FFFFFF; background: transparent; }"
            )
            if hasattr(self, '_icon_label') and self._icon_label.pixmap() is None:
                self._icon_label.setStyleSheet("font-size: 15px; color: #FFFFFF;")
            self._dot_indicator.setStyleSheet(
                "background-color: rgba(255,255,255,0.65); border-radius: 4px; min-width: 16px; max-width: 16px;"
            )
            icon_circle = self.findChild(QFrame, "navIconCircle")
            if icon_circle:
                icon_circle.setStyleSheet(
                    "QFrame#navIconCircle { background: rgba(255,255,255,0.25); border-radius: 18px; border: none; }"
                )
        else:
            self.setStyleSheet("")
            self._text_label.setStyleSheet(
                "QLabel#navItemText { font-size: 14px; font-weight: 600; color: #182431; background: transparent; }"
            )
            self._dot_indicator.setStyleSheet(
                "background-color: #C4C6CC; border-radius: 4px;"
            )
            icon_circle = self.findChild(QFrame, "navIconCircle")
            if icon_circle:
                icon_circle.setStyleSheet(
                    "QFrame#navIconCircle { background-color: #007DFF; border-radius: 18px; border: none; }"
                )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ========== 设置入口按钮（左下角独立） ==========
class SettingsEntryWidget(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        icon_frame = QFrame()
        icon_frame.setFixedSize(QSize(32, 32))
        icon_frame.setStyleSheet(
            "QFrame { background-color: #F5F5F5; border-radius: 16px; }"
        )
        il = QVBoxLayout(icon_frame)
        il.setContentsMargins(0, 0, 0, 0)
        el_pm = load_element_pixmap("Element_16.png")
        if not el_pm.isNull():
            lbl = QLabel()
            lbl.setPixmap(el_pm.scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            lbl = QLabel("⚙️")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 15px;")
        il.addWidget(lbl)
        layout.addWidget(icon_frame, 0)

        lbl = QLabel("设置")
        lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #99A2B1;")
        layout.addWidget(lbl, 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ========== 侧边栏 ==========
class Sidebar(QWidget):
    nav_clicked = Signal(str)
    settings_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setMinimumWidth(248)
        self.setMaximumWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(8)

        self._ripple = RippleDecor(self)
        self._ripple.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # ===== 品牌区 =====
        brand_container = QWidget()
        brand_container.setStyleSheet("background: transparent;")
        brand_container.setMinimumHeight(72)
        brand_layout = QHBoxLayout(brand_container)
        brand_layout.setContentsMargins(8, 4, 8, 8)
        brand_layout.setSpacing(12)

        # Logo
        logo_container = QFrame()
        logo_container.setObjectName("iconCircle")
        logo_container.setFixedSize(QSize(46, 46))
        logo_container.setStyleSheet(
            "QFrame#iconCircle { background-color: #007DFF; border-radius: 23px; border: none; }"
        )
        logo_layout = QVBoxLayout(logo_container)
        logo_layout.setContentsMargins(4, 4, 4, 4)
        logo_pixmap = load_element_pixmap("Element_07.png")
        if not logo_pixmap.isNull():
            scaled_logo = logo_pixmap.scaled(
                32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            logo_icon_label = QLabel()
            logo_icon_label.setPixmap(scaled_logo)
        else:
            logo_icon_label = QLabel("📺")
            logo_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_icon_label.setStyleSheet("font-size: 22px;")
        logo_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(logo_icon_label)
        brand_layout.addWidget(logo_container, 0)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        brand = QLabel("为投个屏")
        brand.setStyleSheet("font-size: 19px; font-weight: 700; color: #182431; letter-spacing: 0.4px;")
        brand_text.addWidget(brand)
        subtitle = QLabel("HarmonyOS")
        subtitle.setStyleSheet("font-size: 12px; color: #99A2B1; font-weight: 500;")
        brand_text.addWidget(subtitle)
        brand_layout.addLayout(brand_text, 1)
        layout.addWidget(brand_container)

        # ===== 导航列表（去掉搜索框与"导 航"标题，严格匹配参考图） =====
        nav_wrap = QWidget()
        nav_wrap_l = QVBoxLayout(nav_wrap)
        nav_wrap_l.setContentsMargins(0, 0, 0, 0)
        nav_wrap_l.setSpacing(6)

        # 按用户要求：只保留"设备投屏"，去掉工具箱/性能监控/扩展功能
        nav_items_data = [
            ("📱", "设备投屏", "device", "Element_07.png"),
        ]
        self._nav_widgets = []
        for (icon_text, label, page_id, el_name) in nav_items_data:
            nw = NavItemWidget(icon_text, label, el_name)
            nw.clicked.connect(lambda pid=page_id, w=nw: self._on_nav_clicked(pid, w))
            nav_wrap_l.addWidget(nw)
            self._nav_widgets.append((page_id, nw))
        layout.addWidget(nav_wrap)

        layout.addStretch(1)

        # ===== 底部：设置入口 + 版本号（去掉状态指示器，匹配参考图） =====
        bottom_wrap = QWidget()
        bottom_l = QVBoxLayout(bottom_wrap)
        bottom_l.setContentsMargins(2, 2, 2, 2)
        bottom_l.setSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #E5E8EB; margin: 2px 6px;")
        bottom_l.addWidget(sep)

        # 设置入口
        self._settings_entry = SettingsEntryWidget()
        self._settings_entry.clicked.connect(self.settings_clicked.emit)
        bottom_l.addWidget(self._settings_entry)

        # 版本号
        self.version_label = QLabel("版本号 2.0.0")
        self.version_label.setStyleSheet(
            "font-size: 11px; color: #99A2B1; padding: 6px 12px 4px 12px; font-weight: 600;"
        )
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        bottom_l.addWidget(self.version_label)

        layout.addWidget(bottom_wrap)

        # 默认选中第一个
        if self._nav_widgets:
            self._nav_widgets[0][1].set_selected(True)

    def _on_nav_clicked(self, page_id: str, widget: NavItemWidget):
        for pid, w in self._nav_widgets:
            w.set_selected(w is widget)
        self.nav_clicked.emit(page_id)

    def select_nav(self, page_id: str):
        for pid, w in self._nav_widgets:
            w.set_selected(pid == page_id)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_ripple'):
            self._ripple.setGeometry(0, 0, self.width(), self.height())


# ========== 主窗口 ==========
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.hdc_client = HDCClient()
        self.hdc_cast = HDCCastService()
        self.input_mgr = InputManager()
        self.audio_mgr = AudioManager()
        self._init_services()

        self.setWindowTitle("为投个屏 - HarmonyOS 投屏工具")
        # 合理默认尺寸 + 最小尺寸，避免挤压
        self.resize(1380, 860)
        self.setMinimumSize(1180, 720)

        self._sidebar_widget = Sidebar()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._sidebar_widget, 0)

        content_container = QWidget()
        content_container.setObjectName("content")
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("content")
        self.stack.setStyleSheet("QStackedWidget { background-color: #F1F3F5; border: none; }")

        self.device_page = DevicePage(self.hdc_client)
        self.toolbox_page = ToolboxPage()
        self.performance_page = PerformancePage()
        self.cast_page = CastPage(self.hdc_client)
        self.cast_page.set_hdc_cast_service(self.hdc_cast)
        self.cast_page.set_input_manager(self.input_mgr)
        self.cast_page.set_audio_manager(self.audio_mgr)
        # 独立投屏窗口（设备页投屏按钮 → 打开独立窗口）
        from ui.cast_window import CastWindow
        self.cast_window = CastWindow(
            self.hdc_client, self.hdc_cast, self.input_mgr, self.audio_mgr
        )
        self.extensions_page = ExtensionsPage(
            self.input_mgr, self.audio_mgr, self.hdc_cast
        )
        self.settings_page = SettingsPage()

        # 顺序：device(0), toolbox(1), performance(2), extensions(3), cast(4), settings(5)
        self.stack.addWidget(self.device_page)
        self.stack.addWidget(self.toolbox_page)
        self.stack.addWidget(self.performance_page)
        self.stack.addWidget(self.extensions_page)
        self.stack.addWidget(self.cast_page)
        self.stack.addWidget(self.settings_page)

        # 让 stack 有弹性空间，不会挤压
        stack_wrap = QWidget()
        sw = QVBoxLayout(stack_wrap)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.addWidget(self.stack)

        content_layout.addWidget(stack_wrap, 1)
        main_layout.addWidget(content_container, 1)

        # 状态栏
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")
        self.statusBar().setStyleSheet(
            "QStatusBar { background: #FFFFFF; color: #99A2B1; border-top: 1px solid #E5E8EB;"
            "font-size: 12px; padding: 4px 16px; }"
        )

        # 信号连接
        self._sidebar_widget.nav_clicked.connect(self._on_nav_changed)
        self._sidebar_widget.settings_clicked.connect(self._goto_settings)

        # 设备投屏 -> 投屏页跳转
        if hasattr(self.device_page, 'start_cast_requested'):
            self.device_page.start_cast_requested.connect(self._goto_cast)
        self.hdc_cast.connection_status.connect(self._on_cast_status)
        self.hdc_cast.fps_updated.connect(self._on_fps_updated)
        self.hdc_cast.fps_updated.connect(self.performance_page.set_fps)

    def _build_skill_placeholder(self):
        page = QWidget()
        page.setStyleSheet("background-color: #F1F3F5;")
        vl = QVBoxLayout(page)
        vl.setContentsMargins(40, 30, 40, 30)

        hd = QVBoxLayout()
        hd.setSpacing(4)
        t = QLabel("设备技能")
        t.setStyleSheet("font-size: 26px; font-weight: 700; color: #182431;")
        hd.addWidget(t)
        s = QLabel("快捷管理常用设备技能与自动化操作")
        s.setStyleSheet("font-size: 13px; color: #99A2B1; font-weight: 500;")
        hd.addWidget(s)
        hd_w = QWidget()
        hd_w.setLayout(hd)
        vl.addWidget(hd_w)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border-radius: 12px; border: 1px solid #E5E8EB; }"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(36, 48, 36, 48)
        cl.setSpacing(16)
        icon_f = QFrame()
        icon_f.setFixedSize(QSize(84, 84))
        icon_f.setStyleSheet(
            "QFrame { background-color: #E6F0FF; border-radius: 42px; }"
        )
        il = QVBoxLayout(icon_f)
        il.setContentsMargins(0, 0, 0, 0)
        pm = load_element_pixmap("Element_02.png")
        if not pm.isNull():
            l = QLabel()
            l.setPixmap(pm.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation))
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            l = QLabel("🎛️")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet("font-size: 36px;")
        il.addWidget(l)
        iw = QHBoxLayout()
        iw.addStretch()
        iw.addWidget(icon_f)
        iw.addStretch()
        cl.addLayout(iw)
        tt = QLabel("设备技能即将上线")
        tt.setStyleSheet("font-size: 20px; font-weight: 700; color: #182431;")
        tt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(tt)
        dd = QLabel("设备技能板块将在后续版本开放，敬请期待。")
        dd.setStyleSheet("font-size: 13px; color: #99A2B1; line-height: 1.8;")
        dd.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dd.setWordWrap(True)
        cl.addWidget(dd)
        cl.addStretch()

        cw = QHBoxLayout()
        cw.addStretch()
        cw.addWidget(card, 1)
        cw.addStretch()
        cw_w = QWidget()
        cw_w.setLayout(cw)
        vl.addWidget(cw_w, 1)
        return page

    def _init_services(self):
        self.input_mgr.set_cast_engine(self.hdc_cast)
        self.audio_mgr.set_auto_mute(True)

    def _on_nav_changed(self, page_id: str):
        page_map = {"device": 0, "toolbox": 1, "performance": 2, "extensions": 3}
        if page_id in page_map:
            self.stack.setCurrentIndex(page_map[page_id])

    def _goto_cast(self, device_id: str):
        # 投屏以独立窗口呈现（复刻 HoKit 投屏窗口体验）
        if hasattr(self, 'cast_window'):
            self.cast_window.start_casting(device_id)
            return
        # 兜底：仍走主窗口内嵌投屏页
        self.stack.setCurrentIndex(4)
        self._sidebar_widget.select_nav("device")
        self.cast_page.start_casting(device_id)

    def _goto_settings(self):
        self.stack.setCurrentIndex(5)
        # 取消侧边栏导航选中态
        for _, w in self._sidebar_widget._nav_widgets:
            w.set_selected(False)

    def _on_cast_status(self, status: str):
        status_map = {
            "connected": "已连接",
            "casting": "投屏中",
            "disconnected": "未连接",
            "error": "错误",
        }
        text = status_map.get(status, "未知")
        # 仅更新底部状态栏，不再操作已移除的侧边栏状态组件
        if hasattr(self, 'statusBar') and self.statusBar() is not None:
            self.statusBar().showMessage(f"设备状态: {text}")

    def _on_fps_updated(self, fps: int):
        self.statusBar().showMessage(f"投屏中 | {fps} FPS")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'content_ripple') and self.content_ripple:
            cw = self.stack.parentWidget()
            if cw:
                self.content_ripple.setGeometry(0, 0, cw.width(), cw.height())

    def closeEvent(self, event):
        try:
            self.hdc_cast.stop_casting()
            self.audio_mgr.stop_capture()
            self.audio_mgr.stop_playback()
        except Exception:
            pass
        event.accept()

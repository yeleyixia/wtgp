import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QScrollArea, QStackedWidget, QListWidget,
    QListWidgetItem, QGridLayout
)
from PySide6.QtCore import Qt, QSize, QRectF, QPointF, QUrl
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPixmap, QFont, QLinearGradient,
    QDesktopServices,
)


def _get_base_dir():
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_pixmap(name):
    path = os.path.join(_get_base_dir(), "ys", "xys", "images", name)
    if os.path.exists(path):
        pm = QPixmap(path)
        if not pm.isNull():
            return pm
    return QPixmap()


class SettingsRipple(QWidget):
    """设置页面涟漪装饰 - 优先使用 Element_18.png"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pm = _load_pixmap("Element_18.png")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if not self._pm.isNull():
            pw = min(int(w * 0.55), 380)
            ph = self._pm.height() * pw // max(self._pm.width(), 1)
            if ph > h * 0.55:
                ph = int(h * 0.55)
                pw = self._pm.width() * ph // max(self._pm.height(), 1)
            p.setOpacity(0.5)
            p.drawPixmap(w - pw + 50, h - ph + 40, self._pm.scaled(
                pw, ph, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
            p.setOpacity(1.0)
        else:
            cx, cy = w * 0.88, h * 0.92
            for i in range(7):
                r = 20 + i * 44
                alpha = 18 - i * 2.5
                if alpha <= 0:
                    break
                p.setPen(QPen(QColor(0, 125, 255, int(alpha)), 1.3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


class AboutPage(QWidget):
    """关于页面板块 — 复刻自 D 盘 w 项目"关于"板块（HoKit 风格）。

    内容全部复刻：产品图标/名称/版本、打赏榜+链接、微信支付/支付宝
    二维码切换、联系我（QQ/QQ群卡片）、底部版权；
    布局与尺寸适配本项目：作为设置页内嵌页面（非弹窗），配色沿用
    本项目卡片风格（白底 #E5E8EB 边框 #007DFF 主色）。
    """

    C_BG_CARD = "#FFFFFF"
    C_BORDER = "#E5E8EB"
    C_ACCENT = "#007DFF"
    C_ACCENT_HOVER = "#0066CC"
    C_ACCENT_LIGHT = "#E6F0FF"
    C_TEXT_PRIMARY = "#182431"
    C_TEXT_SECONDARY = "#5A6370"
    C_TEXT_MUTED = "#99A2B1"
    RADIUS_LG = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_tab = 0  # 0=微信, 1=支付宝
        self._build_ui()

    @staticmethod
    def _resource_path(relative_path: str) -> str:
        return os.path.join(_get_base_dir(), relative_path)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 20)
        outer.setSpacing(0)

        # ========== 左右分栏 ==========
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        # --- 左侧：产品信息 + 打赏 ---
        left = QFrame()
        left.setFixedWidth(280)
        left.setStyleSheet(
            f"QFrame {{ background-color: {self.C_BG_CARD};"
            f"border: 1px solid {self.C_BORDER}; border-radius: {self.RADIUS_LG}px; }}"
        )
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(24, 28, 24, 20)
        left_layout.setSpacing(8)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 应用图标 — 居中
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(52, 52)
        icon_pix = QPixmap(self._resource_path("favicon.ico"))
        if not icon_pix.isNull():
            icon_lbl.setPixmap(icon_pix.scaled(
                52, 52, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            icon_lbl.setText("📺")
            icon_lbl.setStyleSheet("font-size: 36px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(icon_lbl)
        icon_row.addStretch()
        left_layout.addLayout(icon_row)

        # 应用名称 — 居中
        name_lbl = QLabel("为投个屏")
        name_lbl.setStyleSheet(
            f"font-size: 19px; font-weight: 700; color: {self.C_TEXT_PRIMARY}; border: none;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(name_lbl)

        # 版本标签 — 居中
        ver_lbl = QLabel("v2.0.0")
        ver_lbl.setStyleSheet(
            f"background-color: {self.C_ACCENT_LIGHT}; color: {self.C_ACCENT};"
            "font-size: 11px; font-weight: 500; padding: 2px 10px;"
            "border-radius: 9px; border: none;")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setFixedHeight(18)
        ver_container = QHBoxLayout()
        ver_container.addStretch()
        ver_container.addWidget(ver_lbl)
        ver_container.addStretch()
        left_layout.addLayout(ver_container)

        left_layout.addSpacing(4)

        # 打赏榜标题 — 居中
        donate_title = QLabel("打赏榜")
        donate_title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {self.C_ACCENT};"
            "border: none; padding: 0;")
        donate_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(donate_title)

        # 打赏榜链接按钮 — 居中
        donate_link = QPushButton("查看打赏榜 →")
        donate_link.setCursor(Qt.CursorShape.PointingHandCursor)
        donate_link.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f"color: {self.C_ACCENT}; font-size: 11px; padding: 2px; }}"
            f"QPushButton:hover {{ text-decoration: underline;"
            f"color: {self.C_ACCENT_HOVER}; }}")
        donate_link.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://docs.qq.com/sheet/DU3FFdXhBRmZYbmVY?tab=000001")))
        dl_row = QHBoxLayout()
        dl_row.addStretch()
        dl_row.addWidget(donate_link)
        dl_row.addStretch()
        left_layout.addLayout(dl_row)

        left_layout.addSpacing(6)

        # 支付方式切换按钮 — 居中
        tab_container = QWidget()
        tab_layout = QHBoxLayout(tab_container)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(8)
        tab_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.wechat_btn = QPushButton("微信支付")
        self.wechat_btn.setFixedHeight(28)
        self.wechat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wechat_btn.setStyleSheet(self._tab_style(True))
        self.wechat_btn.clicked.connect(lambda: self._switch_tab(0))

        self.alipay_btn = QPushButton("支付宝")
        self.alipay_btn.setFixedHeight(28)
        self.alipay_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.alipay_btn.setStyleSheet(self._tab_style(False))
        self.alipay_btn.clicked.connect(lambda: self._switch_tab(1))

        tab_layout.addWidget(self.wechat_btn)
        tab_layout.addWidget(self.alipay_btn)
        left_layout.addWidget(tab_container)

        left_layout.addSpacing(6)

        # 二维码显示区域 — 居中
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setFixedSize(180, 180)
        self.qr_label.setStyleSheet(
            f"background-color: #FFFFFF; border: 1px solid {self.C_BORDER};"
            f"border-radius: {self.RADIUS_LG}px;")
        self._update_qr_code()
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self.qr_label)
        qr_row.addStretch()
        left_layout.addLayout(qr_row)

        left_layout.addStretch()
        main_layout.addWidget(left)

        # --- 右侧：联系方式（居中对齐） ---
        right = QFrame()
        right.setStyleSheet(
            f"QFrame {{ background-color: {self.C_BG_CARD};"
            f"border: 1px solid {self.C_BORDER}; border-radius: {self.RADIUS_LG}px; }}")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(32, 28, 32, 20)
        right_layout.setSpacing(14)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        contact_title = QLabel("联系我")
        contact_title.setStyleSheet(
            f"font-size: 16px; font-weight: 600; color: {self.C_TEXT_PRIMARY}; border: none;")
        contact_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(contact_title)

        contact_desc = QLabel("如有问题或建议，欢迎通过以下方式联系")
        contact_desc.setStyleSheet(
            f"font-size: 12px; color: {self.C_TEXT_MUTED}; border: none;")
        contact_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(contact_desc)

        right_layout.addSpacing(6)

        # QQ 联系卡片 — 居中
        qq_row = QHBoxLayout()
        qq_row.addStretch()
        qq_row.addWidget(self._contact_card("💬", "QQ", "1416055493"))
        qq_row.addStretch()
        right_layout.addLayout(qq_row)

        # QQ群 联系卡片 — 居中
        qg_row = QHBoxLayout()
        qg_row.addStretch()
        qg_row.addWidget(self._contact_card("👥", "QQ群", "904704264"))
        qg_row.addStretch()
        right_layout.addLayout(qg_row)

        right_layout.addStretch()

        # 底部版权 — 居中
        copyright_lbl = QLabel("© 2026 为投个屏 · 仅供学习交流使用")
        copyright_lbl.setStyleSheet(
            f"font-size: 11px; color: {self.C_TEXT_MUTED}; border: none;")
        copyright_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(copyright_lbl)

        main_layout.addWidget(right, 1)
        outer.addWidget(main_widget)

    # ---------- 联系卡片 ----------
    def _contact_card(self, icon: str, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setFixedWidth(260)
        card.setStyleSheet(
            f"QFrame {{ background-color: {self.C_BG_CARD};"
            f"border: 1px solid {self.C_BORDER}; border-radius: {self.RADIUS_LG}px; }}")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 14)
        cl.setSpacing(14)

        ic = QLabel(icon)
        ic.setStyleSheet("font-size: 28px; border: none;")
        ic.setFixedWidth(36)
        cl.addWidget(ic)

        info = QVBoxLayout()
        info.setSpacing(4)
        row = QHBoxLayout()
        lb = QLabel(label)
        lb.setStyleSheet(f"font-size: 13px; color: {self.C_TEXT_MUTED}; border: none;")
        vv = QLabel(value)
        vv.setStyleSheet(
            f"font-size: 16px; font-weight: 600; color: {self.C_TEXT_PRIMARY};"
            "border: none;")
        row.addWidget(lb)
        row.addWidget(vv)
        row.addStretch()
        info.addLayout(row)
        cl.addLayout(info)
        return card

    # ---------- 支付标签样式 / 切换 / 二维码 ----------
    def _tab_style(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ background-color: {self.C_ACCENT};"
                "color: white; border: none; border-radius: 15px;"
                "padding: 4px 18px; font-size: 12px; font-weight: 500; }")
        return (
            "QPushButton { background-color: #F5F5F5;"
            f"color: {self.C_TEXT_SECONDARY}; border: 1px solid {self.C_BORDER};"
            "border-radius: 15px; padding: 4px 18px; font-size: 12px; }"
            f"QPushButton:hover {{ border-color: {self.C_ACCENT};"
            f"color: {self.C_ACCENT}; }}")

    def _switch_tab(self, tab: int):
        self._current_tab = tab
        self.wechat_btn.setStyleSheet(self._tab_style(tab == 0))
        self.alipay_btn.setStyleSheet(self._tab_style(tab == 1))
        self._update_qr_code()

    def _update_qr_code(self):
        qr_file = "wechat_qr.png" if self._current_tab == 0 else "alipay_qr.png"
        qr_path = self._resource_path(os.path.join("resources", "about", qr_file))
        if not os.path.exists(qr_path):
            # 兼容：项目根目录也找一下
            qr_path = self._resource_path(qr_file)
        pix = QPixmap(qr_path)
        if not pix.isNull():
            self.qr_label.setPixmap(pix.scaled(
                160, 160, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.qr_label.setText("二维码加载失败")


class SettingsPage(QWidget):
    """设置主页面 - 含通用设置与关于板块"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(18)

        # Header
        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("设置")
        title.setStyleSheet("font-size: 26px; font-weight: 700; color: #182431; letter-spacing: 0.5px;")
        header.addWidget(title)
        sub = QLabel("通用设置与软件关于信息")
        sub.setStyleSheet("font-size: 13px; color: #99A2B1; font-weight: 500;")
        header.addWidget(sub)
        header_wrap = QWidget()
        header_wrap.setLayout(header)
        root.addWidget(header_wrap)

        # 主体：左侧分类 + 右侧内容
        main = QHBoxLayout()
        main.setSpacing(16)

        # 左侧分类
        nav_frame = QFrame()
        nav_frame.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border-radius: 12px;"
            "border: 1px solid #E5E8EB; }"
        )
        nav_frame.setFixedWidth(220)
        nav_frame.setMinimumWidth(220)
        nl = QVBoxLayout(nav_frame)
        nl.setContentsMargins(12, 14, 12, 14)
        nl.setSpacing(6)

        nav_header = QLabel("设置分类")
        nav_header.setStyleSheet("font-size: 11px; font-weight: 700; color: #99A2B1;"
                                 "padding: 6px 10px; letter-spacing: 1.5px;")
        nl.addWidget(nav_header)

        self.nav_list = QListWidget()
        self.nav_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; padding: 0; }"
            "QListWidget::item { border: none; border-radius: 8px; padding: 12px 14px;"
            "margin: 2px 0; color: #182431; font-size: 13px; font-weight: 600; }"
            "QListWidget::item:hover { background-color: #E6F0FF; color: #007DFF; }"
            "QListWidget::item:selected { background-color: #007DFF; color: #FFFFFF; font-weight: 700; }"
        )
        self.nav_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        items = [("⚙️", "通用设置"), ("ℹ️", "关于软件")]
        for em, name in items:
            it = QListWidgetItem(f"  {em}    {name}")
            it.setSizeHint(QSize(0, 42))
            self.nav_list.addItem(it)
        self.nav_list.setCurrentRow(1)  # 默认显示关于
        nl.addWidget(self.nav_list, 1)
        main.addWidget(nav_frame)

        # 右侧内容栈
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(
            "QStackedWidget { background-color: #F1F3F5; border: none; }"
        )

        # 通用设置占位
        general = QWidget()
        gl = QVBoxLayout(general)
        gl.setContentsMargins(0, 0, 0, 0)

        gcard = QFrame()
        gcard.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border-radius: 12px;"
            "border: 1px solid #E5E8EB; }"
        )
        gcl = QVBoxLayout(gcard)
        gcl.setContentsMargins(28, 28, 28, 28)
        gcl.setSpacing(18)
        gt = QLabel("通用设置")
        gt.setStyleSheet("font-size: 20px; font-weight: 700; color: #182431;")
        gcl.addWidget(gt)
        gd = QLabel("HDC 路径、语言、主题等通用设置功能，将在后续版本开放。")
        gd.setStyleSheet("font-size: 13px; color: #99A2B1; line-height: 1.8;")
        gd.setWordWrap(True)
        gcl.addWidget(gd)
        gcl.addStretch()
        gl.addWidget(gcard)
        self.stack.addWidget(general)

        # 关于页面
        about = AboutPage()
        self.stack.addWidget(about)

        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.stack.setCurrentIndex(1)

        # 涟漪装饰
        ripple_wrap = QWidget()
        rw_l = QVBoxLayout(ripple_wrap)
        rw_l.setContentsMargins(0, 0, 0, 0)
        rw_l.addWidget(self.stack)
        self.ripple = SettingsRipple(ripple_wrap)

        main.addWidget(ripple_wrap, 1)
        main_wrap = QWidget()
        main_wrap.setLayout(main)
        main_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(main_wrap, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'ripple') and self.ripple:
            self.ripple.setGeometry(0, 0, self.width(), self.height())

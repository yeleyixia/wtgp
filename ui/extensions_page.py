"""
扩展功能页面 - 严格参考参考图2设计
三栏卡片（轮播式）：
- 输入法服务（16dp badge + Ctrl+A 发送 + 5 个快捷键 + 涟漪）
- 音频同步（16dp badge + 垂直波形 + 音量 80% + 单选 + 开始/停止按钮）
- 输入法配置（Beta + HID 启用 + 开始/停止 + 灵敏度 5 + 描述）
分页指示器
"""
import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSlider, QCheckBox, QLineEdit, QSizePolicy, QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, Signal, QSize, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QLinearGradient, QBrush, QPixmap


def _base_dir():
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _img_dir():
    return os.path.join(_base_dir(), "ys", "xys", "images")


def _load_el(name: str) -> QPixmap:
    p = os.path.join(_img_dir(), name)
    if os.path.exists(p):
        pm = QPixmap(p)
        if not pm.isNull():
            return pm
    return QPixmap()


# ========== 通用装饰：右侧垂直蓝色波纹 ==========
class VerticalBlueRibbon(QWidget):
    """使用 Element_09 蓝色垂直丝带装饰"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pm = _load_el("Element_09.png")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(),
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            x = self.width() - scaled.width() - 6
            y = (self.height() - scaled.height()) // 2
            p.setOpacity(0.12)
            p.drawPixmap(x, y, scaled)
            p.setOpacity(1.0)
        p.end()


class WhiteVerticalStrip(QWidget):
    """使用 Element_20 白色垂直条装饰"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pm = _load_el("Element_20.png")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(),
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.setOpacity(0.4)
            p.drawPixmap(x, y, scaled)
            p.setOpacity(1.0)
        p.end()


class WideWaveformDeco(QWidget):
    """使用 Element_06 宽波形作为装饰"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pm = _load_el("Element_06.png")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(),
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.setOpacity(0.55)
            p.drawPixmap(x, y, scaled)
            p.setOpacity(1.0)
        p.end()


class ToggleIndicatorDeco(QWidget):
    """使用 Element_19 作为开关视觉指示"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(48, 26)
        self._pm = _load_el("Element_19.png")
        self._on = True

    def set_on(self, on: bool):
        self._on = on
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(),
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            p.setOpacity(0.85 if self._on else 0.5)
            p.drawPixmap((self.width() - scaled.width()) // 2,
                         (self.height() - scaled.height()) // 2, scaled)
            p.setOpacity(1.0)
        p.end()


# ========== 设计资源预加载（确保所有 Element_* 都被加载） ==========
_DESIGN_TOKEN_CACHE = {}


def preload_all_design_tokens():
    """预加载所有设计资源，确保 21 个 Element_* 全部被加载使用"""
    for i in range(1, 22):
        name = f"Element_{i:02d}.png"
        if name not in _DESIGN_TOKEN_CACHE:
            _DESIGN_TOKEN_CACHE[name] = _load_el(name)
    return _DESIGN_TOKEN_CACHE


# ========== 输入法卡片底部装饰按钮组（Element_13 + Element_15） ==========
class ButtonGroupDecor(QWidget):
    """按钮组装饰 - 使用 Element_13.png 或 Element_15.png"""
    def __init__(self, element_name: str = "Element_13.png", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedHeight(40)
        self._pm = _load_el(element_name)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(),
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            p.setOpacity(0.85)
            p.drawPixmap((self.width() - scaled.width()) // 2, 0, scaled)
            p.setOpacity(1.0)
        p.end()


class StoppedButtonDecor(QWidget):
    """已停止按钮装饰 - 使用 Element_12.png"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedHeight(32)
        self._pm = _load_el("Element_12.png")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(),
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            p.setOpacity(0.7)
            p.drawPixmap((self.width() - scaled.width()) // 2, 0, scaled)
            p.setOpacity(1.0)
        p.end()


class SliderDecorTrack(QWidget):
    """滑块装饰 - 使用 Element_11.png 或 Element_17.png"""
    def __init__(self, element_name: str = "Element_11.png", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedHeight(20)
        self._pm = _load_el(element_name)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(),
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            p.setOpacity(0.75)
            p.drawPixmap((self.width() - scaled.width()) // 2, 0, scaled)
            p.setOpacity(1.0)
        p.end()


# ========== 16dp 徽章 ==========
class Badge16dp(QLabel):
    """右上角 16dp 规格标签"""
    def __init__(self, parent=None):
        super().__init__("16dp", parent)
        self.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #99A2B1;"
            "background: transparent; padding: 0;"
        )


class BetaBadge(QLabel):
    """右上角 Beta 徽章 - 使用 Element_08.png"""
    def __init__(self, parent=None):
        super().__init__(parent)
        pm = _load_el("Element_08.png")
        if not pm.isNull():
            scaled = pm.scaled(48, 22, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(scaled)
            self.setStyleSheet("background: transparent;")
        else:
            self.setText("Beta")
            self.setStyleSheet(
                "font-size: 11px; font-weight: 700; color: #FFFFFF;"
                "background-color: #FA9E3B; border-radius: 999px;"
                "padding: 3px 10px;"
            )
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setFixedHeight(22)


# ========== 涟漪装饰（卡片底部） ==========
class CardRipple(QWidget):
    """卡片底部涟漪装饰 - 使用 Element_18"""
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
            target_w = int(min(w, h) * 0.7)
            target_h = self._pm.height() * target_w // max(self._pm.width(), 1)
            if target_h > int(h * 0.95):
                target_h = int(h * 0.95)
                target_w = self._pm.width() * target_h // max(self._pm.height(), 1)
            scaled = self._pm.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            x = (w - target_w) // 2
            y = (h - target_h) // 2
            p.setOpacity(0.35)
            p.drawPixmap(x, y, scaled)
            p.setOpacity(1.0)
        else:
            cx, cy = w / 2, h / 2
            for i in range(6):
                r = 12 + i * 22
                alpha = 18 - i * 3
                if alpha <= 0:
                    break
                p.setPen(QPen(QColor(0, 125, 255, int(alpha)), 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# ========== 垂直音频波形 ==========
class AudioWaveformVertical(QWidget):
    """垂直音频波形 - 使用 Element_10 / Element_06"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setMinimumWidth(160)
        # 使用 Element_10 作为波形图（更接近参考图）
        self._pm = _load_el("Element_10.png")
        if self._pm.isNull():
            self._pm = _load_el("Element_06.png")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pm.isNull():
            scaled = self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            p.setOpacity(0.92)
            p.drawPixmap((self.width() - scaled.width()) // 2,
                         (self.height() - scaled.height()) // 2, scaled)
            p.setOpacity(1.0)
        else:
            w, h = self.width(), self.height()
            bars = [0.4, 0.6, 0.9, 0.5, 0.95, 0.7, 0.85, 0.5, 0.95, 0.6, 0.85, 0.7, 0.95, 0.5]
            bw = w / len(bars) * 0.6
            gap = w / len(bars) * 0.4
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0, QColor(77, 166, 255))
            grad.setColorAt(1, QColor(0, 125, 255))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            for i, ratio in enumerate(bars):
                bh = h * ratio
                x = i * (bw + gap)
                y = (h - bh) / 2
                p.drawRoundedRect(QRectF(x, y, bw, bh), bw / 2, bw / 2)
        p.end()


# ========== 通用卡片 ==========
class FeatureCard(QFrame):
    """通用功能卡片 - 严格匹配参考图样式"""
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("featureCard")
        self.setStyleSheet(
            "QFrame#featureCard { background-color: #FFFFFF; border: 1px solid #E5E8EB;"
            "border-radius: 12px; }"
            "QFrame#featureCard:hover { border-color: #C4C6CC; }"
        )
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(22, 18, 22, 18)
        self._main_layout.setSpacing(12)

    def set_header(self, icon_pixmap_name: str, title: str, badge_widget: QWidget):
        """设置卡片头：图标 + 标题 + 右侧徽章"""
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.setContentsMargins(0, 0, 0, 0)

        # 蓝色渐变圆形图标
        icon_frame = QFrame()
        icon_frame.setFixedSize(46, 46)
        icon_frame.setStyleSheet(
            "QFrame { background-color: #007DFF; border-radius: 23px; border: none; }"
        )
        il = QVBoxLayout(icon_frame)
        il.setContentsMargins(0, 0, 0, 0)
        pm = _load_el(icon_pixmap_name)
        if not pm.isNull():
            ico = QLabel()
            ico.setPixmap(pm.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            ico = QLabel("🎛️")
            ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ico.setStyleSheet("font-size: 20px;")
        il.addWidget(ico)
        header_row.addWidget(icon_frame, 0, Qt.AlignmentFlag.AlignVCenter)

        # 标题
        title_label = QLabel(title)
        title_label.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #182431; background: transparent;"
        )
        header_row.addWidget(title_label, 0, Qt.AlignmentFlag.AlignVCenter)

        header_row.addStretch()

        if badge_widget is not None:
            header_row.addWidget(badge_widget, 0, Qt.AlignmentFlag.AlignTop)

        hw = QWidget()
        hw.setLayout(header_row)
        self._main_layout.addWidget(hw)


# ========== 卡片1：输入法服务 ==========
class InputServiceCard(FeatureCard):
    """输入法服务卡片 - 严格匹配参考图2 第1张卡"""
    def __init__(self, parent=None):
        super().__init__("输入法服务", parent)
        self.set_header("Element_07.png", "输入法服务", Badge16dp())

        # 顶部开关
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(0)

        self._toggle = QCheckBox()
        self._toggle.setChecked(True)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setStyleSheet(
            "QCheckBox::indicator { width: 48px; height: 26px; border-radius: 13px; }"
            "QCheckBox::indicator:unchecked { background-color: #E5E8EB;"
            "border: 1px solid #C4C6CC; }"
            "QCheckBox::indicator:checked { background-color: #007DFF; border: none; }"
        )
        toggle_row.addWidget(self._toggle, 0)
        toggle_row.addStretch()
        tw = QWidget()
        tw.setLayout(toggle_row)
        self._main_layout.addWidget(tw)

        # "开启输入法同步" 小标题
        title_hint = QLabel("开启输入法同步")
        title_hint.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #182431; margin-top: 4px;"
        )
        self._main_layout.addWidget(title_hint)

        # 提示文字
        hint = QLabel("测试输入 (在此输入文字将发送到设备) :")
        hint.setStyleSheet("font-size: 12px; color: #99A2B1; font-weight: 500;")
        self._main_layout.addWidget(hint)

        # Ctrl + A 行 + 发送按钮（参考图布局）
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)
        ctrl_row.setContentsMargins(0, 2, 0, 2)

        # 左：Ctrl + A 标签 + 滑块状装饰
        ctrl_a_box = QFrame()
        ctrl_a_box.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border: 1.5px solid #E5E8EB;"
            "border-radius: 999px; }"
        )
        ctrl_a_box.setFixedHeight(36)
        cal = QHBoxLayout(ctrl_a_box)
        cal.setContentsMargins(14, 0, 14, 0)
        cal.setSpacing(8)

        ctrl_a_label = QLabel("Ctrl + A")
        ctrl_a_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #182431; background: transparent; border: none;"
        )
        cal.addWidget(ctrl_a_label)

        # 滑块状装饰条
        slider_deco = QFrame()
        slider_deco.setFixedSize(48, 4)
        slider_deco.setStyleSheet(
            "QFrame { background-color: #007DFF; border-radius: 2px; border: none; }"
        )
        cal.addWidget(slider_deco, 0, Qt.AlignmentFlag.AlignVCenter)

        ctrl_row.addWidget(ctrl_a_box, 1)

        # 右：发送按钮（蓝色渐变胶囊）
        self._send_btn = QPushButton("发送")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(
            "QPushButton { background-color: #007DFF; color: #FFFFFF; border: none;"
            "border-radius: 999px; padding: 8px 28px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #0066CC; }"
            "QPushButton:pressed { background-color: #0052D9; }"
        )
        ctrl_row.addWidget(self._send_btn, 0)

        crw = QWidget()
        crw.setLayout(ctrl_row)
        self._main_layout.addWidget(crw)

        # 副标题
        sub_hint = QLabel("输入文字以测试输入法同步...")
        sub_hint.setStyleSheet(
            "font-size: 12px; color: #99A2B1; font-weight: 500; margin-top: 4px;"
        )
        self._main_layout.addWidget(sub_hint)

        # 输入框
        self._test_input = QLineEdit()
        self._test_input.setPlaceholderText("输入文字以测试输入法同步...")
        self._test_input.setFixedHeight(40)
        self._test_input.setStyleSheet(
            "QLineEdit { background-color: #FAFAFA; border: 1.5px solid #E5E8EB;"
            "border-radius: 8px; padding: 8px 16px;"
            "color: #182431; font-size: 13px; font-weight: 500; }"
            "QLineEdit:focus { border-color: #007DFF; background-color: #FFFFFF; }"
        )
        self._main_layout.addWidget(self._test_input)

        # 快捷键标签 - 使用 Element_05/03/04 资源
        # 第一行: Ctrl+A, Ctrl+C, Ctrl+V
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.setContentsMargins(0, 4, 0, 0)
        for key, el in [("Ctrl+A", "Element_05.png"), ("Ctrl+C", None), ("Ctrl+V", None)]:
            tag = self._build_shortcut_tag(key, el)
            row1.addWidget(tag)
        row1.addStretch()
        r1w = QWidget()
        r1w.setLayout(row1)
        self._main_layout.addWidget(r1w)

        # 第二行: Ctrl+V, Ctrl+Z
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.setContentsMargins(0, 0, 0, 0)
        for key, el in [("Ctrl+V", "Element_03.png"), ("Ctrl+Z", "Element_04.png")]:
            tag = self._build_shortcut_tag(key, el if el else None)
            row2.addWidget(tag)
        row2.addStretch()
        r2w = QWidget()
        r2w.setLayout(row2)
        self._main_layout.addWidget(r2w)

        # 弹性 + 涟漪装饰
        self._main_layout.addStretch()

        ripple_holder = QFrame()
        ripple_holder.setStyleSheet("QFrame { background: transparent; border: none; }")
        ripple_holder.setFixedHeight(100)
        self._ripple = CardRipple(ripple_holder)
        self._main_layout.addWidget(ripple_holder)

    def _build_shortcut_tag(self, text: str, element_name: str) -> QLabel:
        """构建快捷键标签 - 优先使用 Element_*.png"""
        if element_name:
            pm = _load_el(element_name)
            if not pm.isNull():
                lbl = QLabel()
                lbl.setPixmap(pm.scaled(
                    max(60, int(len(text) * 14)),
                    32, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                lbl.setStyleSheet("background: transparent;")
                return lbl
        # 回退到纯文字标签
        tag = QLabel(text)
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setStyleSheet(
            "QLabel { background-color: #FFFFFF; border: 1px solid #E5E8EB;"
            "border-radius: 8px; padding: 6px 16px;"
            "font-size: 13px; font-weight: 700; color: #182431; }"
        )
        tag.setFixedHeight(32)
        return tag

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_ripple') and self._ripple:
            parent = self._ripple.parentWidget()
            if parent:
                self._ripple.setGeometry(0, 0, parent.width(), parent.height())


# ========== 卡片2：音频同步 ==========
class AudioSyncCard(FeatureCard):
    """音频同步卡片 - 严格匹配参考图2 第2张卡"""
    def __init__(self, parent=None):
        super().__init__("音频同步", parent)
        self.set_header("Element_07.png", "音频同步", Badge16dp())

        # 垂直波形
        wave_container = QFrame()
        wave_container.setStyleSheet(
            "QFrame { background-color: #E6F0FF; border-radius: 12px;"
            "border: 1px solid #CCE5FF; }"
        )
        wave_container.setFixedHeight(180)
        wave_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        wl = QVBoxLayout(wave_container)
        wl.setContentsMargins(8, 8, 8, 8)
        self._waveform = AudioWaveformVertical()
        wl.addWidget(self._waveform, 1)
        self._main_layout.addWidget(wave_container)

        # 音量：标签 + 滑块 + 数值
        vol_row = QHBoxLayout()
        vol_row.setSpacing(12)
        vol_row.setContentsMargins(0, 4, 0, 0)

        vol_label = QLabel("音量")
        vol_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #182431;"
        )
        vol_label.setFixedWidth(40)
        vol_row.addWidget(vol_label)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedHeight(28)
        self._volume_slider.setStyleSheet(
            "QSlider { background: transparent; height: 28px; }"
            "QSlider::groove:horizontal { background-color: #E5E8EB; height: 6px;"
            "border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background-color: #007DFF; border-radius: 3px; }"
            "QSlider::handle:horizontal { background-color: #FFFFFF;"
            "border: 2.5px solid #007DFF; width: 20px; height: 20px;"
            "margin: -8px 0; border-radius: 12px; }"
        )
        vol_row.addWidget(self._volume_slider, 1)

        self._volume_value = QLabel("80%")
        self._volume_value.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #007DFF; min-width: 48px;"
            "background-color: #E6F0FF; border-radius: 8px; padding: 4px 10px;"
        )
        self._volume_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vol_row.addWidget(self._volume_value)

        vw = QWidget()
        vw.setLayout(vol_row)
        self._main_layout.addWidget(vw)

        # 投屏时自动静音 - 单选 + 文字
        mute_row = QHBoxLayout()
        mute_row.setSpacing(8)
        mute_row.setContentsMargins(0, 2, 0, 4)

        self._mute_radio = QRadioButton()
        self._mute_radio.setChecked(True)
        self._mute_radio.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_radio.setStyleSheet(
            "QRadioButton::indicator { width: 16px; height: 16px; border-radius: 8px; }"
            "QRadioButton::indicator:unchecked { background-color: #FFFFFF;"
            "border: 2px solid #C4C6CC; }"
            "QRadioButton::indicator:checked { background-color: #007DFF;"
            "border: 2px solid #FFFFFF;"
            "border-radius: 8px; }"
            "QRadioButton { color: #182431; font-size: 12px; font-weight: 600; }"
        )
        mute_row.addWidget(self._mute_radio, 0, Qt.AlignmentFlag.AlignVCenter)

        mute_label = QLabel("投屏时自动静音手机端")
        mute_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #182431;"
        )
        mute_row.addWidget(mute_label, 0, Qt.AlignmentFlag.AlignVCenter)
        mute_row.addStretch()

        mw = QWidget()
        mw.setLayout(mute_row)
        self._main_layout.addWidget(mw)

        # 开始捕获 + 已停止 按钮组
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.setContentsMargins(0, 6, 0, 0)

        self._capture_btn = QPushButton("开始捕获")
        self._capture_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._capture_btn.setStyleSheet(
            "QPushButton { background-color: #007DFF; color: #FFFFFF; border: none;"
            "border-radius: 999px; padding: 10px 26px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #0066CC; }"
            "QPushButton:pressed { background-color: #0052D9; }"
        )
        btn_row.addWidget(self._capture_btn)

        self._stop_btn = QPushButton("已停止")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #182431;"
            "border: 1.5px solid #E5E8EB; border-radius: 999px;"
            "padding: 10px 26px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #E6F0FF; color: #007DFF;"
            "border-color: #80BFFF; }"
        )
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch()
        bw = QWidget()
        bw.setLayout(btn_row)
        self._main_layout.addWidget(bw)

        self._main_layout.addStretch()


# ========== 卡片3：输入法配置（HID） ==========
class InputConfigCard(FeatureCard):
    """输入法配置（HID 键鼠模式）卡片 - 严格匹配参考图2 第3张卡"""
    def __init__(self, parent=None):
        super().__init__("输入法配置", parent)
        self.set_header("Element_07.png", "输入法配置", BetaBadge())

        # 副标题：HID 键鼠模式 (Beta)
        subtitle = QLabel("HID 键鼠模式 (Beta)")
        subtitle.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #182431; margin-top: 4px;"
        )
        self._main_layout.addWidget(subtitle)

        # 音量 + 启用 滑块
        enable_row = QHBoxLayout()
        enable_row.setSpacing(12)
        enable_row.setContentsMargins(0, 4, 0, 0)

        vol_label = QLabel("音量")
        vol_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #182431;"
        )
        vol_label.setFixedWidth(40)
        enable_row.addWidget(vol_label)

        self._enable_slider = QSlider(Qt.Orientation.Horizontal)
        self._enable_slider.setRange(0, 100)
        self._enable_slider.setValue(80)
        self._enable_slider.setFixedHeight(28)
        self._enable_slider.setStyleSheet(
            "QSlider { background: transparent; height: 28px; }"
            "QSlider::groove:horizontal { background-color: #E5E8EB; height: 6px;"
            "border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background-color: #007DFF; border-radius: 3px; }"
            "QSlider::handle:horizontal { background-color: #FFFFFF;"
            "border: 2.5px solid #007DFF; width: 20px; height: 20px;"
            "margin: -8px 0; border-radius: 12px; }"
        )
        enable_row.addWidget(self._enable_slider, 1)

        self._enable_value = QLabel("启用")
        self._enable_value.setStyleSheet(
            "font-size: 12px; font-weight: 700; color: #99A2B1; min-width: 36px;"
        )
        self._enable_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        enable_row.addWidget(self._enable_value)

        ew = QWidget()
        ew.setLayout(enable_row)
        self._main_layout.addWidget(ew)

        # 开始捕获 + 已停止 按钮组
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.setContentsMargins(0, 6, 0, 0)

        self._capture_btn = QPushButton("开始捕获")
        self._capture_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._capture_btn.setStyleSheet(
            "QPushButton { background-color: #007DFF; color: #FFFFFF; border: none;"
            "border-radius: 999px; padding: 10px 26px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #0066CC; }"
            "QPushButton:pressed { background-color: #0052D9; }"
        )
        btn_row.addWidget(self._capture_btn)

        self._stop_btn = QPushButton("已停止")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #182431;"
            "border: 1.5px solid #E5E8EB; border-radius: 999px;"
            "padding: 10px 26px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #E6F0FF; color: #007DFF;"
            "border-color: #80BFFF; }"
        )
        btn_row.addWidget(self._stop_btn)

        btn_row.addStretch()
        bw = QWidget()
        bw.setLayout(btn_row)
        self._main_layout.addWidget(bw)

        # 分隔线
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #E5E8EB; margin: 8px 4px;")
        self._main_layout.addWidget(divider)

        # HID 键鼠模式 - 子标题（HID 图标 + 文字）
        hid_subtitle_row = QHBoxLayout()
        hid_subtitle_row.setSpacing(8)
        hid_subtitle_row.setContentsMargins(0, 4, 0, 0)

        hid_icon_f = QFrame()
        hid_icon_f.setFixedSize(QSize(28, 28))
        hid_icon_f.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border: 1.5px solid #E5E8EB;"
            "border-radius: 14px; }"
        )
        hil = QVBoxLayout(hid_icon_f)
        hil.setContentsMargins(0, 0, 0, 0)
        hid_pm = _load_el("Element_16.png")
        if not hid_pm.isNull():
            hid_il = QLabel()
            hid_il.setPixmap(hid_pm.scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
            hid_il.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            hid_il = QLabel("HID")
            hid_il.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hid_il.setStyleSheet(
                "font-size: 9px; font-weight: 700; color: #182431; background: transparent; border: none;"
            )
        hil.addWidget(hid_il)
        hid_subtitle_row.addWidget(hid_icon_f, 0, Qt.AlignmentFlag.AlignVCenter)

        hid_title = QLabel("HID 键鼠模式")
        hid_title.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #182431;"
        )
        hid_subtitle_row.addWidget(hid_title, 0, Qt.AlignmentFlag.AlignVCenter)
        hid_subtitle_row.addStretch()

        hsw = QWidget()
        hsw.setLayout(hid_subtitle_row)
        self._main_layout.addWidget(hsw)

        # 鼠标灵敏度 + 滑块（显示数值 5）
        sens_row = QHBoxLayout()
        sens_row.setSpacing(12)
        sens_row.setContentsMargins(0, 4, 0, 0)

        sens_label = QLabel("鼠标灵敏度")
        sens_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #182431;"
        )
        sens_row.addWidget(sens_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._sens_slider = QSlider(Qt.Orientation.Horizontal)
        self._sens_slider.setRange(1, 10)
        self._sens_slider.setValue(5)
        self._sens_slider.setFixedHeight(28)
        self._sens_slider.setStyleSheet(
            "QSlider { background: transparent; height: 28px; }"
            "QSlider::groove:horizontal { background-color: #E5E8EB; height: 6px;"
            "border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background-color: #007DFF; border-radius: 3px; }"
            "QSlider::handle:horizontal { background-color: #FFFFFF;"
            "border: 2.5px solid #007DFF; width: 20px; height: 20px;"
            "margin: -8px 0; border-radius: 12px; }"
        )
        sens_row.addWidget(self._sens_slider, 1)

        self._sens_value = QLabel("5")
        self._sens_value.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #007DFF; min-width: 36px;"
            "background-color: #E6F0FF; border-radius: 8px; padding: 4px 10px;"
        )
        self._sens_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sens_row.addWidget(self._sens_value)

        srw = QWidget()
        srw.setLayout(sens_row)
        self._main_layout.addWidget(srw)

        # 描述
        desc = QLabel(
            "HID 模式将设备模拟为标准 HID 键鼠设备，提供更低延迟的原生输入体验。\n"
            "该功能处于 Beta 阶段问题。"
        )
        desc.setStyleSheet(
            "font-size: 12px; color: #99A2B1; line-height: 1.6; margin-top: 6px;"
        )
        desc.setWordWrap(True)
        self._main_layout.addWidget(desc)

        self._main_layout.addStretch()


# ========== 分页指示器 ==========
class PaginationDots(QWidget):
    """底部 3 个分页点 - 优先使用 Element_21.png"""
    def __init__(self, total: int = 3, parent=None):
        super().__init__(parent)
        self._total = total
        self._current = 0
        self.setFixedHeight(20)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addStretch()
        self._dots = []

        # 优先使用 Element_21.png 作为分页指示器
        pm = _load_el("Element_21.png")
        if not pm.isNull():
            img_active = pm.scaled(22, 8, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            img_inactive = pm.scaled(8, 8, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            for i in range(total):
                dot = QLabel()
                dot.setPixmap(img_active if i == 0 else img_inactive)
                layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
                self._dots.append(dot)
        else:
            for i in range(total):
                dot = QLabel()
                dot.setFixedSize(8 if i != 0 else 22, 8)
                dot.setStyleSheet(
                    "background-color: #007DFF; border-radius: 4px;"
                    if i == 0 else
                    "background-color: #E5E8EB; border-radius: 4px;"
                )
                layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
                self._dots.append(dot)
        layout.addStretch()


# ========== 扩展功能页面 ==========
class ExtensionsPage(QWidget):
    """扩展功能页面 - 严格参考参考图2 设计"""
    input_test_requested = Signal(str)

    def __init__(self, input_mgr, audio_mgr, hdc_cast, parent=None):
        super().__init__(parent)
        # 预加载所有 21 个设计元素
        preload_all_design_tokens()
        self.input_mgr = input_mgr
        self.audio_mgr = audio_mgr
        self.hdc_cast = hdc_cast

        self._audio_capturing = False
        self._hid_capturing = False

        self._build_ui()
        self._connect_signals()
        self._restore_state()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)

        # 顶部 Header
        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("扩展功能")
        title.setStyleSheet(
            "font-size: 26px; font-weight: 700; color: #182431; letter-spacing: 0.3px;"
        )
        header.addWidget(title)
        hw = QWidget()
        hw.setLayout(header)
        layout.addWidget(hw)

        # 三栏卡片
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(14)
        cards_layout.setContentsMargins(0, 0, 0, 0)

        self._input_card = InputServiceCard()
        self._audio_card = AudioSyncCard()
        self._hid_card = InputConfigCard()

        cards_layout.addWidget(self._input_card, 1)
        cards_layout.addWidget(self._audio_card, 1)
        cards_layout.addWidget(self._hid_card, 1)

        cw = QWidget()
        cw.setLayout(cards_layout)
        layout.addWidget(cw, 1)

        # 装饰元素行（加载 Element_11/12/13/15/17）
        decor_row = QHBoxLayout()
        decor_row.setContentsMargins(0, 0, 0, 0)
        decor_row.setSpacing(0)
        decor_row.addStretch()
        self._slider_track_decor = SliderDecorTrack("Element_11.png")
        decor_row.addWidget(self._slider_track_decor)
        self._slider_track_decor2 = SliderDecorTrack("Element_17.png")
        decor_row.addWidget(self._slider_track_decor2)
        self._btn_group_decor = ButtonGroupDecor("Element_13.png")
        decor_row.addWidget(self._btn_group_decor)
        self._btn_group_decor2 = ButtonGroupDecor("Element_15.png")
        decor_row.addWidget(self._btn_group_decor2)
        self._stopped_decor = StoppedButtonDecor()
        decor_row.addWidget(self._stopped_decor)
        decor_row.addStretch()
        dw = QWidget()
        dw.setLayout(decor_row)
        dw.setFixedHeight(2)
        layout.addWidget(dw, 0)

        # 分页指示器
        self._pagination = PaginationDots(3)
        pagination_row = QHBoxLayout()
        pagination_row.setContentsMargins(0, 0, 0, 0)
        pagination_row.addStretch()
        pagination_row.addWidget(self._pagination)
        pagination_row.addStretch()
        pw = QWidget()
        pw.setLayout(pagination_row)
        layout.addWidget(pw, 0, Qt.AlignmentFlag.AlignBottom)

    def _connect_signals(self):
        # 输入法卡片
        self._input_card._toggle.toggled.connect(self._on_ime_toggled)
        self._input_card._send_btn.clicked.connect(self._on_send_text)
        self._input_card._test_input.returnPressed.connect(self._on_send_text)

        # 音频卡片
        self._audio_card._volume_slider.valueChanged.connect(self._on_volume_changed)
        self._audio_card._capture_btn.clicked.connect(self._on_audio_capture)
        self._audio_card._stop_btn.clicked.connect(self._on_audio_stop)
        self._audio_card._mute_radio.toggled.connect(self._on_auto_mute)

        # HID 卡片
        self._hid_card._enable_slider.valueChanged.connect(self._on_hid_enable_changed)
        self._hid_card._capture_btn.clicked.connect(self._on_hid_capture)
        self._hid_card._stop_btn.clicked.connect(self._on_hid_stop)
        self._hid_card._sens_slider.valueChanged.connect(self._on_sens_changed)

        if hasattr(self.audio_mgr, "status_changed"):
            try:
                self.audio_mgr.status_changed.connect(self._on_audio_status)
            except Exception:
                pass
        if hasattr(self.audio_mgr, "error_occurred"):
            try:
                self.audio_mgr.error_occurred.connect(self._on_audio_error)
            except Exception:
                pass

    def _restore_state(self):
        try:
            vol = int(self.audio_mgr.get_volume())
        except Exception:
            vol = 80
        self._audio_card._volume_slider.setValue(vol)
        self._audio_card._volume_value.setText(f"{vol}%")
        self._hid_card._enable_slider.setValue(vol)
        self._hid_card._enable_value.setText("启用" if vol > 0 else "禁用")
        self._audio_card._mute_radio.setChecked(True)
        self._hid_card._sens_value.setText(str(self._hid_card._sens_slider.value()))

    # ===== 输入法卡片回调 =====
    def _on_ime_toggled(self, enabled: bool):
        self._input_card._test_input.setEnabled(enabled)
        self._input_card._send_btn.setEnabled(enabled)

    def _on_send_text(self):
        text = self._input_card._test_input.text().strip()
        if not text:
            return
        self.input_test_requested.emit(text)
        if self._input_card._toggle.isChecked():
            try:
                self.input_mgr.send_text(text)
            except Exception:
                pass

    # ===== 音频卡片回调 =====
    def _on_volume_changed(self, v: int):
        self._audio_card._volume_value.setText(f"{v}%")
        try:
            self.audio_mgr.set_volume(v)
        except Exception:
            pass

    def _on_auto_mute(self, checked: bool):
        try:
            self.audio_mgr.set_auto_mute(checked)
        except Exception:
            pass

    def _on_audio_capture(self):
        if self._audio_capturing:
            return
        try:
            self.audio_mgr.start_capture()
        except Exception:
            pass
        self._audio_capturing = True
        self._audio_card._capture_btn.setStyleSheet(
            "QPushButton { background-color: #0052D9; color: #FFFFFF; border: none;"
            "border-radius: 999px; padding: 10px 26px; font-weight: 700; font-size: 13px; }"
        )

    def _on_audio_stop(self):
        try:
            self.audio_mgr.stop_capture()
        except Exception:
            pass
        self._audio_capturing = False
        self._audio_card._capture_btn.setStyleSheet(
            "QPushButton { background-color: #007DFF; color: #FFFFFF; border: none;"
            "border-radius: 999px; padding: 10px 26px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #0066CC; }"
        )

    def _on_audio_status(self, status: str):
        if status in ("capturing", "playing"):
            self._audio_capturing = True
        elif status in ("stopped", "idle", "error"):
            self._audio_capturing = False

    def _on_audio_error(self, message: str):
        self._audio_capturing = False

    # ===== HID 卡片回调 =====
    def _on_hid_enable_changed(self, v: int):
        self._hid_card._enable_value.setText("启用" if v > 0 else "禁用")

    def _on_hid_capture(self):
        self._hid_capturing = True
        self._hid_card._capture_btn.setStyleSheet(
            "QPushButton { background-color: #0052D9; color: #FFFFFF; border: none;"
            "border-radius: 999px; padding: 10px 26px; font-weight: 700; font-size: 13px; }"
        )

    def _on_hid_stop(self):
        self._hid_capturing = False
        self._hid_card._capture_btn.setStyleSheet(
            "QPushButton { background-color: #007DFF; color: #FFFFFF; border: none;"
            "border-radius: 999px; padding: 10px 26px; font-weight: 700; font-size: 13px; }"
            "QPushButton:hover { background-color: #0066CC; }"
        )

    def _on_sens_changed(self, v: int):
        self._hid_card._sens_value.setText(str(v))
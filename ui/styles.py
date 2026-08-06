APP_QSS = """
* {
    font-family: "HarmonyOS Sans SC", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    color: #182431;
}

QMainWindow {
    background-color: #F1F3F5;
}

QWidget#sidebar {
    background-color: #FFFFFF;
    border-right: 1px solid #E5E8EB;
}

QWidget#content {
    background-color: #F1F3F5;
}

QLabel#appTitle {
    font-size: 22px;
    font-weight: 700;
    color: #007DFF;
    padding: 24px 20px 4px 20px;
    letter-spacing: 1px;
}

QLabel#appSubtitle {
    font-size: 12px;
    color: #99A2B1;
    padding: 0 20px 20px 20px;
    letter-spacing: 0.3px;
}

QLabel#brandLabel {
    font-size: 13px;
    font-weight: 700;
    color: #007DFF;
    padding: 12px 20px 4px 20px;
}

QLabel#brandSub {
    font-size: 11px;
    color: #C4C6CC;
    padding: 0 20px 4px 20px;
}

QLabel#sidebarStatus {
    font-size: 11px;
    color: #99A2B1;
    padding: 10px 20px;
    border-top: 1px solid #E5E8EB;
}

QLabel#versionLabel {
    font-size: 10px;
    color: #C4C6CC;
    padding: 8px 20px 16px 20px;
}

QListWidget#navList {
    background: transparent;
    border: none;
    outline: none;
    padding: 8px;
    spacing: 6px;
}

QListWidget#navList::item {
    padding: 12px 14px;
    border-radius: 8px;
    color: #99A2B1;
    font-size: 14px;
    font-weight: 600;
}

QListWidget#navList::item:hover {
    background-color: #E6F0FF;
    color: #007DFF;
}

QListWidget#navList::item:selected {
    background-color: #007DFF;
    color: #FFFFFF;
    font-weight: 700;
}

QListWidget#navList::item:selected:hover {
    background-color: #0066CC;
}

QPushButton {
    background-color: #FFFFFF;
    color: #182431;
    border: 1px solid #E5E8EB;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #FAFAFA;
    border-color: #C4C6CC;
    color: #007DFF;
}

QPushButton:pressed {
    background-color: #F5F5F5;
}

QPushButton#primaryBtn {
    background-color: #007DFF;
    color: #FFFFFF;
    border: none;
    border-radius: 999px;
    padding: 12px 28px;
    font-weight: 700;
    font-size: 14px;
}

QPushButton#primaryBtn:hover {
    background-color: #0066CC;
}

QPushButton#primaryBtn:pressed {
    background-color: #0052D9;
}

QPushButton#capsuleBtn {
    background-color: #007DFF;
    color: #FFFFFF;
    border: none;
    border-radius: 999px;
    padding: 14px 36px;
    font-weight: 700;
    font-size: 15px;
}

QPushButton#capsuleBtn:hover {
    background-color: #0066CC;
}

QPushButton#capsuleBtn:pressed {
    background-color: #0052D9;
}

QPushButton#stopCapsuleBtn {
    background-color: #FFFFFF;
    color: #182431;
    border: 1.5px solid #E5E8EB;
    border-radius: 999px;
    padding: 14px 36px;
    font-weight: 700;
    font-size: 15px;
}

QPushButton#stopCapsuleBtn:hover {
    background-color: #E6F0FF;
    color: #007DFF;
    border-color: #80BFFF;
}

QPushButton#ghostBtn {
    background-color: #FFFFFF;
    color: #99A2B1;
    border: 1.5px solid #E5E8EB;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 600;
}

QPushButton#ghostBtn:hover {
    background-color: #E6F0FF;
    color: #007DFF;
    border-color: #80BFFF;
}

QPushButton#iconBtn {
    background-color: #F5F5F5;
    border: 1px solid #E5E8EB;
    border-radius: 8px;
    padding: 10px;
    color: #99A2B1;
    font-size: 16px;
}

QPushButton#iconBtn:hover {
    background-color: #E6F0FF;
    color: #007DFF;
    border-color: #80BFFF;
}

QLabel#pageTitle {
    font-size: 28px;
    font-weight: 700;
    color: #182431;
    letter-spacing: 0.5px;
}

QLabel#pageSubtitle {
    font-size: 14px;
    color: #99A2B1;
    font-weight: 500;
}

QFrame#card {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 12px;
}

QFrame#card:hover {
    border-color: #C4C6CC;
}

QLabel#cardTitle {
    font-size: 17px;
    font-weight: 700;
    color: #182431;
}

QLabel#cardSubtitle {
    font-size: 14px;
    color: #99A2B1;
    font-weight: 500;
}

QLabel#cardDesc {
    font-size: 13px;
    color: #C4C6CC;
}

QLabel#deviceName {
    font-size: 15px;
    font-weight: 700;
    color: #182431;
}

QLabel#deviceId {
    font-family: Consolas, Monaco, monospace;
    font-size: 12px;
    color: #99A2B1;
}

QLabel#badge {
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 999px;
    background-color: #F5F5F5;
    color: #99A2B1;
}

QLabel#badgeOnline {
    background-color: #E6F0FF;
    color: #007DFF;
    border: 1px solid #80BFFF;
    font-weight: 700;
}

QLabel#badgeCasting {
    background-color: #E6F0FF;
    color: #007DFF;
    border: 1px solid #80BFFF;
    font-weight: 700;
}

QLabel#badgeError {
    background-color: #FFF0F0;
    color: #FA2A2D;
    border: 1px solid #FFCCCC;
    font-weight: 700;
}

QFrame#iconBadge {
    background-color: #007DFF;
    border-radius: 18px;
    border: none;
}

QLabel#iconLabel {
    font-size: 24px;
    color: #FFFFFF;
}

QCheckBox#toggleSwitch {
    spacing: 0;
}

QCheckBox#toggleSwitch::indicator {
    width: 52px;
    height: 30px;
    border-radius: 15px;
    background-color: #E5E8EB;
    border: none;
}

QCheckBox#toggleSwitch::indicator:checked {
    background-color: #007DFF;
    border: none;
}

QCheckBox#toggleSwitch::indicator:hover {
    background-color: #C4C6CC;
}

QCheckBox#toggleSwitch::indicator:checked:hover {
    background-color: #0066CC;
}

QSlider {
    background: transparent;
    height: 28px;
}

QSlider::groove:horizontal {
    background-color: #E5E8EB;
    height: 6px;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background-color: #007DFF;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #FFFFFF;
    border: 3px solid #007DFF;
    width: 22px;
    height: 22px;
    margin: -8px 0;
    border-radius: 14px;
}

QSlider::handle:horizontal:hover {
    border-color: #4DA6FF;
    background-color: #E6F0FF;
}

QStatusBar {
    background-color: #FFFFFF;
    color: #99A2B1;
    border-top: 1px solid #E5E8EB;
    font-size: 12px;
}

QStatusBar::item {
    border: none;
}

QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #C4C6CC;
    border-radius: 3px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #99A2B1;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 6px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #C4C6CC;
    border-radius: 3px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #99A2B1;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QComboBox {
    background-color: #FFFFFF;
    border: 1.5px solid #E5E8EB;
    border-radius: 8px;
    padding: 10px 16px;
    color: #182431;
    min-width: 140px;
    font-size: 14px;
    font-weight: 600;
}

QComboBox:hover {
    border-color: #80BFFF;
}

QComboBox::drop-down {
    border: none;
    width: 28px;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    color: #182431;
    selection-background-color: #E6F0FF;
    selection-color: #007DFF;
}

QLineEdit {
    background-color: #FFFFFF;
    border: 1.5px solid #E5E8EB;
    border-radius: 8px;
    padding: 10px 16px;
    color: #182431;
    font-size: 14px;
    font-weight: 500;
}

QLineEdit:focus {
    border-color: #007DFF;
    background-color: #FFFFFF;
}

QLineEdit::placeholder {
    color: #C4C6CC;
}

QFrame#phoneShell {
    background-color: #FAFAFA;
    border: 1px solid #E5E8EB;
    border-radius: 40px;
    padding: 12px;
}

QFrame#phoneScreen {
    background: #FFFFFF;
    border-radius: 32px;
}

QLabel#searchIcon {
    color: #99A2B1;
    font-size: 16px;
}

QLabel#sectionLabel {
    font-size: 15px;
    font-weight: 700;
    color: #007DFF;
    letter-spacing: 0.5px;
}

QLabel#sectionHint {
    font-size: 13px;
    color: #C4C6CC;
}

QFrame#settingsCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 12px;
}

QLabel#settingLabel {
    font-size: 14px;
    font-weight: 600;
    color: #182431;
}

QLabel#settingValue {
    font-size: 14px;
    font-weight: 700;
    color: #007DFF;
}

QLabel#fpsDisplay {
    font-family: Consolas, Monaco, monospace;
    font-size: 13px;
    font-weight: 700;
    color: #FFFFFF;
    background-color: #007DFF;
    border-radius: 999px;
    padding: 6px 14px;
}

QFrame#featureCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 12px;
}

QFrame#featureCard:hover {
    border-color: #C4C6CC;
}

QLabel#featureTitle {
    font-size: 16px;
    font-weight: 700;
    color: #182431;
}

QLabel#featureDesc {
    font-size: 13px;
    color: #99A2B1;
    font-weight: 500;
}

QLabel#featureSubtitle {
    font-size: 13px;
    color: #99A2B1;
    font-weight: 500;
}

QLabel#emptyStateTitle {
    font-size: 17px;
    font-weight: 700;
    color: #182431;
}

QLabel#emptyStateDesc {
    font-size: 14px;
    color: #99A2B1;
}

QFrame#emptyState {
    background-color: #FFFFFF;
    border: 2px dashed #C4C6CC;
    border-radius: 12px;
}

QSpinBox {
    background-color: #FFFFFF;
    border: 1.5px solid #E5E8EB;
    border-radius: 8px;
    padding: 8px 14px;
    color: #182431;
    font-size: 14px;
    font-weight: 600;
}

QSpinBox::up-button, QSpinBox::down-button {
    border: none;
    background: transparent;
    width: 20px;
}

QSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #007DFF;
}

QSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #007DFF;
}

QCheckBox {
    color: #182431;
    font-size: 14px;
    font-weight: 600;
    spacing: 12px;
}

QCheckBox::indicator {
    width: 22px;
    height: 22px;
    border-radius: 7px;
    border: 1.5px solid #C4C6CC;
    background: #FFFFFF;
}

QCheckBox::indicator:checked {
    background-color: #007DFF;
    border: 1.5px solid #007DFF;
}

QCheckBox::indicator:hover {
    border-color: #80BFFF;
}

QFrame#toolbar {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 12px;
}

QFrame#settingsPanel {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 12px;
}

QLabel#dotIndicator {
    background-color: #E5E8EB;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

QLabel#dotIndicatorActive {
    background-color: #007DFF;
    border-radius: 4px;
    min-width: 20px;
    max-width: 20px;
    min-height: 8px;
    max-height: 8px;
}

QLabel#shortcutTag {
    background-color: #FAFAFA;
    border: 1px solid #E5E8EB;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 14px;
    font-weight: 600;
    color: #182431;
}

QLabel#betaBadge {
    background-color: #FA9E3B;
    color: #FFFFFF;
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 700;
}

QLabel#hidTag {
    background-color: #FFFFFF;
    border: 1.5px solid #E5E8EB;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 14px;
    font-weight: 700;
    color: #182431;
}

QLabel#statusCapsule {
    background-color: #FFFFFF;
    border: 1.5px solid #E5E8EB;
    border-radius: 999px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 600;
    color: #99A2B1;
}

QLabel#statusCapsuleActive {
    background-color: #007DFF;
    color: #FFFFFF;
    border-radius: 999px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 700;
}

QFrame#decorRipple {
    background: transparent;
    border: none;
}

QFrame#rippleContainer {
    background: transparent;
    border: none;
}

QLabel#waveformContainer {
    background: transparent;
}

QPushButton#toolBtn {
    background-color: #007DFF;
    border: none;
    border-radius: 12px;
    color: #FFFFFF;
    font-size: 18px;
}

QPushButton#toolBtn:hover {
    background-color: #0066CC;
}

QPushButton#toolBtn:checked {
    background-color: #0052D9;
}

QLabel#navDot {
    background-color: #C4C6CC;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

QLabel#navDotActive {
    background-color: #007DFF;
    border-radius: 4px;
    min-width: 24px;
    max-width: 24px;
    min-height: 8px;
    max-height: 8px;
}

QLabel#sectionDivider {
    background-color: #E5E8EB;
    min-height: 1px;
    max-height: 1px;
}

QLabel#waveLabel {
    color: #99A2B1;
    font-size: 12px;
    font-weight: 600;
}

QFrame#iconCircle {
    background-color: #007DFF;
    border-radius: 50%;
    border: none;
}

QLabel#navIconLabel {
    color: #FFFFFF;
    font-size: 18px;
}

QLabel#deviceIconLabel {
    color: #FFFFFF;
    font-size: 24px;
}

QLabel#featureIconLabel {
    color: #FFFFFF;
    font-size: 28px;
}

QLabel#statusText {
    font-size: 13px;
    font-weight: 600;
}

QLabel#numberBadge {
    background-color: #007DFF;
    color: #FFFFFF;
    border-radius: 12px;
    padding: 4px 12px;
    font-size: 14px;
    font-weight: 700;
}

QLabel#rippleBg {
    background: transparent;
    border: none;
}

QFrame#circleDecor {
    background: transparent;
    border: none;
    border-radius: 50%;
}

QLabel#labelWithIcon {
    color: #99A2B1;
    font-size: 14px;
    font-weight: 600;
}

QPushButton#iconRoundBtn {
    background-color: #FFFFFF;
    border: 1.5px solid #E5E8EB;
    border-radius: 50%;
    color: #99A2B1;
    font-size: 16px;
}

QPushButton#iconRoundBtn:hover {
    background-color: #E6F0FF;
    color: #007DFF;
    border-color: #80BFFF;
}

QLabel#badge16dp {
    font-size: 11px;
    font-weight: 700;
    color: #99A2B1;
    background: transparent;
    padding: 0;
}

QLabel#betaBadgeV2 {
    font-size: 11px;
    font-weight: 700;
    color: #FFFFFF;
    background-color: #FA9E3B;
    border-radius: 999px;
    padding: 3px 10px;
}

QLabel#hidBadge {
    font-size: 11px;
    font-weight: 700;
    color: #182431;
    background: #FFFFFF;
    border: 1.5px solid #E5E8EB;
    border-radius: 8px;
    padding: 2px 8px;
}

QLabel#paginationDotActive {
    background-color: #007DFF;
    border-radius: 4px;
    min-width: 22px;
    max-width: 22px;
    min-height: 8px;
    max-height: 8px;
}

QLabel#paginationDot {
    background-color: #E5E8EB;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

QFrame#cardRippleContainer {
    background: transparent;
    border: none;
}
"""

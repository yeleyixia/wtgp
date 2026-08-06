import sys
import os
import traceback
import tempfile

def find_base_dir() -> str:
    candidates = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates.append(sys._MEIPASS)
    candidates.append(os.path.dirname(sys.executable))
    candidates.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    for path in candidates:
        if path and os.path.isdir(os.path.join(path, "resources", "tools", "hdc")):
            return path
    return candidates[-1]

BASE_DIR = find_base_dir()

if getattr(sys, 'frozen', False) or not os.path.exists(os.path.join(BASE_DIR, "main.py")):
    log_file = os.path.join(tempfile.gettempdir(), "weitougeping.log")
    try:
        sys.stderr = open(log_file, 'w', encoding='utf-8')
    except Exception:
        pass
os.environ['QT_QPA_PLATFORM'] = 'windows'

from PySide6.QtWidgets import QApplication, QSplashScreen, QMessageBox
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QIcon
from PySide6.QtCore import Qt, QTimer

from ui.styles import APP_QSS


def resource_path(rel_path: str) -> str:
    """Resolve resource path for both dev mode and frozen (Nuitka/PyInstaller) onefile mode."""
    # Dev mode: relative to this file
    dev_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)
    if os.path.exists(dev_path):
        return dev_path
    # Frozen: check next to the executable (for files placed alongside exe)
    exe_dir = os.path.dirname(sys.executable)
    exe_path = os.path.join(exe_dir, rel_path)
    if os.path.exists(exe_path):
        return exe_path
    # PyInstaller / Nuitka temp extract dir (MEIPASS)
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        meipath = os.path.join(sys._MEIPASS, rel_path)
        if os.path.exists(meipath):
            return meipath
    # Fallback: BASE_DIR
    fallback = os.path.join(BASE_DIR, rel_path)
    return fallback


def set_app_icon(app, window=None):
    """Try to load favicon.ico and set as app + window icon."""
    ico_path = resource_path("favicon.ico")
    if os.path.exists(ico_path):
        icon = QIcon(ico_path)
        if not icon.isNull():
            app.setWindowIcon(icon)
            if window is not None:
                window.setWindowIcon(icon)
            return True
    # Fallback: try the old icon path
    alt_path = resource_path(os.path.join("resources", "tools", "icon.ico"))
    if os.path.exists(alt_path):
        icon = QIcon(alt_path)
        if not icon.isNull():
            app.setWindowIcon(icon)
            if window is not None:
                window.setWindowIcon(icon)
            return True
    return False


def create_splash():
    pixmap = QPixmap(480, 280)
    pixmap.fill(QColor("#F1F3F5"))
    painter = QPainter(pixmap)
    
    painter.setPen(QColor("#007DFF"))
    painter.setFont(QFont("HarmonyOS Sans SC", 36, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "为投个屏")
    painter.setPen(QColor("#99A2B1"))
    painter.setFont(QFont("HarmonyOS Sans SC", 11))
    sub_rect = pixmap.rect()
    sub_rect.setTop(180)
    painter.drawText(sub_rect, Qt.AlignmentFlag.AlignHCenter, "HarmonyOS 投屏工具")
    painter.end()
    return pixmap


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    app.setApplicationName("为投个屏")

    splash_pix = create_splash()
    splash = QSplashScreen(splash_pix)
    splash.show()
    app.processEvents()

    try:
        from ui.main_window import MainWindow
        window = MainWindow()
        window.resize(1280, 800)
        window.setWindowTitle("为投个屏 - HarmonyOS 投屏工具")

        # 设置应用和窗口图标
        set_app_icon(app, window)

        QTimer.singleShot(800, lambda: (splash.finish(window), window.show()))

        sys.exit(app.exec())
    except Exception as e:
        splash.close()
        err_msg = f"启动失败：{str(e)}\n\n{traceback.format_exc()}"
        print(err_msg, file=sys.stderr)
        QMessageBox.critical(None, "启动错误", err_msg)
        sys.exit(1)


if __name__ == "__main__":
    main()

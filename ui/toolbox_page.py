import os
import sys
import time
import subprocess
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QTextEdit, QLineEdit, QGridLayout,
    QFileDialog, QListWidget, QListWidgetItem, QSizePolicy, QSplitter
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat, QIcon, QPixmap


def _find_hdc():
    candidates = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates.append(sys._MEIPASS)
    candidates.append(os.path.dirname(sys.executable))
    candidates.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for path in candidates:
        hdc_path = os.path.join(path, "resources", "tools", "hdc", "hdc.exe")
        if os.path.exists(hdc_path):
            return hdc_path
    return "hdc"


class ShellWorker(QThread):
    """后台执行 HDC shell 命令"""
    output_ready = Signal(str)
    finished_execution = Signal()

    def __init__(self, hdc_path, device_id, command, parent=None):
        super().__init__(parent)
        self._hdc_path = hdc_path
        self._device_id = device_id
        self._command = command

    def run(self):
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            # 判断命令是否已包含 hdc 前缀
            if self._command.strip().lower().startswith("hdc"):
                parts = self._command.strip().split()
                # 用内置 hdc 路径替换 "hdc" 前缀，避免依赖系统 PATH
                if parts and parts[0].lower() == "hdc":
                    parts[0] = self._hdc_path
                cmd = parts
            else:
                # 通过 hdc shell 执行
                cmd = [self._hdc_path, "-t", self._device_id, "shell", self._command]

            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=15,
                creationflags=creationflags
            )
            output = result.stdout or result.stderr or "(无输出)"
            self.output_ready.emit(output)
        except subprocess.TimeoutExpired:
            self.output_ready.emit("(命令执行超时)")
        except Exception as e:
            self.output_ready.emit(f"错误: {str(e)}")
        finally:
            self.finished_execution.emit()


class LogWorker(QThread):
    """后台采集设备日志"""
    log_line = Signal(str, str)  # (level, message)
    stopped = Signal()

    def __init__(self, hdc_path, device_id, filter_tag="", parent=None):
        super().__init__(parent)
        self._hdc_path = hdc_path
        self._device_id = device_id
        self._filter_tag = filter_tag
        self._running = False

    def run(self):
        self._running = True
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            cmd = [self._hdc_path, "-t", self._device_id, "shell", "hilog"]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
                bufsize=1,
            )
            while self._running and proc.poll() is None:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                # 解析日志级别
                level = "INFO"
                if " F " in line or "Fatal" in line:
                    level = "ERROR"
                elif " W " in line or "Warn" in line:
                    level = "WARN"
                elif " D " in line or "Debug" in line:
                    level = "DEBUG"
                # 过滤标签
                if self._filter_tag and self._filter_tag.lower() not in line.lower():
                    continue
                self.log_line.emit(level, line)
        except Exception:
            pass
        finally:
            self.stopped.emit()

    def stop(self):
        self._running = False
        self.wait(3000)


class ToolboxPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._hdc_path = _find_hdc()
        self._device_id = None
        self._shell_worker = None
        self._log_worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        page_title = QLabel("工具箱")
        page_title.setObjectName("pageTitle")
        title_col.addWidget(page_title)

        page_sub = QLabel("集成常用的设备调试工具")
        page_sub.setObjectName("pageSubtitle")
        title_col.addWidget(page_sub)

        header.addLayout(title_col, 1)

        # 设备选择
        self.device_label = QLabel("设备: 未选择")
        self.device_label.setStyleSheet(
            "font-size: 13px; color: #99A2B1; font-weight: 600;"
            "background: #FFFFFF; border: 1px solid #E5E8EB; border-radius: 8px;"
            "padding: 8px 16px;"
        )
        header.addWidget(self.device_label)

        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #E5E8EB;
                border-radius: 12px;
                background-color: #FFFFFF;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #F1F3F5;
                color: #99A2B1;
                padding: 10px 24px;
                border: 1px solid #E5E8EB;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 2px;
                font-size: 14px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background-color: #FFFFFF;
                color: #007DFF;
                border-bottom: 2px solid #007DFF;
            }
            QTabBar::tab:hover:!selected {
                color: #182431;
            }
        """)

        self._create_shell_tab()
        self._create_file_manager_tab()
        self._create_log_viewer_tab()

        layout.addWidget(self.tabs, 1)

        # 定时刷新设备
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_device)
        self._refresh_timer.start(3000)
        self._refresh_device()

    def set_device(self, device_id: str):
        self._device_id = device_id
        if device_id:
            self.device_label.setText(f"设备: {device_id}")
            self.device_label.setStyleSheet(
                "font-size: 13px; color: #007DFF; font-weight: 700;"
                "background: #E6F0FF; border: 1px solid #80BFFF; border-radius: 8px;"
                "padding: 8px 16px;"
            )
        else:
            self.device_label.setText("设备: 未选择")
            self.device_label.setStyleSheet(
                "font-size: 13px; color: #99A2B1; font-weight: 600;"
                "background: #FFFFFF; border: 1px solid #E5E8EB; border-radius: 8px;"
                "padding: 8px 16px;"
            )

    def _refresh_device(self):
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(
                [self._hdc_path, "list", "targets"],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=5,
                creationflags=creationflags
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("["):
                        # 行格式: "<device_id> <status>"，只需设备 ID
                        self.set_device(line.split()[0])
                        return
            self.set_device(None)
        except Exception:
            pass

    def _create_shell_tab(self):
        shell_widget = QWidget()
        shell_layout = QVBoxLayout(shell_widget)
        shell_layout.setContentsMargins(16, 16, 16, 16)
        shell_layout.setSpacing(12)

        # 提示
        hint = QLabel("输入 hdc 命令或 shell 命令。例如: hilog -x | param get const.product.name")
        hint.setStyleSheet("font-size: 12px; color: #99A2B1; font-weight: 500;")
        shell_layout.addWidget(hint)

        self.shell_output = QTextEdit()
        self.shell_output.setReadOnly(True)
        self.shell_output.setStyleSheet("""
            QTextEdit {
                background-color: #FAFAFA;
                color: #182431;
                border: 1px solid #E5E8EB;
                border-radius: 8px;
                padding: 12px;
                font-family: Consolas, Monaco, monospace;
                font-size: 13px;
            }
        """)
        self.shell_output.setPlainText("HarmonyOS Shell 就绪\n输入命令后按回车执行...\n")
        shell_layout.addWidget(self.shell_output, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.shell_input = QLineEdit()
        self.shell_input.setPlaceholderText("输入命令，如: param get const.product.name")
        self.shell_input.setFixedHeight(36)
        self.shell_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1.5px solid #E5E8EB;
                border-radius: 8px;
                padding: 8px 16px;
                color: #182431;
                font-size: 14px;
                font-weight: 500;
            }
            QLineEdit:focus {
                border-color: #007DFF;
            }
        """)
        self.shell_input.returnPressed.connect(self._execute_shell_command)
        input_row.addWidget(self.shell_input, 1)

        self.exec_btn = QPushButton("执行")
        self.exec_btn.setObjectName("primaryBtn")
        self.exec_btn.setFixedHeight(36)
        self.exec_btn.clicked.connect(self._execute_shell_command)
        input_row.addWidget(self.exec_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setFixedHeight(36)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #99A2B1;
                border: 1.5px solid #E5E8EB;
                border-radius: 8px;
                padding: 8px 20px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #E6F0FF;
                color: #007DFF;
                border-color: #80BFFF;
            }
        """)
        clear_btn.clicked.connect(lambda: self.shell_output.clear())
        input_row.addWidget(clear_btn)

        shell_layout.addLayout(input_row)

        self.tabs.addTab(shell_widget, "终端")

    def _execute_shell_command(self):
        command = self.shell_input.text().strip()
        if not command:
            return

        if not self._device_id and not command.lower().startswith("hdc"):
            self._append_shell_text("错误: 未选择设备，请先连接设备\n", "#FA2A2D")
            return

        cursor = self.shell_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#007DFF"))
        fmt.setFontWeight(QFont.Weight.Bold)
        cursor.setCharFormat(fmt)
        cursor.insertText(f"$ {command}\n")

        self.shell_input.clear()
        self.exec_btn.setEnabled(False)

        device = self._device_id or ""
        self._shell_worker = ShellWorker(self._hdc_path, device, command)
        self._shell_worker.output_ready.connect(
            lambda text: self._append_shell_text(text + "\n", "#182431")
        )
        self._shell_worker.finished_execution.connect(
            lambda: self.exec_btn.setEnabled(True)
        )
        self._shell_worker.start()

    def _append_shell_text(self, text: str, color: str = "#182431"):
        cursor = self.shell_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontFamily("Consolas")
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.shell_output.setTextCursor(cursor)
        self.shell_output.ensureCursorVisible()

    def _create_file_manager_tab(self):
        file_widget = QWidget()
        file_layout = QHBoxLayout(file_widget)
        file_layout.setContentsMargins(16, 16, 16, 16)
        file_layout.setSpacing(16)

        # 本地文件面板
        local_panel = QFrame()
        local_panel.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border: 1px solid #E5E8EB; border-radius: 12px; }"
        )
        local_layout = QVBoxLayout(local_panel)
        local_layout.setContentsMargins(12, 12, 12, 12)
        local_layout.setSpacing(8)

        local_header = QHBoxLayout()
        local_title = QLabel("本地文件")
        local_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #182431;")
        local_header.addWidget(local_title)
        local_header.addStretch()

        local_upload_btn = QPushButton("上传到设备")
        local_upload_btn.setFixedHeight(30)
        local_upload_btn.setStyleSheet("""
            QPushButton {
                background-color: #007DFF;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)
        local_upload_btn.clicked.connect(self._upload_file)
        local_header.addWidget(local_upload_btn)
        local_layout.addLayout(local_header)

        # 本地路径输入
        self.local_path_input = QLineEdit()
        self.local_path_input.setPlaceholderText("本地路径...")
        self.local_path_input.setFixedHeight(30)
        self.local_path_input.setStyleSheet("""
            QLineEdit {
                background-color: #FAFAFA;
                border: 1px solid #E5E8EB;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QLineEdit:focus { border-color: #007DFF; }
        """)
        local_browse_btn = QPushButton("浏览")
        local_browse_btn.setFixedHeight(30)
        local_browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F3F5;
                color: #182431;
                border: 1px solid #E5E8EB;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #E6F0FF; color: #007DFF; }
        """)
        local_browse_btn.clicked.connect(self._browse_local_file)

        local_path_row = QHBoxLayout()
        local_path_row.addWidget(self.local_path_input, 1)
        local_path_row.addWidget(local_browse_btn)
        local_layout.addLayout(local_path_row)

        self.local_list = QListWidget()
        self.local_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; color: #182431; font-size: 13px; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #F1F3F5; }"
            "QListWidget::item:hover { background-color: #E6F0FF; }"
            "QListWidget::item:selected { background-color: #007DFF; color: #FFFFFF; }"
        )
        local_layout.addWidget(self.local_list, 1)
        file_layout.addWidget(local_panel, 1)

        # 设备文件面板
        remote_panel = QFrame()
        remote_panel.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border: 1px solid #E5E8EB; border-radius: 12px; }"
        )
        remote_layout = QVBoxLayout(remote_panel)
        remote_layout.setContentsMargins(12, 12, 12, 12)
        remote_layout.setSpacing(8)

        remote_header = QHBoxLayout()
        remote_title = QLabel("设备文件")
        remote_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #182431;")
        remote_header.addWidget(remote_title)
        remote_header.addStretch()

        remote_download_btn = QPushButton("下载到本地")
        remote_download_btn.setFixedHeight(30)
        remote_download_btn.setStyleSheet("""
            QPushButton {
                background-color: #007DFF;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #0066CC; }
        """)
        remote_download_btn.clicked.connect(self._download_file)
        remote_header.addWidget(remote_download_btn)
        remote_layout.addLayout(remote_header)

        # 设备路径输入
        self.remote_path_input = QLineEdit("/data/local/tmp/")
        self.remote_path_input.setFixedHeight(30)
        self.remote_path_input.setStyleSheet("""
            QLineEdit {
                background-color: #FAFAFA;
                border: 1px solid #E5E8EB;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                font-family: Consolas, monospace;
            }
            QLineEdit:focus { border-color: #007DFF; }
        """)
        remote_refresh_btn = QPushButton("刷新")
        remote_refresh_btn.setFixedHeight(30)
        remote_refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F3F5;
                color: #182431;
                border: 1px solid #E5E8EB;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #E6F0FF; color: #007DFF; }
        """)
        remote_refresh_btn.clicked.connect(self._refresh_remote_files)
        remote_path_row = QHBoxLayout()
        remote_path_row.addWidget(self.remote_path_input, 1)
        remote_path_row.addWidget(remote_refresh_btn)
        remote_layout.addLayout(remote_path_row)

        self.remote_list = QListWidget()
        self.remote_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; color: #182431; font-size: 13px; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #F1F3F5; }"
            "QListWidget::item:hover { background-color: #E6F0FF; }"
            "QListWidget::item:selected { background-color: #007DFF; color: #FFFFFF; }"
        )
        self.remote_list.itemDoubleClicked.connect(self._navigate_remote)
        remote_layout.addWidget(self.remote_list, 1)
        file_layout.addWidget(remote_panel, 1)

        self.tabs.addTab(file_widget, "文件管理")

    def _browse_local_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if path:
            self.local_path_input.setText(path)

    def _upload_file(self):
        local_path = self.local_path_input.text().strip()
        if not local_path or not os.path.exists(local_path):
            return
        if not self._device_id:
            return
        remote_dir = self.remote_path_input.text().strip() or "/data/local/tmp/"
        filename = os.path.basename(local_path)
        remote_path = f"{remote_dir.rstrip('/')}/{filename}"

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(
                [self._hdc_path, "-t", self._device_id, "file", "send", local_path, remote_path],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=30,
                creationflags=creationflags
            )
            if result.returncode == 0:
                self._refresh_remote_files()
        except Exception:
            pass

    def _download_file(self):
        if not self._device_id:
            return
        current = self.remote_list.currentItem()
        if not current:
            return
        filename = current.text()
        # 如果是目录，不下载
        if filename.startswith("[DIR]"):
            return
        # 优先使用保存的真实文件名，避免显示文本中的大小信息混入路径
        filename = current.data(Qt.ItemDataRole.UserRole) or filename
        remote_dir = self.remote_path_input.text().strip()
        remote_path = f"{remote_dir.rstrip('/')}/{filename}"

        save_path, _ = QFileDialog.getSaveFileName(self, "保存文件", filename)
        if not save_path:
            return

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(
                [self._hdc_path, "-t", self._device_id, "file", "recv", remote_path, save_path],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=30,
                creationflags=creationflags
            )
        except Exception:
            pass

    def _refresh_remote_files(self):
        if not self._device_id:
            self.remote_list.clear()
            self.remote_list.addItem("(未连接设备)")
            return

        remote_dir = self.remote_path_input.text().strip() or "/data/local/tmp/"
        self.remote_list.clear()

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(
                [self._hdc_path, "-t", self._device_id, "shell", "ls", "-la", remote_dir],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=8,
                creationflags=creationflags
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if not line or line.startswith("total"):
                        continue
                    # 解析 ls -la 输出
                    parts = line.split()
                    if len(parts) >= 8:
                        is_dir = parts[0].startswith("d")
                        name = " ".join(parts[7:])
                        if is_dir:
                            item = QListWidgetItem(f"[DIR]  {name}/")
                            item.setForeground(QColor("#007DFF"))
                        else:
                            size = parts[4]
                            item = QListWidgetItem(f"[FILE] {name}  ({size} bytes)")
                        # 保存真实文件名，避免从显示文本反解出错
                        item.setData(Qt.ItemDataRole.UserRole, name)
                        self.remote_list.addItem(item)
            else:
                self.remote_list.addItem("(无法读取目录)")
        except Exception:
            self.remote_list.addItem("(读取失败)")

    def _navigate_remote(self, item):
        text = item.text()
        if text.startswith("[DIR]"):
            dirname = item.data(Qt.ItemDataRole.UserRole) or text
            dirname = dirname.replace("/", "").strip()
            current = self.remote_path_input.text().strip()
            if dirname == "..":
                parts = current.rstrip("/").split("/")
                parts.pop()
                new_path = "/".join(parts) or "/"
            else:
                new_path = f"{current.rstrip('/')}/{dirname}"
            self.remote_path_input.setText(new_path + "/")
            self._refresh_remote_files()

    def _create_log_viewer_tab(self):
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(16, 16, 16, 16)
        log_layout.setSpacing(12)

        log_header = QHBoxLayout()
        log_header.setSpacing(8)

        log_title = QLabel("实时日志")
        log_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #182431;")
        log_header.addWidget(log_title)

        log_header.addStretch()

        filter_label = QLabel("过滤:")
        filter_label.setStyleSheet("font-size: 13px; color: #99A2B1; font-weight: 600;")
        log_header.addWidget(filter_label)

        self.log_filter_input = QLineEdit()
        self.log_filter_input.setPlaceholderText("过滤标签 (可选)")
        self.log_filter_input.setFixedWidth(150)
        self.log_filter_input.setFixedHeight(32)
        self.log_filter_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1.5px solid #E5E8EB;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QLineEdit:focus { border-color: #007DFF; }
        """)
        log_header.addWidget(self.log_filter_input)

        self.log_start_btn = QPushButton("开始")
        self.log_start_btn.setObjectName("primaryBtn")
        self.log_start_btn.setFixedHeight(32)
        self.log_start_btn.clicked.connect(self._toggle_log)
        log_header.addWidget(self.log_start_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setFixedHeight(32)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #99A2B1;
                border: 1.5px solid #E5E8EB;
                border-radius: 8px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #E6F0FF; color: #007DFF; }
        """)
        clear_btn.clicked.connect(lambda: self.log_output.clear())
        log_header.addWidget(clear_btn)

        log_layout.addLayout(log_header)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background-color: #FAFAFA;
                color: #182431;
                border: 1px solid #E5E8EB;
                border-radius: 8px;
                padding: 12px;
                font-family: Consolas, Monaco, monospace;
                font-size: 12px;
            }
        """)
        log_layout.addWidget(self.log_output, 1)

        self.tabs.addTab(log_widget, "日志查看")

    def _toggle_log(self):
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()
            self._log_worker = None
            self.log_start_btn.setText("开始")
        else:
            if not self._device_id:
                self._append_log("ERROR", "未连接设备，无法采集日志")
                return

            filter_tag = self.log_filter_input.text().strip()
            self._log_worker = LogWorker(self._hdc_path, self._device_id, filter_tag)
            self._log_worker.log_line.connect(self._on_log_line)
            self._log_worker.stopped.connect(lambda: self.log_start_btn.setText("开始"))
            self._log_worker.start()
            self.log_start_btn.setText("停止")

    def _on_log_line(self, level: str, message: str):
        color_map = {
            "INFO": "#182431",
            "WARN": "#FA9E3B",
            "ERROR": "#FA2A2D",
            "DEBUG": "#99A2B1",
        }
        color = color_map.get(level, "#182431")
        self._append_log(level, message, color)

    def _append_log(self, level: str, message: str, color: str = "#182431"):
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontFamily("Consolas")
        cursor.setCharFormat(fmt)
        timestamp = time.strftime("%H:%M:%S")
        cursor.insertText(f"[{timestamp}] {level:5s} | {message}\n")
        self.log_output.setTextCursor(cursor)
        self.log_output.ensureCursorVisible()

    def stop(self):
        """外部调用：停止所有后台任务"""
        self._refresh_timer.stop()
        if self._log_worker:
            self._log_worker.stop()
            self._log_worker = None
        if self._shell_worker:
            self._shell_worker.quit()
            self._shell_worker = None

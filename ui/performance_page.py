import time
import subprocess
import re
import os
import sys
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QScrollArea, QSizePolicy, QComboBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QPoint
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QPolygon, QPainterPath


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


class MetricCard(QFrame):
    def __init__(self, title: str, unit: str, parent=None):
        super().__init__(parent)
        self.setObjectName("deviceCard")
        self.setFixedHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._value = 0
        self._max_value = 100
        self._title = title
        self._unit = unit
        self._history = []
        self._max_history = 60

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 12px; color: #99A2B1; font-weight: 600;")
        layout.addWidget(title_label)

        self.value_label = QLabel(f"-- {unit}")
        self.value_label.setStyleSheet("font-size: 24px; font-weight: 700; color: #007DFF;")
        layout.addWidget(self.value_label)

        self.chart = MiniChart()
        self.chart.setFixedHeight(40)
        layout.addWidget(self.chart, 1)

    def update_value(self, value: float):
        self._value = value
        self._history.append(value)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        if self._unit == "FPS":
            self.value_label.setText(f"{value:.0f} {self._unit}")
        elif self._unit == "%":
            self.value_label.setText(f"{value:.1f} {self._unit}")
        else:
            self.value_label.setText(f"{value:.0f} {self._unit}")

        self.chart.update_data(self._history)


class MiniChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self._max = 100

    def update_data(self, data: list):
        self._data = data
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        if len(self._data) < 2:
            painter.end()
            return

        max_val = max(max(self._data) * 1.2, 1) if self._data else 1
        min_val = min(self._data) * 0.8 if self._data else 0
        val_range = max_val - min_val if max_val != min_val else 1

        painter.setPen(Qt.PenStyle.NoPen)

        points = []
        step_x = rect.width() / max(len(self._data) - 1, 1)
        for i, val in enumerate(self._data):
            x = i * step_x
            y = rect.height() - ((val - min_val) / val_range) * rect.height() * 0.9 - 2
            points.append((x, y))

        path_points = [QPoint(int(x), int(y)) for x, y in points]

        polygon = QPolygon(path_points + [
            QPoint(int(points[-1][0]), rect.height()),
            QPoint(int(points[0][0]), rect.height())
        ])

        gradient = painter.createLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0, QColor(0, 125, 255, 100))
        gradient.setColorAt(1, QColor(0, 125, 255, 0))
        painter.setBrush(QBrush(gradient))
        painter.drawPolygon(polygon)

        pen = QPen(QColor(0, 125, 255))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        path = QPainterPath()
        if path_points:
            path.moveTo(path_points[0])
            for pt in path_points[1:]:
                path.lineTo(pt)
            painter.drawPath(path)

        painter.end()


class DeviceMetricThread(QThread):
    """后台线程：通过 HDC 采集设备性能指标"""
    metrics_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, hdc_path: str, device_id: str, parent=None):
        super().__init__(parent)
        self._hdc_path = hdc_path
        self._device_id = device_id
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            metrics = {}
            try:
                # CPU 使用率：通过 top 命令
                cpu = self._get_cpu_usage()
                if cpu is not None:
                    metrics["cpu"] = cpu

                # 内存：通过 hidumper
                mem = self._get_memory_usage()
                if mem is not None:
                    metrics["memory"] = mem

                # 电量
                battery = self._get_battery()
                if battery is not None:
                    metrics["battery"] = battery

                # 温度
                temp = self._get_temperature()
                if temp is not None:
                    metrics["temp"] = temp

                if metrics:
                    self.metrics_ready.emit(metrics)
            except Exception:
                pass
            self.msleep(2000)

    def stop(self):
        self._running = False
        self.wait(3000)

    def _run_hdc_shell(self, cmd_str: str, timeout: int = 8) -> str:
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(
                [self._hdc_path, "-t", self._device_id, "shell", cmd_str],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=timeout,
                creationflags=creationflags
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _get_cpu_usage(self) -> float | None:
        out = self._run_hdc_shell("top -n 1 -b 2>/dev/null | head -5")
        if not out:
            out = self._run_hdc_shell("top -n 1 2>/dev/null | head -5")
        if out:
            # 尝试匹配 CPU 使用率百分比
            match = re.search(r"(\d+\.?\d*)%.*cpu", out, re.IGNORECASE)
            if match:
                return float(match.group(1))
            # 尝试匹配 "CPU: x%" 格式
            match = re.search(r"cpu[:\s]+(\d+\.?\d*)%", out, re.IGNORECASE)
            if match:
                return float(match.group(1))
        return None

    def _get_memory_usage(self) -> float | None:
        out = self._run_hdc_shell("hidumper -s ResourceManager -a \"meminfo\" 2>/dev/null | head -20")
        used = self._parse_mem_used(out)
        if used is not None:
            return used
        # hidumper 输出非空但解析不出 MemTotal 时，回退到 /proc/meminfo
        out = self._run_hdc_shell("cat /proc/meminfo 2>/dev/null | head -5")
        return self._parse_mem_used(out)

    @staticmethod
    def _parse_mem_used(out: str) -> float | None:
        if not out:
            return None
        total_match = re.search(r"MemTotal:\s+(\d+)", out)
        avail_match = re.search(r"MemAvailable:\s+(\d+)", out)
        if total_match and avail_match:
            total = int(total_match.group(1))
            avail = int(avail_match.group(1))
            return (total - avail) / 1024  # 转为 MB
        return None

    def _get_battery(self) -> float | None:
        # 优先使用 hidumper BatteryService
        out = self._run_hdc_shell("hidumper -s BatteryService -a \"-i\" 2>/dev/null | head -20")
        if out:
            # capacity: 100
            match = re.search(r"capacity:\s*(\d+)", out, re.IGNORECASE)
            if match:
                return float(match.group(1))
        # 回退: sysfs
        out = self._run_hdc_shell("cat /sys/class/power_supply/battery/capacity 2>/dev/null")
        if out:
            try:
                return float(out.strip())
            except ValueError:
                pass
        return None

    def _get_temperature(self) -> float | None:
        # 优先使用 hidumper BatteryService (温度值需要除以10)
        out = self._run_hdc_shell("hidumper -s BatteryService -a \"-i\" 2>/dev/null | head -20")
        if out:
            match = re.search(r"temperature:\s*(\d+)", out, re.IGNORECASE)
            if match:
                return float(match.group(1)) / 10.0
        # 回退: thermal zone
        out = self._run_hdc_shell("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
        if out:
            try:
                val = float(out.strip())
                return val / 1000 if val > 1000 else val
            except ValueError:
                pass
        return None


class PerformancePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitoring = False
        self._device_id = None
        self._hdc_path = _find_hdc()
        self._metric_thread: DeviceMetricThread | None = None
        self._fps = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        page_title = QLabel("性能监控")
        page_title.setObjectName("pageTitle")
        title_col.addWidget(page_title)

        page_sub = QLabel("实时采集设备性能指标")
        page_sub.setObjectName("pageSubtitle")
        title_col.addWidget(page_sub)

        header.addLayout(title_col, 1)

        self.start_btn = QPushButton("开始监控")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.setFixedHeight(36)
        self.start_btn.clicked.connect(self._toggle_monitoring)
        header.addWidget(self.start_btn)

        layout.addLayout(header)

        devices_label = QLabel("选择设备:")
        devices_label.setStyleSheet("font-size: 13px; color: #99A2B1; font-weight: 600;")
        layout.addWidget(devices_label)

        self.device_combo = QComboBox()
        self.device_combo.setFixedHeight(36)
        layout.addWidget(self.device_combo)

        grid = QGridLayout()
        grid.setSpacing(16)

        self.fps_card = MetricCard("投屏帧率 FPS", "FPS")
        self.cpu_card = MetricCard("CPU 占用", "%")
        self.gpu_card = MetricCard("GPU 负载", "%")
        self.memory_card = MetricCard("内存使用", "MB")
        self.battery_card = MetricCard("电量", "%")
        self.temp_card = MetricCard("温度", "°C")

        grid.addWidget(self.fps_card, 0, 0)
        grid.addWidget(self.cpu_card, 0, 1)
        grid.addWidget(self.gpu_card, 0, 2)
        grid.addWidget(self.memory_card, 1, 0)
        grid.addWidget(self.battery_card, 1, 1)
        grid.addWidget(self.temp_card, 1, 2)

        layout.addLayout(grid, 1)

        # 提示信息
        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet("font-size: 12px; color: #99A2B1; padding: 8px 4px;")
        layout.addWidget(self.hint_label)

        # 定时刷新设备列表
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_devices)
        self._refresh_timer.start(3000)
        self._refresh_devices()

        # FPS 更新定时器 (模拟，实际 FPS 由外部设置)
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._update_fps)

    def set_fps(self, fps: int):
        """外部调用：更新投屏帧率"""
        self._fps = fps

    def _refresh_devices(self):
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
                devices = []
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("["):
                        # 行格式: "<device_id> <status>"，只需设备 ID
                        devices.append(line.split()[0])
                current = self.device_combo.currentText()
                self.device_combo.clear()
                for d in devices:
                    self.device_combo.addItem(d)
                if current and current in devices:
                    self.device_combo.setCurrentText(current)
                if not devices:
                    self.device_combo.addItem("（无设备连接）")
                    self.hint_label.setText("提示: 请通过 USB 连接 HarmonyOS 设备并开启调试模式")
                else:
                    self.hint_label.setText("")
        except Exception:
            if self.device_combo.count() == 0:
                self.device_combo.addItem("（HDC 未找到）")

    def _toggle_monitoring(self):
        if self._monitoring:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self):
        device = self.device_combo.currentText()
        if not device or device.startswith("（"):
            self.hint_label.setText("请先选择一个已连接的设备")
            return

        self._device_id = device
        self._monitoring = True
        self.start_btn.setText("停止监控")

        # 启动指标采集线程
        self._metric_thread = DeviceMetricThread(self._hdc_path, device)
        self._metric_thread.metrics_ready.connect(self._on_metrics_ready)
        self._metric_thread.start()

        # 启动 FPS 显示
        self._fps_timer.start(500)

    def _stop_monitoring(self):
        self._monitoring = False
        self.start_btn.setText("开始监控")
        self._fps_timer.stop()

        if self._metric_thread:
            self._metric_thread.stop()
            self._metric_thread = None

    def _on_metrics_ready(self, metrics: dict):
        if "cpu" in metrics:
            self.cpu_card.update_value(metrics["cpu"])
        if "memory" in metrics:
            self.memory_card.update_value(metrics["memory"])
        if "battery" in metrics:
            self.battery_card.update_value(metrics["battery"])
        if "temp" in metrics:
            self.temp_card.update_value(metrics["temp"])

    def _update_fps(self):
        self.fps_card.update_value(self._fps if self._fps > 0 else 0)
        # GPU 负载暂时无法直接获取，显示为 0
        self.gpu_card.update_value(0)

    def stop(self):
        """外部调用：停止所有监控"""
        self._refresh_timer.stop()
        self._stop_monitoring()

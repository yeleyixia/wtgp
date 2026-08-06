import socket
import struct
import threading
import time
import numpy as np
from typing import Optional, List, Dict, Callable
from collections import deque
from PySide6.QtCore import QObject, Signal

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


class CastEngine(QObject):
    frame_received = Signal(np.ndarray)
    connection_status = Signal(str)
    error_occurred = Signal(str)
    fps_updated = Signal(int)
    stats_updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._socket: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._send_thread: Optional[threading.Thread] = None
        self._fps_counter = 0
        self._last_fps_time = time.time()
        self._current_fps = 0
        self._frame_times = deque(maxlen=30)
        self._bitrate_window = deque(maxlen=30)
        self._current_bitrate = 0
        self._resolution = (1080, 2400)
        self._codec = "h264"
        self._connected_clients = 0
        self._max_clients = 100
        self._lock = threading.Lock()
        self._pending_commands: deque = deque()

    def configure(self, resolution: tuple = (1080, 2400),
                  codec: str = "h264", max_fps: int = 120,
                  bitrate: int = 30):
        self._resolution = resolution
        self._codec = codec
        self._max_fps = max_fps
        self._bitrate = bitrate

    def start(self, host: str = "127.0.0.1", port: int = 9999) -> bool:
        if self._running:
            return False
        self._running = True
        self._recv_thread = threading.Thread(
            target=self._receive_loop, args=(host, port), daemon=True
        )
        self._recv_thread.start()
        self._send_thread = threading.Thread(
            target=self._send_loop, daemon=True
        )
        self._send_thread.start()
        self.connection_status.emit("connecting")
        return True

    def stop(self):
        self._running = False
        with self._lock:
            self._pending_commands.clear()
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        if self._recv_thread:
            self._recv_thread.join(timeout=2)
            self._recv_thread = None
        if self._send_thread:
            self._send_thread.join(timeout=2)
            self._send_thread = None
        self.connection_status.emit("disconnected")

    def _receive_loop(self, host: str, port: int):
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            self._socket.settimeout(5)
            self._socket.connect((host, port))
            self.connection_status.emit("connected")
            self._socket.settimeout(None)

            while self._running:
                try:
                    data = self._recv_frame()
                    if data is None:
                        break
                    frame = self._decode_frame(data)
                    if frame is not None:
                        now = time.time()
                        self._frame_times.append(now)
                        self._fps_counter += 1
                        frame_size = len(data)
                        self._bitrate_window.append((now, frame_size))
                        self._update_bitrate()
                        self.frame_received.emit(frame)
                        self._update_stats()
                except ConnectionError:
                    break
                except Exception as e:
                    if self._running:
                        self.error_occurred.emit(str(e))
                    break

        except ConnectionRefusedError:
            self.connection_status.emit("error")
            self.error_occurred.emit("无法连接到投屏服务")
        except OSError as e:
            self.connection_status.emit("error")
            self.error_occurred.emit(f"连接失败: {str(e)}")
        except Exception as e:
            if self._running:
                self.error_occurred.emit(str(e))
        finally:
            self._running = False
            self.connection_status.emit("disconnected")

    def _send_loop(self):
        while self._running:
            try:
                with self._lock:
                    if self._pending_commands:
                        cmd = self._pending_commands.popleft()
                    else:
                        cmd = None
                if cmd and self._socket:
                    try:
                        self._socket.sendall(cmd)
                    except Exception:
                        pass
                time.sleep(0.001)
            except Exception:
                break

    def _recv_frame(self) -> Optional[bytes]:
        if not self._socket:
            return None
        try:
            header = self._recv_exact(16)
            if header is None:
                return None
            frame_type, width, height, size = struct.unpack("!IIII", header)
            if size > 50 * 1024 * 1024:
                return None
            data = self._recv_exact(size)
            if data is None:
                return None
            return header + data
        except Exception:
            return None

    def _recv_exact(self, n: int) -> Optional[bytes]:
        if not self._socket:
            return None
        data = b""
        while len(data) < n:
            try:
                chunk = self._socket.recv(min(n - len(data), 65536))
            except Exception:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def _decode_frame(self, data: bytes) -> Optional[np.ndarray]:
        try:
            if len(data) < 16:
                return None
            frame_type, width, height, size = struct.unpack("!IIII", data[:16])
            payload = data[16:]

            if frame_type == 1:
                return self._decode_jpeg(payload, width, height)
            elif frame_type == 2:
                return self._decode_h264(payload, width, height)
            elif frame_type == 3:
                return self._decode_h265(payload, width, height)
            elif frame_type == 4:
                return self._decode_raw_rgb(payload, width, height)
            else:
                return self._decode_jpeg(payload, width, height)
        except Exception:
            return None

    def _decode_jpeg(self, data: bytes, width: int, height: int) -> Optional[np.ndarray]:
        if not HAS_CV2:
            return self._decode_raw_rgb(data, width, height)
        try:
            arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            return None
        except Exception:
            return None

    def _decode_h264(self, data: bytes, width: int, height: int) -> Optional[np.ndarray]:
        """H.264 解码 — 复刻 scrcpy decoder.c + packet_merger.c
        使用 PyAV/FFmpeg avcodec_send_packet + receive_frame 硬件加速解码。
        回退: 若 PyAV 不可用，尝试 raw_rgb 解码。"""
        try:
            from core.scrcpy_decoder import H264Decoder, HAS_PYAV
            if not hasattr(self, '_h264_dec'):
                if HAS_PYAV:
                    self._h264_dec = H264Decoder("h264")
                else:
                    return self._decode_raw_rgb(data, width, height)
            return self._h264_dec.decode_raw(data)
        except Exception:
            return self._decode_raw_rgb(data, width, height)

    def _decode_h265(self, data: bytes, width: int, height: int) -> Optional[np.ndarray]:
        return self._decode_h264(data, width, height)

    def _decode_raw_rgb(self, data: bytes, width: int, height: int) -> Optional[np.ndarray]:
        try:
            expected_size = width * height * 3
            if len(data) >= expected_size:
                frame = np.frombuffer(data[:expected_size], dtype=np.uint8)
                return frame.reshape(height, width, 3).copy()
            return None
        except Exception:
            return None

    def _update_bitrate(self):
        now = time.time()
        cutoff = now - 1.0
        valid = [(t, s) for t, s in self._bitrate_window if t > cutoff]
        if valid:
            total_bytes = sum(s for _, s in valid)
            self._current_bitrate = int(total_bytes * 8 / 1_000_000)
        else:
            self._current_bitrate = 0

    def _update_stats(self):
        now = time.time()
        if now - self._last_fps_time >= 1.0:
            self._current_fps = self._fps_counter
            self._fps_counter = 0
            self._last_fps_time = now
            self.fps_updated.emit(self._current_fps)
            self.stats_updated.emit({
                "fps": self._current_fps,
                "bitrate_mbps": self._current_bitrate,
                "resolution": f"{self._resolution[0]}x{self._resolution[1]}",
                "codec": self._codec,
                "clients": self._connected_clients,
            })

    def send_control(self, data: bytes):
        with self._lock:
            self._pending_commands.append(data)

    def send_touch(self, x: int, y: int, action: int):
        msg = struct.pack("!BBHH", 1, action, x, y)
        self.send_control(msg)

    def send_key(self, key_code: int):
        msg = struct.pack("!Bi", 2, key_code)
        self.send_control(msg)

    def send_swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int):
        # Biiii = 5 个字段，但这里有 6 个参数（+ duration），改为 Biiiii
        msg = struct.pack("!Biiiii", 3, x1, y1, x2, y2, duration)
        self.send_control(msg)

    def send_text_input(self, text: str):
        text_bytes = text.encode('utf-16-le')
        msg = struct.pack("!BI", 4, len(text_bytes)) + text_bytes
        self.send_control(msg)

    def send_clipboard(self, text: str):
        text_bytes = text.encode('utf-8')
        msg = struct.pack("!BI", 5, len(text_bytes)) + text_bytes
        self.send_control(msg)

    def send_key_combo(self, modifiers: list, key_code: int):
        modifier_mask = 0
        for m in modifiers:
            modifier_mask |= (1 << m)
        msg = struct.pack("!BBi", 6, modifier_mask, key_code)
        self.send_control(msg)

    @property
    def current_fps(self) -> int:
        return self._current_fps

    @property
    def current_bitrate(self) -> int:
        return self._current_bitrate

    @property
    def resolution(self) -> tuple:
        return self._resolution


class MultiDeviceManager(QObject):
    device_registered = Signal(str, str)
    device_removed = Signal(str)
    active_changed = Signal(int, int)

    MAX_PARALLEL_DEVICES = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: Dict[str, dict] = {}
        self._active_devices: Dict[str, CastEngine] = {}
        self._lock = threading.Lock()

    def register_device(self, device_id: str, device_info: dict):
        with self._lock:
            self._devices[device_id] = {
                "info": device_info,
                "registered_at": time.time(),
                "status": "idle",
            }
        self.device_registered.emit(device_id, device_info.get("name", device_id))

    def unregister_device(self, device_id: str):
        with self._lock:
            if device_id in self._devices:
                del self._devices[device_id]
            if device_id in self._active_devices:
                engine = self._active_devices.pop(device_id)
                engine.stop()
        self.device_removed.emit(device_id)

    def start_casting(self, device_id: str, engine: CastEngine) -> bool:
        with self._lock:
            if len(self._active_devices) >= self.MAX_PARALLEL_DEVICES:
                return False
            if device_id not in self._devices:
                return False
            self._active_devices[device_id] = engine
            self._devices[device_id]["status"] = "casting"
        self.active_changed.emit(
            len(self._active_devices),
            self.MAX_PARALLEL_DEVICES
        )
        return True

    def stop_casting(self, device_id: str):
        with self._lock:
            if device_id in self._active_devices:
                engine = self._active_devices.pop(device_id)
                engine.stop()
                if device_id in self._devices:
                    self._devices[device_id]["status"] = "idle"
        self.active_changed.emit(
            len(self._active_devices),
            self.MAX_PARALLEL_DEVICES
        )

    def get_active_count(self) -> int:
        with self._lock:
            return len(self._active_devices)

    def get_available_slots(self) -> int:
        with self._lock:
            return self.MAX_PARALLEL_DEVICES - len(self._active_devices)

    def list_devices(self) -> list:
        with self._lock:
            return [
                {"id": did, **info, "active": did in self._active_devices}
                for did, info in self._devices.items()
            ]


class MockCastEngine(CastEngine):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mock_thread: Optional[threading.Thread] = None
        self._running = False
        self._test_frame_index = 0

    def start(self, host: str = "127.0.0.1", port: int = 9999) -> bool:
        if self._running:
            return False
        self._running = True
        self._mock_thread = threading.Thread(target=self._mock_loop, daemon=True)
        self._mock_thread.start()
        self.connection_status.emit("connected")
        return True

    def stop(self):
        self._running = False
        if self._mock_thread:
            self._mock_thread.join(timeout=2)
            self._mock_thread = None
        self.connection_status.emit("disconnected")

    def _mock_loop(self):
        width, height = self._resolution
        t = 0
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        while self._running:
            t += 0.016
            frame[:] = np.array([18, 18, 20], dtype=np.uint8)

            for i in range(8):
                y_pos = int(150 + i * 280 + np.sin(t * 2 + i * 0.5) * 40)
                x_pos = int(200 + np.cos(t * 1.5 + i * 0.3) * 60)
                if 0 < y_pos < height - 80 and 0 < x_pos < width - 80:
                    color = np.array([
                        int(120 + 80 * np.sin(t + i)),
                        int(180 + 60 * np.cos(t + i * 2)),
                        int(200 + 55 * np.sin(t + i * 3))
                    ], dtype=np.uint8)
                    frame[y_pos:y_pos+60, x_pos:x_pos+60] = color

            progress = (t * 0.3) % (width - 200)
            frame[height-100:height-80, 100:int(100+progress)] = np.array([59, 130, 246], dtype=np.uint8)

            self._fps_counter += 1
            self._frame_times.append(t)
            self._bitrate_window.append((t, len(frame.tobytes())))
            self._update_bitrate()
            self.frame_received.emit(frame.copy())
            self._update_stats()
            time.sleep(0.016)

import threading
import time
import struct
import socket
import numpy as np
from typing import Optional, Dict
from collections import deque
from PySide6.QtCore import QObject, Signal

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False


class AudioManager(QObject):
    audio_frame = Signal(np.ndarray, int)
    volume_changed = Signal(int)
    mute_state_changed = Signal(bool)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._capture_thread: Optional[threading.Thread] = None
        self._playback_thread: Optional[threading.Thread] = None
        self._audio_socket: Optional[socket.socket] = None
        self._volume = 80
        self._muted = False
        self._stream = None
        self._input_stream = None
        self._output_stream = None
        self._lock = threading.Lock()
        self._audio_buffer: deque = deque(maxlen=100)
        self._sample_rate = 44100
        self._channels = 2
        self._frame_size = 1024
        self._auto_mute = True

    def set_volume(self, volume: int):
        self._volume = max(0, min(100, volume))
        self.volume_changed.emit(self._volume)

    def get_volume(self) -> int:
        return self._volume

    def set_muted(self, muted: bool):
        self._muted = muted
        self.mute_state_changed.emit(muted)

    def is_muted(self) -> bool:
        return self._muted

    def set_auto_mute(self, enabled: bool):
        self._auto_mute = enabled

    def start_capture(self, device_id: str = "default"):
        if self._running:
            return False
        self._running = True
        if self._auto_mute:
            self.set_muted(True)
        self._capture_thread = threading.Thread(
            target=self._capture_loop, args=(device_id,), daemon=True
        )
        self._capture_thread.start()
        self.status_changed.emit("capturing")
        return True

    def stop_capture(self):
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2)
            self._capture_thread = None
        self._stop_stream()
        self.status_changed.emit("stopped")

    def start_playback(self, host: str = "127.0.0.1", port: int = 9998):
        if self._running:
            return False
        self._running = True
        self._playback_thread = threading.Thread(
            target=self._playback_loop, args=(host, port), daemon=True
        )
        self._playback_thread.start()
        self.status_changed.emit("playing")
        return True

    def stop_playback(self):
        self._running = False
        if self._playback_thread:
            self._playback_thread.join(timeout=2)
            self._playback_thread = None
        self.status_changed.emit("stopped")

    def _capture_loop(self, device_id: str):
        if HAS_SOUNDDEVICE:
            try:
                device_info = sd.query_devices(device_id)
                self._sample_rate = device_info['default_samplerate']
                self._channels = min(device_info['max_input_channels'], 2)

                with sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype='int16',
                    blocksize=self._frame_size,
                    device=device_id if device_id != "default" else None,
                    callback=self._audio_callback,
                ):
                    while self._running:
                        time.sleep(0.1)
            except Exception as e:
                self.error_occurred.emit(f"音频捕获失败: {str(e)}")
        elif HAS_PYAUDIO:
            try:
                p = pyaudio.PyAudio()
                self._input_stream = p.open(
                    format=pyaudio.paInt16,
                    channels=self._channels,
                    rate=self._sample_rate,
                    input=True,
                    frames_per_buffer=self._frame_size,
                )
                while self._running:
                    try:
                        data = self._input_stream.read(self._frame_size)
                        self._process_audio_data(data)
                    except Exception:
                        break
            except Exception as e:
                self.error_occurred.emit(f"音频捕获失败: {str(e)}")
        else:
            self.error_occurred.emit("未安装音频库 (sounddevice 或 pyaudio)")

    def _audio_callback(self, indata, frames, time_info, status):
        if self._muted:
            return
        try:
            audio_int16 = (indata * 32767).astype(np.int16)
            self._process_audio_data(audio_int16.tobytes())
        except Exception:
            pass

    def _process_audio_data(self, data: bytes):
        try:
            frame = np.frombuffer(data, dtype=np.int16)
            if frame.size > 0:
                with self._lock:
                    self._audio_buffer.append((time.time(), frame.copy()))
                self.audio_frame.emit(frame, self._sample_rate)
        except Exception:
            pass

    def _playback_loop(self, host: str, port: int):
        try:
            self._audio_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._audio_socket.settimeout(5)
            self._audio_socket.connect((host, port))
            self._audio_socket.settimeout(None)

            while self._running:
                try:
                    data = self._recv_audio_frame()
                    if data is None:
                        break
                    self._play_audio(data)
                except Exception:
                    break
        except Exception as e:
            self.error_occurred.emit(f"音频播放连接失败: {str(e)}")
        finally:
            self._stop_stream()

    def _recv_audio_frame(self) -> Optional[bytes]:
        if not self._audio_socket:
            return None
        try:
            header = self._recv_exact(12)
            if header is None:
                return None
            sample_rate, channels, size = struct.unpack("!III", header)
            if size > 1024 * 1024:
                return None
            return self._recv_exact(size)
        except Exception:
            return None

    def _recv_exact(self, n: int) -> Optional[bytes]:
        if not self._audio_socket:
            return None
        data = b""
        while len(data) < n:
            try:
                chunk = self._audio_socket.recv(min(n - len(data), 65536))
            except Exception:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def _play_audio(self, data: bytes):
        if self._muted:
            return
        try:
            if HAS_SOUNDDEVICE:
                audio_data = np.frombuffer(data, dtype=np.int16)
                audio_float = audio_data.astype(np.float32) / 32767.0
                if self._volume < 100:
                    audio_float *= (self._volume / 100.0)
                sd.play(audio_float, self._sample_rate)
            elif HAS_PYAUDIO:
                if not self._output_stream:
                    p = pyaudio.PyAudio()
                    self._output_stream = p.open(
                        format=pyaudio.paInt16,
                        channels=self._channels,
                        rate=self._sample_rate,
                        output=True,
                    )
                self._output_stream.write(data)
        except Exception:
            pass

    def _stop_stream(self):
        if self._output_stream:
            try:
                self._output_stream.stop_stream()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None
        if self._input_stream:
            try:
                self._input_stream.stop_stream()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None
        if self._audio_socket:
            try:
                self._audio_socket.close()
            except Exception:
                pass
            self._audio_socket = None

    def get_audio_level(self) -> float:
        with self._lock:
            if self._audio_buffer:
                _, last_frame = self._audio_buffer[-1]
                return np.max(np.abs(last_frame)) / 32767.0
        return 0.0


class AudioStreamServer(QObject):
    client_connected = Signal(str)
    client_disconnected = Signal(str)
    audio_streaming = Signal(bool)

    def __init__(self, port: int = 9998, parent=None):
        super().__init__(parent)
        self._port = port
        self._server_socket: Optional[socket.socket] = None
        self._clients: Dict[str, socket.socket] = {}
        self._running = False
        self._accept_thread: Optional[threading.Thread] = None
        self._audio_source: Optional[AudioManager] = None
        self._broadcast_thread: Optional[threading.Thread] = None

    def set_audio_source(self, audio_mgr: AudioManager):
        self._audio_source = audio_mgr

    def start(self):
        if self._running:
            return False
        self._running = True
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(("0.0.0.0", self._port))
        self._server_socket.listen(10)
        self._server_socket.settimeout(1.0)
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        self._broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._broadcast_thread.start()
        return True

    def stop(self):
        self._running = False
        for client_id, sock in self._clients.items():
            try:
                sock.close()
            except Exception:
                pass
        self._clients.clear()
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None
        if self._accept_thread:
            self._accept_thread.join(timeout=2)
        if self._broadcast_thread:
            self._broadcast_thread.join(timeout=2)

    def _accept_loop(self):
        while self._running:
            try:
                client_sock, addr = self._server_socket.accept()
                client_id = f"{addr[0]}:{addr[1]}"
                self._clients[client_id] = client_sock
                self.client_connected.emit(client_id)
            except socket.timeout:
                continue
            except Exception:
                break

    def _broadcast_loop(self):
        while self._running:
            if self._audio_source and self._clients:
                try:
                    audio_data = self._get_latest_audio()
                    if audio_data:
                        self._broadcast_audio(audio_data)
                except Exception:
                    pass
            time.sleep(0.01)

    def _get_latest_audio(self):
        if self._audio_source:
            with self._audio_source._lock:
                if self._audio_source._audio_buffer:
                    _, frame = self._audio_source._audio_buffer[-1]
                    return frame
        return None

    def _broadcast_audio(self, frame: np.ndarray):
        data = frame.tobytes()
        header = struct.pack("!III", 44100, 2, len(data))
        packet = header + data
        dead_clients = []
        for client_id, sock in self._clients.items():
            try:
                sock.sendall(packet)
            except Exception:
                dead_clients.append(client_id)
        for client_id in dead_clients:
            try:
                self._clients[client_id].close()
            except Exception:
                pass
            del self._clients[client_id]
            self.client_disconnected.emit(client_id)

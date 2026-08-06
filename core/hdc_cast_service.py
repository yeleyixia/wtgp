import sys
import subprocess
import socket
import struct
import threading
import time
import os
import shutil
import re
import numpy as np
from typing import Optional, Tuple, List, Dict
from collections import deque
from PySide6.QtCore import QObject, Signal

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# ═══ scrcpy 复刻模块 ═══
try:
    from core.scrcpy_decoder import H264Decoder, StreamDemuxer, PacketMerger, HAS_PYAV
except ImportError:
    HAS_PYAV = False
    H264Decoder = None
    StreamDemuxer = None
    PacketMerger = None

try:
    from core.scrcpy_regulator import VideoRegulator
except ImportError:
    VideoRegulator = None

try:
    from core.scrcpy_control import (
        ControlQueue, ControlMessage, TouchEventAggregator,
        UinputBatcher, PointersState,
        POINTER_ID_GENERIC_FINGER, ACTION_DOWN, ACTION_UP, ACTION_MOVE,
        MSG_TYPE_INJECT_TOUCH_EVENT, MSG_TYPE_INJECT_SCROLL_EVENT,
    )
except ImportError:
    ControlQueue = None
    ControlMessage = None
    TouchEventAggregator = None
    UinputBatcher = None
    PointersState = None

# ═══ HoKit 同款 JPEG 截图流通道（高性能投屏）═══
try:
    from core.hokit_jpeg_channel import HokitJpegChannel
except ImportError:
    HokitJpegChannel = None

# ═══ HoKit 同款 H.264 流通道（scrcpy_server.so + gRPC）═══
try:
    from core.hokit_h264_channel import HokitH264Channel
except ImportError:
    HokitH264Channel = None


def find_base_dir() -> str:
    """自动检测项目根目录，兼容开发模式和多种打包器"""
    candidates = []

    # PyInstaller
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates.append(sys._MEIPASS)

    # Nuitka / 其他打包器：sys.executable 所在目录（onefile 临时解压目录）
    candidates.append(os.path.dirname(sys.executable))

    # sys.argv[0] 所在目录（原始 exe 路径）
    candidates.append(os.path.dirname(os.path.abspath(sys.argv[0])))

    # 开发模式
    candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    for path in candidates:
        if path and os.path.isdir(os.path.join(path, "resources", "tools", "hdc")):
            return path
    return candidates[-1]


BASE_DIR = find_base_dir()
TOOLS_DIR = os.path.join(BASE_DIR, "resources", "tools")


def find_hdc() -> str:
    hdc_paths = [
        os.path.join(TOOLS_DIR, "hdc", "hdc.exe"),
        os.path.join(TOOLS_DIR, "hdc", "hdc"),
    ]
    for path in hdc_paths:
        if os.path.exists(path):
            return path
    system_hdc = shutil.which("hdc")
    if system_hdc:
        return system_hdc
    return "hdc"


class HDCCastService(QObject):
    frame_received = Signal(np.ndarray)
    connection_status = Signal(str)
    error_occurred = Signal(str)
    fps_updated = Signal(int)
    device_info = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hdc_path = find_hdc()
        self._device_id: Optional[str] = None
        self._port_forwarded = False
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._control_thread: Optional[threading.Thread] = None
        self._running = False
        self._fps_counter = 0
        self._last_fps_time = time.time()
        self._current_fps = 0
        self._frame_times = deque(maxlen=60)
        self._current_bitrate = 0
        self._resolution = (1080, 2400)
        self._codec = "jpeg"
        self._lock = threading.Lock()
        self._pending_commands: deque = deque()
        self._cmd_event = threading.Event()  # 控制指令事件通知
        self._local_port = 9999
        self._screenshot_interval = 0.0  # 不限制帧率，让捕获速度决定
        self._capture_mode = "screenshot"
        self._max_fps = 60
        self._bitrate_mbps = 10       # 码率 MB/s（H.264 流模式下生效）
        self._scale_pct = 100          # 缩放比例 %（发送到设备端的截图缩放）
        self._screen_id = 0            # 屏幕 ID（多屏设备时选择投屏哪一个）
        self._repeat_interval = 16     # repeatInterval ms（H.264 编码重复间隔，16=高性能/60FPS 级）
        self._touch_x, self._touch_y = 0, 0  # 触摸 move 起点（uinput -m 需 起点→终点）
        self._drag_latest = None  # 拖动期间积攒的轨迹终点（抬手时合成单条连续滑动）
        self._click_pending = None     # 快速点击合并：down 位置（60ms 内 up 且无 move → -c）
        self._click_ts = 0.0
        self._click_lock = threading.Lock()   # 点击合并状态锁（GUI 线程 vs 补发线程）
        self._click_flush_active = False      # 补发线程活跃标志
        self._frame_idx = 0
        self._pipe_failed = False  # 设备不支持 /dev/stdout 时置 True
        self._shell_proc = None  # 持久化 shell 会话进程
        self._shell_mode = ""  # "raw" 或 "base64"

        # 持久化输入 shell：避免每次鼠标事件都创建子进程，延迟从 ~150ms 降到 ~5ms
        self._input_proc = None
        self._input_lock = threading.Lock()
        self._input_fail_count = 0

        # ===== scrcpy 风格的最新帧缓冲 =====
        # 单槽缓冲：新帧直接覆盖旧帧，UI 线程按需拉取，避免 Qt 事件队列堆积
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._frame_version = 0  # 帧版本号，UI 据此判断是否有新帧

        # ===== 输入指令丢弃策略（scrcpy controller.c 风格） =====
        # 队列上限 60，超过则丢弃瞬态事件（move），保留 down/up/key 等
        self._cmd_queue_limit = 60
        self._droppable_actions = {1}  # action=1 (move) 可丢弃

        # ═══ scrcpy 复刻：H.264 硬解码器 (decoder.c + packet_merger.c) ═══
        # 替代原有 _decode_h264 的空实现，使用 PyAV/FFmpeg 硬件加速
        self._h264_decoder: Optional[object] = None  # H264Decoder 实例
        self._packet_merger: Optional[object] = None  # PacketMerger 实例

        # ═══ scrcpy 复刻：PTS 帧调节器 (video_regulator.c) ═══
        # 吸收网络/解码抖动，平滑输出节奏
        self._video_regulator: Optional[object] = None  # VideoRegulator 实例

        # ═══ scrcpy 复刻：控制队列 (controller.c) ═══
        # 专用控制线程 + 条件变量 + 可丢弃策略
        self._control_queue: Optional[ControlQueue] = None
        self._touch_aggregator: Optional[TouchEventAggregator] = None
        self._pointers_state: Optional[PointersState] = PointersState()

        # ═══ HoKit 同款 JPEG 截图流（agent_jpeg 模式）═══
        self._agent_channel: Optional[object] = None
        self._agent_thread: Optional[threading.Thread] = None

        # ═══ HoKit 同款 H.264 流（stream 模式）═══
        self._h264_channel: Optional[object] = None
        self._h264_last_frame = 0.0
        self._h264_stimulated = False

    def _push_frame(self, frame: np.ndarray):
        """scrcpy 风格：把最新帧写入单槽缓冲（覆盖旧帧），并发射低频信号通知 UI。
        捕获线程调用，锁内只做指针赋值，不做耗时操作。"""
        with self._frame_lock:
            self._latest_frame = frame
            self._frame_version += 1
        # 仅做 FPS 统计，不再每帧 emit（避免 Qt 跨线程事件队列堆积）
        self._fps_counter += 1
        self._update_stats()

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """UI 线程按需拉取最新帧（单槽缓冲，无新帧时返回 None）。"""
        with self._frame_lock:
            return self._latest_frame

    @property
    def frame_version(self) -> int:
        with self._frame_lock:
            return self._frame_version

    def run_hdc(self, args: List[str], timeout: int = 10) -> Tuple[int, str, str]:
        cmd = [self.hdc_path] + args
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=timeout, creationflags=creationflags
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except FileNotFoundError:
            return -1, "", "HDC not found"
        except Exception as e:
            return -1, "", str(e)

    def connect_device(self, device_id: str) -> bool:
        self._device_id = device_id
        code, stdout, stderr = self.run_hdc(["list", "targets"])
        if code != 0:
            self.error_occurred.emit(f"无法连接设备列表: {stderr}")
            return False

        connected = False
        for line in stdout.split("\n"):
            if device_id in line:
                connected = True
                break

        if not connected:
            self.error_occurred.emit(f"设备 {device_id} 未找到")
            return False

        self._port_forwarded = self._setup_port_forwarding()
        self.connection_status.emit("connected")
        return True

    def _setup_port_forwarding(self) -> bool:
        if not self._device_id:
            return False

        code, stdout, stderr = self.run_hdc([
            "-t", self._device_id, "port", f"tcp:{self._local_port}", "tcp:5555"
        ])
        if code == 0:
            return True

        code, stdout, stderr = self.run_hdc([
            "-t", self._device_id, "port", f"tcp:{self._local_port}", "tcp:8888"
        ])
        return code == 0

    def set_capture_mode(self, mode: str):
        """设置捕获模式: 'jpeg' (截图模式) 或 'h264' (视频流模式)"""
        self._capture_mode = "screenshot" if mode == "jpeg" else "stream"
        self._codec = mode

    def set_max_fps(self, fps: int):
        """设置最大帧率（上限 120；H.264 通道支持 5-120）"""
        self._max_fps = max(1, min(120, fps))
        self._screenshot_interval = 0.0

    def set_bitrate(self, mbps: int):
        """设置码率 (MB/s)，仅 H.264 流模式生效"""
        self._bitrate_mbps = max(1, min(100, int(mbps)))

    def set_scale(self, scale_pct: int):
        """设置缩放比例 (%)"""
        self._scale_pct = max(10, min(100, int(scale_pct)))

    def set_screen_id(self, screen_id: int):
        """设置屏幕 ID（多屏设备时使用）"""
        self._screen_id = max(0, int(screen_id))

    def set_repeat_interval(self, repeat_ms: int):
        """设置 H.264 编码 repeatInterval（ms）：33=HoKit 同款 30FPS 级，16=高性能，8=极速"""
        self._repeat_interval = max(8, min(100, int(repeat_ms)))

    def apply_cast_config(self, config) -> bool:
        """
        批量应用 CastConfig。
        - 若未在投屏中：保存配置，待 start_casting 时生效
        - 若正在投屏：热应用 -> 重启投屏以切换新模式
        返回 True 表示进行了热重启。
        """
        from core.cast_config import CastConfig
        if not isinstance(config, CastConfig):
            return False
        self.set_capture_mode(config.capture_mode)
        self.set_max_fps(config.fps)
        self.set_bitrate(config.bitrate_mbps)
        self.set_scale(config.scale_pct)
        self.set_screen_id(config.screen_id)
        self.set_repeat_interval(config.repeat_interval)
        # 热重启：只要正在投屏就重启，保证所有参数立即生效
        if self._running:
            mode = config.cast_engine_mode
            self.stop_casting()
            # 重新启动投屏
            try:
                self.start_casting(mode=mode)
                return True
            except Exception:
                return False
        return False

    def start_casting(self, mode: str = "screenshot") -> bool:
        if self._running:
            return False
        if not self._device_id:
            self.error_occurred.emit("未连接设备")
            return False

        self._capture_mode = mode
        self._running = True

        # 启动持久化输入 shell，显著降低鼠标操作延迟
        self._start_input_shell()

        # ═══ scrcpy 复刻: 初始化控制队列 (controller.c) ═══
        # 专用控制线程 + 条件变量唤醒 + 可丢弃策略
        if ControlQueue is not None:
            self._control_queue = ControlQueue(
                send_fn=self._send_input_cmd
            )
            self._control_queue.start()
            self._touch_aggregator = TouchEventAggregator(self._control_queue)

        if mode == "stream":
            # H.264 流模式：在后台线程启动（避免阻塞 UI）
            self._start_stream_async()
            return True
        elif mode == "agent_jpeg":
            # HoKit 同款 JPEG 截图流：agent.so + uitest daemon RPC
            success = self._start_agent_jpeg_capture()
            if success:
                self.connection_status.emit("casting")
            return success
        elif mode == "screenshot":
            shell_ok = self._start_persistent_shell()
            if not shell_ok:
                self._pipe_failed = False
            success = self._start_screenshot_capture()
            if success:
                self.connection_status.emit("casting")
            return success
        else:
            success = self._start_screenshot_capture()
            if success:
                self.connection_status.emit("casting")
            return success

    def _start_stream_async(self):
        """在后台线程中启动 H.264 流捕获（避免阻塞 UI 主线程）"""
        def worker():
            try:
                success = self._start_stream_capture()
                if success:
                    self.connection_status.emit("casting")
                elif self._running:
                    self._running = False
                    # 这是预期内的自动降级，不是用户错误，不弹错误框
                    print("[HDCCastService] H.264 流不可用，自动降级为截图模式")
                    # 自动降级到截图模式
                    if self._shell_proc:
                        self._stop_persistent_shell()
                    self._running = True
                    self._capture_mode = "screenshot"
                    shell_ok = self._start_persistent_shell()
                    if not shell_ok:
                        self._pipe_failed = False
                    self._start_screenshot_capture()
                    self.connection_status.emit("casting")
            except Exception as e:
                if self._running:
                    self._running = False
                    self.error_occurred.emit(f"投屏启动异常: {str(e)}")

        threading.Thread(target=worker, daemon=True).start()

    def stop_casting(self):
        self._running = False
        with self._lock:
            self._pending_commands.clear()

        # 重置捕获状态，保证下次 start_casting 从干净状态开始
        self._pipe_failed = False
        self._shell_mode = ""
        with self._frame_lock:
            self._latest_frame = None
            self._frame_version = 0

        # 停止持久化 shell 会话
        self._stop_persistent_shell()

        # 停止持久化输入 shell
        self._stop_input_shell()

        # ═══ scrcpy 复刻: 停止控制队列 (controller.c) ═══
        if self._control_queue is not None:
            self._control_queue.stop()
            self._control_queue = None
        self._touch_aggregator = None

        # 停止 H.264 解码器 (decoder.c)
        if self._h264_decoder is not None:
            try:
                self._h264_decoder.reset()
            except Exception:
                pass
            self._h264_decoder = None
        self._packet_merger = None

        # 停止帧调节器 (video_regulator.c)
        if self._video_regulator is not None:
            self._video_regulator.stop()
            self._video_regulator = None

        if self._client_socket:
            try:
                self._client_socket.close()
            except Exception:
                pass
            self._client_socket = None

        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        # 先停 H.264 通道（cancel gRPC 流 → read_packet 立即返回 None，
        # 线程快速退出，避免 join 超时后旧线程污染新会话）
        if self._h264_channel is not None:
            try:
                self._h264_channel.stop()
            except Exception:
                pass
            self._h264_channel = None

        if self._recv_thread:
            self._recv_thread.join(timeout=3)
            self._recv_thread = None

        if self._control_thread:
            self._control_thread.join(timeout=2)
            self._control_thread = None

        # 停止 HoKit 同款 JPEG 截图流通道
        if self._agent_channel is not None:
            try:
                self._agent_channel.stop()
            except Exception:
                pass
            self._agent_channel = None
        if self._agent_thread:
            self._agent_thread.join(timeout=3)
            self._agent_thread = None

        self.connection_status.emit("disconnected")

    def _start_stream_capture(self) -> bool:
        """H.264 流模式 — HoKit 同款链路：scrcpy_server.so + gRPC onStart 拉流。"""
        if HokitH264Channel is None:
            print("[HDCCastService] 缺少 hokit_h264_channel 模块，无法使用 H.264 流模式")
            return False
        try:
            # HoKit scale 语义: 1=100%, 2=50%；用户配置 50% → 2
            scale = 1 if self._scale_pct >= 100 else 2
            channel = HokitH264Channel(
                self.hdc_path,
                self._device_id,
                scale=scale,
                frame_rate=max(5, min(120, self._max_fps or 30)),
                bitrate_mbps=max(1, self._bitrate_mbps or 10),
                screen_id=self._screen_id,
                repeat_interval=self._repeat_interval,
            )
            channel.start()
        except Exception as e:
            # 预期内的失败：调用方(_start_stream_async)会自动降级为截图模式，不弹错误框
            print(f"[HDCCastService] H.264 流启动失败，将降级为截图模式: {str(e)}")
            return False
        self._h264_channel = channel
        self._h264_last_frame = time.time()
        self._h264_stimulated = False
        self._recv_thread = threading.Thread(target=self._h264_grpc_loop, daemon=True)
        self._recv_thread.start()
        self._control_thread = threading.Thread(target=self._control_send_loop, daemon=True)
        self._control_thread.start()
        return True

    def _h264_grpc_loop(self):
        """H.264 gRPC 拉流解码循环（HoKit H264CastingChannel 复刻）。

        - gRPC 帧直接送 H264Decoder（Annex-B 流）
        - 帧率上限用 min_interval 控制
        - 静止 >15s 软刺激（uinput 微移）保持编码器活跃；>25s 唤醒+刺激
        """
        channel = self._h264_channel
        if HAS_PYAV and H264Decoder is not None:
            try:
                self._h264_decoder = H264Decoder("h264")
                self._packet_merger = self._h264_decoder._merger
            except Exception:
                self._h264_decoder = None

        # 注：不再使用 VideoRegulator —— 本项目不解析 gRPC PTS（pts 恒为 0），
        # regulator 的 delay=0.05 会为每帧引入固定 50ms 缓冲延迟；
        # 解码帧直接推给 _push_frame，配合 UI 16ms 拉取，端到端延迟更低。

        min_interval = 1.0 / max(1, min(120, self._max_fps or 30))
        last_capture_time = 0.0
        # 启动保底：H.264 编码器静止时不产帧，若启动后 3s 仍无帧
        # （含静止桌面），补一张即时截图作为首帧，避免投屏窗口黑屏
        start_time = time.time()
        got_first_frame = False

        while self._running and channel is not None and channel.started:
            try:
                packet = channel.read_packet(timeout=2.0)
            except Exception:
                packet = None
            if packet is None:
                break
            now = time.time()
            if packet:
                # read_packet 返回 (data, pts_flags)
                data, flags = packet
                self._h264_last_frame = now
                self._h264_stimulated = False

                # ═══ 残影修复核心：永不丢 P 帧 ═══
                # 旧版在 burst 积压时 drain_to_latest 丢包、min_interval
                # 跳包，丢弃的 P 帧会破坏 GOP 参考链 → 画面带旧帧残影/
                # 马赛克，直到下一个 IDR 才恢复。
                # 现在：积压包按序全部送解码器（维持参考链），仅对要
                # 显示的那一包做像素转换，其余用快速解码（只解不转），
                # 追帧成本可控且画面永远正确。
                items = [packet]
                if channel.qsize():
                    items.extend(channel.take_available(512))

                display_due = (now - last_capture_time) >= min_interval
                frame = None
                last_i = len(items) - 1
                for i, (pkt_data, pkt_flags) in enumerate(items):
                    if i == last_i and display_due:
                        frame = self._decode_h264_frame(pkt_data, pkt_flags)
                    else:
                        self._decode_h264_fast(pkt_data, pkt_flags)

                if frame is not None:
                    self._push_frame(frame)
                    got_first_frame = True  # 首帧保底：解码推送成功才算
                    last_capture_time = now
            else:
                # 超时无数据：软刺激 / 唤醒（与 HoKit 阈值一致）
                idle = now - self._h264_last_frame
                # 启动保底：3s 无帧则补一张即时截图（静止画面也能立即显示）
                if not got_first_frame and now - start_time > 3:
                    try:
                        shot = self._take_screenshot()
                        if shot is not None:
                            self._push_frame(shot)
                            got_first_frame = True  # 截图成功推送后才算
                    except Exception:
                        pass
                if idle > 25:
                    try:
                        channel.wake()
                        channel.stimulate()
                        self._h264_stimulated = True
                    except Exception:
                        pass
                elif idle > 15 and not self._h264_stimulated:
                    try:
                        channel.stimulate()
                        self._h264_stimulated = True
                    except Exception:
                        pass

        # 清理解码资源
        if self._h264_decoder is not None:
            try:
                self._h264_decoder.reset()
            except Exception:
                pass
            self._h264_decoder = None
        self._packet_merger = None

    def _start_device_capture_service(self):
        if not self._device_id:
            return

        self.run_hdc([
            "-t", self._device_id, "shell",
            "param", "set", "const.security.developermode.state", "true"
        ])

        self.run_hdc([
            "-t", self._device_id, "shell",
            "snapshot", "-n", "10", "/data/local/tmp/capture"
        ], timeout=5)

    def _start_screenshot_capture(self) -> bool:
        self._recv_thread = threading.Thread(target=self._screenshot_loop, daemon=True)
        self._recv_thread.start()
        self._control_thread = threading.Thread(target=self._control_send_loop, daemon=True)
        self._control_thread.start()
        return True

    # ═══════════════════════════════════════════════════════════
    # HoKit 同款 JPEG 截图流（agent_jpeg 模式）
    # 实测：scale=0.5 时约 7fps（华为畅享 90 Pro Max / OpenHarmony 6.1.1.125）
    # ═══════════════════════════════════════════════════════════
    def _start_agent_jpeg_capture(self) -> bool:
        if HokitJpegChannel is None:
            self.error_occurred.emit("缺少 hokit_jpeg_channel 模块，无法使用高性能模式")
            return False
        try:
            scale = self._scale_pct / 100.0
            # 用户配置 100% → 0.99（全分辨率，慢）；其余按比例映射到 [0.4, 0.99]
            if scale <= 0.0:
                scale = 0.5
            else:
                scale = min(max(scale, 0.4), 0.99)
            channel = HokitJpegChannel(self.hdc_path, self._device_id, scale=scale)
            channel.start()
        except Exception as e:
            self.error_occurred.emit(f"高性能截图流启动失败: {str(e)}")
            return False
        self._agent_channel = channel
        self._agent_thread = threading.Thread(target=self._agent_jpeg_loop, daemon=True)
        self._agent_thread.start()
        return True

    def _agent_jpeg_loop(self):
        """接收 agent 推送的 JPEG 帧并解码入帧缓冲。"""
        channel = self._agent_channel
        while self._running and channel is not None and channel.started:
            try:
                jpeg = channel.read_frame(timeout=2.0)
            except Exception:
                jpeg = None
            if not self._running:
                break
            if not jpeg:
                continue
            frame = self._decode_jpeg_bytes(jpeg)
            if frame is not None:
                self._push_frame(frame)
                self._fps_counter += 1
                self._update_stats()

    @staticmethod
    def _decode_jpeg_bytes(jpeg: bytes):
        """cv2 解码 JPEG 字节为 BGR ndarray。"""
        if not HAS_CV2:
            return None
        try:
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            return None

    def _stream_receive_loop(self):
        """H.264 流接收循环 — scrcpy 风格完整复刻:
        - PacketMerger 合并 SPS/PPS config 包到关键帧 (packet_merger.c)
        - H264Decoder 用 PyAV/FFmpeg 硬解 (decoder.c: avcodec_send/receive)
        - VideoRegulator PTS 时钟平滑输出 (video_regulator.c)
        - 解码后写入单槽缓冲，UI 拉取，避免跨线程事件队列堆积"""
        # 初始化 scrcpy 复刻模块
        if HAS_PYAV and H264Decoder is not None:
            try:
                self._h264_decoder = H264Decoder("h264")
                self._packet_merger = self._h264_decoder._merger  # 共享 merger
                logger_info = True
            except Exception as e:
                self._h264_decoder = None
                logger_info = False
        else:
            logger_info = False

        # 注：不再使用 VideoRegulator —— 本项目 pts 恒为 0，50ms 缓冲纯增延迟
        last_capture_time = 0
        min_interval = 1.0 / max(1, min(120, self._max_fps))

        while self._running and self._client_socket:
            try:
                frame_data = self._recv_frame()
                if frame_data is None:
                    break

                now = time.time()
                # 残影修复：帧率限制只控制"显示"，不控制"解码"。
                # 跳包不解码会破坏 GOP 参考链导致残影/花屏。
                if now - last_capture_time >= min_interval:
                    frame = self._decode_h264_frame(frame_data)
                    if frame is not None:
                        # 直接推帧（不再经 VideoRegulator 50ms 缓冲，降低延迟）
                        self._push_frame(frame)
                        last_capture_time = now
                else:
                    self._decode_h264_fast(frame_data)
            except Exception:
                if self._running:
                    self.error_occurred.emit("接收帧数据异常")
                break

        # 清理

    def _screenshot_loop(self):
        """scrcpy 风格截图循环：单线程 capture+decode，写入单槽缓冲。
        - 去除双缓冲解码线程（减少锁竞争和延迟）
        - 去除重复的 min_interval 检查（单点限速）
        - 不再每帧 emit 信号（UI 定时器拉取）"""
        min_interval = 1.0 / max(1, min(120, self._max_fps))
        last_capture_time = 0.0

        while self._running:
            try:
                now = time.time()
                # 帧率限制：单点检查，避免过快采集压垮设备
                if now - last_capture_time < min_interval:
                    time.sleep(max(0.001, min_interval - (now - last_capture_time)))
                    continue

                frame = None
                if self._shell_proc is not None:
                    # 持久化 shell 已退出：清理引用，让下面的降级路径接管
                    if self._shell_proc.poll() is not None:
                        self._stop_persistent_shell()
                        # 不立即尝试重启 shell（避免死循环），直接走管道/文件降级
                        self._pipe_failed = True
                        time.sleep(0.05)
                        continue
                    # 持久化 shell 优先（最快路径）
                    frame = self._read_persistent_frame()
                elif not self._pipe_failed:
                    # stdout 管道截图
                    raw = self._capture_pipe_raw()
                    if raw is not None:
                        frame = self._decode_pipe_bytes(raw)
                    else:
                        self._pipe_failed = True

                if frame is None and not self._shell_proc and self._pipe_failed:
                    # 回退路径：base64 → 文件
                    frame = self._take_screenshot_base64()
                    if frame is None:
                        frame = self._take_screenshot_fast()

                if frame is not None:
                    self._push_frame(frame)
                    last_capture_time = time.time()
                else:
                    # 无帧可取时短暂休眠，避免空转
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.05)

    def _capture_pipe_raw(self) -> Optional[bytes]:
        """快速截图：通过 stdout 管道在单次 subprocess 调用中获取 JPEG 数据。
        尝试 snapshot_display -f /dev/stdout，若设备不支持则返回 None。
        使用 Popen + 后台读取线程，带超时保护。"""
        if not self._device_id:
            return None

        cmd = [self.hdc_path, "-t", self._device_id, "shell",
               "snapshot_display", "-f", "/dev/stdout"]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except Exception:
            return None

        result: List[Optional[bytes]] = [None]
        err_result: List[bytes] = [b""]

        def reader():
            try:
                result[0] = proc.stdout.read()
            except Exception:
                result[0] = None
            try:
                err_result[0] = proc.stderr.read()
            except Exception:
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=3)

        if t.is_alive():
            # 超时：杀掉进程，丢弃本次结果
            try:
                proc.kill()
            except Exception:
                pass
            return None

        try:
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        raw = result[0]
        if not raw or len(raw) < 64:
            # /dev/stdout 不被设备支持时的典型情况
            self._pipe_failed = True
            return None

        # 简单校验：JPEG 以 0xFFD8 开头，PNG 以 0x89504E47 开头
        if not (raw[:2] == b"\xff\xd8" or raw[:4] == b"\x89PNG"):
            # 可能是 stderr 中含错误信息且 stdout 为空
            self._pipe_failed = True
            return None

        return raw

    def _take_screenshot_base64(self) -> Optional[np.ndarray]:
        """单次 subprocess 调用截图 + base64 传输。
        在设备端执行 snapshot_display + base64 编码，通过 stdout 一次性传回。
        比文件方式快 2-3 倍（省去 file recv 和 rm 两个子进程调用）。"""
        if not self._device_id:
            return None

        import base64 as b64mod

        remote_path = "/data/local/tmp/sc_b64.jpeg"
        cmd_str = (
            f"snapshot_display -f {remote_path} && "
            f"echo B64_START && "
            f"base64 {remote_path}"
        )

        cmd = [self.hdc_path, "-t", self._device_id, "shell", cmd_str]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except Exception:
            return None

        result: list = [b""]
        err_result: list = [b""]

        def reader():
            try:
                result[0] = proc.stdout.read()
            except Exception:
                pass
            try:
                err_result[0] = proc.stderr.read()
            except Exception:
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=8)

        if t.is_alive():
            try:
                proc.kill()
            except Exception:
                pass
            return None

        try:
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        raw = result[0]
        if not raw:
            return None

        # 分割诊断文本和 base64 数据
        try:
            text = raw.decode('utf-8', errors='replace')
        except Exception:
            return None

        marker = "B64_START"
        idx = text.find(marker)
        if idx < 0:
            return None

        b64_data = text[idx + len(marker):].strip()
        # 移除可能的换行和空格
        b64_clean = b64_data.replace('\n', '').replace('\r', '').replace(' ', '')

        if len(b64_clean) < 64:
            return None

        try:
            jpeg_bytes = b64mod.b64decode(b64_clean)
        except Exception:
            return None

        if len(jpeg_bytes) < 64:
            return None

        # 验证 JPEG 头
        if jpeg_bytes[:2] != b'\xff\xd8':
            return None

        if HAS_CV2:
            try:
                arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    return img  # BGR
            except Exception:
                pass

        return None

    def _start_persistent_shell(self) -> bool:
        """启动持久化 hdc shell 会话，优先使用原始二进制帧传输，
        失败时回退到 base64 模式。只创建一次子进程，消除每帧进程开销。"""
        if not self._device_id:
            return False

        # 先尝试原始二进制模式（最快，无 base64 编解码开销）
        if self._try_start_raw_shell():
            self._shell_mode = "raw"
            return True

        # 回退到 base64 模式
        if self._try_start_b64_shell():
            self._shell_mode = "base64"
            return True

        self._shell_proc = None
        self._shell_mode = ""
        return False

    def _try_start_raw_shell(self) -> bool:
        """启动原始二进制帧传输：设备端循环截图并通过 stdout 输出 JPEG 原始字节，
        使用 'FRMEND' 标记分隔帧。"""
        if not self._device_id:
            return False

        loop_script = (
            "while true; do "
            "snapshot_display -f /data/local/tmp/sc_raw.jpeg 2>/dev/null && "
            "cat /data/local/tmp/sc_raw.jpeg 2>/dev/null && "
            "printf 'FRMEND'; "
            "done"
        )
        cmd = [self.hdc_path, "-t", self._device_id, "shell", loop_script]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self._shell_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                creationflags=creationflags,
                bufsize=0,
            )
        except Exception:
            self._shell_proc = None
            return False

        # 启动后台线程排空 stderr
        def drain_stderr():
            try:
                while self._shell_proc and self._shell_proc.poll() is None:
                    data = self._shell_proc.stderr.read(4096)
                    if not data:
                        break
            except Exception:
                pass

        threading.Thread(target=drain_stderr, daemon=True).start()

        # 在 5 秒内读取并验证第一帧
        self._raw_buffer = bytearray()
        frame_marker = b'FRMEND'
        deadline = time.time() + 5.0

        while time.time() < deadline:
            if self._shell_proc.poll() is not None:
                self._shell_proc = None
                return False
            try:
                chunk = self._shell_proc.stdout.read(8192)
            except Exception:
                chunk = None
            if not chunk:
                time.sleep(0.01)
                continue

            self._raw_buffer.extend(chunk)
            idx = self._raw_buffer.find(frame_marker)
            if idx >= 0:
                frame_data = bytes(self._raw_buffer[:idx])
                self._raw_buffer = bytearray(self._raw_buffer[idx + len(frame_marker):])
                # 验证 JPEG 完整性
                if (len(frame_data) > 64 and
                        frame_data[:2] == b'\xff\xd8' and
                        b'\xff\xd9' in frame_data):
                    return True

        # 验证超时，停止并返回失败
        self._stop_persistent_shell()
        return False

    def _try_start_b64_shell(self) -> bool:
        """启动 base64 编码帧传输模式（兼容性更好）。"""
        if not self._device_id:
            return False

        remote_path = "/data/local/tmp/sc_b64.jpeg"
        loop_script = (
            f"while true; do "
            f"snapshot_display -f {remote_path} 2>/dev/null && "
            f"echo FRAME_DELIM && "
            f"base64 {remote_path} && "
            f"echo FRAME_END; "
            f"done"
        )
        cmd = [self.hdc_path, "-t", self._device_id, "shell", loop_script]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self._shell_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                creationflags=creationflags,
                bufsize=0,
            )
        except Exception:
            self._shell_proc = None
            return False

        # 启动后台线程排空 stderr
        def drain_stderr():
            try:
                while self._shell_proc and self._shell_proc.poll() is None:
                    data = self._shell_proc.stderr.read(4096)
                    if not data:
                        break
            except Exception:
                pass

        threading.Thread(target=drain_stderr, daemon=True).start()
        return True

    def _read_persistent_frame(self) -> Optional[np.ndarray]:
        """从持久化 shell 会话读取一帧数据并解码。
        根据 _shell_mode 自动选择原始二进制或 base64 解码。"""
        if not self._shell_proc or self._shell_proc.poll() is not None:
            return None

        if getattr(self, '_shell_mode', '') == "raw":
            raw = self._read_raw_frame()
            return self._decode_pipe_bytes(raw) if raw else None

        # base64 模式
        import base64 as b64mod

        try:
            b64_lines = []
            in_frame = False
            timeout_count = 0

            while self._running and self._shell_proc and self._shell_proc.poll() is None:
                line = self._shell_proc.stdout.readline()
                if not line:
                    timeout_count += 1
                    if timeout_count > 5:
                        return None
                    time.sleep(0.01)
                    continue

                text = line.decode('utf-8', errors='replace').strip()

                if text == 'FRAME_DELIM':
                    in_frame = True
                    b64_lines = []
                elif text == 'FRAME_END':
                    if in_frame and b64_lines:
                        b64_data = ''.join(b64_lines)
                        try:
                            jpeg_bytes = b64mod.b64decode(b64_data)
                        except Exception:
                            return None

                        if len(jpeg_bytes) < 64 or jpeg_bytes[:2] != b'\xff\xd8':
                            return None

                        if HAS_CV2:
                            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if img is not None:
                                return img  # BGR
                    in_frame = False
                    b64_lines = []
                elif in_frame:
                    b64_lines.append(text)
        except Exception:
            return None

        return None

    def _read_raw_frame(self) -> Optional[bytes]:
        """从原始二进制流中读取一帧 JPEG 数据。
        使用 'FRMEND' 标记分割帧，带 2 秒超时保护。"""
        if not self._shell_proc or self._shell_proc.poll() is not None:
            return None

        frame_marker = b'FRMEND'
        deadline = time.time() + 2.0

        while self._running and self._shell_proc and self._shell_proc.poll() is None:
            if time.time() > deadline:
                return None

            idx = self._raw_buffer.find(frame_marker)
            if idx >= 0:
                frame_data = bytes(self._raw_buffer[:idx])
                self._raw_buffer = bytearray(self._raw_buffer[idx + len(frame_marker):])
                if len(frame_data) > 64 and frame_data[:2] == b'\xff\xd8':
                    return frame_data
                # 数据损坏，继续读下一帧
                continue

            try:
                chunk = self._shell_proc.stdout.read(16384)
            except Exception:
                return None

            if chunk:
                self._raw_buffer.extend(chunk)
            else:
                time.sleep(0.001)

        return None

    def _stop_persistent_shell(self):
        """停止持久化 shell 会话"""
        if self._shell_proc:
            try:
                self._shell_proc.stdin.close()
            except Exception:
                pass
            try:
                self._shell_proc.terminate()
            except Exception:
                pass
            try:
                self._shell_proc.wait(timeout=2)
            except Exception:
                try:
                    self._shell_proc.kill()
                except Exception:
                    pass
            self._shell_proc = None

    # ========== 持久化输入 shell ==========

    def _start_input_shell(self) -> bool:
        """占位：保持调用点兼容。

        原实现创建无参数 `hdc shell` 持久化进程并通过 stdin 发送 uinput
        命令，但 hdc 3.2.0c 在该设备上不支持 stdio TTY 模式
        （`Not support stdio TTY mode`），stdin 写入的命令不会执行。
        现输入命令统一走 `_send_input_cmd`（单次 hdc shell 批量执行），
        此处不再创建进程，避免遗留挂死的 hdc 子进程。
        """
        return True

    def _stop_input_shell(self):
        """停止持久化输入 shell"""
        if self._input_proc:
            try:
                self._input_proc.stdin.close()
            except Exception:
                pass
            try:
                self._input_proc.terminate()
            except Exception:
                pass
            try:
                self._input_proc.wait(timeout=2)
            except Exception:
                try:
                    self._input_proc.kill()
                except Exception:
                    pass
            self._input_proc = None

    def _send_input_cmd(self, cmd: str) -> bool:
        """通过 hdc shell 单次执行输入命令（支持 `;` 连接的多命令批）。

        说明：hdc 3.2.0c 的 `hdc shell`（无参数）在该设备上不支持
        stdio TTY 模式（`Not support stdio TTY mode`），stdin 写入的命令
        不会执行。因此不再依赖持久化 stdin 进程，改用单次
        `hdc shell <cmd>` 子进程 —— 可靠但单条约 100~150ms；
        滑动类高频事件由 ControlQueue 批量合成一条命令串摊薄开销。

        并发与幂等：用 _input_lock 串行化（控制线程与 GUI 直调线程
        交错会打断 down/move/up 序列）；批串（含 `;`）失败**不重试**
        —— 重试会重复执行已成功的命令（如 down 成功后 move 失败，
        重试整串会二次注入 down）。仅单命令允许重试一次。
        """
        if not self._device_id:
            return False
        with self._input_lock:
            try:
                # 批串判定：以包含多条 uinput 命令为准（";" in cmd 会误伤
                # send_text 中单引号内的分号文本）
                is_batch = cmd.count("uinput") > 1
                rc, _, _ = self.run_hdc(
                    ["-t", self._device_id, "shell", cmd],
                    timeout=10 if not is_batch else 5,
                )
                if rc == 0:
                    return True
                if is_batch:
                    # 批串：不重试（避免非幂等命令重复执行）
                    return False
                rc, _, _ = self.run_hdc(["-t", self._device_id, "shell", cmd], timeout=10)
                return rc == 0
            except Exception:
                return False

    def _decode_pipe_bytes(self, raw: bytes) -> Optional[np.ndarray]:
        """将 stdout 管道拿到的原始图像字节解码为 BGR ndarray（跳过 cvtColor，由 Qt 用 BGR888 渲染）"""
        if not raw:
            return None
        try:
            if HAS_CV2:
                arr = np.frombuffer(raw, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    return img  # 直接返回 BGR，Qt 用 Format_BGR888 渲染
            else:
                return self._decode_jpeg(raw, 0, 0)
        except Exception:
            return None
        return None

    def _take_screenshot_fast(self) -> Optional[np.ndarray]:
        """快速截图：mkstemp 唯一临时文件名避免符号链接/覆写面，缩短超时"""
        if not self._device_id:
            return None

        self._frame_idx = (self._frame_idx + 1) % 4
        remote_path = f"/data/local/tmp/sc_{self._frame_idx}.jpeg"
        # 独占创建唯一本地临时文件（避免固定名 + 秒级时间戳的可预测攻击面）
        import tempfile
        fd, local_path = tempfile.mkstemp(suffix=".jpeg", dir=BASE_DIR)
        os.close(fd)
        try:
            # 截图 + 传输 + 删除合并为快速序列，使用短超时
            code, _, _ = self.run_hdc([
                "-t", self._device_id, "shell", "snapshot_display", "-f", remote_path
            ], timeout=5)
            if code != 0:
                return None

            code, _, _ = self.run_hdc([
                "-t", self._device_id, "file", "recv", remote_path, local_path
            ], timeout=5)
            if code != 0:
                return None

            # 异步删除远程文件（不等待）
            self.run_hdc(["-t", self._device_id, "shell", "rm", remote_path], timeout=2)

            try:
                if HAS_CV2:
                    with open(local_path, 'rb') as f:
                        data = f.read()
                    arr = np.frombuffer(data, dtype=np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img is not None:
                        return img  # BGR
            except Exception:
                pass
            return None
        finally:
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass

    def _take_screenshot(self) -> Optional[np.ndarray]:
        if not self._device_id:
            return None

        remote_path = "/data/local/tmp/screenshot_cast.jpeg"
        import tempfile
        fd, local_path = tempfile.mkstemp(suffix=".jpeg", dir=BASE_DIR)
        os.close(fd)
        try:
            code, stdout, stderr = self.run_hdc([
                "-t", self._device_id, "shell", "snapshot_display", "-f", remote_path
            ], timeout=10)
            if code != 0:
                return None

            code, stdout, stderr = self.run_hdc([
                "-t", self._device_id, "file", "recv", remote_path, local_path
            ], timeout=10)
            if code != 0:
                return None

            self.run_hdc(["-t", self._device_id, "shell", "rm", remote_path])

            if HAS_CV2:
                with open(local_path, 'rb') as f:
                    data = f.read()
                arr = np.frombuffer(data, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    return img  # BGR
            else:
                with open(local_path, 'rb') as f:
                    data = f.read()
                return self._decode_jpeg(data, 0, 0)
            return None
        finally:
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass
        return None

    def _recv_frame(self) -> Optional[bytes]:
        if not self._client_socket:
            return None
        try:
            header = self._recv_exact(16)
            if header is None:
                return None
            frame_type, width, height, size = struct.unpack("!IIII", header)
            if size > 50 * 1024 * 1024:
                return None
            payload = self._recv_exact(size)
            if payload is None:
                return None
            return header + payload
        except Exception:
            return None

    def _recv_exact(self, n: int) -> Optional[bytes]:
        if not self._client_socket:
            return None
        data = b""
        while len(data) < n:
            try:
                chunk = self._client_socket.recv(min(n - len(data), 65536))
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
                return self._decode_raw_rgb(payload, width, height)
            elif frame_type == 3:
                return self._decode_png(payload)
            else:
                return self._decode_jpeg(payload, width, height)
        except Exception:
            return None

    def _decode_h264_frame(self, data: bytes, pts_flags: int = 0) -> Optional[np.ndarray]:
        """H.264 帧解码 — 复刻 scrcpy decoder.c + packet_merger.c

        1. PacketMerger 合并 config 包 (SPS/PPS) 到关键帧前（pts_flags 高位）
        2. H264Decoder 用 PyAV/FFmpeg avcodec_send_packet + receive_frame
        3. 输出 BGR ndarray 供 Qt Format_BGR888 渲染

        若 PyAV 不可用，回退到旧的 _decode_frame (JPEG/raw)。
        """
        if self._h264_decoder is not None:
            # scrcpy decoder.c 路径: merger → avcodec → frame
            return self._h264_decoder.decode_packet(data, pts_flags)

        # PyAV 不可用时的回退路径
        return self._decode_frame(data)

    def _decode_h264_fast(self, data: bytes, pts_flags: int = 0) -> None:
        """只解码不转换像素 — burst 追帧用，维持 GOP 参考链不断。

        丢 P 帧是残影根因；追帧时中间包必须送解码器，但无需像素
        转换。PyAV 不可用时无法"只解不转"，直接丢弃中间包的影响
        与旧版一致（仅在极端回退场景）。
        """
        if self._h264_decoder is not None:
            try:
                self._h264_decoder.decode_packet(data, pts_flags, convert=False)
            except Exception:
                pass

    def _decode_jpeg(self, data: bytes, width: int, height: int) -> Optional[np.ndarray]:
        if not HAS_CV2:
            return None
        try:
            arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return img  # BGR，由 Qt BGR888 渲染
        except Exception:
            return None

    def _decode_png(self, data: bytes) -> Optional[np.ndarray]:
        if not HAS_CV2:
            return None
        try:
            arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return img  # BGR
        except Exception:
            return None

    def _decode_raw_rgb(self, data: bytes, width: int, height: int) -> Optional[np.ndarray]:
        try:
            expected_size = width * height * 3
            if len(data) >= expected_size and width > 0 and height > 0:
                frame = np.frombuffer(data[:expected_size], dtype=np.uint8)
                return frame.reshape(height, width, 3).copy()  # 保持 RGB（raw 格式）
            return None
        except Exception:
            return None

    def _control_send_loop(self):
        """控制指令发送循环 — 用 Event 唤醒替代 1ms 轮询，降低 CPU 开销"""
        while self._running:
            try:
                with self._lock:
                    if self._pending_commands:
                        cmd = self._pending_commands.popleft()
                    else:
                        cmd = None
                if cmd and self._client_socket:
                    try:
                        self._client_socket.sendall(cmd)
                    except Exception:
                        pass
                else:
                    # 无指令时等待事件唤醒，不空转
                    self._cmd_event.wait(timeout=0.1)
                    self._cmd_event.clear()
            except Exception:
                break

    def _update_stats(self):
        now = time.time()
        if now - self._last_fps_time >= 1.0:
            self._current_fps = self._fps_counter
            self._fps_counter = 0
            self._last_fps_time = now
            self.fps_updated.emit(self._current_fps)

    def send_touch(self, x: int, y: int, action: int):
        """scrcpy 风格: 通过 ControlQueue (controller.c) + 可丢弃策略发送触控事件。
        - action 语义与 scrcpy 一致: ACTION_DOWN=0 / ACTION_UP=1 / ACTION_MOVE=2
        - move 事件在队列满时自动丢弃，降低积压延迟
        - 专用控制线程 + 条件变量唤醒，不轮询
        - 触摸 move 起点由 ControlQueue._touch_state（主路径）或
          self._touch_x/_touch_y（回退路径）维护，单一状态源
        - 快速点击合并：down 延迟 60ms 内 up（无 move）→ uinput -c 单命令
          （一次 shell 往返完成点击，响应 ~103ms 而非 ~206ms）；超过
          60ms 或收到 move 则补发 down（长按/拖拽语义不变）"""
        if not self._device_id:
            # 无 hdc 设备：走旧 TCP 引擎触控通道（struct 协议发给 agent 客户端）
            msg = struct.pack("!BBHH", 1, action, x, y)
            with self._lock:
                self._pending_commands.append(msg)
            self._cmd_event.set()
            return

        # ---- 快速点击合并（down 延迟，move/up/超时决定补发）----
        if action == 0:  # ACTION_DOWN：暂存，延迟发送
            with self._click_lock:
                self._click_pending = (x, y)
                self._click_ts = time.time()
            self._drag_latest = None  # 新一次手势开始
            self._schedule_click_flush()
            return
        elif action == 2:  # ACTION_MOVE：拖拽开始 → 补发 down；拖动中只积攒不发送
            with self._click_lock:
                pending = self._click_pending
                self._click_pending = None
            if pending is not None:
                self._push_down(*pending)
            # ═══ "一滑一屏"关键修复 ═══
            # 逐批发送 move 时，每批都是一段高速动画，抬手时的速度采样
            # 会触发 launcher 惯性连甩（一滑飞多屏，实机标定复现）。
            # 改为：拖动期间只记录轨迹终点，抬手时合成"单条连续
            # uinput -T -m 起点 终点 smooth(=距离)"与 up 同批发出，
            # 即实机标定验证过的"一次滑动恰好一屏"的手势形态。
            self._drag_latest = (x, y)
            return
        elif action == 1:  # ACTION_UP
            with self._click_lock:
                pending = self._click_pending
                self._click_pending = None
                click_ts = self._click_ts
            if pending is not None and (time.time() - click_ts) < 0.06:
                # 快速点击 → 合并为单命令
                cmd = f"uinput -T -c {pending[0]} {pending[1]}"
                if not self._send_input_cmd(cmd):
                    self.run_hdc(["-t", self._device_id, "shell", cmd])
                return
            if pending is not None:
                # 长按结束（超时线程尚未补发）→ 补发 down 再 up
                self._push_down(*pending)

        # 抬手：把积攒的拖动轨迹合成单条连续 move，与 up 同批发送
        latest = self._drag_latest
        self._drag_latest = None

        # scrcpy 复刻路径: ControlQueue → send_fn → uinput
        # （move 起点由 ControlQueue._touch_state 维护，此处不触碰实例状态）
        if self._control_queue is not None:
            if latest is not None:
                move_msg = ControlMessage.create_touch(
                    action=ACTION_MOVE,
                    pointer_id=POINTER_ID_GENERIC_FINGER,
                    x=latest[0], y=latest[1],
                    screen_w=self._resolution[0],
                    screen_h=self._resolution[1],
                )
                self._control_queue.push(move_msg)
            msg = ControlMessage.create_touch(
                action=action,
                pointer_id=POINTER_ID_GENERIC_FINGER,
                x=x, y=y,
                screen_w=self._resolution[0],
                screen_h=self._resolution[1],
            )
            self._control_queue.push(msg)
            return

        # 回退路径：实例维护 move 起点；抬手时整串一次发（不 split）
        if latest is not None:
            px, py = self._touch_x, self._touch_y
            dist = int(((latest[0] - px) ** 2 + (latest[1] - py) ** 2) ** 0.5)
            smooth = max(40, min(1500, dist))
            cmd = (f"uinput -T -m {px} {py} {latest[0]} {latest[1]} {smooth}; "
                   f"uinput -T -u {x} {y}")
            self._touch_x, self._touch_y = x, y
        elif action == 1:  # ACTION_UP（无拖动，直接抬手）
            cmd = f"uinput -T -u {x} {y}"
        else:
            cmd = f"uinput -T -c {x} {y}"
        if not self._send_input_cmd(cmd):
            self.run_hdc(["-t", self._device_id, "shell", cmd])

    def _push_down(self, x: int, y: int):
        """补发 down（点击合并超时/拖拽/长按场景），与主路径走同一通道"""
        if self._control_queue is not None:
            msg = ControlMessage.create_touch(
                action=ACTION_DOWN,
                pointer_id=POINTER_ID_GENERIC_FINGER,
                x=x, y=y,
                screen_w=self._resolution[0],
                screen_h=self._resolution[1],
            )
            self._control_queue.push(msg)
        else:
            self._touch_x, self._touch_y = x, y
            cmd = f"uinput -T -d {x} {y}"
            if not self._send_input_cmd(cmd):
                self.run_hdc(["-t", self._device_id, "shell", cmd])

    def _schedule_click_flush(self):
        """down 暂存后 60ms 无 move/up → 后台补发 down（长按场景）"""
        if self._click_flush_active:
            return
        self._click_flush_active = True

        def _flush():
            try:
                time.sleep(0.06)
                with self._click_lock:
                    pending = self._click_pending
                    self._click_pending = None
                if pending is not None and (time.time() - self._click_ts) >= 0.06:
                    self._push_down(*pending)
            finally:
                self._click_flush_active = False

        threading.Thread(target=_flush, daemon=True).start()

    def send_tap(self, x: int, y: int):
        if self._device_id:
            cmd = f"uinput -T -c {x} {y}"
            if not self._send_input_cmd(cmd):
                self.run_hdc(["-t", self._device_id, "shell", cmd])

    def send_swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        if self._device_id:
            # uinput -T -g 要求 press_time >= 500ms 且 total_time - press_time >= 500ms
            press_time = max(500, duration)
            total_time = max(1000, press_time + 500)
            cmd = f"uinput -T -g {x1} {y1} {x2} {y2} {press_time} {total_time}"
            if not self._send_input_cmd(cmd):
                self.run_hdc(["-t", self._device_id, "shell", cmd])

    def send_key(self, key_code: int):
        if self._device_id:
            key_map = {
                2007: "276",
                2003: "102",
                2049: "254",
                2076: "116",
                2058: "115",
                2059: "114",
                2060: "113",
            }
            key_name = key_map.get(key_code, str(key_code))
            d_cmd = f"uinput -K -d {key_name}"
            u_cmd = f"uinput -K -u {key_name}"
            if self._send_input_cmd(d_cmd) and self._send_input_cmd(u_cmd):
                return
            # 回退
            self.run_hdc(["-t", self._device_id, "shell", d_cmd])
            time.sleep(0.02)
            self.run_hdc(["-t", self._device_id, "shell", u_cmd])
        else:
            msg = struct.pack("!Bi", 2, key_code)
            with self._lock:
                self._pending_commands.append(msg)
            self._cmd_event.set()

    def send_text(self, text: str):
        if self._device_id:
            # 对 text 做 shell 转义：单引号包裹 + '\'' 转义 + 过滤换行，
            # 防止注入设备端 shell 命令（安全审查 MEDIUM 修复）
            safe_text = (text or "").replace("\r", " ").replace("\n", " ")
            safe_text = safe_text.replace("'", "'\\''")
            cmd = f"uinput -K -t '{safe_text}'"
            if not self._send_input_cmd(cmd):
                # 回退路径与主路径一致（经 shell 转义），避免 argv 直传注入
                self.run_hdc(["-t", self._device_id, "shell", cmd])
        else:
            text_bytes = text.encode('utf-16-le')
            msg = struct.pack("!BI", 4, len(text_bytes)) + text_bytes
            with self._lock:
                self._pending_commands.append(msg)
            self._cmd_event.set()

    def send_clipboard(self, text: str):
        if self._device_id:
            # 剪贴板内容不可信：单引号包裹 + 转义 + 过滤换行，防止注入
            # hdc shell param set 命令（安全审查 MEDIUM 修复）
            safe_text = (text or "").replace("\r", " ").replace("\n", " ")
            safe_text = safe_text.replace("'", "'\\''")
            self.run_hdc([
                "-t", self._device_id, "shell",
                "param", "set", "const.clipboard.data", f"'{safe_text}'"
            ])
        else:
            text_bytes = text.encode('utf-8')
            msg = struct.pack("!BI", 5, len(text_bytes)) + text_bytes
            with self._lock:
                self._pending_commands.append(msg)
            self._cmd_event.set()

    def get_device_screen_size(self) -> Tuple[int, int]:
        if self._device_id:
            # 优先使用 hidumper 获取渲染分辨率
            code, stdout, stderr = self.run_hdc([
                "-t", self._device_id, "shell", "hidumper", "-s", "RenderService", "-a", "screen"
            ], timeout=8)
            if code == 0 and stdout:
                match = re.search(r"render resolution=(\d+)x(\d+)", stdout)
                if match:
                    self._resolution = (int(match.group(1)), int(match.group(2)))
                    return self._resolution
                match = re.search(r"physical resolution=(\d+)x(\d+)", stdout)
                if match:
                    self._resolution = (int(match.group(1)), int(match.group(2)))
                    return self._resolution
            # 回退：wm size
            code, stdout, stderr = self.run_hdc([
                "-t", self._device_id, "shell", "wm", "size"
            ])
            if code == 0:
                match = re.search(r"(\d+)x(\d+)", stdout)
                if match:
                    self._resolution = (int(match.group(1)), int(match.group(2)))
        return self._resolution

    def get_device_info(self) -> dict:
        if not self._device_id:
            return {}

        info = {"id": self._device_id}

        param_names = [
            ("const.product.name", "name"),
            ("const.product.model", "model"),
            ("const.ohos.fullname", "version"),
            ("const.product.hardware.udid", "udid"),
        ]

        for param, key in param_names:
            code, stdout, stderr = self.run_hdc([
                "-t", self._device_id, "shell", "param", "get", param
            ])
            if code == 0 and stdout.strip() and stdout.strip() != "error":
                info[key] = stdout.strip()

        width, height = self.get_device_screen_size()
        info["resolution"] = f"{width}x{height}"

        self._resolution = (width, height)
        self.device_info.emit(info)
        return info

    def set_resolution(self, width: int, height: int):
        self._resolution = (width, height)

    def set_codec(self, codec: str):
        self._codec = codec

    @property
    def is_casting(self) -> bool:
        return self._running

    @property
    def device_id(self) -> Optional[str]:
        return self._device_id

    @property
    def fps(self) -> int:
        return self._current_fps

    @property
    def max_fps(self) -> int:
        return self._max_fps

    @property
    def bitrate_mbps(self) -> int:
        return self._bitrate_mbps

    @property
    def scale_pct(self) -> int:
        return self._scale_pct

    @property
    def screen_id(self) -> int:
        return self._screen_id

    @property
    def capture_mode_codec(self) -> str:
        """返回 'jpeg' 或 'h264'"""
        return self._codec

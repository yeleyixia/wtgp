"""
scrcpy_decoder.py — 复刻 scrcpy 的 decoder.c + packet_merger.c

复刻内容：
  1. PacketMerger    ← app/src/packet_merger.c
     将 MediaCodec 输出的 SPS/PPS config 包内联到每个关键帧前，
     避免解码器在丢包后无法恢复（scrcpy 服务端 Streamer.writePacket
     会将 config 包单独发送，客户端必须缓存并合并）。
  2. H264Decoder     ← app/src/decoder.c
     基于 PyAV (av) 的 FFmpeg avcodec_send_packet / avcodec_receive_frame
     硬件加速解码循环，替代原有 cv2.VideoCapture 空实现。
     支持 H.264 / H.265 / AV1，输出 BGR ndarray 供 Qt BGR888 渲染。

对应 scrcpy 源文件：
  - app/src/decoder.c            (sc_decoder_push → avcodec_send/receive)
  - app/src/packet_merger.c      (sc_packet_merger_merge)
  - app/src/demuxer.c            (SC_PACKET_FLAG_CONFIG / KEY_FRAME 解析)
"""

import struct
import logging
import threading
import numpy as np
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  常量 — 对应 demuxer.c 的 flag 定义
# ═══════════════════════════════════════════════════════════════

# demuxer.c: SC_PACKET_FLAG_CONFIG = (1ULL << 62)
PACKET_FLAG_CONFIG = 1 << 62
# demuxer.c: SC_PACKET_FLAG_KEY_FRAME = (1ULL << 61)
PACKET_FLAG_KEY_FRAME = 1 << 61
# demuxer.c: SC_PACKET_PTS_MASK
PTS_MASK = PACKET_FLAG_KEY_FRAME - 1

# demuxer.c: sc_demuxer_to_avcodec_id()
# "h264" / "h265" / "av1" 的 ASCII uint32 (big-endian)
CODEC_ID_H264 = 0x68323634
CODEC_ID_H265 = 0x68323635
CODEC_ID_AV1 = 0x00617631

_CODEC_MAP = {
    CODEC_ID_H264: ("h264", "H264"),
    CODEC_ID_H265: ("h265", "HEVC"),
    CODEC_ID_AV1: ("av1", "AV1"),
    "h264": ("h264", "H264"),
    "h265": ("h265", "HEVC"),
    "av1": ("av1", "AV1"),
    "H264": ("h264", "H264"),
    "H265": ("h265", "HEVC"),
}

try:
    import av as pyav
    HAS_PYAV = True
except ImportError:
    HAS_PYAV = False
    pyav = None


# ═══════════════════════════════════════════════════════════════
#  PacketMerger — 复刻 app/src/packet_merger.c
# ═══════════════════════════════════════════════════════════════

class PacketMerger:
    """
    复刻 scrcpy app/src/packet_merger.c 的 sc_packet_merger。

    scrcpy 服务端 (Streamer.java) 将 MediaCodec 的 config 包 (SPS/PPS)
    作为单独的 AV_NOPTS_VALUE 包发送。客户端 demuxer.c 将其标记为
    config 包，packet_merger.c 缓存该 config 数据，并在下一个媒体包
    到来时将其 prepend 到包数据前面，使解码器能正确初始化/恢复。

    不做这一步的话，H.264 解码器在码流中途接入或丢包后无法解码关键帧。
    """

    def __init__(self):
        # sc_packet_merger.c: merger->config = NULL
        self._config: Optional[bytes] = None
        self._config_size: int = 0
        self._lock = threading.Lock()

    def merge(self, data: bytes, pts_flags: int) -> bytes:
        """
        对应 sc_packet_merger.c: sc_packet_merger_merge()

        :param data: 原始包数据
        :param pts_flags: demuxer.c 解析的 pts_and_flags (64-bit)
        :return: 合并后的包数据（可能 prepend 了 config）
        """
        is_config = (pts_flags & PACKET_FLAG_CONFIG) != 0

        with self._lock:
            if is_config:
                # sc_packet_merger.c: 缓存 config，free 旧的
                self._config = bytes(data)
                self._config_size = len(data)
                # config 包本身不送解码器
                return b""
            elif self._config is not None:
                # sc_packet_merger.c: 将 config prepend 到媒体包前
                merged = self._config + data
                self._config = None
                return merged
            else:
                return data

    def reset(self):
        """重置缓存（对应 sc_packet_merger_destroy）"""
        with self._lock:
            self._config = None
            self._config_size = 0


# ═══════════════════════════════════════════════════════════════
#  H264Decoder — 复刻 app/src/decoder.c
# ═══════════════════════════════════════════════════════════════

class H264Decoder:
    """
    复刻 scrcpy app/src/decoder.c 的 sc_decoder。

    sc_decoder_push() 的核心循环：
      avcodec_send_packet(ctx, packet)
      for (;;) {
          avcodec_receive_frame(ctx, frame)
          if (EAGAIN || EOF) break
          sc_frame_source_sinks_push(frame)  // 推给下游
      }

    PyAV 的 codec.decode() 内部等价于 send_packet + receive_frame 循环，
    返回可迭代的 frame 列表。我们取最新一帧推给下游（单槽缓冲）。
    """

    def __init__(self, codec_name: str = "h264"):
        """
        :param codec_name: "h264" / "h265" / "av1"
        """
        if not HAS_PYAV:
            raise RuntimeError(
                "PyAV (av) 未安装，H.264 硬解不可用。请运行: pip install av"
            )

        self._codec_name = codec_name
        self._codec = None
        self._merger = PacketMerger()
        self._init_codec()

    def _init_codec(self):
        """初始化 FFmpeg 解码器（对应 decoder.c 的 sc_decoder_open）"""
        # PyAV: av.CodecContext.create(codec_name, mode='r')（r=读/解码，w=写/编码）
        pyav_name, _ = _CODEC_MAP.get(self._codec_name, ("h264", "H264"))
        self._codec = pyav.CodecContext.create(pyav_name, mode="r")
        # 低延迟解码参数 — 对应 scrcpy 客户端 avcodec_open2 前的设置
        # scrcpy 编码端已设 KEY_LATENCY=1，解码端也启用低延迟
        try:
            self._codec.low_delay = 1
        except Exception:
            pass
        try:
            self._codec.thread_type = "FRAME"  # 避免帧重排
        except Exception:
            pass
        try:
            self._codec.flags |= 0x00080000   # AV_CODEC_FLAG_LOW_DELAY
        except Exception:
            pass

        logger.info(
            "H264Decoder 初始化: codec=%s, low_delay=True, thread=NONE",
            pyav_name,
        )

    def decode_packet(self, data: bytes, pts_flags: int = 0,
                      convert: bool = True) -> Optional[np.ndarray]:
        """
        对应 decoder.c: sc_decoder_push()

        1. packet_merger 合并 config 包
        2. avcodec_send_packet
        3. avcodec_receive_frame 循环
        4. convert=True 时返回最新一帧 BGR ndarray (H, W, 3)；
           convert=False 时只做解码（维持参考链），返回是否产出帧

        :param data: 原始 H.264 NAL 数据
        :param pts_flags: demuxer.c 格式的 pts+flags (0 表示无元数据)
        :param convert: 是否做像素转换（burst 追帧时传 False 省开销）
        :return: convert=True → BGR ndarray 或 None；
                 convert=False → True(产出帧)/None
        """
        # Step 1: packet_merger 合并
        merged = self._merger.merge(data, pts_flags)
        if not merged:
            return None  # config 包已缓存，不送解码器

        # Step 2+3: avcodec_send_packet + avcodec_receive_frame
        # PyAV: codec.parse() + codec.decode()
        try:
            packet = pyav.Packet(merged)
            frames = self._codec.decode(packet)
        except Exception as e:
            logger.debug("解码异常: %s (len=%d)", e, len(merged))
            return None

        if not frames:
            return None

        if not convert:
            return True  # 已解码但未转换像素

        # Step 4: 取最新一帧（对应 scrcpy 单槽缓冲策略）
        frame = frames[-1]
        return self._frame_to_bgr(frame)

    def decode_packet_fast(self, data: bytes, pts_flags: int = 0):
        """只解码不转换像素 — 用于 burst 追帧，维持 GOP 参考链不断。

        丢 P 帧是残影/花屏的根因：参考链断裂后画面会带着旧帧残影
        直到下一个 IDR。追帧时所有包都必须送解码器，但中间包无需
        像素转换（to_ndarray 约 2-4ms/帧），只转换最终要显示的帧。
        """
        return self.decode_packet(data, pts_flags, convert=False)

    def decode_raw(self, data: bytes) -> Optional[np.ndarray]:
        """
        无元数据的便捷方法 — 用于 H.264 原始流（无 12 字节 header）。
        """
        return self.decode_packet(data, pts_flags=0)

    def flush(self) -> list:
        """刷新解码器缓冲（对应 avcodec_send_packet(NULL) + drain）"""
        if not self._codec:
            return []
        try:
            frames = self._codec.decode(None)
        except Exception:
            return []
        return [self._frame_to_bgr(f) for f in frames]

    def reset(self):
        """重置解码器 + merger（码流断开重连时调用）"""
        self._merger.reset()
        if self._codec:
            self._codec.close()
        self._init_codec()

    @staticmethod
    def _frame_to_bgr(frame) -> np.ndarray:
        """
        将 PyAV Frame 转为 BGR ndarray。

        scrcpy decoder.c 输出 AVFrame (YUV420P)，由 opengl.c 上传为纹理
        并由 shader 做 YUV→RGB 转换。我们用 frame.to_ndarray() 直接转 RGB，
        再 flip 为 BGR 以匹配 Qt Format_BGR888（省掉 cvtColor）。
        """
        # PyAV: to_ndarray(format='bgr0') 直接输出 BGR
        # 比 to_ndarray(format='rgb24') + cvtColor 更快
        try:
            arr = frame.to_ndarray(format="bgr0")
            # bgr0 是 4 通道，取前 3 个
            if arr.ndim == 3 and arr.shape[2] == 4:
                return arr[:, :, :3].copy()
            return arr
        except Exception:
            # 回退: rgb24 → BGR
            arr = frame.to_ndarray(format="rgb24")
            return np.ascontiguousarray(arr[:, :, ::-1])


# ═══════════════════════════════════════════════════════════════
#  Demuxer — 复刻 app/src/demuxer.c 的包解析逻辑
# ═══════════════════════════════════════════════════════════════

class StreamDemuxer:
    """
    复刻 scrcpy app/src/demuxer.c 的流解析逻辑。

    scrcpy 的流格式 (Streamer.java + demuxer.c):
      - 初始 4 字节: codec_id (uint32 BE) — "h264" / "h265" / "av1"
      - 每个 packet:
          12 字节 header: [pts_and_flags(8B BE)] [packet_size(4B BE)]
          + packet_size 字节的原始数据
      - session packet: MSB=1, 包含 width/height/client_resized
      - media packet:   MSB=0, pts + config_flag + key_frame_flag

    本类提供静态方法解析 12 字节 header，供 hdc_cast_service 的
    _stream_receive_loop 调用。
    """

    HEADER_SIZE = 12  # demuxer.c: SC_PACKET_HEADER_SIZE

    @staticmethod
    def parse_header(header: bytes) -> Optional[Tuple[int, int, bool, bool, bool]]:
        """
        解析 12 字节包头。

        :return: (pts, packet_size, is_config, is_key_frame, is_session)
                 解析失败返回 None
        """
        if len(header) < StreamDemuxer.HEADER_SIZE:
            return None

        pts_and_flags = struct.unpack(">Q", header[:8])[0]
        packet_size = struct.unpack(">I", header[8:12])[0]

        is_session = (pts_and_flags & (1 << 63)) != 0
        is_config = (pts_and_flags & PACKET_FLAG_CONFIG) != 0
        is_key_frame = (pts_and_flags & PACKET_FLAG_KEY_FRAME) != 0
        pts = int(pts_and_flags & PTS_MASK)

        return pts, packet_size, is_config, is_key_frame, is_session

    @staticmethod
    def parse_session(header: bytes) -> Optional[Tuple[int, int, bool]]:
        """
        解析 session 包（对应 demuxer.c: sc_demuxer_parse_session）。

        :return: (width, height, client_resized)
        """
        if len(header) < 12:
            return None
        width = struct.unpack(">I", header[4:8])[0]
        height = struct.unpack(">I", header[8:12])[0]
        client_resized = (header[3] & 1) != 0
        return width, height, client_resized

    @staticmethod
    def parse_codec_id(codec_id: int) -> str:
        """对应 demuxer.c: sc_demuxer_to_avcodec_id"""
        mapping = {
            CODEC_ID_H264: "h264",
            CODEC_ID_H265: "h265",
            CODEC_ID_AV1: "av1",
        }
        return mapping.get(codec_id, "h264")

"""
scrcpy_regulator.py — 复刻 scrcpy 的 video_regulator.c

复刻内容：
  VideoRegulator  ← app/src/video_regulator.c

scrcpy 的 video_regulator.c 实现了一个基于 PTS 时钟的帧延迟缓冲器：
  - 接收解码后的帧，按 PTS 计算"应该显示的时间"
  - 在缓冲线程中等待到该时间 + delay 后才推给下游
  - 这样即使网络抖动导致帧到达不均匀，输出节奏仍然平滑
  - first_frame_asap: 第一帧立即输出（降低首帧延迟）

对应 scrcpy 源文件：
  - app/src/video_regulator.c   (run_buffering + sc_video_regulator_frame_sink_push)
  - app/src/clock.c             (sc_clock_update — PTS↔系统时钟映射)
"""

import threading
import time
import logging
import numpy as np
from typing import Optional, Callable, List
from collections import deque

logger = logging.getLogger(__name__)


class _Clock:
    """
    复刻 scrcpy app/src/clock.c 的 sc_clock。

    sc_clock 维护 PTS 到系统时间的线性映射：
      - 每次 push 帧时调用 sc_clock_update(clock, now, pts)
      - 后续查询时用 sc_clock_to_system_time(clock, pts) 得到该 PTS 对应的系统时间
      - 实现方式: 记录最后一个 (system_tick, pts) 对，用差值推算
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._system_base: float = 0.0  # 系统时间基准 (秒)
        self._pts_base: float = 0.0      # PTS 基准 (秒)
        self._range = 0                 # 已更新次数

    def update(self, system_now: float, pts: float):
        """对应 clock.c: sc_clock_update"""
        with self._lock:
            self._system_base = system_now
            self._pts_base = pts
            self._range += 1

    def to_system_time(self, pts: float) -> float:
        """对应 clock.c: sc_clock_to_system_time"""
        with self._lock:
            if self._range == 0:
                return time.time()  # 未初始化，返回当前时间
            return self._system_base + (pts - self._pts_base)

    @property
    def range(self) -> int:
        with self._lock:
            return self._range


class VideoRegulator:
    """
    复刻 scrcpy app/src/video_regulator.c 的 sc_video_regulator。

    线程模型 (对应 video_regulator.c 的 run_buffering):
      - push() 由解码线程调用，将帧入队 + signal
      - _buffer_loop() 线程从队列取帧，等待到 deadline 后回调

    参数:
      - delay: 缓冲延迟 (秒)。scrcpy 默认 ~0.05s，用于吸收网络抖动
      - first_frame_asap: True 时第一帧立即输出 (降低首帧延迟)
      - max_queue: 队列上限，防止内存爆炸
    """

    def __init__(
        self,
        delay: float = 0.05,
        first_frame_asap: bool = True,
        max_queue: int = 30,
        on_frame: Optional[Callable[[np.ndarray], None]] = None,
    ):
        self._delay = delay
        self._first_frame_asap = first_frame_asap
        self._max_queue = max_queue
        self._on_frame = on_frame

        self._queue: deque = deque()
        self._mutex = threading.Lock()
        self._queue_cond = threading.Condition(self._mutex)
        self._wait_cond = threading.Condition(self._mutex)
        self._stopped = False
        self._clock = _Clock()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """启动缓冲线程（对应 video_regulator.c: sc_video_regulator_frame_sink_open）"""
        self._stopped = False
        self._thread = threading.Thread(
            target=self._buffer_loop, daemon=True, name="scrcpy-vruf"
        )
        self._thread.start()

    def stop(self):
        """停止（对应 video_regulator.c: sc_video_regulator_frame_sink_close）"""
        with self._mutex:
            self._stopped = True
            self._queue_cond.notify_all()
            self._wait_cond.notify_all()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        # 清空队列
        with self._mutex:
            self._queue.clear()

    def push(self, frame: np.ndarray, pts: float = 0.0):
        """
        对应 video_regulator.c: sc_video_regulator_frame_sink_push

        1. 更新时钟 (sc_clock_update)
        2. 若 first_frame_asap 且是第一帧 → 直接回调
        3. 否则入队 + signal queue_cond
        """
        system_now = time.time()
        pts_sec = pts / 1_000_000.0  # scrcpy PTS 单位是微秒

        with self._mutex:
            if self._stopped:
                return

            self._clock.update(system_now, pts_sec)
            self._wait_cond.notify_all()  # 唤醒等待线程重新计算 deadline

            if self._first_frame_asap and self._clock.range == 1:
                # 第一帧立即输出
                if self._on_frame:
                    self._on_frame(frame)
                return

            # 队列满时丢弃最旧的帧（比 scrcpy 更激进，适配 Python 性能）
            while len(self._queue) >= self._max_queue:
                self._queue.popleft()

            self._queue.append((frame, pts_sec))
            self._queue_cond.notify_all()

    def _buffer_loop(self):
        """
        对应 video_regulator.c: run_buffering()

        循环:
          1. 等待队列非空
          2. 取出 (frame, pts)
          3. 计算 deadline = clock.to_system_time(pts) + delay
          4. 等待到 deadline (或 stopped)
          5. 回调输出帧
        """
        while True:
            with self._mutex:
                while not self._stopped and not self._queue:
                    self._queue_cond.wait(timeout=0.5)

                if self._stopped:
                    return

                frame, pts = self._queue.popleft()

                # 计算显示 deadline
                max_deadline = time.time() + self._delay
                deadline = self._clock.to_system_time(pts) + self._delay
                if deadline > max_deadline:
                    deadline = max_deadline

                # 等待到 deadline
                while not self._stopped:
                    now = time.time()
                    wait_time = deadline - now
                    if wait_time <= 0:
                        break
                    self._wait_cond.wait(timeout=min(wait_time, 0.1))

                if self._stopped:
                    return

            # 输出帧（锁外回调，避免死锁）
            if self._on_frame:
                try:
                    self._on_frame(frame)
                except Exception as e:
                    logger.warning("VideoRegulator 回调异常: %s", e)

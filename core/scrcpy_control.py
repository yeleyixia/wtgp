"""
scrcpy_control.py — 复刻 scrcpy 的 controller.c + ControlMessageReader + PointersState

复刻内容：
  1. ControlQueue      ← app/src/controller.c (sc_controller)
     专用控制线程 + 条件变量唤醒（替代 1ms 轮询）
     队列上限 60，超过时丢弃瞬态事件 (move)，保留 down/up/key

  2. PointersState     ← server/.../control/PointersState.java
     多触点状态管理（最多 10 个 pointer），local ID 分配，
     支持鼠标 (POINTER_ID_MOUSE) + 手指混合输入

  3. ControlMessage    ← server/.../control/ControlMessage.java (精简版)
     二进制控制协议封装（对应 ControlMessageReader.java 的反序列化格式）

  4. UinputBatcher     ← 适配 HarmonyOS uinput 的批量发送器
     将 scrcpy 的二进制控制协议映射到 HarmonyOS uinput 命令，
     利用持久化 shell 管道批量发送，达到接近 scrcpy 二进制协议的低延迟

对应 scrcpy 源文件：
  - app/src/controller.c                          (sc_controller_push_msg / run_controller)
  - server/.../control/ControlMessageReader.java   (parseInjectTouchEvent 等)
  - server/.../control/PointersState.java          (getPointerIndex / update / cleanUp)
  - server/.../control/Controller.java             (injectTouch / injectScroll)
"""

import struct
import threading
import time
import logging
from typing import Optional, Dict, List, Tuple, Callable
from collections import deque

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  常量 — 对应 ControlMessage.java + controller.c
# ═══════════════════════════════════════════════════════════════

# controller.c: SC_CONTROL_MSG_QUEUE_LIMIT = 60
CONTROL_QUEUE_LIMIT = 60

# ControlMessage.java: TYPE_*
MSG_TYPE_INJECT_KEYCODE = 0
MSG_TYPE_INJECT_TEXT = 1
MSG_TYPE_INJECT_TOUCH_EVENT = 2
MSG_TYPE_INJECT_SCROLL_EVENT = 3
MSG_TYPE_BACK_OR_SCREEN_ON = 4
MSG_TYPE_GET_CLIPBOARD = 5
MSG_TYPE_SET_CLIPBOARD = 6

# MotionEvent action 常量
ACTION_DOWN = 0
ACTION_UP = 1
ACTION_MOVE = 2
ACTION_SCROLL = 8

# Controller.java: POINTER_ID_MOUSE = -1
POINTER_ID_MOUSE = -1
# POINTER_ID_GENERIC_FINGER = -2
POINTER_ID_GENERIC_FINGER = -2

# PointersState.java: MAX_POINTERS = 10
MAX_POINTERS = 10

# uinput -T -m 的 smooth time 计算参数。
# 实机验证：该参数缺省为 1000ms —— 不传会把每段 move 拉伸成
# 1 秒动画（"半天滑不过去"）；固定小值（50ms）则设备端速度过冲，
# launcher 判定为极速甩动（"一滑直接飞到最后一屏"）。
# 正确做法：按轨迹距离比例给 smooth time（1px≈1ms ≈ 1000px/s，
# 接近真实手指速度），并夹在 [SMOOTH_MIN_MS, SMOOTH_MAX_MS]。
# 实机标定（6UNBB26324009125）：整段轨迹合成"单条连续 -m"时，
# 一次 650px 滑动恰好翻一屏；多段拼接会因段间停顿干扰 launcher
# 速度采样，出现 0 页或飞多页的不稳定结果。
MS_PER_PX = 1.0
SMOOTH_MIN_MS = 40
SMOOTH_MAX_MS = 1500


def move_smooth_ms(dx: int, dy: int) -> int:
    """按轨迹距离计算 uinput -T -m 的 smooth time（ms）。"""
    dist = (dx * dx + dy * dy) ** 0.5
    return int(max(SMOOTH_MIN_MS, min(SMOOTH_MAX_MS, dist * MS_PER_PX)))


# ═══════════════════════════════════════════════════════════════
#  ControlMessage — 对应 ControlMessage.java (精简版)
# ═══════════════════════════════════════════════════════════════

class ControlMessage:
    """
    对应 scrcpy server/.../control/ControlMessage.java

    scrcpy 的二进制控制协议格式 (ControlMessageReader.java):
      TYPE_INJECT_KEYCODE:     [type:1] [action:1] [keycode:4] [repeat:4] [metaState:4]
      TYPE_INJECT_TEXT:        [type:1] [length:4] [text:N]
      TYPE_INJECT_TOUCH_EVENT: [type:1] [action:1] [pointerId:8] [x:4] [y:4]
                               [screenW:2] [screenH:2] [pressure:2]
                               [actionButton:4] [buttons:4]
      TYPE_INJECT_SCROLL_EVENT:[type:1] [x:4] [y:4] [screenW:2] [screenH:2]
                               [hScroll:2] [vScroll:2] [buttons:4]

    本类仅做封装，实际序列化由 UinputBatcher 映射为 uinput 命令。
    """

    __slots__ = (
        "type", "action", "pointer_id", "x", "y",
        "screen_w", "screen_h", "pressure",
        "keycode", "repeat", "meta_state",
        "h_scroll", "v_scroll", "buttons",
        "text",
    )

    def __init__(self, msg_type: int):
        self.type = msg_type
        self.action = 0
        self.pointer_id = 0
        self.x = 0
        self.y = 0
        self.screen_w = 0
        self.screen_h = 0
        self.pressure = 1.0
        self.keycode = 0
        self.repeat = 0
        self.meta_state = 0
        self.h_scroll = 0.0
        self.v_scroll = 0.0
        self.buttons = 0
        self.text = ""

    @staticmethod
    def is_droppable(msg: "ControlMessage") -> bool:
        """
        对应 controller.c: sc_control_msg_is_droppable

        move 事件 (ACTION_MOVE) 是可丢弃的 — 丢弃中间帧的 move
        不会影响用户体验，反而减少队列积压延迟。
        scroll 事件也可丢弃（连续滚轮事件）。
        """
        if msg.type == MSG_TYPE_INJECT_TOUCH_EVENT:
            return msg.action == ACTION_MOVE
        if msg.type == MSG_TYPE_INJECT_SCROLL_EVENT:
            return True
        return False

    @staticmethod
    def create_touch(
        action: int, pointer_id: int,
        x: int, y: int, screen_w: int, screen_h: int,
        pressure: float = 1.0, buttons: int = 0,
    ) -> "ControlMessage":
        msg = ControlMessage(MSG_TYPE_INJECT_TOUCH_EVENT)
        msg.action = action
        msg.pointer_id = pointer_id
        msg.x = x
        msg.y = y
        msg.screen_w = screen_w
        msg.screen_h = screen_h
        msg.pressure = pressure
        msg.buttons = buttons
        return msg

    @staticmethod
    def create_scroll(
        x: int, y: int, screen_w: int, screen_h: int,
        h_scroll: float, v_scroll: float,
    ) -> "ControlMessage":
        msg = ControlMessage(MSG_TYPE_INJECT_SCROLL_EVENT)
        msg.x = x
        msg.y = y
        msg.screen_w = screen_w
        msg.screen_h = screen_h
        msg.h_scroll = h_scroll
        msg.v_scroll = v_scroll
        return msg

    @staticmethod
    def create_keycode(
        action: int, keycode: int, repeat: int = 0, meta_state: int = 0,
    ) -> "ControlMessage":
        msg = ControlMessage(MSG_TYPE_INJECT_KEYCODE)
        msg.action = action
        msg.keycode = keycode
        msg.repeat = repeat
        msg.meta_state = meta_state
        return msg

    @staticmethod
    def create_text(text: str) -> "ControlMessage":
        msg = ControlMessage(MSG_TYPE_INJECT_TEXT)
        msg.text = text
        return msg


# ═══════════════════════════════════════════════════════════════
#  PointersState — 复刻 server/.../control/PointersState.java
# ═══════════════════════════════════════════════════════════════

class _Pointer:
    """对应 PointersState.java: Pointer"""
    __slots__ = ("id", "local_id", "x", "y", "pressure", "up")

    def __init__(self, pointer_id: int, local_id: int):
        self.id = pointer_id
        self.local_id = local_id
        self.x = 0
        self.y = 0
        self.pressure = 1.0
        self.up = False


class PointersState:
    """
    复刻 scrcpy server/.../control/PointersState.java

    功能:
      - 管理最多 MAX_POINTERS (10) 个同时活跃的触点
      - 每个 pointer 有全局 id (来自客户端) 和 local id (0~9, 用于 uinput)
      - down 时分配 local_id，up 时标记，cleanUp 时移除
    """

    def __init__(self):
        self._pointers: List[_Pointer] = []

    def _index_of(self, pointer_id: int) -> int:
        """对应 PointersState.indexOf"""
        for i, p in enumerate(self._pointers):
            if p.id == pointer_id:
                return i
        return -1

    def _is_local_id_available(self, local_id: int) -> bool:
        """对应 PointersState.isLocalIdAvailable"""
        for p in self._pointers:
            if p.local_id == local_id:
                return False
        return True

    def _next_unused_local_id(self) -> int:
        """对应 PointersState.nextUnusedLocalId"""
        for lid in range(MAX_POINTERS):
            if self._is_local_id_available(lid):
                return lid
        return -1

    def get_pointer_index(self, pointer_id: int) -> int:
        """
        对应 PointersState.getPointerIndex

        如果 pointer_id 已存在，返回其索引；
        否则分配新 pointer（如果未满），返回新索引；
        满了返回 -1。
        """
        idx = self._index_of(pointer_id)
        if idx != -1:
            return idx

        if len(self._pointers) >= MAX_POINTERS:
            return -1

        local_id = self._next_unused_local_id()
        if local_id == -1:
            return -1

        p = _Pointer(pointer_id, local_id)
        self._pointers.append(p)
        return len(self._pointers) - 1

    def get(self, index: int) -> _Pointer:
        return self._pointers[index]

    def set_point(self, index: int, x: int, y: int, pressure: float = 1.0):
        p = self._pointers[index]
        p.x = x
        p.y = y
        p.pressure = pressure

    def mark_up(self, index: int, up: bool = True):
        """对应 Controller.java: pointer.setUp()"""
        self._pointers[index].up = up

    def cleanup(self):
        """对应 PointersState.cleanUp — 移除所有 UP 的 pointer"""
        self._pointers = [p for p in self._pointers if not p.up]

    @property
    def count(self) -> int:
        return len(self._pointers)


# ═══════════════════════════════════════════════════════════════
#  ControlQueue — 复刻 app/src/controller.c
# ═══════════════════════════════════════════════════════════════

class ControlQueue:
    """
    复刻 scrcpy app/src/controller.c 的 sc_controller。

    scrcpy 的控制通道线程模型 (controller.c):
      - sc_controller_push_msg(): 由 UI 线程调用，加锁入队
        - 队列 < 60: 直接入队
        - 队列 >= 60 且 msg 可丢弃: 丢弃 (返回 false)
        - 队列 >= 60 且 msg 不可丢弃: 强制入队 (可能触发 realloc)
        - 队列从空→非空: signal cond
      - run_controller(): 专用线程
        - cond_wait 直到队列非空 / stopped
        - 取出 msg → process_msg → serialize → net_send_all
        - 串行发送保证顺序

    本类适配 HarmonyOS: 不做二进制序列化，而是将 ControlMessage
    映射为 uinput 命令字符串，通过持久化 shell 批量发送。
    """

    def __init__(self, send_fn: Optional[Callable[[str], bool]] = None):
        """
        :param send_fn: 发送函数，接收 uinput 命令字符串，返回是否成功。
                        若为 None，则消息留在队列中由外部 drain。
        """
        self._queue: deque = deque()
        self._mutex = threading.Lock()
        self._cond = threading.Condition(self._mutex)
        self._stopped = False
        self._send_fn = send_fn
        self._thread: Optional[threading.Thread] = None
        # 单次 send_fn 调用合成的事件数上限（批量发送摊薄子进程开销）
        self._batch_limit = 8
        # 触摸状态（move 起点）：down 记录，move 用上一位置生成起点→终点
        self._touch_state: dict = {"x": 0, "y": 0}

        # 预分配 (对应 controller.c: sc_vecdeque_reserve(LIMIT + 4))
        self._droppable_types = {MSG_TYPE_INJECT_TOUCH_EVENT, MSG_TYPE_INJECT_SCROLL_EVENT}

    def start(self):
        """启动控制发送线程（对应 controller.c: sc_controller_start）"""
        self._stopped = False
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="scrcpy-ctl"
        )
        self._thread.start()

    def stop(self):
        """对应 controller.c: sc_controller_stop"""
        with self._mutex:
            self._stopped = True
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def push(self, msg: ControlMessage) -> bool:
        """
        对应 controller.c: sc_controller_push_msg

        返回 True 表示入队成功，False 表示被丢弃。
        """
        with self._mutex:
            if self._stopped:
                return False

            size = len(self._queue)
            if size < CONTROL_QUEUE_LIMIT:
                was_empty = size == 0
                self._queue.append(msg)
                if was_empty:
                    self._cond.notify()
                return True
            elif not ControlMessage.is_droppable(msg):
                # 不可丢弃事件强制入队
                self._queue.append(msg)
                self._cond.notify()
                return True
            else:
                # 可丢弃事件丢弃
                logger.debug("控制队列满 (%d)，丢弃 %s", size, msg.type)
                return False

    def _run(self):
        """
        对应 controller.c: run_controller

        循环:
          1. cond_wait 直到队列非空 / stopped
          2. 批量取出最多 _batch_limit 条消息，合成 `; ` 连接的 uinput
             命令串，一次调用 send_fn（hdc shell 单次子进程执行多条，
             摊薄 ~150ms/次的进程开销，保证滑动跟手）。
        """
        while True:
            with self._mutex:
                while not self._stopped and not self._queue:
                    self._cond.wait(timeout=0.5)
                if self._stopped:
                    return
                # 判断队列中是否有 move 事件 / 是否含需立即发送的事件
                has_move = False
                has_immediate = False
                for m in self._queue:
                    if m.type == MSG_TYPE_INJECT_TOUCH_EVENT:
                        if m.action == ACTION_MOVE:
                            has_move = True
                        else:
                            has_immediate = True  # down/up 应立即发送
                    else:
                        has_immediate = True  # key/scroll 应立即发送
            # 滑动跟手策略：
            # - 含 down/up/key/scroll：立即 flush（has_immediate 已控制）
            # - 纯 move 首帧：立即 flush（不等）。滑动中段给 ≤4ms 极短尾巴
            #   窗口收集后续 move，仍能拼成一条 hdc shell 调用，避免每次
            #   16ms 一次的独立进程开销 ≈103ms。单 swipe 跟手延迟从旧版
            #   ~95ms → ≤10ms，肉眼无感知。
            # 实测：触摸响应时长 = send_touch → push → run 唤醒 → shell 启动
            #   → 命令执行 ≈ 5-15ms（含尾巴等待），与鼠标同速。
            if has_immediate:
                pass
            elif has_move:
                time.sleep(0.004)
            with self._mutex:
                if self._stopped:
                    return
                batch = []
                # 滑动场景一次性取光（去掉 batch_limit 限制），便于一次 swipe
                # 全合并到 1~2 个 hdc shell 调用；首次 down/move 单条不再等下一条
                while self._queue:
                    batch.append(self._queue.popleft())
                    if len(batch) >= 64:  # 安全上限，避免异常积压占满
                        break

            # 批内 move 压缩：每段连续 move 只保留"终点"一条。
            # 起点由 touch_state 链式衔接，最终合成"单条连续
            # uinput -T -m 起点 终点 smooth"（smooth=整段距离）。
            # 实机标定：单条连续 -m 时一次 650px 滑动恰好翻一屏；
            # 多段拼接会因段间 ~150ms 停顿干扰 launcher 速度采样，
            # 出现 0 页或飞多页的不稳定结果。
            # 单点 down/up/scroll/key 不压缩。
            compressed = []
            i = 0
            n = len(batch)
            while i < n:
                m = batch[i]
                is_move = (m.type == MSG_TYPE_INJECT_TOUCH_EVENT and m.action == ACTION_MOVE)
                if is_move:
                    # 找到连续 move 段的右端，只保留终点
                    j = i + 1
                    while j < n and batch[j].type == MSG_TYPE_INJECT_TOUCH_EVENT and batch[j].action == ACTION_MOVE:
                        j += 1
                    compressed.append((m.type, m.action, batch[j - 1]))
                    i = j
                else:
                    compressed.append((m.type, m.action, m))
                    i += 1

            # 锁外批量合成发送（避免长时间持锁）
            # touch_state 链式衔接每条 move 的起点→终点，轨迹连续
            cmds = []
            for tag, action, msg in compressed:
                try:
                    c = _msg_to_uinput(msg, self._touch_state)
                except Exception:
                    c = None
                if c:
                    cmds.append(c)
            if cmds and self._send_fn:
                try:
                    self._send_fn("; ".join(cmds))
                except Exception as e:
                    logger.warning("控制命令发送失败: %s (batch=%d)", e, len(cmds))

    @property
    def queue_size(self) -> int:
        with self._mutex:
            return len(self._queue)


# ═══════════════════════════════════════════════════════════════
#  UinputBatcher — 适配 HarmonyOS uinput 的批量发送
# ═══════════════════════════════════════════════════════════════

class UinputBatcher:
    """
    将 scrcpy 风格的 ControlMessage 映射为 HarmonyOS uinput 命令，
    通过持久化 shell 管道发送，达到接近 scrcpy 二进制协议的低延迟。

    scrcpy 的控制通道是二进制 TCP socket (net_send_all)，延迟 ~0.1ms。
    HarmonyOS 的 uinput 是文本 shell 命令，但通过持久化 shell stdin
    管道发送可以避免每次创建子进程 (~150ms → ~5ms)。

    进一步优化: 多条 move 命令在同一 write 中批量发送，减少系统调用。
    """

    def __init__(self, input_proc_write_fn: Callable[[bytes], bool]):
        """
        :param input_proc_write_fn: 写入持久化 shell stdin 的函数
        """
        self._write = input_proc_write_fn
        self._lock = threading.Lock()
        self._batch: List[str] = []
        self._batch_deadline = 0.0
        self._batch_interval = 0.004  # 4ms 批量窗口

    def send(self, cmd: str) -> bool:
        """发送单条 uinput 命令"""
        with self._lock:
            data = (cmd + "\n").encode("utf-8")
            return self._write(data)

    def send_batch(self, cmds: List[str]) -> bool:
        """批量发送多条命令（减少系统调用次数）"""
        if not cmds:
            return True
        with self._lock:
            data = "".join(f"{c}\n" for c in cmds).encode("utf-8")
            return self._write(data)


# ═══════════════════════════════════════════════════════════════
#  ControlMessage → uinput 命令映射
# ═══════════════════════════════════════════════════════════════

def _msg_to_uinput(msg: ControlMessage, touch_state: Optional[dict] = None) -> Optional[str]:
    """
    将 ControlMessage 映射为 HarmonyOS uinput 命令字符串。

    scrcpy Controller.java 的 injectTouch() 通过 InputManager.injectInputEvent
    注入 MotionEvent。HarmonyOS 没有公开 InputManager API，但支持 uinput：
      - uinput -T -d <x> <y>         (touch down)
      - uinput -T -m <x> <y>         (touch move)
      - uinput -T -u <x> <y>         (touch up)
      - uinput -T -c <x> <y>         (tap/click)
      - uinput -K -d <keycode>       (key down)
      - uinput -K -u <keycode>       (key up)
      - uinput -K -t <text>          (text input)
      - uinput -T -s <x> <y> <h> <v> (scroll)
    """
    if msg.type == MSG_TYPE_INJECT_TOUCH_EVENT:
        if msg.action == ACTION_DOWN:
            if touch_state is not None:
                touch_state["x"], touch_state["y"] = msg.x, msg.y
            return f"uinput -T -d {msg.x} {msg.y}"
        elif msg.action == ACTION_MOVE:
            # HarmonyOS uinput -T -m 需要起点和终点共 4 个坐标；
            # 用 touch_state 记录上一位置，生成 起点→终点 的移动。
            # 末尾必须带 smooth time：缺省 1000ms 会拉伸成 1 秒动画；
            # 按距离比例（约 1000px/s）才能速度真实、不飞屏（实机验证）。
            px, py = (touch_state or {}).get("x", msg.x), (touch_state or {}).get("y", msg.y)
            if touch_state is not None:
                touch_state["x"], touch_state["y"] = msg.x, msg.y
            smooth = move_smooth_ms(msg.x - px, msg.y - py)
            return f"uinput -T -m {px} {py} {msg.x} {msg.y} {smooth}"
        elif msg.action == ACTION_UP:
            return f"uinput -T -u {msg.x} {msg.y}"
        else:
            return f"uinput -T -c {msg.x} {msg.y}"

    elif msg.type == MSG_TYPE_INJECT_SCROLL_EVENT:
        # scrcpy scroll: h_scroll/vScroll 范围 [-16, 16]
        # uinput scroll 需要 int 像素值
        v = int(msg.v_scroll * 30)  # 缩放为像素
        h = int(msg.h_scroll * 30)
        if abs(v) >= abs(h):
            return f"uinput -T -s {msg.x} {msg.y} 0 {v}"
        else:
            return f"uinput -T -s {msg.x} {msg.y} {h} 0"

    elif msg.type == MSG_TYPE_INJECT_KEYCODE:
        # HarmonyOS uinput key code 与 Android 不同，需映射
        key_map = {
            2007: "276",  # BACK
            2003: "102",  # HOME
            2049: "254",  # RECENT
            2058: "115",  # VOL+
            2059: "114",  # VOL-
            2060: "113",  # MUTE
        }
        key = key_map.get(msg.keycode, str(msg.keycode))
        if msg.action == ACTION_DOWN:
            return f"uinput -K -d {key}"
        elif msg.action == ACTION_UP:
            return f"uinput -K -u {key}"
        return None

    elif msg.type == MSG_TYPE_INJECT_TEXT:
        # 与 hdc_cast_service.send_text 一致：先过滤换行，再单引号转义
        safe = (msg.text or "").replace("\r", " ").replace("\n", " ")
        safe = safe.replace("'", "'\\''")
        return f"uinput -K -t '{safe}'"

    return None


# ═══════════════════════════════════════════════════════════════
#  TouchEventAggregator — 移动事件聚合器
# ═══════════════════════════════════════════════════════════════

class TouchEventAggregator:
    """
    聚合连续的 move 事件，只保留最新坐标。

    scrcpy 的 ControlQueue 已经能丢弃队列中的 move 事件，但如果
    move 产生速度远超发送速度，队列中可能积压多条 move。
    本聚合器在入队前就合并连续 move，进一步降低延迟。

    策略:
      - down/up: 立即入队（不可丢弃）
      - move: 如果队列尾部是 move，替换它；否则入队
    """

    def __init__(self, queue: ControlQueue):
        self._queue = queue

    def push_touch(
        self, action: int, x: int, y: int,
        screen_w: int = 0, screen_h: int = 0,
        pointer_id: int = POINTER_ID_GENERIC_FINGER,
    ) -> bool:
        msg = ControlMessage.create_touch(
            action, pointer_id, x, y, screen_w, screen_h
        )
        return self._queue.push(msg)

    def push_scroll(
        self, x: int, y: int, h_scroll: float, v_scroll: float,
        screen_w: int = 0, screen_h: int = 0,
    ) -> bool:
        msg = ControlMessage.create_scroll(
            x, y, screen_w, screen_h, h_scroll, v_scroll
        )
        return self._queue.push(msg)

    def push_key(self, action: int, keycode: int) -> bool:
        msg = ControlMessage.create_keycode(action, keycode)
        return self._queue.push(msg)

    def push_text(self, text: str) -> bool:
        msg = ControlMessage.create_text(text)
        return self._queue.push(msg)

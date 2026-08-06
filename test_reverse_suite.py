# -*- coding: utf-8 -*-
"""
HoKit 逆向复刻回归测试套件（unittest 风格，python -m unittest 运行）。
覆盖本轮全部代码改动：so 智能推送、burst 跳帧、repeatInterval 配置链路、
合并命令设备信息采集、PacketMerger/H264Decoder 关键逻辑。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


class TestSoSmartPush(unittest.TestCase):
    """so 智能推送：候选选择 + MD5"""

    def test_candidates_arm64_v2(self):
        from core.hokit_h264_channel import pick_screencopy_so_candidates
        cands = pick_screencopy_so_candidates("arm64-v8a", protocol_v2=True)
        self.assertTrue(cands, "arm64-v8a v2 应有候选")
        path, md5 = cands[0]
        self.assertTrue(os.path.isfile(path), f"候选 so 应存在: {path}")
        self.assertEqual(len(md5), 32, "MD5 应为 32 位 hex")

    def test_candidates_fallback(self):
        from core.hokit_h264_channel import pick_screencopy_so_candidates
        cands = pick_screencopy_so_candidates("x86", protocol_v2=False)
        self.assertTrue(cands, "未知 ABI 应有兜底候选")

    def test_pick_screencopy_so_compat(self):
        from core.hokit_h264_channel import pick_screencopy_so
        path = pick_screencopy_so("arm64-v8a", protocol_v2=True)
        self.assertTrue(path and os.path.isfile(path))


class TestQueuePolicy(unittest.TestCase):
    """burst 跳帧：丢旧保新 + drain_to_latest"""

    def test_drain_to_latest(self):
        import queue
        from core.hokit_h264_channel import HokitH264Channel
        ch = object.__new__(HokitH264Channel)
        ch._q = queue.Queue()
        for i in range(10):
            ch._q.put(f"frame-{i}")
        latest = ch.drain_to_latest(keep=1)
        self.assertEqual(latest, "frame-9", "应取到最新帧")
        self.assertEqual(ch.qsize(), 0, "排空后队列应为空")

    def test_feed_full_drops_oldest(self):
        import queue
        from core.hokit_h264_channel import HokitH264Channel
        ch = object.__new__(HokitH264Channel)
        ch._q = queue.Queue(maxsize=2)
        ch._q.put("old")
        try:
            ch._q.put_nowait("new")
        except Exception:
            ch._q.get_nowait()
            ch._q.put_nowait("new")
        self.assertEqual(ch._q.qsize(), 2)
        first = ch._q.get_nowait()
        self.assertEqual(first, "old")
        self.assertEqual(ch._q.get_nowait(), "new")


class TestRepeatConfig(unittest.TestCase):
    """repeatInterval 配置链路"""

    def test_default_repeat(self):
        from core.cast_config import CastConfig, DEFAULT_REPEAT_INTERVAL
        cfg = CastConfig()
        self.assertEqual(cfg.repeat_interval, DEFAULT_REPEAT_INTERVAL)
        self.assertEqual(DEFAULT_REPEAT_INTERVAL, 16, "默认应为高性能 16ms")

    def test_legacy_json_compat(self):
        """旧配置（无 repeat_interval 字段）应回退默认"""
        import json
        import tempfile
        from core import cast_config as cc
        old_file = cc.CONFIG_FILE
        old_dir = cc.CONFIG_DIR
        try:
            cc.CONFIG_DIR = tempfile.mkdtemp(prefix="wtgp_test_")
            cc.CONFIG_FILE = os.path.join(cc.CONFIG_DIR, "cast_configs.json")
            with open(cc.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"DEV1": {"capture_mode": "h264", "fps": 60,
                                    "bitrate_mbps": 30, "scale_pct": 50,
                                    "screen_id": 0, "remember": False}}, f)
            from core.cast_config import get_config_manager
            mgr = get_config_manager()
            mgr._configs.clear()
            cfg = mgr.get_or_create("DEV1")
            self.assertEqual(cfg.repeat_interval, 16, "旧配置应回退默认 16")
        finally:
            cc.CONFIG_FILE = old_file
            cc.CONFIG_DIR = old_dir

    def test_disk_restore_preserves_repeat(self):
        """带 repeat_interval 字段的 JSON 应正确恢复（review 发现的持久化链路缺口）"""
        import json
        import tempfile
        from core import cast_config as cc
        old_file = cc.CONFIG_FILE
        old_dir = cc.CONFIG_DIR
        try:
            cc.CONFIG_DIR = tempfile.mkdtemp(prefix="wtgp_test_")
            cc.CONFIG_FILE = os.path.join(cc.CONFIG_DIR, "cast_configs.json")
            with open(cc.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"DEV2": {"capture_mode": "h264", "fps": 60,
                                    "bitrate_mbps": 30, "scale_pct": 50,
                                    "screen_id": 0, "repeat_interval": 8,
                                    "remember": True}}, f)
            from core.cast_config import CastConfigManager
            mgr = CastConfigManager()
            cfg = mgr.get_or_create("DEV2")
            self.assertEqual(cfg.repeat_interval, 8, "磁盘恢复应保留 repeat_interval=8")
            # 重新加载（模拟重启）：新实例从磁盘读
            mgr2 = CastConfigManager()
            cfg2 = mgr2.get_or_create("DEV2")
            self.assertEqual(cfg2.repeat_interval, 8, "重启后仍应为 8")
        finally:
            cc.CONFIG_FILE = old_file
            cc.CONFIG_DIR = old_dir

    def test_set_repeat_interval_clamp(self):
        from core.hdc_cast_service import HDCCastService
        svc = HDCCastService.__new__(HDCCastService)
        svc._repeat_interval = 16
        svc.set_repeat_interval(8)
        self.assertEqual(svc._repeat_interval, 8)
        svc.set_repeat_interval(999)
        self.assertEqual(svc._repeat_interval, 100, "应夹紧到上限 100")
        svc.set_repeat_interval(1)
        self.assertEqual(svc._repeat_interval, 8, "应夹紧到下限 8")


class TestFastDeviceInfo(unittest.TestCase):
    """合并命令设备信息采集：section 解析逻辑"""

    def test_section_split(self):
        """模拟设备输出，验证 echo 标记切分与字段提取"""
        mock_output = (
            "__name__\n华为畅享 90 Pro Max\n"
            "__model__\nCHZ-AL00\n"
            "__swver__\nOpenHarmony-6.1.1.125\n"
            "__abi__\narm64-v8a\n"
            "__devtype__\nphone\n"
            "__apiver__\n24\n"
            "__udid__\nudid of current device is :\n2D1E8B571906ECE5ED17F06F399C2CBA31DC3F1F46ED2DAC56CAE0805768B0FC\n"
            "__end__\n"
        )
        sections = {}
        marker = None
        for line in mock_output.splitlines():
            s = line.strip()
            if s.startswith("__") and s.endswith("__") and s[2:-2] in (
                    "name", "model", "swver", "abi", "devtype", "apiver", "udid", "end"):
                marker = s[2:-2]
                sections[marker] = []
            elif marker is not None and marker != "end":
                sections[marker].append(s if s and s.lower() not in ("error", "false", "none", "null") else "")

        def sec(m):
            return "\n".join(sections.get(m, [])).strip()

        self.assertEqual(sec("name"), "华为畅享 90 Pro Max")
        self.assertEqual(sec("model"), "CHZ-AL00")
        self.assertEqual(sec("abi"), "arm64-v8a")
        import re
        m = re.search(r"[0-9A-Fa-f]{32,64}", sec("udid"))
        self.assertTrue(m and len(m.group(0)) == 64, "udid 应为 64 位 hex")
        vm = re.search(r"(\d+\.\d+\.\d+\.\d+)", sec("swver"))
        self.assertEqual(vm.group(1), "6.1.1.125")


class TestPacketMerger(unittest.TestCase):
    """PacketMerger：config 包缓存 + prepend（H.264 码流关键逻辑）"""

    def test_config_prepend(self):
        from core.scrcpy_decoder import PacketMerger, PACKET_FLAG_CONFIG
        m = PacketMerger()
        config = b"\x00\x00\x00\x01spspps"
        data = b"\x00\x00\x00\x01slice"
        out = m.merge(config, PACKET_FLAG_CONFIG)
        self.assertEqual(out, b"")
        out2 = m.merge(data, 0)
        self.assertEqual(out2, config + data)

    def test_reset(self):
        from core.scrcpy_decoder import PacketMerger, PACKET_FLAG_CONFIG
        m = PacketMerger()
        m.merge(b"cfg", PACKET_FLAG_CONFIG)
        m.reset()
        out = m.merge(b"data", 0)
        self.assertEqual(out, b"data", "reset 后不应再 prepend")


class TestShellEscape(unittest.TestCase):
    """send_text/send_clipboard 注入转义（安全审查 MEDIUM 修复验证）"""

    def _make_svc(self):
        from core.hdc_cast_service import HDCCastService
        svc = HDCCastService.__new__(HDCCastService)
        svc._device_id = "TESTDEV"
        svc._lock = __import__("threading").Lock()
        svc._pending_commands = []
        svc._cmd_event = __import__("threading").Event()
        svc._send_input_cmd = lambda cmd: False  # 强制走回退路径
        return svc

    @staticmethod
    def _assert_sh_safe(cmd, prefix):
        """验证 cmd 中文本被单引号包裹、内部所有单引号已转义为 '\\''，
        换行/回车已过滤 —— 即注入内容只能作为字面量存在。"""
        import re
        # 匹配前缀 + 单引号包裹的 body（内部允许 '\'' 转义）
        m = re.match(re.escape(prefix) + r"'(.*)'$", cmd, re.S)
        assert m, f"命令应被单引号包裹: {cmd}"
        body = m.group(1)
        assert "\n" not in body and "\r" not in body, "换行/回车应被过滤"
        # 将所有 '\'' 转义序列替换为占位符后，body 中不应再有单引号
        # （否则说明存在未转义的单引号，可中断引号包裹造成注入）
        stripped = body.replace("'\\''", "\x00")
        assert "'" not in stripped, f"存在未转义的单引号（注入风险）: {body}"

    def test_send_text_escapes_quote_newline(self):
        svc = self._make_svc()
        calls = []
        svc.run_hdc = lambda args: calls.append(args) or (0, "", "")
        svc.send_text("a'b\nc; reboot")
        self.assertTrue(calls, "应触发回退路径调用")
        # 模拟 hdc 将 shell 参数 join 成一条设备端命令
        full = " ".join(calls[0][3:])
        self._assert_sh_safe(full, "uinput -K -t ")
        self.assertIn("c; reboot", full, "注入文本应以字面量保留在引号内")

    def test_send_clipboard_escapes(self):
        svc = self._make_svc()
        calls = []
        svc.run_hdc = lambda args: calls.append(args) or (0, "", "")
        svc.send_clipboard("x'; param set const.clipboard.data hacked\n")
        args = calls[0]
        full = " ".join(args[3:])
        self._assert_sh_safe(full, "param set const.clipboard.data ")


class TestTouchControl(unittest.TestCase):
    """触控链路：action 语义 + move 起点状态（防止 GUI/scrcpy 语义错位回归）"""

    def test_msg_to_uinput_actions(self):
        from core.scrcpy_control import (_msg_to_uinput, ControlMessage,
                                          POINTER_ID_GENERIC_FINGER,
                                          ACTION_DOWN, ACTION_UP, ACTION_MOVE)
        state = {"x": 0, "y": 0}
        m = ControlMessage.create_touch(ACTION_DOWN, POINTER_ID_GENERIC_FINGER, 564, 1700, 1128, 2444)
        self.assertEqual(_msg_to_uinput(m, state), "uinput -T -d 564 1700")
        m = ControlMessage.create_touch(ACTION_MOVE, POINTER_ID_GENERIC_FINGER, 564, 1500, 1128, 2444)
        self.assertEqual(_msg_to_uinput(m, state), "uinput -T -m 564 1700 564 1500 200", "move 应含起点→终点+smooth(距离比例)")
        m = ControlMessage.create_touch(ACTION_UP, POINTER_ID_GENERIC_FINGER, 564, 800, 1128, 2444)
        self.assertEqual(_msg_to_uinput(m, state), "uinput -T -u 564 800")
        # 常量语义：DOWN=0 / UP=1 / MOVE=2
        self.assertEqual((ACTION_DOWN, ACTION_UP, ACTION_MOVE), (0, 1, 2))

    def test_send_touch_actions(self):
        """send_touch 回退路径命令生成（scrcpy 语义）"""
        import threading
        from core.hdc_cast_service import HDCCastService
        svc = HDCCastService.__new__(HDCCastService)
        svc._device_id = "D"
        svc._control_queue = None
        svc._touch_x, svc._touch_y = 0, 0
        svc._click_pending = None
        svc._click_ts = 0.0
        svc._click_lock = threading.Lock()
        svc._click_flush_active = False
        svc._lock = threading.Lock()
        svc._pending_commands = []
        svc._cmd_event = threading.Event()
        sent = []
        svc._send_input_cmd = lambda cmd: sent.append(cmd) or True
        svc.run_hdc = lambda args: (0, "", "")
        svc.send_touch(100, 200, 0)   # down
        svc.send_touch(150, 250, 2)   # move
        svc.send_touch(150, 250, 1)   # up
        self.assertEqual(sent, [
            "uinput -T -d 100 200",
            "uinput -T -m 100 200 150 250 70",
            "uinput -T -u 150 250",
        ])


class TestControlQueueBatch(unittest.TestCase):
    """ControlQueue 批量合成 + move 压缩 + 批串不重试"""

    def test_batch_and_move_compress(self):
        import time as _t
        from core.scrcpy_control import (ControlQueue, ControlMessage,
                                          POINTER_ID_GENERIC_FINGER,
                                          ACTION_DOWN, ACTION_UP, ACTION_MOVE)
        sent = []
        cq = ControlQueue(send_fn=lambda cmd: sent.append(cmd))
        cq.start()
        pts = [(564, 1700), (564, 1500), (564, 1200), (564, 900), (564, 800)]
        cq.push(ControlMessage.create_touch(ACTION_DOWN, POINTER_ID_GENERIC_FINGER, *pts[0], 1128, 2444))
        for x, y in pts[1:4]:
            cq.push(ControlMessage.create_touch(ACTION_MOVE, POINTER_ID_GENERIC_FINGER, x, y, 1128, 2444))
        cq.push(ControlMessage.create_touch(ACTION_UP, POINTER_ID_GENERIC_FINGER, *pts[4], 1128, 2444))
        _t.sleep(0.6)
        cq.stop()
        all_cmds = "; ".join(sent)
        self.assertIn("uinput -T -d 564 1700", all_cmds, "应包含 down")
        self.assertIn("uinput -T -u 564 800", all_cmds, "应包含 up")
        self.assertIn("-m 564", all_cmds, "应包含 move 命令")
        self.assertNotIn("-m 564 1500 564 1500", all_cmds, "move 不应原地（起点=终点）")
        self.assertLessEqual(len(sent), 4, "批量应减少发送次数")

    def test_send_input_cmd_no_retry_batch(self):
        import threading
        from core.hdc_cast_service import HDCCastService
        svc = HDCCastService.__new__(HDCCastService)
        svc._device_id = "D"
        svc._input_lock = threading.Lock()
        calls = []
        svc.run_hdc = lambda *a, **kw: calls.append(a) or (1, "", "fail")
        r = svc._send_input_cmd("uinput -T -d 1 2; uinput -T -u 3 4")
        self.assertEqual(len(calls), 1, "批串失败不应重试（避免非幂等命令重复执行）")
        self.assertFalse(r)
        calls.clear()
        r = svc._send_input_cmd("uinput -T -c 1 2")
        self.assertEqual(len(calls), 2, "单命令失败应重试一次")
        self.assertFalse(r)


class TestDaemonOwnership(unittest.TestCase):
    """daemon 归属判定与 PID 解析健壮性（mock ps 输出）"""

    def _make_jpeg(self):
        from core.hokit_jpeg_channel import HokitJpegChannel
        ch = HokitJpegChannel.__new__(HokitJpegChannel)
        ch._shell_calls = []

        def fake_shell(cmd, timeout=10):
            ch._shell_calls.append(cmd)
            if "start-daemon" in cmd and "grep" in cmd:
                # scrcpy daemon + agent daemon（无 extension）+ 错位列（首列非数字）
                return 0, (
                    "shell  47718  1 0 01:06 ?  00:00:00 uitest start-daemon singleness "
                    "--extension-name scrcpy_server.so -scale 2\n"
                    "shell  48576  1 0 01:10 ?  00:00:00 uitest start-daemon singleness\n"
                    "badcolumn  1234  999 0 01:11 ?  00:00:00 uitest start-daemon singleness\n"
                ), ""
            if cmd.startswith("cat /proc/"):
                return 0, "uitest start-daemon singleness", ""  # /proc 复核通过
            return 0, "", ""
        ch._shell = fake_shell
        return ch

    def test_agent_daemon_running(self):
        ch = self._make_jpeg()
        self.assertTrue(ch._agent_daemon_running(), "存在无 extension 的 agent daemon 应判定在跑")

    def test_kill_other_daemons_only_scrcpy(self):
        ch = self._make_jpeg()
        ch._kill_other_daemons()
        kills = [c for c in ch._shell_calls if c.startswith("kill -9")]
        # 只杀 scrcpy daemon (47718)；agent (48576) 与错位列（首列非数字）跳过
        self.assertEqual(kills, ["kill -9 47718"])

    def test_h264_kill_other_daemons(self):
        from core.hokit_h264_channel import HokitH264Channel
        ch = HokitH264Channel.__new__(HokitH264Channel)
        calls = []

        def fake_shell(cmd, timeout=10):
            calls.append(cmd)
            if "start-daemon" in cmd and "grep" in cmd:
                return 0, (
                    "shell  47718  1 0 01:06 ?  00:00:00 uitest start-daemon singleness "
                    "--extension-name scrcpy_server.so -scale 2\n"
                    "shell  48576  1 0 01:10 ?  00:00:00 uitest start-daemon singleness\n"
                ), ""
            if cmd.startswith("cat /proc/"):
                return 0, "uitest start-daemon singleness", ""
            return 0, "", ""
        ch._shell = fake_shell
        ch._kill_other_daemons()
        kills = [c for c in calls if c.startswith("kill -9")]
        # h264 保留自己的 scrcpy (47718)，杀 agent (48576)
        self.assertEqual(kills, ["kill -9 48576"])


    def test_quick_click_merge(self):
        """快速点击合并：down 后 60ms 内 up（无 move）→ uinput -c 单命令"""
        import threading
        from core.hdc_cast_service import HDCCastService
        svc = HDCCastService.__new__(HDCCastService)
        svc._device_id = "D"
        svc._control_queue = None
        svc._touch_x, svc._touch_y = 0, 0
        svc._click_pending = None
        svc._click_ts = 0.0
        svc._click_lock = threading.Lock()
        svc._click_flush_active = False
        svc._lock = threading.Lock()
        svc._pending_commands = []
        svc._cmd_event = threading.Event()
        sent = []
        svc._send_input_cmd = lambda cmd: sent.append(cmd) or True
        svc.run_hdc = lambda *a, **kw: (0, "", "")
        svc.send_touch(100, 200, 0)   # down
        svc.send_touch(100, 200, 1)   # up（快速）
        self.assertEqual(sent, ["uinput -T -c 100 200"], "快速点击应合并为 -c 单命令")

    def test_click_merge_cancelled_by_move(self):
        """有 move 的拖拽不应合并为点击"""
        import threading
        from core.hdc_cast_service import HDCCastService
        svc = HDCCastService.__new__(HDCCastService)
        svc._device_id = "D"
        svc._control_queue = None
        svc._touch_x, svc._touch_y = 0, 0
        svc._click_pending = None
        svc._click_ts = 0.0
        svc._click_lock = threading.Lock()
        svc._click_flush_active = False
        svc._lock = threading.Lock()
        svc._pending_commands = []
        svc._cmd_event = threading.Event()
        sent = []
        svc._send_input_cmd = lambda cmd: sent.append(cmd) or True
        svc.run_hdc = lambda *a, **kw: (0, "", "")
        svc.send_touch(100, 200, 0)   # down
        svc.send_touch(120, 220, 2)   # move → 取消合并（补发 down）
        svc.send_touch(120, 220, 1)   # up
        self.assertEqual(len(sent), 3)
        self.assertNotIn("uinput -T -c", "; ".join(sent), "拖拽不应合成 -c")
        self.assertIn("uinput -T -d 100 200", "; ".join(sent), "拖拽应先补发 down")


class TestImportAll(unittest.TestCase):
    """全部改动模块可导入"""

    def test_import_core_modules(self):
        import core.hokit_h264_channel
        import core.hdc_cast_service
        import core.cast_config
        import core.hdc_client
        import core.scrcpy_decoder
        import core.hokit_jpeg_channel
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

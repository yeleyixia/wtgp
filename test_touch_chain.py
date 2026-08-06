# -*- coding: utf-8 -*-
"""
触控链路真机验证：启动投屏（agent_jpeg）→ send_touch/send_swipe → 截图对比画面变化
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEVICE_ID = "6UNBB26324009125"
HDC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "tools", "hdc", "hdc.exe")


def _snap(hdc, path):
    import subprocess
    subprocess.run([hdc, "-t", DEVICE_ID, "shell", f"snapshot_display -f {path}"],
                   capture_output=True, timeout=10)


def main():
    from core.cast_config import CastConfig
    from core.hdc_cast_service import HDCCastService

    svc = HDCCastService()
    assert svc.connect_device(DEVICE_ID), "设备连接失败"
    cfg = CastConfig(capture_mode="agent_jpeg", fps=60, bitrate_mbps=30,
                     scale_pct=50, screen_id=0, repeat_interval=16)
    svc.apply_cast_config(cfg)
    print("[tc] 启动 agent_jpeg 投屏...")
    assert svc.start_casting(mode=cfg.cast_engine_mode), "投屏启动失败"
    time.sleep(3)  # 等待首帧

    # 确认控制队列就绪
    print(f"[tc] _control_queue={svc._control_queue is not None}, "
          f"_input_proc alive={svc._input_proc is not None and svc._input_proc.poll() is None}")

    # 回到桌面
    svc.send_key(102)
    time.sleep(1.0)
    # 打开设置页（滑动有内容变化）
    svc.run_hdc(["-t", DEVICE_ID, "shell",
                 "aa start -b com.huawei.hmos.settings -a com.huawei.hmos.settings.MainAbility"], timeout=10)
    time.sleep(2.0)

    # 滑动前截图
    _snap(HDC, "/data/local/tmp/tc_before.jpeg")
    time.sleep(0.5)

    print("[tc] 发送滑动事件 (1700 → 800)...")
    # 模拟鼠标拖拽：down(0) → 多步 move(2) → up(1)（scrcpy 语义）
    t0 = time.time()
    # 打印实际批命令（通过 monkeypatch send_fn）
    sent_batches = []
    orig_fn = svc._control_queue._send_fn

    def spy(cmd):
        sent_batches.append(cmd)
        return orig_fn(cmd)

    svc._control_queue._send_fn = spy
    svc.send_touch(564, 1700, 0)  # down
    for y in range(1650, 799, -100):
        svc.send_touch(564, y, 2)  # move
        time.sleep(0.02)
    svc.send_touch(564, 800, 1)  # up
    print(f"[tc] 触控事件发送耗时 {time.time()-t0:.2f}s")
    svc._control_queue._send_fn = orig_fn
    print(f"[tc] 实际发送批数: {len(sent_batches)}")
    for i, b in enumerate(sent_batches[:3]):
        print(f"  batch{i}: {b[:180]}")
    time.sleep(1.0)

    # 滑动后截图
    _snap(HDC, "/data/local/tmp/tc_after.jpeg")
    time.sleep(0.3)
    svc.stop_casting()

    # 对比
    import subprocess
    subprocess.run([HDC, "-t", DEVICE_ID, "file", "recv", "/data/local/tmp/tc_before.jpeg",
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reverse", "tc_before.jpeg")],
                   capture_output=True, timeout=10)
    subprocess.run([HDC, "-t", DEVICE_ID, "file", "recv", "/data/local/tmp/tc_after.jpeg",
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reverse", "tc_after.jpeg")],
                   capture_output=True, timeout=10)
    import cv2
    import numpy as np
    a = cv2.imread(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reverse", "tc_before.jpeg"))
    b = cv2.imread(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reverse", "tc_after.jpeg"))
    if a is None or b is None:
        print("[tc] ❌ 截图读取失败")
        return 1
    diff = np.abs(a.astype(int) - b.astype(int)).mean()
    pct = (np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 10).mean()
    print(f"[tc] 平均像素差异={diff:.1f}, 变化像素占比={pct:.2%}")
    if pct > 0.05:
        print("[tc] ✅ 滑动生效（画面明显变化）")
        return 0
    print("[tc] ❌ 滑动未生效（画面几乎无变化）")
    return 1


if __name__ == "__main__":
    sys.exit(main())

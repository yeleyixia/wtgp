# -*- coding: utf-8 -*-
"""H.264 通道分步诊断：定位 e2e 0 帧根因"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEVICE = "6UNBB26324009125"
HDC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "resources", "tools", "hdc", "hdc.exe")


def main():
    from core.hokit_h264_channel import HokitH264Channel, _so_md5, pick_screencopy_so_candidates
    ch = HokitH264Channel(HDC, DEVICE, scale=2, frame_rate=60,
                          bitrate_mbps=30, screen_id=0, repeat_interval=16)

    abi = ch._device_abi()
    print(f"[diag] abi={abi!r}")
    v2 = ch._device_protocol_v2()
    print(f"[diag] protocol_v2={v2}")

    cands = pick_screencopy_so_candidates(abi, v2)
    for p, m in cands:
        print(f"[diag] 候选: {os.path.basename(p)} md5={m[:12]}")

    dev_md5 = ch._device_so_md5()
    print(f"[diag] 设备 so md5={dev_md5[:12] if dev_md5 else '(无)'}")

    # daemon 状态
    print(f"[diag] scrcpy daemon 在跑: {ch._scrcpy_running()}")

    # 分步启动
    t0 = time.time()
    ok_try = ch._try_daemon(v2)
    print(f"[diag] _try_daemon={ok_try} ({(time.time()-t0)*1000:.0f}ms)")
    if not ok_try:
        print("[diag] ❌ daemon 启动失败")
        return 1

    ok_fwd = ch._forward(v2)
    print(f"[diag] _forward={ok_fwd} target={ch._forward_target} port={ch.local_port}")
    if not ok_fwd:
        print("[diag] ❌ 端口转发失败")
        return 1

    try:
        ch._connect_grpc(v2)
        print("[diag] gRPC 连接成功")
    except Exception as e:
        print(f"[diag] ❌ gRPC 连接失败: {e}")
        return 1

    # 收包测试 6s（带软刺激）
    ch._kick_start()
    t0 = time.time()
    n_packets = 0
    n_frames = 0
    while time.time() - t0 < 6:
        try:
            item = ch._q.get(timeout=0.5)
        except Exception:
            item = None
        if item is None:
            continue
        n_packets += 1
        if len(item) > 1024 * 1024:  # 疑似帧数据
            n_frames += 1
    print(f"[diag] 6s 收包: {n_packets} 大包(帧?) {n_frames}")

    # 清理
    try:
        ch.stop()
        print("[diag] 清理完成")
    except Exception as e:
        print(f"[diag] 清理异常: {e}")
    return 0 if n_frames > 5 else 1


if __name__ == "__main__":
    sys.exit(main())

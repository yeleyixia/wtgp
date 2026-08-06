# -*- coding: utf-8 -*-
"""
H.264 端到端集成测试：
配置 → 通道启动 → gRPC 拉流 → 解码 → get_latest_frame 输出
"""
import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEVICE_ID = "6UNBB26324009125"


def main():
    from core.cast_config import CastConfig
    from core.hdc_cast_service import HDCCastService

    cfg = CastConfig(
        capture_mode="h264",
        fps=60,
        bitrate_mbps=30,
        scale_pct=50,
        screen_id=0,
        repeat_interval=16,
        remember=False,
    )
    svc = HDCCastService()
    ok = svc.connect_device(DEVICE_ID)
    print(f"[e2e] 连接设备: {ok}")
    if not ok:
        return 1
    svc.apply_cast_config(cfg)

    t0 = time.time()
    print(f"[e2e] 启动 H.264 投屏 (fps=60, bitrate=30MB/s, scale=50%, repeat=16)...")
    success = svc.start_casting(mode=cfg.cast_engine_mode)
    print(f"[e2e] 启动结果: {success} (耗时 {time.time()-t0:.2f}s)")
    if not success:
        print("[e2e] ❌ 启动失败")
        return 1

    # 动画线程（设置页滑动，制造画面变化）
    stop = False

    def anim():
        svc.run_hdc(["-t", DEVICE_ID, "shell",
                     "aa start -b com.huawei.hmos.settings -a com.huawei.hmos.settings.MainAbility"], timeout=10)
        time.sleep(1.0)
        while not stop:
            svc.run_hdc(["-t", DEVICE_ID, "shell", "uinput -T -d 564 1700"], timeout=10)
            for i in range(1, 5):
                y = 1700 + (700 - 1700) * i // 4
                svc.run_hdc(["-t", DEVICE_ID, "shell", f"uinput -T -m 564 1700 564 {y} 10"], timeout=10)
                time.sleep(0.08)
            svc.run_hdc(["-t", DEVICE_ID, "shell", "uinput -T -u 564 700"], timeout=10)
            time.sleep(0.3)

    threading.Thread(target=anim, daemon=True).start()

    # 消费：轮询最新帧
    last_ver = -1
    frames = 0
    first_frame_t = None
    t_end = time.time() + 15
    while time.time() < t_end:
        ver = svc.frame_version
        if ver != last_ver:
            frame = svc.get_latest_frame()
            if frame is not None:
                if first_frame_t is None:
                    first_frame_t = time.time()
                    print(f"[e2e] 首帧到达（启动后 {first_frame_t - t0:.2f}s）")
                frames += 1
                last_ver = ver
        time.sleep(0.02)
    stop = True
    svc.stop_casting()

    print(f"[e2e] 15s 内渲染帧数: {frames}（平均 {frames/15:.1f} FPS）")
    if frames > 100:
        print(f"[e2e] ✅ 端到端流畅（>100 帧）")
        return 0
    print(f"[e2e] ❌ 帧数不足（期望 >100）")
    return 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
H.264 投屏通道实机性能测试（无 GUI）
用法: python bench_h264.py [scale] [frame_rate] [bitrate_mbps] [duration_sec]
默认: scale=1 frame_rate=120 bitrate=30MB/s duration=15s
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEVICE_ID = "6UNBB26324009125"
HDC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "tools", "hdc", "hdc.exe")


def main():
    scale = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frame_rate = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    bitrate = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    duration = float(sys.argv[4]) if len(sys.argv) > 4 else 15.0

    from core.hokit_h264_channel import HokitH264Channel
    from core.scrcpy_decoder import H264Decoder, PacketMerger

    ch = HokitH264Channel(
        hdc_path=HDC,
        device_id=DEVICE_ID,
        scale=scale,
        frame_rate=frame_rate,
        bitrate_mbps=bitrate,
        screen_id=0,
    )

    t0 = time.time()
    print(f"[bench] 启动 H.264 通道: scale={scale} fps={frame_rate} bitrate={bitrate}MB/s ...")
    ok = ch.start()
    t_start = time.time() - t0
    if not ok:
        print("[bench] 启动失败")
        return 1
    print(f"[bench] 启动耗时 {t_start:.2f}s")

    decoder = H264Decoder()
    merger = PacketMerger()

    # 统计
    total_packets = 0
    total_bytes = 0
    decoded_frames = 0
    first_frame_at = None
    sizes = []
    fps_window = []

    t_end = time.time() + duration
    last_report = time.time()
    last_stim = time.time()
    stim_mode = os.environ.get("STIM", "move")  # move=微移 burst=滑动burst none=无刺激
    stim_interval = 0.4
    if stim_mode == "rapid":
        stim_interval = 0.1
    if stim_mode in ("gesture", "burst"):
        # 打开系统设置（持续动画/滚动内容源）
        ch._shell("aa start -b com.huawei.hmos.settings -a com.huawei.hmos.settings.MainAbility", timeout=10)
        time.sleep(1.0)
    elif stim_mode == "none":
        pass  # 依赖画面自身变化（相机等）
    else:
        # 回到桌面
        ch._shell("uinput -K -d 102 -u 102", timeout=10)
        time.sleep(0.5)

    burst_active = 0.0
    burst_frames = 0
    burst_fps = 0.0
    burst_last = 0.0

    def _scroll(y1=1700, y2=800, steps=4, step_delay=0.02):
        x = 564
        ch._shell(f"uinput -T -d {x} {y1}", timeout=10)
        for i in range(1, steps + 1):
            y = y1 + (y2 - y1) * i // steps
            ch._shell(f"uinput -T -m {x} {y1} {x} {y} 10", timeout=10)
            time.sleep(step_delay)
        ch._shell(f"uinput -T -u {x} {y2}", timeout=10)

    while time.time() < t_end:
        # 持续画面刺激：静止时编码器不产帧，需周期刺激保持画面变化
        now = time.time()
        if now - last_stim >= stim_interval:
            try:
                if stim_mode == "gesture":
                    if now - burst_last >= 1.0:
                        burst_last = now
                        if int(now) % 2 == 0:
                            _scroll(1700, 800)
                        else:
                            _scroll(800, 1700)
                elif stim_mode == "burst":
                    # 每 3.5s 一次长滑动动画（~1.2s），统计动画期间瞬时帧率
                    if now - burst_last >= 3.5:
                        burst_last = now
                        burst_active = now + 1.5
                        burst_frames = 0
                        _scroll(1700, 700, steps=8, step_delay=0.1)
                else:
                    ch.stimulate()
            except Exception:
                pass
            last_stim = now
        pkt = ch.read_packet(timeout=0.3)
        if pkt:
            if now < burst_active:
                burst_frames += 1
        if burst_active and now >= burst_active:
            burst_fps = burst_frames / 1.2
            print(f"[bench] 滑动动画瞬时帧率: {burst_fps:.1f} FPS ({burst_frames} 帧/1.2s)")
            burst_active = 0.0
        if pkt is None:
            print("[bench] 流已结束")
            break
        if pkt:
            total_packets += 1
            total_bytes += len(pkt)
            sizes.append(len(pkt))
            if first_frame_at is None:
                first_frame_at = time.time() - t0
            # 尝试解码（统计有效帧）
            try:
                merged = merger.merge(pkt, 0)
                if merged is not None:
                    frame = decoder.decode_packet(merged, 0)
                    if frame is not None:
                        decoded_frames += 1
                        fps_window.append(time.time())
            except Exception:
                pass
        now = time.time()
        if now - last_report >= 2:
            # 计算当前 FPS（最近 2s 窗口）
            while fps_window and fps_window[0] < now - 2:
                fps_window.pop(0)
            cur_fps = len(fps_window) / max(now - last_report, 0.001)
            print(
                f"[bench] t={now-t0:5.1f}s  包={total_packets:5d}  解码帧={decoded_frames:5d}  吞吐={total_bytes/1024/1024:6.1f}MB"
                f"  当前FPS≈{cur_fps:5.1f}"
            )
            last_report = now

    ch.stop()
    elapsed = time.time() - t0 - t_start
    real_fps = decoded_frames / max(elapsed, 0.001)
    avg_size = (sum(sizes) / len(sizes)) / 1024 if sizes else 0
    print("\n[bench] ===== 结果 =====")
    print(f"[bench] 启动耗时:      {t_start:.2f}s")
    print(f"[bench] 首帧到达:      {first_frame_at:.2f}s (启动后)")
    print(f"[bench] 采集时长:      {elapsed:.1f}s")
    print(f"[bench] 数据包数:      {total_packets}")
    print(f"[bench] 解码帧数:      {decoded_frames}")
    print(f"[bench] 实际帧率:      {real_fps:.1f} FPS")
    print(f"[bench] 平均包大小:    {avg_size:.1f} KB")
    print(f"[bench] 总吞吐:        {total_bytes/1024/1024:.1f} MB")
    print(f"[bench] 平均码率:      {total_bytes*8/elapsed/1e6:.1f} Mbps")
    return 0


if __name__ == "__main__":
    sys.exit(main())

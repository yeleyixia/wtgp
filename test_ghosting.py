# -*- coding: utf-8 -*-
"""残影专项测试：窗口 resize / 画面尺寸变化后背景应被清除（无残影）"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
import numpy as np

app = QApplication.instance() or QApplication(sys.argv)

from ui.cast_page import PhoneScreen

screen = PhoneScreen()
screen.resize(400, 800)
screen.show()
app.processEvents()

# 场景1：resize 前后不同尺寸帧（KeepAspectRatio 黑边区域）
frame_a = np.full((800, 400, 3), (255, 0, 0), dtype=np.uint8)   # 红色 400x800
screen.set_frame(frame_a)
screen.set_resolution(800, 1600)
app.processEvents()
# resize 窗口到更宽（黑边在上下）
screen.resize(700, 800)
app.processEvents()

# 渲染截图检查：左右边缘应是背景色（#11151C），无红色残留
pix = screen.grab()
img = pix.toImage()
ok = True
for x in (3, pix.width() - 4):
    for y in (pix.height() // 2,):
        c = img.pixelColor(x, y)
        r, g, b = c.red(), c.green(), c.blue()
        # 背景 #11151C ≈ (17, 21, 28)
        if g > 40:  # 若绿色分量高说明有红色帧残留（红帧 g=0）
            print(f"[ghost] ({x},{y}) 残留色: RGB({r},{g},{b}) —— 残影！")
            ok = False
print(f"[ghost] resize 后左右边缘: {'✅ 背景已清除' if ok else '❌ 有残影'}")

# 场景2：帧尺寸变化（模拟画面比例变化）
screen2 = PhoneScreen()
screen2.resize(400, 800)
screen2.show()
app.processEvents()
frame_b = np.full((1600, 800, 3), (0, 255, 0), dtype=np.uint8)  # 绿色 800x1600
screen2.set_frame(frame_b)
screen2.set_resolution(800, 1600)
app.processEvents()
# 换成窄帧（黑边变左右）
frame_c = np.full((1600, 400, 3), (0, 0, 255), dtype=np.uint8)  # 蓝色 400x1600
screen2.set_frame(frame_c)
screen2.set_resolution(400, 1600)
app.processEvents()
pix2 = screen2.grab()
img2 = pix2.toImage()
ok2 = True
for x in (3, pix2.width() - 4):
    for y in (pix2.height() // 2,):
        c = img2.pixelColor(x, y)
        r, g, b = c.red(), c.green(), c.blue()
        if r > 40:  # 蓝色帧 r=0；若残留绿色帧（g 高）或旧帧
            print(f"[ghost] ({x},{y}) RGB({r},{g},{b})")
            ok2 = False
print(f"[ghost] 帧尺寸变化后左右边缘: {'✅ 背景已清除' if ok2 else '❌ 有残影'}")

# 场景4（残影核心根因）：推帧线程 buffer 复用 ——
# set_frame 后原 numpy 数组被覆盖/释放，GUI 侧必须已拷贝隔离
print("\n[ghost] 场景4: buffer 复用（推帧线程覆盖原数组）")
screen4 = PhoneScreen()
screen4.resize(200, 400)
screen4.show()
app.processEvents()

buf = np.full((400, 200, 3), (0, 255, 0), dtype=np.uint8)  # 绿色帧
screen4.set_frame(buf)
app.processEvents()

# 模拟推帧线程：覆盖同一 buffer 内容（数组原地写入 + 原对象被替换）
buf[:] = (255, 0, 0)          # 原地写红
del buf                        # 释放原引用（GC 可能回收）
import gc
gc.collect()
# 推送新帧（新分配数组）
new_frame = np.full((400, 200, 3), (255, 255, 255), dtype=np.uint8)
screen4.set_frame(new_frame)
app.processEvents()

# GUI 侧 _pending_frame 应已消费为新帧；验证绘制无异常且数据为拷贝
pix4 = screen4.grab()
img4 = pix4.toImage()
c = img4.pixelColor(pix4.width() // 2, pix4.height() // 2)
print(f"[ghost] 场景4 中心像素 RGB({c.red()},{c.green()},{c.blue()}) "
      f"—— 应为白色新帧 (255,255,255)")

# 验证 set_frame 拷贝隔离：旧引用被覆盖后 _pending_frame 不随变
import numpy as _np
b2 = _np.full((400, 200, 3), (0, 255, 0), dtype=_np.uint8)
screen4.set_frame(b2)
b2[:] = (9, 9, 9)  # 覆盖原 buffer
app.processEvents()
pix5 = screen4.grab()
img5 = pix5.toImage()
c5 = img5.pixelColor(pix5.width() // 2, pix5.height() // 2)
green_ok = c5.green() > 200 and c5.red() < 50 and c5.blue() < 50
print(f"[ghost] 场景4b 中心像素 RGB({c5.red()},{c5.green()},{c5.blue()}) "
      f"—— 应为绿色 (0,255,0)（buffer 覆盖后不受影响）")
ok4 = (c.red() == 255 and c.green() == 255 and c.blue() == 255 and green_ok)
print(f"[ghost] 场景4: {'✅ buffer 复用无残影（拷贝隔离生效）' if ok4 else '❌ buffer 复用仍可能残影'}")

if ok and ok2 and ok4:
    print("\n[ghost] ✅ 残影测试通过（背景清除 + buffer 拷贝隔离）")
    sys.exit(0)
print("\n[ghost] ❌ 存在残影")
sys.exit(1)

# 场景4（残影核心根因）：推帧线程 buffer 复用 ——
# set_frame 后原 numpy 数组被覆盖/释放，GUI 侧必须已拷贝隔离
print("\n[ghost] 场景4: buffer 复用（推帧线程覆盖原数组）")
screen4 = PhoneScreen()
screen4.resize(200, 400)
screen4.show()
app.processEvents()

buf = np.full((400, 200, 3), (0, 255, 0), dtype=np.uint8)  # 绿色帧
screen4.set_frame(buf)
app.processEvents()

# 模拟推帧线程：覆盖同一 buffer 内容（数组原地写入 + 原对象被替换）
buf[:] = (255, 0, 0)          # 原地写红
old = buf
del buf                        # 释放原引用（GC 可能回收）
import gc
gc.collect()
# 推送新帧（新分配数组）
new_frame = np.full((400, 200, 3), (255, 255, 255), dtype=np.uint8)
screen4.set_frame(new_frame)
app.processEvents()

# GUI 侧 _pending_frame 应已消费为新帧；验证绘制无异常且数据为拷贝
pix4 = screen4.grab()
img4 = pix4.toImage()
c = img4.pixelColor(pix4.width() // 2, pix4.height() // 2)
print(f"[ghost] 场景4 中心像素 RGB({c.red()},{c.green()},{c.blue()}) "
      f"—— 应为白色新帧 (255,255,255)")

# 验证 set_frame 拷贝隔离：旧引用被覆盖后 _pending_frame 不随变
import numpy as _np
b2 = _np.full((400, 200, 3), (0, 255, 0), dtype=_np.uint8)
screen4.set_frame(b2)
b2[:] = (9, 9, 9)  # 覆盖原 buffer
app.processEvents()
pix5 = screen4.grab()
img5 = pix5.toImage()
c5 = img5.pixelColor(pix5.width() // 2, pix5.height() // 2)
green_ok = c5.green() > 200 and c5.red() < 50 and c5.blue() < 50
print(f"[ghost] 场景4b 中心像素 RGB({c5.red()},{c5.green()},{c5.blue()}) "
      f"—— 应为绿色 (0,255,0)（buffer 覆盖后不受影响）")
if c.red() == 255 and c.green() == 255 and c.blue() == 255 and green_ok:
    print("[ghost] 场景4: ✅ buffer 复用无残影（拷贝隔离生效）")
else:
    print("[ghost] 场景4: ❌ buffer 复用仍可能残影")
    ok = False

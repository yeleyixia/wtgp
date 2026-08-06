# -*- coding: utf-8 -*-
"""ControlQueue 批量行为隔离测试"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.scrcpy_control import ControlQueue, ControlMessage, POINTER_ID_GENERIC_FINGER

sent = []
cq = ControlQueue(send_fn=lambda cmd: sent.append(cmd))
cq.start()
for i in range(10):
    action = 0 if i == 0 else (2 if i == 9 else 1)
    msg = ControlMessage.create_touch(action=action, pointer_id=POINTER_ID_GENERIC_FINGER,
                                      x=564, y=1700 - i * 100, screen_w=1128, screen_h=2444)
    ok = cq.push(msg)
    print(f"push#{i} action={action} ok={ok}")
    time.sleep(0.02)
time.sleep(1.0)
cq.stop()
print(f"\n[probe] send_fn 调用 {len(sent)} 次:")
for s in sent:
    print(f"  {s}")

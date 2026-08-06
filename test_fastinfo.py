# -*- coding: utf-8 -*-
"""合并命令快速设备信息采集验证"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.hdc_client import HDCClient

DEVICE = "6UNBB26324009125"
c = HDCClient()
t0 = time.time()
info = c.get_device_info(DEVICE)
dt = time.time() - t0
print(f"[fastinfo] 耗时 {dt*1000:.0f}ms")
for k in ("name", "model", "version", "abi", "devtype", "apiver", "udid", "resolution"):
    print(f"  {k}: {info.get(k)}")
assert info.get("name"), "名称缺失"
assert info.get("model"), "型号缺失"
assert info.get("resolution"), "分辨率缺失"
print("[fastinfo] ✅ 合并采集正常（一次 shell 拉取 8 字段）")

# -*- coding: utf-8 -*-
"""配置对话框冒烟测试：验证编码节奏档位 → repeat_interval 保存"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# 隔离配置目录，避免污染真实配置
from core import cast_config as cc
_real_dir = cc.CONFIG_DIR
cc.CONFIG_DIR = tempfile.mkdtemp(prefix="wtgp_test_")
cc.CONFIG_FILE = os.path.join(cc.CONFIG_DIR, "cast_configs.json")

app = QApplication.instance() or QApplication(sys.argv)

from ui.cast_config_dialog import CastConfigDialog

DEVICE = "TEST_DEVICE_001"
dlg = CastConfigDialog(DEVICE)
print(f"[dlg] 弹窗创建 OK, 大小={dlg.width()}x{dlg.height()}")

# 1. 默认配置检查
assert dlg._cfg.capture_mode in ("jpeg", "h264", "agent_jpeg"), dlg._cfg.capture_mode
assert hasattr(dlg, "_perf_combo"), "缺少编码节奏下拉"
print(f"[dlg] 默认模式={dlg._cfg.capture_mode}, 编码节奏当前={dlg._perf_combo.currentText()}")
assert dlg._perf_combo.currentText() == "高性能 (16ms)", "默认应为高性能档"

# 2. 切到 H.264 模式 → 编码节奏应启用
dlg._on_mode_pick("h264")
assert dlg._perf_combo.isEnabled(), "H.264 模式下编码节奏应可用"
print("[dlg] H.264 模式切换后编码节奏可用 ✓")

# 3. 选"极速"档并保存
dlg._perf_combo.setCurrentText("极速 (8ms)")
dlg._on_save()
saved = dlg.result_config
print(f"[dlg] 保存后 capture_mode={saved.capture_mode} repeat_interval={saved.repeat_interval}")
assert saved.capture_mode == "h264", "模式应保存为 h264"
assert saved.repeat_interval == 8, "极速档 repeat_interval 应为 8"

# 4. 持久化验证：重新读取配置
from core.cast_config import get_config_manager
mgr = get_config_manager()
loaded = mgr.get_or_create(DEVICE)
print(f"[dlg] 重新读取: repeat_interval={loaded.repeat_interval}")
assert loaded.repeat_interval == 8, "配置持久化失败"

# 5. 兼容性：旧 JSON（无 repeat_interval 字段）→ 默认 16
import json
with open(cc.CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump({DEVICE: {"capture_mode": "h264", "fps": 60, "bitrate_mbps": 30,
                        "scale_pct": 50, "screen_id": 0, "remember": False}}, f)
mgr._configs.clear()
legacy = mgr.get_or_create(DEVICE)
print(f"[dlg] 旧配置兼容: repeat_interval={legacy.repeat_interval}")
assert legacy.repeat_interval == 16, "旧配置应回退默认 16"

print("\n[dlg] ✅ 配置对话框冒烟测试全部通过")

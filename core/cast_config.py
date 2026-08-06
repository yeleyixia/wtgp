"""
投屏配置管理模块
- 按设备ID保存和加载投屏配置
- 支持投屏模式(JPEG/H.264)、帧率、码率、缩放、屏幕ID
- 支持"记住此配置"开关
"""
import json
import os
import sys
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict


def _get_config_dir() -> str:
    """获取配置存储目录，优先在 exe 同级，否则在用户目录"""
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.dirname(sys.executable))
    candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # Windows 用户目录回退
    candidates.append(os.path.join(os.path.expanduser("~"), ".weitougeping"))
    for p in candidates:
        try:
            if p and os.path.isdir(p):
                test = os.path.join(p, "cast_configs")
                os.makedirs(test, exist_ok=True)
                # 写测试
                probe = os.path.join(test, ".write_probe")
                with open(probe, "w") as f:
                    f.write("ok")
                os.remove(probe)
                return p
        except Exception:
            continue
    return candidates[-1]


CONFIG_DIR = _get_config_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, "cast_configs.json")

# 默认值常量
# H.264 流模式属于后续规划功能，当前设备端没有对应的编码服务，
# 默认使用 JPEG 截图模式以保证"开始投屏"立即可用
DEFAULT_CAPTURE_MODE = "jpeg"      # "jpeg" 或 "h264"
DEFAULT_FPS = 60                    # 帧率（过高会导致设备/解码压力过大）
DEFAULT_BITRATE_MBPS = 30           # 码率 MB/s (仅 H.264 生效)
DEFAULT_SCALE_PCT = 50              # 缩放比例 %
DEFAULT_SCREEN_ID = 0               # 屏幕 ID
DEFAULT_REPEAT_INTERVAL = 16        # H.264 repeatInterval ms（16=高性能60FPS级，33=HoKit同款30FPS级）
DEFAULT_REMEMBER = False            # 是否记住此配置


@dataclass
class CastConfig:
    """单设备投屏配置"""
    capture_mode: str = DEFAULT_CAPTURE_MODE   # jpeg | h264
    fps: int = DEFAULT_FPS                      # 帧率上限
    bitrate_mbps: int = DEFAULT_BITRATE_MBPS    # 码率 (MB/s，H.264 才用)
    scale_pct: int = DEFAULT_SCALE_PCT          # 缩放 %
    screen_id: int = DEFAULT_SCREEN_ID          # 屏幕 ID
    repeat_interval: int = DEFAULT_REPEAT_INTERVAL  # H.264 编码重复间隔 ms（16=高性能）
    remember: bool = DEFAULT_REMEMBER           # 是否记住配置

    # ---- 便捷属性 ----
    @property
    def is_h264(self) -> bool:
        return self.capture_mode == "h264"

    @property
    def cast_engine_mode(self) -> str:
        """返回 HDCCastService 期望的 mode 参数"""
        if self.capture_mode == "h264":
            return "stream"
        if self.capture_mode == "agent_jpeg":
            return "agent_jpeg"
        return "screenshot"


class CastConfigManager:
    """配置管理器 - 单例使用"""

    def __init__(self):
        self._configs: Dict[str, CastConfig] = {}
        self._load_all()

    # ---------- 持久化 ----------
    def _load_all(self):
        """从磁盘加载所有配置"""
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for did, obj in raw.items():
                    if isinstance(obj, dict):
                        cfg = CastConfig(
                            capture_mode=str(obj.get("capture_mode", DEFAULT_CAPTURE_MODE)),
                            fps=int(obj.get("fps", DEFAULT_FPS)),
                            bitrate_mbps=int(obj.get("bitrate_mbps", DEFAULT_BITRATE_MBPS)),
                            scale_pct=int(obj.get("scale_pct", DEFAULT_SCALE_PCT)),
                            screen_id=int(obj.get("screen_id", DEFAULT_SCREEN_ID)),
                            repeat_interval=int(obj.get("repeat_interval", DEFAULT_REPEAT_INTERVAL)),
                            remember=bool(obj.get("remember", DEFAULT_REMEMBER)),
                        )
                        self._configs[did] = cfg
        except Exception:
            # 配置损坏时静默忽略，不影响使用
            pass

    def _save_all(self):
        """保存所有配置到磁盘（只保存 remember=True 的）"""
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            data = {}
            for did, cfg in self._configs.items():
                if cfg.remember:
                    data[did] = asdict(cfg)
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            pass

    # ---------- 对外 API ----------
    def get(self, device_id: str) -> CastConfig:
        """获取某个设备的配置（记忆过就返回记忆的，否则返回默认值）"""
        if device_id in self._configs:
            return self._configs[device_id]
        return CastConfig()  # 返回默认值，不自动加入字典

    def get_or_create(self, device_id: str) -> CastConfig:
        """获取设备配置，如不存在则创建默认配置并加入管理"""
        if device_id not in self._configs:
            self._configs[device_id] = CastConfig()
        return self._configs[device_id]

    def set(self, device_id: str, config: CastConfig, save: bool = True):
        """更新某个设备的配置。save=True 立即写入磁盘"""
        self._configs[device_id] = config
        if save:
            self._save_all()

    def clear(self, device_id: str):
        """删除某设备的记忆配置"""
        if device_id in self._configs:
            del self._configs[device_id]
            self._save_all()

    def list_remembered(self) -> Dict[str, CastConfig]:
        """返回所有标记 remember=True 的配置"""
        return {did: cfg for did, cfg in self._configs.items() if cfg.remember}


# 全局单例（进程内共享）
_config_manager: Optional[CastConfigManager] = None


def get_config_manager() -> CastConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = CastConfigManager()
    return _config_manager

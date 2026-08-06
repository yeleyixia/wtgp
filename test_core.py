import sys
sys.path.insert(0, '.')

print('=== 测试模块导入 ===')
modules = [
    ('core.hdc_client', ['HDCClient', 'DeviceMonitor']),
    ('core.hdc_cast_service', ['HDCCastService']),
    ('core.cast_engine', ['CastEngine', 'MultiDeviceManager', 'MockCastEngine']),
    ('core.input_manager', ['InputManager', 'ClipboardSync']),
    ('core.audio_manager', ['AudioManager', 'AudioStreamServer']),
    ('core.web_cast_server', ['WebCastServer', 'PermissionManager']),
    ('ui.styles', ['APP_QSS']),
    ('ui.main_window', ['MainWindow', 'Sidebar', 'WebCastPage', 'AudioSetupPage']),
    ('ui.device_page', ['DevicePage', 'DeviceCard']),
    ('ui.cast_page', ['CastPage', 'PhoneScreen', 'CastToolbar']),
]

for module_path, classes in modules:
    try:
        mod = __import__(module_path, fromlist=classes)
        print(f'  OK {module_path}')
    except Exception as e:
        print(f'  FAIL {module_path}: {e}')

print()
print('=== 测试核心类 ===')

from core.cast_engine import MultiDeviceManager
mgr = MultiDeviceManager()
print(f'  OK MultiDeviceManager: MAX={mgr.MAX_PARALLEL_DEVICES}')

from core.web_cast_server import PermissionManager
perm_mgr = PermissionManager()
token_info = perm_mgr.create_share_token('test_device', 'standard')
token_short = token_info['token'][:8]
print(f'  OK PermissionManager: token={token_short}...')

valid = perm_mgr.validate_token(token_info['token'])
print(f'  OK validate_token: valid={valid is not None}')

from core.audio_manager import AudioManager
audio = AudioManager()
audio.set_volume(80)
print(f'  OK AudioManager: volume={audio.get_volume()}')

from core.input_manager import InputManager
key_count = len(InputManager.KEY_MAP)
print(f'  OK InputManager: KEY_MAP has {key_count} keys')

print()
print('=== 测试 HDC 连接 ===')
from core.hdc_cast_service import HDCCastService
hdc_cast = HDCCastService()
devices = hdc_cast.run_hdc(["list", "targets"])
print(f'  HDC list result: code={devices[0]}, stdout="{devices[1][:100]}"')

import os
hdc_path = hdc_cast.hdc_path
print(f'  HDC path: {hdc_path}')
print(f'  HDC exists: {os.path.exists(hdc_path)}')

print()
print('=== 所有测试完成 ===')

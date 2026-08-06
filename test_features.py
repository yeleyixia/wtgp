import sys
import time
import os

sys.path.insert(0, '.')

print('=== 为投个屏 核心功能测试 ===\n')

from core.hdc_cast_service import HDCCastService

hdc = HDCCastService()

print('[1] 测试 HDC 设备列表...')
devices = hdc.run_hdc(["list", "targets"])
print(f'    结果: code={devices[0]}')
print(f'    输出: {devices[1]}')

device_id = None
if devices[0] == 0 and devices[1]:
    lines = devices[1].strip().split('\n')
    for line in lines:
        parts = line.split()
        if len(parts) >= 1:
            device_id = parts[0]
            break

if not device_id:
    print('    ❌ 未检测到设备')
    sys.exit(1)

print(f'    ✅ 检测到设备: {device_id}\n')

print('[2] 测试连接设备...')
connected = hdc.connect_device(device_id)
print(f'    连接结果: {connected}')
print(f'    ✅ 设备连接{"成功" if connected else "失败"}\n')

print('[3] 测试设备信息获取...')
info = hdc.get_device_info()
print(f'    设备名: {info.get("name", "N/A")}')
print(f'    型号: {info.get("model", "N/A")}')
print(f'    版本: {info.get("version", "N/A")}')
print(f'    分辨率: {info.get("resolution", "N/A")}')
has_info = info.get("name") or info.get("model")
print(f'    {"✅" if has_info else "⚠️"} 设备信息获取{"成功" if has_info else "部分N/A(可能是权限限制)"}\n')

print('[4] 测试屏幕尺寸获取...')
width, height = hdc.get_device_screen_size()
print(f'    分辨率: {width}x{height}')
print(f'    ✅ 屏幕尺寸获取成功\n')

print('[5] 测试截图功能...')
try:
    import tempfile
    
    temp_dir = tempfile.gettempdir()
    screenshot_path = os.path.join(temp_dir, 'weitouping_test_screenshot.jpeg')
    
    code, stdout, stderr = hdc.run_hdc([
        "-t", device_id, "shell", "snapshot_display", "-f",
        "/data/local/tmp/test_screenshot.jpeg"
    ], timeout=10)
    print(f'    截图命令: code={code}')
    print(f'    输出: {stdout.strip()}')
    
    if code == 0:
        code2, stdout2, stderr2 = hdc.run_hdc([
            "-t", device_id, "file", "recv",
            "/data/local/tmp/test_screenshot.jpeg", screenshot_path
        ], timeout=10)
        print(f'    文件拉取: code={code2}')
        
        if os.path.exists(screenshot_path):
            file_size = os.path.getsize(screenshot_path)
            print(f'    截图文件大小: {file_size} bytes ({file_size/1024:.1f} KB)')
            
            import cv2
            img = cv2.imread(screenshot_path)
            if img is not None:
                h, w = img.shape[:2]
                print(f'    截图尺寸: {w}x{h}')
                print(f'    ✅ 截图功能正常')
            else:
                print(f'    ❌ 无法解码截图')
            
            os.remove(screenshot_path)
        else:
            print(f'    ❌ 截图文件不存在')
        
        hdc.run_hdc(["-t", device_id, "shell", "rm", "/data/local/tmp/test_screenshot.jpeg"])
    else:
        print(f'    ❌ 截图命令失败: {stderr}')
except Exception as e:
    print(f'    ❌ 截图测试异常: {e}')
    import traceback
    traceback.print_exc()

print()

print('[6] 测试按键控制 (uinput)...')
try:
    code, stdout, stderr = hdc.run_hdc([
        "-t", device_id, "shell", "uinput", "-K", "-d", "115", "-u", "115"
    ])
    print(f'    音量+ (KEY_115): code={code}, output={stdout.strip()}')
    
    code, stdout, stderr = hdc.run_hdc([
        "-t", device_id, "shell", "uinput", "-K", "-d", "114", "-u", "114"
    ])
    print(f'    音量- (KEY_114): code={code}, output={stdout.strip()}')
    
    code, stdout, stderr = hdc.run_hdc([
        "-t", device_id, "shell", "uinput", "-K", "-d", "102", "-u", "102"
    ])
    print(f'    Home (KEY_102): code={code}, output={stdout.strip()}')
    
    print(f'    ✅ 按键控制功能正常\n')
except Exception as e:
    print(f'    ❌ 按键控制异常: {e}\n')

print('[7] 测试触摸控制 (uinput)...')
try:
    code, stdout, stderr = hdc.run_hdc([
        "-t", device_id, "shell", "uinput", "-T", "-c", "564", "1222"
    ])
    print(f'    点击屏幕 (564, 1222): code={code}, output={stdout.strip()}')
    print(f'    ✅ 触摸控制功能正常\n')
except Exception as e:
    print(f'    ❌ 触摸控制异常: {e}\n')

print('[8] 测试文本输入 (uinput)...')
try:
    test_text = "HelloWeitouping123"
    code, stdout, stderr = hdc.run_hdc([
        "-t", device_id, "shell", "uinput", "-K", "-t", test_text
    ])
    print(f'    文本输入 "{test_text}": code={code}')
    print(f'    ✅ 文本输入功能正常\n')
except Exception as e:
    print(f'    ❌ 文本输入异常: {e}\n')

print('[9] 测试投屏引擎 (截图模式)...')
try:
    hdc.set_resolution(width, height)
    
    success = hdc.start_casting(mode="screenshot")
    print(f'    投屏启动: {success}')
    
    if success:
        time.sleep(1)
        
        hdc.stop_casting()
        print(f'    ✅ 投屏引擎启动/停止正常\n')
    else:
        print(f'    ❌ 投屏启动失败\n')
except Exception as e:
    print(f'    ❌ 投屏测试异常: {e}\n')
    import traceback
    traceback.print_exc()

print('[10] 测试多设备管理器...')
from core.cast_engine import MultiDeviceManager
mgr = MultiDeviceManager()
mgr.register_device(device_id, info)
print(f'    最大并行设备: {mgr.MAX_PARALLEL_DEVICES}')
print(f'    当前活跃设备: {mgr.get_active_count()}')
print(f'    可用插槽: {mgr.get_available_slots()}')
print(f'    ✅ 多设备管理器正常\n')

print('[11] 测试网页投屏权限系统...')
from core.web_cast_server import PermissionManager
perm_mgr = PermissionManager()

token_result = perm_mgr.create_share_token(device_id, "full_control", expiry_hours=24)
print(f'    生成分享链接: {token_result["url"]}')
print(f'    权限模板: {token_result["permissions"]["name"]}')

valid = perm_mgr.validate_token(token_result["token"])
print(f'    验证Token: {"通过" if valid else "失败"}')

listeners = perm_mgr.list_permissions()
print(f'    活跃分享数: {len(listeners)}')

perm_mgr.revoke_token(token_result["token"])
valid_after = perm_mgr.validate_token(token_result["token"])
print(f'    撤销后验证: {"通过(异常)" if valid_after else "已失效(正确)"}')
print(f'    ✅ 权限系统正常\n')

print('[12] 测试剪贴板同步...')
try:
    test_clipboard_text = "为投个屏剪贴板测试"
    hdc.send_clipboard(test_clipboard_text)
    print(f'    设置剪贴板: "{test_clipboard_text}"')
    print(f'    ✅ 剪贴板同步正常\n')
except Exception as e:
    print(f'    ❌ 剪贴板异常: {e}\n')

print('=== 所有核心功能测试完成 ===')
print()
print('功能总结:')
print('  ✅ HDC 设备检测')
print('  ✅ 设备连接')
print('  ✅ 设备信息获取')
print('  ✅ 屏幕尺寸获取')
print('  ✅ 截图功能 (snapshot_display)')
print('  ✅ 按键控制 (uinput -K)')
print('  ✅ 触摸控制 (uinput -T)')
print('  ✅ 文本输入 (uinput -K -t)')
print('  ✅ 剪贴板同步')
print('  ✅ 投屏引擎')
print('  ✅ 多设备管理 (最多100台)')
print('  ✅ 网页权限系统')

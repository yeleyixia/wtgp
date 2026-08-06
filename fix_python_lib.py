import urllib.request
import os
import tarfile
import shutil
import time

mirrors = [
    'https://registry.npmmirror.com/-/binary/python/3.10.11/Python-3.10.11.tgz',
    'https://www.python.org/ftp/python/3.10.11/Python-3.10.11.tgz',
    'https://mirrors.aliyun.com/python-release/source/Python-3.10.11.tgz',
]

tgz_path = 'Python-3.10.11-src.tgz'  # 用新文件名避免旧文件锁

# 旧文件锁住了就不管了，直接用新文件名

# Try each mirror
downloaded = False
for url in mirrors:
    try:
        print(f'Trying: {url}')
        urllib.request.urlretrieve(url, tgz_path)
        size = os.path.getsize(tgz_path)
        print(f'  Downloaded: {size / 1024 / 1024:.1f} MB')
        if size > 20000000:  # > 20 MB
            # Verify it's a valid tarball
            with tarfile.open(tgz_path, 'r:gz') as tar:
                members = [m for m in tar.getmembers() if m.name.startswith('Python-3.10.11/Lib/') and m.name.endswith('.py')]
                print(f'  Valid tarball with {len(members)} .py files')
                if len(members) > 100:
                    downloaded = True
                    break
                else:
                    print(f'  Not enough .py files, trying next mirror')
                    os.remove(tgz_path)
        else:
            print(f'  File too small, trying next mirror')
            os.remove(tgz_path)
    except Exception as e:
        print(f'  Failed: {e}')
        if os.path.exists(tgz_path):
            os.remove(tgz_path)

if not downloaded:
    print('ERROR: All mirrors failed!')
    exit(1)

# Extract only the Lib directory
print('\nExtracting Lib directory...')
with tarfile.open(tgz_path, 'r:gz') as tar:
    members = [m for m in tar.getmembers() if m.name.startswith('Python-3.10.11/Lib/')]
    tar.extractall(members=members)

# Copy Lib to build_env\Scripts\lib
src_lib = 'Python-3.10.11/Lib'
dst_lib = 'build_env/Scripts/lib'

print(f'Copying {src_lib} -> {dst_lib}...')
if os.path.exists(dst_lib):
    shutil.rmtree(dst_lib)
shutil.copytree(src_lib, dst_lib)

# Verify
site_py = os.path.join(dst_lib, 'site.py')
print(f'site.py exists: {os.path.exists(site_py)}')
py_count = sum(1 for f in os.listdir(dst_lib) if f.endswith('.py'))
print(f'.py files in root of lib: {py_count}')
print('Done!')

# Clean up
shutil.rmtree('Python-3.10.11', ignore_errors=True)
try:
    os.remove(tgz_path)
except:
    pass
print('Cleaned up temp files.')
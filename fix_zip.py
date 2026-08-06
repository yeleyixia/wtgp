"""
将 Python 标准库 .py 源文件添加到 python310.zip 中，
使 Nuitka 能够读取源码进行编译。
"""
import zipfile
import os
import shutil

zip_path = r'D:\为投个屏\build_env\Scripts\python310.zip'
lib_dir = r'D:\为投个屏\build_env\Scripts\lib'

print(f'python310.zip: {zip_path}')
print(f'Lib source dir: {lib_dir}')

# 1. 读取现有 zip 中的文件列表
with zipfile.ZipFile(zip_path, 'r') as z:
    existing_names = set(z.namelist())
    py_files_in_zip = [n for n in existing_names if n.endswith('.py')]
    pyc_files_in_zip = [n for n in existing_names if n.endswith('.pyc')]
    print(f'现有 .py 文件: {len(py_files_in_zip)}')
    print(f'现有 .pyc 文件: {len(pyc_files_in_zip)}')

# 2. 收集 lib 目录中所有 .py 文件
py_files_to_add = []
for root, dirs, files in os.walk(lib_dir):
    for f in files:
        if f.endswith('.py'):
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, lib_dir).replace('\\', '/')
            # 只添加 zip 中不存在的 .py 文件
            if rel_path not in existing_names:
                py_files_to_add.append((full_path, rel_path))

print(f'需要添加的 .py 文件: {len(py_files_to_add)}')

# 3. 将 .py 文件追加到 zip 中
if py_files_to_add:
    # 先复制 zip 到临时文件
    temp_zip = zip_path + '.tmp'
    shutil.copy2(zip_path, temp_zip)

    with zipfile.ZipFile(temp_zip, 'a') as z:
        for full_path, rel_path in py_files_to_add:
            z.write(full_path, rel_path)

    # 替换原 zip
    os.remove(zip_path)
    os.rename(temp_zip, zip_path)
    print(f'已添加 {len(py_files_to_add)} 个 .py 文件到 python310.zip')
else:
    print('没有需要添加的文件')

# 4. 验证
with zipfile.ZipFile(zip_path, 'r') as z:
    names = z.namelist()
    py_count = sum(1 for n in names if n.endswith('.py'))
    pyc_count = sum(1 for n in names if n.endswith('.pyc'))
    site_py = 'site.py' in names
    print(f'\n验证结果:')
    print(f'  .py 文件: {py_count}')
    print(f'  .pyc 文件: {pyc_count}')
    print(f'  site.py 存在: {site_py}')

print('\n完成！')
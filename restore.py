import os
src = r'D:\为投个屏\build_env\Scripts\python310.zip.bak'
dst = r'D:\为投个屏\build_env\Scripts\python310.zip'
if os.path.exists(src):
    os.rename(src, dst)
    print('Restored OK')
elif os.path.exists(dst):
    print('Already exists')
else:
    print('FAILED - neither bak nor zip exists')
"""
设置 PYTHONPATH 环境变量让 Nuitka 能找到 .py 源码，然后执行 build.py
"""
import os
import sys
import subprocess

project_dir = os.path.dirname(os.path.abspath(__file__))
lib_dir = os.path.join(project_dir, "build_env", "Scripts", "lib")

# 设置 PYTHONPATH，让 lib 目录（含 .py 源码）排在 python310.zip 之前
env = os.environ.copy()
existing = env.get("PYTHONPATH", "")
if existing:
    env["PYTHONPATH"] = lib_dir + os.pathsep + existing
else:
    env["PYTHONPATH"] = lib_dir

print(f"PYTHONPATH = {env['PYTHONPATH']}")
print("Starting build...")

# 用设置了 PYTHONPATH 的环境运行 build.py
result = subprocess.run(
    [sys.executable, "build.py"],
    cwd=project_dir,
    env=env,
)
sys.exit(result.returncode)
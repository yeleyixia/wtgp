# -*- coding: utf-8 -*-
"""验证 hdc shell 持久化进程 stdin 写入是否执行设备命令"""
import subprocess, time, os, sys

HDC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "tools", "hdc", "hdc.exe")
DEVICE = "6UNBB26324009125"

p = subprocess.Popen([HDC, "-t", DEVICE, "shell"], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
time.sleep(1.5)
print(f"[probe] 进程存活: {p.poll() is None}")
# 写一条带输出的命令：echo 标记
p.stdin.write(b"echo STDIN_WORKS_12345\n")
p.stdin.flush()
time.sleep(1.0)
# 读 stdout
import threading
out = []
def drain(pipe, tag):
    while True:
        data = pipe.read(4096)
        if not data:
            break
        out.append((tag, data))
threading.Thread(target=drain, args=(p.stdout, "OUT"), daemon=True).start()
threading.Thread(target=drain, args=(p.stderr, "ERR"), daemon=True).start()
time.sleep(1.5)
p.stdin.write(b"echo SECOND_LINE_6789\n")
p.stdin.flush()
time.sleep(1.5)
print(f"[probe] 收集到输出: {len(out)} 段")
for tag, data in out[:8]:
    print(f"  [{tag}] {data.decode('utf-8', 'replace')[:120]!r}")
found = any(b"STDIN_WORKS_12345" in d for _, d in out)
print(f"[probe] stdin 命令执行: {'✅ 有效' if found else '❌ 无效（hdc shell 非交互式）'}")
p.kill()

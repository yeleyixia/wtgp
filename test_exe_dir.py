import sys
import os
print("sys.executable:", sys.executable)
print("sys.frozen:", getattr(sys, 'frozen', False))
print("dirname:", os.path.dirname(sys.executable))
print("hdc path:", os.path.join(os.path.dirname(sys.executable), "resources", "tools", "hdc", "hdc.exe"))
print("hdc exists:", os.path.exists(os.path.join(os.path.dirname(sys.executable), "resources", "tools", "hdc", "hdc.exe")))
input("Press Enter...")

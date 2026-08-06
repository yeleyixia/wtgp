f = open(r'C:\Users\Administrator\AppData\Local\Temp\trae-agent-toolhost\jobs\job-816602b1af7441759777ba2b44bd557e\output.log', 'r', encoding='utf-8', errors='replace')
lines = f.readlines()
f.close()
# Find error lines
for i, l in enumerate(lines):
    ls = l.strip()
    if 'FATAL' in ls or 'error:' in ls.lower() or 'Error:' in ls or 'failed' in ls.lower() and 'Nuitka' not in ls:
        print(f"L{i}: {ls}")
# Also show last 30 lines
print("\n--- Last 30 lines ---")
for l in lines[-30:]:
    print(l.rstrip())
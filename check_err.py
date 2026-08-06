import re
f = open(r'C:\Users\Administrator\AppData\Local\Temp\trae-agent-toolhost\jobs\job-ae04e0a47302462e8a7e2aaf66688e6d\output.log', 'r', encoding='utf-8', errors='replace')
lines = f.readlines()
f.close()
for l in lines:
    if 'FATAL' in l or 'can' in l.lower() and 'open' in l.lower() and 'file' in l.lower():
        print(l.rstrip())
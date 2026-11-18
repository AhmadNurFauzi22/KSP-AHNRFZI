import os
os.chdir(r'D:\xampp\htdocs\lat1')

with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

# Check lines 75-95
for i in range(78, min(95, len(lines))):
    line = lines[i]
    # Show line number and first 60 chars, with visible whitespace
    visible = line[:60].replace(' ', '.').replace('\t', '^T')
    print(f"Line {i+1}: {visible}")
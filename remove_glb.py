import os
os.chdir(r'D:\xampp\htdocs\lat1')

with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

# Remove lines 86-95 (0-indexed: 85-94)
new_lines = lines[:85] + lines[95:]

with open('app/main.py', 'w', encoding='utf-8', errors='ignore') as f:
    f.writelines(new_lines)

print(f"Removed lines 86-95 from main.py")
print(f"Total lines now: {len(new_lines)}")
import os
os.chdir(r'D:\xampp\htdocs\lat1')

with open('app/services/dashboard_service.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

idx = content.find('_member_counts')
print(f"Found _member_counts at position {idx}")
if idx >= 0:
    print(repr(content[idx:idx+500]))
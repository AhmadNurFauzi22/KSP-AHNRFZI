import os
os.chdir(r'D:\xampp\htdocs\lat1')

with open('app/api/v1/users.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Find user-related routes
import re
routes = re.findall(r'@router\.get\(["\']([^"\']+)["\']', content)
print("User routes with /users:")
for r in routes:
    if '/users' in r or '/rbac' in r or '/ai-config' in r:
        print(f"  {r}")

# Also find role definitions
for line in content.split('\n'):
    if 'SystemRole' in line or 'ADMIN' in line or 'role' in line.lower():
        if any(keyword in line.lower() for keyword in ['role', 'systemrole', 'admin']):
            print(f"  Line: {line.strip()[:150]}")
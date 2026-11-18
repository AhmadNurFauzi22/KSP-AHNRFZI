import os
os.chdir(r'D:\xampp\htdocs\lat1')

# Cek struktur file penting
files = [
    'app/api/v1/ai_config.py',
    'app/templates/ai_config.html', 
    'app/main.py',
    'app/core/config.py',
    'app/services/user_query_service.py',
]

print('=== CEK FILE KUNCI ===')
for f in files:
    exists = os.path.exists(f)
    status = 'OK' if exists else 'MISSING'
    print(f'  [{status}] {f}')

# Cek route /ai-config di main.py
print()
print('=== CEK ROUTE /ai-config ===')
with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()
    if '/ai-config' in content:
        print('  Route /ai-config ADA di main.py')
        for line in content.split('\n'):
            if 'ai-config' in line.lower():
                print(f'    {line.strip()[:150]}')
    else:
        print('  Route /ai-config TIDAK DITEMUKAN di main.py')
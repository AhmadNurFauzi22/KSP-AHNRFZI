import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

from app.main import app

print('=== ROUTE DENGAN PREFIX /api/v1 ===')
for route in app.routes:
    path = getattr(route, 'path', '')
    methods = ', '.join(getattr(route, 'methods', []))
    if path and '/api/v1/' in path:
        print(f'  {methods} {path}')

print()

# Cek route ai-config spesifik
for route in app.routes:
    path = getattr(route, 'path', '')
    if path and 'ai-config' in path.lower():
        methods = ', '.join(getattr(route, 'methods', []))
        print(f'  {methods} {path}')
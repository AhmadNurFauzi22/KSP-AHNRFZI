import os
os.chdir(r'D:\xampp\htdocs\lat1')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# Set auth cookie
token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiYWN0aXZlX3JvbGUiOiJBRE1JTl9LT1BFUkFTSSIsInVzZXJuYW1lIjoiYWRtaW5fa29wIiwicm9sZXMiOlsiQURNSU5fS09QRVJBU0kiXSwiZXhwIjoxNzk0NTU3MTk0LCJpYXQiOjE3OTQ1MjgzOTR9.nGcNqPPYSuYcfYJXsU-rl3TZG3aJzLWdyehn-Hb8g1M'

client.cookies['access_token'] = token

print('=== TEST ROUTES WITH AUTH (admin_kop) ===')
print()

# Test route /ai-config
print('Test GET /ai-config (as admin_kop):')
resp = client.get('/ai-config')
print('  Status:', resp.status_code)
if resp.status_code == 200:
    print('  SUCCESS: Halaman terrender!')
    if '/ai-config' in resp.text or 'ai_config' in resp.text.lower():
        print('  Response mengandung referensi ai-config')
else:
    print('  Status:', resp.status_code)

print()

# Test route /rbac-koperasi
print('Test GET /rbac-koperasi (as admin_kop):')
resp = client.get('/rbac-koperasi', follow_redirects=False)
print('  Status:', resp.status_code, 'Location:', resp.headers.get("location", "N/A"))
if resp.status_code == 200:
    print('  SUCCESS: Halaman terrender!')
    if 'rbac-koperasi' in resp.text.lower() or 'rbac_koperasi' in resp.text.lower():
        print('  Response mengandung referensi rbac-koperasi')
elif resp.status_code == 302:
    print('  Redirect ke:', resp.headers.get("location"))

print()

# Test route /rbac-it-pusat
print('Test GET /rbac-it-pusat (as admin_kop):')
resp = client.get('/rbac-it-pusat', follow_redirects=False)
print('  Status:', resp.status_code, 'Location:', resp.headers.get("location", "N/A"))
if resp.status_code == 200:
    print('  SUCCESS: Halaman terrender!')

print()

# Test API endpoint
print('Test GET /api/v1/ai-config/providers (as admin_kop):')
resp = client.get('/api/v1/ai-config/providers')
print('  Status:', resp.status_code)

print()
print('Test GET /api/v1/ai-config/status (as admin_kop):')
resp = client.get('/api/v1/ai-config/status')
print('  Status:', resp.status_code)
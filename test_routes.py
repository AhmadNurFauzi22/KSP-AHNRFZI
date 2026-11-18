import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# Test route /ai-config (tanpa prefix /api/v1)
print('Test GET /ai-config:')
resp = client.get('/ai-config')
print(f'  Status: {resp.status_code}')

# Test route /api/v1/ai-config/providers
print('Test GET /api/v1/ai-config/providers:')
resp = client.get('/api/v1/ai-config/providers')
print(f'  Status: {resp.status_code}')

# Test route /api/v1/ai-config/status
print('Test GET /api/v1/ai-config/status (unauth):')
resp = client.get('/api/v1/ai-config/status')
print(f'  Status: {resp.status_code}')

# Test route /rbac-koperasi (di sidebar)
print('Test GET /rbac-koperasi:')
resp = client.get('/rbac-koperasi', follow_redirects=False)
loc = resp.headers.get("location", "N/A")
print(f'  Status: {resp.status_code}, Location: {loc}')

# Test route /rbac-it-pusat
print('Test GET /rbac-it-pusat:')
resp = client.get('/rbac-it-pusat', follow_redirects=False)
loc = resp.headers.get("location", "N/A")
print(f'  Status: {resp.status_code}, Location: {loc}')
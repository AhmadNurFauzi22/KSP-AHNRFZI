import os
os.chdir(r'D:\xampp\htdocs\lat1')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# First, let's test with a GET request - it will redirect to login since no auth cookie
print('=== TEST ROUTES WITHOUT AUTH (should redirect to /login) ===')
print()

# Test route /ai-config
print('Test GET /ai-config (unauth):')
resp = client.get('/ai-config', follow_redirects=False)
loc = resp.headers.get('location', 'N/A')
print('  Status:', resp.status_code, 'Location:', loc)

# Test route /rbac-koperasi
print('Test GET /rbac-koperasi (unauth):')
resp = client.get('/rbac-koperasi', follow_redirects=False)
loc = resp.headers.get('location', 'N/A')
print('  Status:', resp.status_code, 'Location:', loc)

# Test route /rbac-it-pusat
print('Test GET /rbac-it-pusat (unauth):')
resp = client.get('/rbac-it-pusat', follow_redirects=False)
loc = resp.headers.get('location', 'N/A')
print('  Status:', resp.status_code, 'Location:', loc)

# Test API endpoint
print()
print('=== TEST API ENDPOINTS ===')
print()

print('Test GET /api/v1/ai-config/providers (unauth):')
resp = client.get('/api/v1/ai-config/providers')
print('  Status:', resp.status_code)

print('Test GET /api/v1/ai-config/status (unauth):')
resp = client.get('/api/v1/ai-config/status')
print('  Status:', resp.status_code)

print()
print('=== ALL ROUTE TESTS COMPLETED ===')
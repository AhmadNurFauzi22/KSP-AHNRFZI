import os
os.chdir(r'D:\xampp\htdocs\lat1')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# Test providers endpoint detail
resp = client.get('/api/v1/ai-config/providers')
print('Providers endpoint:')
print(f'  Status: {resp.status_code}')
data = resp.json()
for p in data['providers']:
    print(f'  - {p["label"]}:')
    print(f'    Value: {p["value"]}')
    print(f'    Models: {p["models"]}')
    print(f'    Description: {p["description"]}')
    print(f'    Is Configured: {p["is_configured"]}')
    print(f'    Current Model: {p["current_model"]}')
    print(f'    Current API Key Masked: {p["current_api_key_masked"]}')
    print(f'    Base URL: {p["base_url"]}')
    print(f'    Timeout: {p["timeout"]}')
    print(f'    Temperature: {p["temperature"]}')
    print()
PYEOF
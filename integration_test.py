import os
os.chdir(r'D:\xampp\htdocs\lat1')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# Test save endpoint without auth
print("Testing save endpoint without auth:")
resp = client.post('/api/v1/ai-config/save', content='{"provider": "gemini", "model": "gemini-1.5-flash", "api_key": "test-key-123"}', headers={"Content-Type": "application/json"})
print(f"  Status: {resp.status_code}")
print(f"  Response: {resp.text[:200]}")

print("\nTesting activate endpoint without auth:")
resp = client.post('/api/v1/ai-config/activate', content='{"provider": "gemini"}', headers={"Content-Type": "application/json"})
print(f"  Status: {resp.status_code}")
print(f"  Response: {resp.text[:200]}")

print("\nTesting test endpoint without auth:")
resp = client.post('/api/v1/ai-config/test', content='{"provider": "gemini", "model": "gemini-1.5-flash", "api_key": "test-key-123"}', headers={"Content-Type": "application/json"})
print(f"  Status: {resp.status_code}")
print(f"  Response: {resp.text[:200]}")
import os
os.chdir(r'D:\xampp\htdocs\lat1')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# Test key endpoints
print('GET /api/v1/health:', client.get('/api/v1/health').status_code)
print('GET /api/v1/ai-config/providers:', client.get('/api/v1/ai-config/providers').status_code)
print('GET /login:', client.get('/login').status_code)
print('GET /static/favicon.ico:', client.get('/static/favicon.ico').status_code)
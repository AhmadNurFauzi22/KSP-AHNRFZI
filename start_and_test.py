import subprocess
import sys
import time
import urllib.request
import urllib.error

# Start the server
cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "debug"]
proc = subprocess.Popen(cmd, cwd="D:\\xampp\\htdocs\\lat1", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Wait for startup
time.sleep(3)

# Test the endpoints
try:
    r = urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)
    print(f"Root URL status: {r.status}")
    print(f"Root URL body length: {len(r.read())}")
except urllib.error.HTTPError as e:
    print(f"Root URL HTTP error: {e.code} - {e.reason}")
    print(f"Root URL body: {e.read().decode('utf-8', errors='replace')[:500]}")
except Exception as e:
    print(f"Root URL error: {e}")

try:
    r = urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=3)
    print(f"Login URL status: {r.status}")
    print(f"Login URL body length: {len(r.read())}")
except urllib.error.HTTPError as e:
    print(f"Login URL HTTP error: {e.code} - {e.reason}")
    print(f"Login URL body: {e.read().decode('utf-8', errors='replace')[:500]}")
except Exception as e:
    print(f"Login URL error: {e}")

# Terminate server
proc.terminate()
proc.wait()
print("Server terminated, test complete")
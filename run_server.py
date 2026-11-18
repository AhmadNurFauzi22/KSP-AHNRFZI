import subprocess
import sys

# Run uvicorn directly
cmd = [
    sys.executable, "-m", "uvicorn",
    "app.main:app",
    "--host", "127.0.0.1",
    "--port", "8000",
    "--log-level", "debug",
    "--app-dir", "D:\\xampp\\htdocs\\lat1"
]

print("Running:", " ".join(cmd))
proc = subprocess.Popen(cmd, cwd="D:\\xampp\\htdocs\\lat1", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Wait for 10 seconds
import time
try:
    timer = 0
    while timer < 10:
        timer += 0.5
        time.sleep(0.5)
        if proc.poll() is not None:
            break
    print(f"Process exited after {timer}s with code: {proc.returncode}")
    
    # Read output
    stdout, stderr = proc.communicate(timeout=5)
    print("STDOUT:", stdout.decode("utf-8", errors="replace")[:2000])
    print("STDERR:", stderr.decode("utf-8", errors="replace")[:2000])
except Exception as e:
    print(f"Error: {e}")
    proc.terminate()
    proc.wait()
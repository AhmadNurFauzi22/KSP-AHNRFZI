import subprocess
import time

# Start MySQL with fixed config
mysqld_exe = 'D:/xampp/mysql/bin/mysqld.exe'
config_file = 'D:/xampp/mysql/data/my_fixed.ini'

print(f"Starting MySQL with config: {config_file}")
print(f"mysqlx=OFF is commented out: check config")

proc = subprocess.Popen(
    [mysqld_exe, '--defaults-file', config_file],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=subprocess.CREATE_NEW_CONSOLE
)

print(f"Process started with PID: {proc.pid}")
time.sleep(8)

# Check if process is still running
is_running = proc.poll() is None
print(f"Process still running after 8s: {is_running}")

if is_running:
    print('\\nSUCCESS: MySQL is running!')
    # Try to connect
    try:
        import urllib.request
        r = urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)
        print(f'Web server running, status: {r.status}')
    except Exception as e:
        print(f'Web server check: {e}')
    
    # Try MySQL client
    try:
        result = subprocess.run(
            ['mysql', '-u', 'root', '-e', 'SHOW DATABASES'],
            capture_output=True, text=True, timeout=5
        )
        print('MySQL databases:', result.stdout[:200] if result.stdout else 'Error: ' + result.stderr[:200])
    except FileNotFoundError:
        print('mysql client not found in PATH')
    except Exception as e:
        print('MySQL client error:', e)
    
    # Terminate after test
    proc.terminate()
    proc.wait()
    print('\\nTest completed, process terminated')
else:
    # Print error output
    print('\\nProcess exited with error:')
    stdout_output = proc.stdout.read().decode('utf-8', errors='replace')[:3000]
    stderr_output = proc.stderr.read().decode('utf-8', errors='replace')[:3000]
    print(f'STDOUT: {stdout_output}')
    print(f'STDERR: {stderr_output}')
    proc.wait()
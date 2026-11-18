import os
os.chdir(r'D:\xampp\htdocs\lat1')

try:
    with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
        code = f.read()
    compile(code, 'app/main.py', 'exec')
    print("main.py compiles OK")
except IndentationError as e:
    print(f"IndentationError: {e}")
except Exception as e:
    print(f"Error: {e}")
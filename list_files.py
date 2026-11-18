import os
os.chdir(r'D:\xampp\htdocs\lat1')

for root, dirs, files in os.walk('app'):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in sorted(files):
        if f.endswith('.py'):
            full_path = os.path.join(root, f)
            print(full_path)
import os
os.chdir(r'D:\xampp\htdocs\lat1')

with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Remove the favicon route
bad_pattern = '''@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    from fastapi.responses import FileResponse
    return FileResponse("app/static/favicon.ico")'''

if bad_pattern in content:
    content = content.replace(bad_pattern, '')
    print("Removed favicon route")
else:
    print(" favicon route not found")

with open('app/main.py', 'w', encoding='utf-8', errors='ignore') as f:
    f.write(content)

print("main.py updated")
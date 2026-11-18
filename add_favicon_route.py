import os
os.chdir(r'D:\xampp\htdocs\lat1')

with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Add favicon route before @app.on_event("startup")
# Find the position after the CORS middleware section
idx = content.find('@app.middleware("http")')
if idx >= 0:
    # Insert favicon route before the middleware
    insert_pos = content.rfind('\n', 0, idx) + 1
else:
    insert_pos = len(content)

new_route = '''@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    from fastapi.responses import FileResponse
    return FileResponse("app/static/favicon.ico")'''

new_content = content[:insert_pos] + new_route + content[insert_pos:]

with open('app/main.py', 'w', encoding='utf-8', errors='ignore') as f:
    f.write(new_content)

print(" favicon route ADDED")
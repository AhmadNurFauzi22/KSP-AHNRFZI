import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

with open('app/api/v1/users.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Cari posisi akhir file dan tambah route
# Cari baris terakhir
lines = content.split('\\n')
last_idx = len(lines) - 1
while last_idx >= 0 and not lines[last_idx].strip():
    last_idx -= 1

# Insert new routes after the last line
new_routes = '''\n\n@router.get("/ai-config", include_in_schema=False)
def ai_config_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("ai_config.html", {"request": request})

@router.get("/rbac-koperasi", include_in_schema=False)
def rbac_koperasi_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("rbac_koperasi.html", {"request": request})

@router.get("/rbac-it-pusat", include_in_schema=False)
def rbac_it_pusat_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("rbac_it_pusat.html", {"request": request})
'''
# Add the new routes after the last line
content = content + new_routes

with open('app/api/v1/users.py', 'w', encoding='utf-8', errors='ignore') as f:
    f.write(content)

print('Route berhasil ditambahkan ke users.py')
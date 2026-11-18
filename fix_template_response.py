import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Ganti import TemplateResponse dari jinja2 dengan templates.TemplateResponse
# Cari dan ganti pattern di tiga route yang baru ditambahkan

# Ganti import dari jinja2 dengan menggunakan templates yang sudah ada
# TemplateResponse di main.py sudah tersedia via 'templates' object

# Cari dan ganti tiga route yang baru
# Pattern 1: ai_config_page
old1 = '''@router.get("/ai-config", include_in_schema=False)
def ai_config_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("ai_config.html", {"request": request})'''

new1 = '''@app.get("/ai-config", response_class=HTMLResponse)\nasync def ai_config_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman Konfigurasi Assistant AI.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya Admin Koperasi dan Admin yang boleh\n    if not (\"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"ai_config.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"ai_config\",\n        }\n    )'''

# Pattern 2: rbac_koperasi_page
old2 = '''@router.get("/rbac-koperasi", include_in_schema=False)
def rbac_koperasi_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("rbac_koperasi.html", {"request": request})'''

new2 = '''@app.get("/rbac-koperasi", response_class=HTMLResponse)\nasync def rbac_koperasi_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman RBAC Admin Koperasi.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya Admin Koperasi dan Admin yang boleh\n    if not (\"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"rbac_koperasi.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"rbac_koperasi\",\n        }\n    )'''

# Pattern 3: rbac_it_pusat_page
old3 = '''@router.get("/rbac-it-pusat", include_in_schema=False)
def rbac_it_pusat_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("rbac_it_pusat.html", {"request": request})'''

new3 = '''@app.get("/rbac-it-pusat", response_class=HTMLResponse)\nasync def rbac_it_pusat_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman RBAC Admin IT Pusat.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya IT_PUSAT dan Admin yang boleh\n    has_it_pusat = \"IT_PUSAT\" in [r.code for r in user.roles]\n    has_admin = \"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]\n    \n    if not (has_it_pusat or has_admin):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"rbac_it_pusat.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"rbac_it_pusat\",\n        }\n    )'''

# Replace each pattern
if old1 in content:
    content = content.replace(old1, new1)
    print('Route 1 (ai_config) replaced')
else:
    print('Route 1 (ai_config) NOT found')

if old2 in content:
    content = content.replace(old2, new2)
    print('Route 2 (rbac_koperasi) replaced')
else:
    print('Route 2 (rbac_koperasi) NOT found')

if old3 in content:
    content = content.replace(old3, new3)
    print('Route 3 (rbac_it_pusat) replaced')
else:
    print('Route 3 (rbac_it_pusat) NOT found')

with open('app/main.py', 'w', encoding='utf-8', errors='ignore') as f:
    f.write(content)

print('Done fixing TemplateResponse imports')
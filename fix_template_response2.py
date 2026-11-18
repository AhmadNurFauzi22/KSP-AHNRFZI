import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Ganti import TemplateResponse dari jinja2 dengan templates.TemplateResponse di tiga route
# Pattern untuk ai_config_page
old_ai = '''@app.get("/ai-config", response_class=HTMLResponse)
async def ai_config_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman Konfigurasi Assistant AI.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    from jinja2 import TemplateResponse\n    from app.core.database import get_db\n    from sqlalchemy.orm import Session\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya Admin Koperasi dan Admin yang boleh\n    if not (\"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"ai_config.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"ai_config\",\n        }\n    )'''

# Pattern untuk rbac_koperasi_page
old_koperasi = '''@app.get("/rbac-koperasi", response_class=HTMLResponse)\nasync def rbac_koperasi_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman RBAC Admin Koperasi.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya Admin Koperasi dan Admin yang boleh\n    if not (\"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"rbac_koperasi.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"rbac_koperasi\",\n        }\n    )'''

# Pattern untuk rbac_it_pusat_page
old_it = '''@app.get("/rbac-it-pusat", response_class=HTMLResponse)\nasync def rbac_it_pusat_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman RBAC Admin IT Pusat.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya IT_PUSAT dan Admin yang boleh\n    has_it_pusat = \"IT_PUSAT\" in [r.code for r in user.roles]\n    has_admin = \"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]\n    \n    if not (has_it_pusat or has_admin):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"rbac_it_pusat.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"rbac_it_pusat\",\n        }\n    )'''

# Replace each pattern - ganti import jinja2 dengan templates.TemplateResponse yang sudah ada
# Untuk ai_config
if old_ai in content:
    content = content.replace(old_ai, '''@app.get("/ai-config", response_class=HTMLResponse)\nasync def ai_config_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman Konfigurasi Assistant AI.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya Admin Koperasi dan Admin yang boleh\n    if not (\"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"ai_config.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"ai_config\",\n        }\n    )''')
    print('Route ai_config berhasil diperbaiki')
else:
    print('Route ai_config pattern NOT found')

# Untuk rbac_koperasi
if old_koperasi in content:
    content = content.replace(old_koperasi, '''@app.get("/rbac-koperasi", response_class=HTMLResponse)\nasync def rbac_koperasi_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman RBAC Admin Koperasi.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya Admin Koperasi dan Admin yang boleh\n    if not (\"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"rbac_koperasi.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"rbac_koperasi\",\n        }\n    )''')
    print('Route rbac_koperasi berhasil diperbaiki')
else:
    print('Route rbac_koperasi pattern NOT found')

# Untuk rbac_it_pusat
if old_it in content:
    content = content.replace(old_it, '''@app.get("/rbac-it-pusat", response_class=HTMLResponse)\nasync def rbac_it_pusat_page(request: Request, db: Session = Depends(get_db)):\n    \"\"\"Halaman RBAC Admin IT Pusat.\"\"\"\n    from fastapi.responses import HTMLResponse\n    from fastapi import Request\n    \n    # Get web user\n    user, active_role, user_perms = get_web_user(request, db)\n    if not user:\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    # Cek permission - hanya IT_PUSAT dan Admin yang boleh\n    has_it_pusat = \"IT_PUSAT\" in [r.code for r in user.roles]\n    has_admin = \"ADMIN_KOPERASI\" in [r.code for r in user.roles] or \"ADMIN\" in [r.code for r in user.roles]\n    \n    if not (has_it_pusat or has_admin):\n        return RedirectResponse(url=\"/login\", status_code=status.HTTP_302_FOUND)\n    \n    return templates.TemplateResponse(\n        request=request,\n        name=\"rbac_it_pusat.html\",\n        context={\n            \"current_user\": user,\n            \"active_role\": active_role or (user.roles[0].code if user.roles else \"ANGGOTA\"),\n            \"user_perms\": user_perms,\n            \"active_page\": \"rbac_it_pusat\",\n        }\n    )''')
    print('Route rbac_it_pusat berhasil diperbaiki')
else:
    print('Route rbac_it_pusat pattern NOT found')

with open('app/main.py', 'w', encoding='utf-8', errors='ignore') as f:
    f.write(content)

print('Done fixing TemplateResponse imports')
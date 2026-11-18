import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

with open('app/templates/layouts/dashboard_layout.html', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Cari /ai-config dan ambil context lengkap
pos = content.find('/ai-config')
if pos >= 0:
    # Ambil 400 char sebelum dan 200 char setelah
    start = max(0, pos - 300)
    end = min(len(content), pos + 200)
    context = content[start:end]
    print('=== CONTEXT /ai-config (600 char) ===')
    print(context)
    print()
    
    # Cari kondisi if di sekitar area ini
    # Cari pattern {% if
    import re
    if_starts = [m.start() for m in re.finditer(r'\{% if', context)]
    print('Jumlah {% if %} di area:', len(if_starts))
    for idx, if_pos in enumerate(if_starts):
        # Ambil teks dari if pos hingga 100 char
        segment = context[if_pos:if_pos+100]
        print(' If block', idx+1 + ':', segment)
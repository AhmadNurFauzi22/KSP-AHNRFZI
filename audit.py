import os
os.chdir(r'D:\xampp\htdocs\lat1')

with open('app/templates/layouts/dashboard_layout.html', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Cek kondisi role
adm_kop_marker = "'ADMIN_KOPERASI' in user_perms"
adm_marker = "'ADMIN' in user_perms"

has_adm_kop = adm_kop_marker in content
has_adm = adm_marker in content

print('Kondisi ADMIN_KOPERASI in user_perms ada:', has_adm_kop)
print('Kondisi ADMIN in user_perms ada:', has_adm)

# Cek letak menu AI Config
pos = content.find('/ai-config')
if pos >= 0:
    segment = content[pos:pos+300]
    print()
    print('=== Area /ai-config ===')
    print(segment)
else:
    print('/ai-config NOT found')
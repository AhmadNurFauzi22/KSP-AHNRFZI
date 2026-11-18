import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

with open('app/templates/layouts/dashboard_layout.html', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Cek kemunculan
print('Kemunculan ADMIN_KOPERASI:', content.count('ADMIN_KOPERASI'))
print()

# Cek kondisi spesifik
cond1 = "'ADMIN_KOPERASI' in user_perms" in content
cond2 = "'ADMIN' in user_perms" in content
print("Kondisi ADMIN_KOPERASI in user_perms:", cond1)
print("Kondisi ADMIN in user_perms:", cond2)
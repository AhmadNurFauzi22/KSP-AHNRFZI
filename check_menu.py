import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

with open('app/templates/layouts/dashboard_layout.html', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Cek teks menu
print('Konfigurasi Assistant AI ada:', 'Konfigurasi Assistant AI' in content)
print('Path /ai-config ada:', '/ai-config' in content)

# Cek kondisi role
adm_kop = "'ADMIN_KOPERASI' in user_perms" in content
adm = "'ADMIN' in user_perms" in content
print('Kondisi ADMIN_KOPERASI:', adm_kop)
print('Kondisi ADMIN:', adm)

# Cek struktur if
if_adm_count = content.count("{% if " + "'ADMIN_KOPERASI'")
print('Jumlah if ADMIN_KOPERASI:', if_adm_count)

# Cek %} setelahnya
adm_if_end = content.count("'ADMIN' in user_perms %}")
print('Jumlah %} setelah ADMIN: ', adm_if_end)

print()
print('=== SEMUA CEK SELESAI ===')
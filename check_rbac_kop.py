import os
os.chdir(r'D:\xampp\htdocs\lat1')

f = open('app/templates/rbac_koperasi.html', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()

lines = content.split('\n')
print('Total lines:', len(lines))

# Cari baris yang berisi endblock atau block
for i, line in enumerate(lines, 1):
    if 'block' in line.lower() or 'endblock' in line.lower():
        print(f'Line {i}: {line.strip()[:100]}')

# Cari baris terakhir
print()
print('Lines around end of file:')
for i in range(max(0, len(lines)-10), len(lines)):
    print(f'Line {i+1}: {lines[i][:100]}')
import os
os.chdir(r'D:\xampp\htdocs\lat1')

f = open('app/templates/rbac_it_pusat.html', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()

lines = content.split('\n')
print('Total lines:', len(lines))

# Cari baris block dan endblock secara detail
print()
print('=== Detail block/endblock ===')
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith('{%') and stripped.endswith('%}'):
        print(f'Line {i}: {stripped}')

# Cari baris 380-395
print()
print('Lines 380-395:')
for i in range(380, min(396, len(lines))):
    print(f'Line {i}: {lines[i-1][:100]}')

# Cari baris terakhir
print()
print('Lines around end of file:')
for i in range(max(0, len(lines)-15), len(lines)):
    print(f'Line {i+1}: {lines[i][:100]}')
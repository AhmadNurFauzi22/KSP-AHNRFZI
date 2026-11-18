import os
os.chdir(r'D:\xampp\htdocs\lat1')

f = open('app/templates/rbac_koperasi.html', 'r', encoding='utf-8', errors='ignore')
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

# Cari baris 180-190
print()
print('Lines 180-195:')
for i in range(180, min(196, len(lines))):
    print(f'Line {i}: {lines[i-1][:100]}')

# Cari baris 280-295
print()
print('Lines 280-295:')
for i in range(280, min(296, len(lines))):
    print(f'Line {i}: {lines[i-1][:100]}')
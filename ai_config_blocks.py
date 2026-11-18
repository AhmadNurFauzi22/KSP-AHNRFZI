import os
os.chdir(r'D:\xampp\htdocs\lat1')

f = open('app/templates/ai_config.html', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()

lines = content.split('\n')
print('Total lines:', len(lines))

# Cari semua baris block/endblock
print()
print('=== Semua baris block/endblock ===')
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if stripped.startswith('{%') and stripped.endswith('%}'):
        print(f'Line {i}: {stripped}')

# Cek area baris 730-745
print()
print('=== Lines 730-745 ===')
for i in range(729, min(745, len(lines))):
    print(f'Line {i+1}: {lines[i][:100]}')
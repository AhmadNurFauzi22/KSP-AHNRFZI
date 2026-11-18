import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

with open('app/templates/layouts/dashboard_layout.html', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Cek struktur if
lines = content.split('\n')

# Track stack of if blocks
if_stack = []
errors = []

for i, line in enumerate(lines, 1):
    stripped = line.strip()
    
    # Cek mulai blok if
    if stripped.startswith('{% if '):
        if_stack.append(i)
    # Cek akhir blok if
    elif stripped == '{% endif %}':
        if not if_stack:
            errors.append('Line ' + str(i) + ': {% endif %} tanpa {% if %} pembuka')
        else:
            if_stack.pop()
    
# Setelah iterasi, jika stack masih berisi, ada if yang tidak tertutup
if if_stack:
    for line_num in if_stack:
        errors.append('Line ' + str(line_num) + ': {% if %} tidak ditutup dengan {% endif %}')

if errors:
    print('ERRORS FOUND:')
    for e in errors[:20]:
        print('  ', e)
else:
    print('TIDAK ADA ERROR STRUKTUR IF - Semua blok if tertutup dengan benar')

# Cek jumlah blok if dan endif
if_count = sum(1 for line in lines if line.strip().startswith('{% if '))
endif_count = sum(1 for line in lines if line.strip() == '{% endif %}')
print()
print('Jumlah {% if %}: ' + str(if_count))
print('Jumlah {% endif %}: ' + str(endif_count))
print('Status: ' + ('BALANSA' if if_count == endif_count else 'MENYERTAI' if if_count > endif_count else 'KURANG'))
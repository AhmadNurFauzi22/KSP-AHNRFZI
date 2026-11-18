import os
os.chdir(r'D:\\xampp\\htdocs\\lat1')

with open('app/main.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Cek di mana api_router diinclude
idx = content.find('api_router')
if idx >= 0:
    print('Found api_router inclusion at position', idx)
    # Ambil 300 char setelah
    segment = content[idx:idx+300]
    print(segment)
else:
    print('api_router NOT found in main.py')
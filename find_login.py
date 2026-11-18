import os
os.chdir(r'D:\xampp\htdocs\lat1')

f = open('app/api/v1/users.py', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()

idx = content.find('def login')
if idx >= 0:
    print('Found login at position:', idx)
    print(content[idx:idx+800])
else:
    print('def login NOT found in users.py')

# Also check main.py
f2 = open('app/main.py', 'r', encoding='utf-8', errors='ignore')
content2 = f2.read()
f2.close()

idx2 = content2.find('def login')
if idx2 >= 0:
    print()
    print('Found login at position in main.py:', idx2)
    print(content2[idx2:idx2+800])
else:
    print('def login NOT found in main.py')
import os
os.chdir(r'D:\xampp\htdocs\lat1')

content = open('app/main.py','r',encoding='utf-8',errors='ignore').read()
idx = content.find('def get_web_user')
print('Found at position:', idx)
if idx >= 0:
    print(content[idx:idx+500])
else:
    print('def get_web_user NOT found in main.py')

# Also check api/v1/users.py
content2 = open('app/api/v1/users.py','r',encoding='utf-8',errors='ignore').read()
idx2 = content2.find('def get_web_user')
print()
print('Found in users.py at position:', idx2)
if idx2 >= 0:
    print(content2[idx2:idx2+500])
else:
    print('def get_web_user NOT found in users.py')
import os
os.chdir(r'D:\xampp\htdocs\lat1')

f = open('app/db/models/user.py', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()
idx = content.find('class User')
print('Found at:', idx)
print(content[idx:idx+1000])
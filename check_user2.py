import os
os.chdir(r'D:\xampp\htdocs\lat1')

f = open('app/db/models/user.py', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()
idx = content.find('class User')
print('Found at:', idx)
# Print from class definition to end of relevant part
lines = content[idx:].split('\n')
for i, line in enumerate(lines[:100]):
    print(f'{i+1}: {line}')
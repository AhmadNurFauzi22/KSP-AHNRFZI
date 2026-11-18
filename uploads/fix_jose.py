#!/usr/bin/env python
path = r"C:\Users\lenovo\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\jose.py"
with open(path, 'r') as f:
    content = f.read()
# Find and fix the problematic print statements
# Line 546/547 has: print(decrypt(deserialize_compact(jwt), {'k':key})) 
# But the original was: print decrypt(deserialize_compact(jwt), {'k':key},)
# Need to replace the broken print with proper parentheses
content = content.replace('print decrypt(deserialize_compact(jwt), {\'k\':key},)', 'print(decrypt(deserialize_compact(jwt), {\'k\':key}))')
content = content.replace('print decrypt(deserialize_compact(jwt), {\'k\':key},)', 'print(decrypt(deserialize_compact(jwt), {\'k\':key}))')
content = content.replace('print decrypt(deserialize_compact(jwt), {\'k\':key},\n)', 'print(decrypt(deserialize_compact(jwt), {\'k\':key}))\n')
# Also fix any remaining
content = content.replace("print decrypt(deserialize_compact(jwt), {'k':key},)", "print(decrypt(deserialize_compact(jwt), {'k':key}))")
content = content.replace("print decrypt(deserialize_compact(jwt), {'k':key},)", "print(decrypt(deserialize_compact(jwt), {'k':key}))")
content = content.replace("print decrypt(deserialize_compact(jwt), {'k':key},\n)", "print(decrypt(deserialize_compact(jwt), {'k':key}))\n")
with open(path, 'w') as f:
    f.write(content)
print('Fixed jose.py')
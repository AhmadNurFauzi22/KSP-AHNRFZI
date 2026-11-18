#!/usr/bin/env python
import shutil
src = r"C:\Users\lenovo\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\jose.py"
dst = src + ".bak"
shutil.copy2(src, dst)
print("Backed up jose.py to", dst)
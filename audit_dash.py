#!/usr/bin/env python
import os
os.chdir(r'D:\xampp\htdocs\lat1')

print("=== CHECKING DASHBOARD TEMPLATES ===")
templates_dir = r'app/templates/layouts'
if os.path.exists(templates_dir):
    for f in os.listdir(templates_dir):
        print(f"  {f}")
else:
    print("  Directory not found")

print("\n=== CHECKING DASHBOARD SERVICE ===")
ds = r'app/services/dashboard_service.py'
if os.path.exists(ds):
    with open(ds, 'r') as f:
        content = f.read()
    func_count = content.count('def ')
    print(f"Fungsi di dashboard_service.py: {func_count}")
    keywords = ['member', 'savings', 'loan', 'cashier', 'report', 'user', 'role', 'permission']
    for kw in keywords:
        if kw.lower() in content.lower():
            count = content.lower().count(kw.lower())
            print(f"Menyatakan: {kw} ({count}x)")
else:
    print("File not found")
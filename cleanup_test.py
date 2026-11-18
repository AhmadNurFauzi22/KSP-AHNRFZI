import os
os.chdir(r'D:\xampp\htdocs\lat1')

files_to_remove = [
    'explore.py',
    'check_routes.py', 'check_auth.py', 'test_endpoints.py',
    'debug_template.py', 'fix_health.py', 'add_health_alias.py', 'remove_bad_health.py',
    'verify_health.py', 'add_health_alias2.py', 'remove_health_func.py', 'remove_health_func2.py',
    'remove_health_func3.py', 'fix_indent.py', 'final_fix.py', 'final_test.py',
    'check_favicon_health.py', 'fix_rbac_it.py', 'backup_rbac_it.py',
    'fix_rbac_kop.py', 'backup_rbac_kop.py', 'fix_ai_config.py', 'fix_ai_config2.py',
    'fix_sidebar.py', 'FINAL_REPORT.md', 'check_templates.py', 'final_fix.py',
    'test_ai_integration.py', 'test_ai_service.py', 'cleanup.py',
]

removed = 0
for f in files_to_remove:
    filepath = os.path.join(r'D:\xampp\htdocs\lat1', f)
    if os.path.exists(filepath):
        os.remove(filepath)
        print(f"Removed: {f}")
        removed += 1

print(f"\nTotal removed: {removed}")
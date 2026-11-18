import sqlite3

con = sqlite3.connect("koperasi_ahnrfzi.db")
cur = con.cursor()
cur.execute("""
INSERT OR IGNORE INTO role_permissions (role_id, permission_id, granted_at)
SELECT r.id, p.id, datetime('now')
FROM roles r, permissions p
WHERE r.code IN ('KASIR', 'PENGAWAS_PEMBINA') AND p.code = 'ai.assistant'
""")
con.commit()

res = cur.execute("""
SELECT r.code FROM role_permissions rp
JOIN roles r ON rp.role_id = r.id
JOIN permissions p ON rp.permission_id = p.id
WHERE p.code = 'ai.assistant'
""").fetchall()
print("All roles with ai.assistant:", [r[0] for r in res])
con.close()

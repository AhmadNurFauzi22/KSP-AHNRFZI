import sqlite3
import json

con = sqlite3.connect("koperasi_ahnrfzi.db")
cur = con.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall() if not r[0].startswith("sqlite_")]
schema_info = {}
for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = [{'name': c[1], 'type': c[2], 'notnull': bool(c[3]), 'default_value': c[4], 'pk': bool(c[5])} for c in cur.fetchall()]
    cur.execute(f"PRAGMA foreign_key_list({t})")
    fks = [{'from': f[3], 'table': f[2], 'to': f[4]} for f in cur.fetchall()]
    count = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    schema_info[t] = {'columns': cols, 'foreign_keys': fks, 'row_count': count}

with open("scripts/schema_dump.json", "w", encoding="utf-8") as f:
    json.dump({"tables": tables, "schema": schema_info}, f, indent=2)

print(f"Total tables: {len(tables)}")
print("Tables:", ", ".join(tables))
con.close()

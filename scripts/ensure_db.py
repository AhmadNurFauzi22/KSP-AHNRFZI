"""Dipanggil start_server.bat: pastikan tabel ada & ada user, seed otomatis bila DB kosong."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "koperasi_ahnrfzi.db"

def need_seed() -> bool:
    if not DB.exists():
        return True
    try:
        con = sqlite3.connect(str(DB))
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "users" not in tables:
            return True
        n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return n == 0
    except Exception as e:
        print(f"[DB-CHECK] gagal cek ({e}) -> seed ulang.")
        return True
    finally:
        try:
            con.close()
        except Exception:
            pass

if __name__ == "__main__":
    if need_seed():
        print("[DB] Database kosong/belum ada -> seeding otomatis...")
        from app.db.seed import seed_database
        seed_database()
    else:
        print("[DB] Database OK, lanjut menjalankan server.")

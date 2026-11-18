"""Database Schema Discovery Service untuk KSP AHNRFZI.

Melakukan introspeksi langsung dan dinamis terhadap skema SQLite database:
- 22 Tabel terdaftar
- Kolom, tipe data, nullable, default value, primary key
- Foreign key dan relasi antartabel
- Indeks dan constraint
- Row count aktual di database
"""

import sqlite3
from typing import Dict, Any, List, Optional
from sqlalchemy import inspect
from app.core.database import engine
from app.core.config import settings
from app.core.logging import logger


class DatabaseSchemaDiscovery:
    """Engine introspeksi skema database terotorisasi dan dinamis."""

    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        """Koneksi sqlite3 read-only langsung ke file database."""
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    @classmethod
    def discover_all_tables(cls) -> List[str]:
        """Mendapatkan daftar seluruh tabel non-sistem."""
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            return sorted([t for t in tables if not t.startswith("sqlite_")])
        except Exception as e:
            logger.error(f"[SCHEMA_DISCOVERY] gagal inspect tables: {e}")
            # Fallback ke sqlite pragma
            con = cls.get_connection()
            try:
                cur = con.cursor()
                res = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
                return [t for t in res if not t.startswith("sqlite_")]
            finally:
                con.close()

    @classmethod
    def get_table_details(cls, table_name: str) -> Optional[Dict[str, Any]]:
        """Mendapatkan metadata lengkap sebuah tabel (kolom, PK, FK, row count)."""
        all_tables = cls.discover_all_tables()
        if table_name not in all_tables:
            return None

        inspector = inspect(engine)
        columns_raw = inspector.get_columns(table_name)
        pk_constraint = inspector.get_pk_constraint(table_name)
        pk_columns = pk_constraint.get("constrained_columns", [])
        foreign_keys_raw = inspector.get_foreign_keys(table_name)
        indexes_raw = inspector.get_indexes(table_name)

        columns = []
        for col in columns_raw:
            columns.append({
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": col.get("nullable", True),
                "default": str(col.get("default")) if col.get("default") is not None else None,
                "is_primary_key": col["name"] in pk_columns
            })

        foreign_keys = []
        for fk in foreign_keys_raw:
            foreign_keys.append({
                "constrained_columns": fk.get("constrained_columns", []),
                "referred_table": fk.get("referred_table"),
                "referred_columns": fk.get("referred_columns", [])
            })

        # Hitung row count aktual
        row_count = 0
        try:
            con = cls.get_connection()
            cur = con.cursor()
            row_count = cur.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            con.close()
        except Exception as e:
            logger.warning(f"[SCHEMA_DISCOVERY] gagal hitung baris {table_name}: {e}")

        return {
            "table_name": table_name,
            "columns": columns,
            "primary_key": pk_columns,
            "foreign_keys": foreign_keys,
            "indexes": indexes_raw,
            "row_count": row_count
        }

    @classmethod
    def get_complete_schema_snapshot(cls) -> Dict[str, Any]:
        """Menghasilkan snapshot lengkap seluruh tabel dan relasinya."""
        tables = cls.discover_all_tables()
        schema = {}
        total_rows = 0
        for t in tables:
            details = cls.get_table_details(t)
            if details:
                schema[t] = details
                total_rows += details.get("row_count", 0)

        return {
            "total_tables": len(tables),
            "total_rows_across_database": total_rows,
            "tables": tables,
            "schema": schema
        }

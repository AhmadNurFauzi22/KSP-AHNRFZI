"""Test suite komprehensif untuk Database Intelligence Service, Knowledge Catalog, dan Schema Discovery.

Memverifikasi:
1. Schema Discovery (22 tabel, kolom, PK, FK, row count)
2. Database Knowledge Catalog (22 tabel terpetakan, relasi, rumus finansial, alur transaksi)
3. Endpoints AI Catalog & Schema Discovery (/api/v1/ai/catalog, /api/v1/ai/schema)
4. AI Chat Natural Language Querying (skema, rumus, alur, produk, profil)
5. RBAC & Data Isolation Enforcement (Anggota, Kasir, HRD, Manager, Admin)
6. Read-Only Safety (aksi tulis/modifikasi ditolak)
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.schema_discovery import DatabaseSchemaDiscovery
from app.services.database_knowledge_catalog import DatabaseKnowledgeCatalog, TABLE_CATALOG, FINANCIAL_FORMULAS


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def tokens(client):
    """Token untuk berbagai peran pengguna dalam pengujian RBAC."""
    credentials = {
        "admin": ("admin", "Password123!", "ADMIN_KOPERASI"),
        "manager": ("manager", "Password123!", "MANAGER"),
        "hrd": ("hrd", "Password123!", "HRD"),
        "kasir": ("kasir", "Password123!", "KASIR"),
        "anggota": ("anggota", "Password123!", "ANGGOTA"),
        "itpusat": ("itpusat", "Password123!", "IT_PUSAT"),
    }
    toks = {}
    for role, cred in credentials.items():
        payload = {"username": cred[0], "password": cred[1]}
        if len(cred) > 2 and cred[2]:
            payload["preferred_role"] = cred[2]
        res = client.post("/api/v1/auth/login", json=payload)
        assert res.status_code == 200, f"Gagal login {role}: {res.text}"
        toks[role] = res.json()["access_token"]
    return toks


def auth_hdr(tokens, role):
    return {"Authorization": f"Bearer {tokens[role]}"}


def ask_ai(client, tokens, role, question):
    return client.post(
        "/api/v1/ai/ask",
        json={"question": question},
        headers=auth_hdr(tokens, role)
    )


# =========================================================================
# 1. TEST SCHEMA DISCOVERY ENGINE
# =========================================================================

def test_schema_discovery_all_tables():
    tables = DatabaseSchemaDiscovery.discover_all_tables()
    assert len(tables) >= 22
    assert "users" in tables
    assert "roles" in tables
    assert "permissions" in tables
    assert "employees" in tables
    assert "members" in tables
    assert "savings_accounts" in tables
    assert "loans" in tables
    assert "loan_installments" in tables
    assert "cash_registers" in tables
    assert "cash_transactions" in tables
    assert "chart_of_accounts" in tables
    assert "journal_entries" in tables
    assert "audit_logs" in tables


def test_schema_discovery_table_details():
    loan_details = DatabaseSchemaDiscovery.get_table_details("loans")
    assert loan_details is not None
    assert loan_details["table_name"] == "loans"
    assert "id" in loan_details["primary_key"]
    col_names = [c["name"] for c in loan_details["columns"]]
    assert "loan_no" in col_names
    assert "member_id" in col_names
    assert "product_id" in col_names
    assert "approved_amount" in col_names
    assert "remaining_principal" in col_names
    assert "status" in col_names
    # Cek foreign keys
    ref_tables = [fk["referred_table"] for fk in loan_details["foreign_keys"]]
    assert "members" in ref_tables
    assert "loan_products" in ref_tables


def test_schema_discovery_complete_snapshot():
    snapshot = DatabaseSchemaDiscovery.get_complete_schema_snapshot()
    assert snapshot["total_tables"] >= 22
    assert snapshot["total_rows_across_database"] > 0
    assert len(snapshot["schema"]) >= 22


# =========================================================================
# 2. TEST DATABASE KNOWLEDGE CATALOG
# =========================================================================

def test_database_knowledge_catalog_all_22_tables_mapped():
    catalog_tables = DatabaseKnowledgeCatalog.get_all_tables()
    assert len(catalog_tables) == 22
    for t in catalog_tables:
        meta = DatabaseKnowledgeCatalog.get_table_metadata(t)
        assert meta is not None, f"Tabel {t} tidak memiliki metadata"
        assert meta["table_name"] == t
        assert meta["orm_model"]
        assert meta["module"] in ("SYSTEM", "HRD", "MEMBER", "SAVING", "LOAN", "INSTALLMENT", "CASHIER", "ACCOUNTING", "AUDIT")
        assert len(meta["columns"]) > 0
        assert len(meta["primary_key"]) > 0
        assert len(meta["business_rules"]) > 0


def test_financial_formulas_catalog():
    formulas = DatabaseKnowledgeCatalog.get_all_financial_formulas()
    expected_formulas = [
        "bunga_flat", "bunga_anuitas", "bunga_sliding",
        "biaya_pencairan", "denda_keterlambatan", "credit_score_dsr",
        "rekonsiliasi_kasir", "rekonstruksi_simpanan"
    ]
    for ef in expected_formulas:
        assert ef in formulas
        f = formulas[ef]
        assert f["nama"]
        assert f["rumus"]
        assert f["contoh"]


def test_transaction_flows_catalog():
    flows = DatabaseKnowledgeCatalog.get_transaction_flows()
    assert len(flows) >= 3
    flow_titles = [f["flow_name"] for f in flows]
    assert any("Pinjaman" in t for t in flow_titles)
    assert any("Kasir" in t for t in flow_titles)
    assert any("Simpanan" in t for t in flow_titles)


def test_catalog_search():
    res = DatabaseKnowledgeCatalog.search("pinjaman anuitas")
    assert len(res["matched_tables"]) > 0
    assert any("loan" in t["table_name"] for t in res["matched_tables"])
    assert len(res["matched_formulas"]) > 0
    assert any("anuitas" in f["id"] for f in res["matched_formulas"])


# =========================================================================
# 3. TEST AI CATALOG & SCHEMA ENDPOINTS
# =========================================================================

def test_api_catalog_endpoint_anggota(client, tokens):
    res = client.get("/api/v1/ai/catalog", headers=auth_hdr(tokens, "anggota"))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_tables"] == 22
    assert data["is_staff_view"] is False
    assert len(data["formulas"]) > 0
    assert len(data["transaction_flows"]) > 0


def test_api_catalog_endpoint_admin(client, tokens):
    res = client.get("/api/v1/ai/catalog", headers=auth_hdr(tokens, "admin"))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_tables"] == 22
    assert data["is_staff_view"] is True
    assert len(data["tables"]) == 22


def test_api_table_catalog_detail(client, tokens):
    res = client.get("/api/v1/ai/catalog/table/savings_accounts", headers=auth_hdr(tokens, "anggota"))
    assert res.status_code == 200, res.text
    meta = res.json()
    assert meta["table_name"] == "savings_accounts"
    assert meta["orm_model"] == "SavingsAccount"
    assert meta["module"] == "SAVING"


def test_api_schema_endpoint_rbac(client, tokens):
    # Anggota dilarang mengakses skema teknis langsung
    res_anggota = client.get("/api/v1/ai/schema", headers=auth_hdr(tokens, "anggota"))
    assert res_anggota.status_code == 403

    # Admin diizinkan
    res_admin = client.get("/api/v1/ai/schema", headers=auth_hdr(tokens, "admin"))
    assert res_admin.status_code == 200, res_admin.text
    snap = res_admin.json()
    assert snap["total_tables"] >= 22
    assert "users" in snap["schema"]


# =========================================================================
# 4. TEST NATURAL LANGUAGE QUERIES (DATABASE INTELLIGENCE)
# =========================================================================

def test_ai_query_database_schema(client, tokens):
    res = ask_ai(client, tokens, "admin", "Apa saja tabel di database koperasi?")
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "database_schema"
    assert "22 tabel" in body["answer"]
    assert "savings_accounts" in body["answer"]


def test_ai_query_financial_formula(client, tokens):
    res = ask_ai(client, tokens, "anggota", "Bagaimana rumus bunga anuitas pinjaman?")
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "financial_formula"
    assert "Anuitas" in body["answer"]
    assert "Rumus:" in body["answer"]


def test_ai_query_transaction_flow(client, tokens):
    res = ask_ai(client, tokens, "anggota", "Bagaimana tahapan dan alur pinjaman koperasi?")
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "transaction_flow"
    assert "DIAJUKAN" in body["answer"]
    assert "VERIFIKASI" in body["answer"]
    assert "DISETUJUI" in body["answer"]
    assert "Kasir" in body["answer"]


def test_ai_query_product_catalog(client, tokens):
    res = ask_ai(client, tokens, "anggota", "Apa saja produk simpanan yang ada?")
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "product_catalog"
    assert "Simpanan Pokok" in body["answer"]
    assert "Simpanan Wajib" in body["answer"]
    assert "Simpanan Sukarela" in body["answer"]


# =========================================================================
# 5. TEST RBAC & DATA ISOLATION ENFORCEMENT
# =========================================================================

def test_data_isolation_anggota_profile(client, tokens):
    res = ask_ai(client, tokens, "anggota", "Tampilkan profil saya")
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "my_profile"
    assert "Profil Anggota KSP AHNRFZI:" in body["answer"]
    assert "KSP-2026-" in body["answer"]


def test_data_isolation_anggota_denied_internal_stats(client, tokens):
    # Anggota minta jumlah pegawai HRD -> Ditolak
    r1 = ask_ai(client, tokens, "anggota", "Berapa jumlah pegawai di kantor?")
    assert r1.status_code == 200
    assert r1.json()["intent"] == "forbidden"
    assert "tidak memiliki izin" in r1.json()["answer"].lower()

    # Anggota minta bagan akun / COA -> Ditolak
    r2 = ask_ai(client, tokens, "anggota", "Tampilkan bagan akun COA akuntansi")
    assert r2.status_code == 200
    assert r2.json()["intent"] == "forbidden"
    assert "tidak memiliki izin" in r2.json()["answer"].lower()

    # Anggota minta pipeline pinjaman antrean staf -> Ditolak
    r3 = ask_ai(client, tokens, "anggota", "Tampilkan pipeline pinjaman yang menunggu verifikasi")
    assert r3.status_code == 200
    assert r3.json()["intent"] == "forbidden"


def test_rbac_hrd_access_and_boundaries(client, tokens):
    # HRD berhak melihat pegawai
    res_hrd = ask_ai(client, tokens, "hrd", "Berapa jumlah pegawai?")
    assert res_hrd.status_code == 200
    b_hrd = res_hrd.json()
    assert b_hrd["intent"] == "hrd_summary"
    assert "Total Pegawai:" in b_hrd["answer"]
    assert "Payroll:" in b_hrd["answer"]

    # HRD tidak berhak melihat saldo kas loket kasir (keuangan murni)
    res_kas = ask_ai(client, tokens, "hrd", "Berapa saldo kas koperasi?")
    assert res_kas.status_code == 200
    assert res_kas.json()["intent"] == "forbidden"


def test_rbac_kasir_access(client, tokens):
    # Kasir berhak melihat saldo kas
    res = ask_ai(client, tokens, "kasir", "Berapa saldo kas saat ini?")
    assert res.status_code == 200
    b = res.json()
    assert b["intent"] == "cash_summary"
    assert "saldo kas saat ini" in b["answer"]


def test_rbac_manager_loan_pipeline(client, tokens):
    # Manager berhak melihat antrean verifikasi kredit
    res = ask_ai(client, tokens, "manager", "Bagaimana pipeline pinjaman saat ini?")
    assert res.status_code == 200
    b = res.json()
    assert b["intent"] == "loan_pipeline"
    assert "Pipeline Persetujuan Kredit" in b["answer"]
    assert "Menunggu Verifikasi Staf:" in b["answer"]


def test_rbac_admin_accounting_summary(client, tokens):
    # Admin berhak melihat bagan akun dan pembukuan jurnal
    res = ask_ai(client, tokens, "admin", "Tampilkan ringkasan bagan akun dan jurnal")
    assert res.status_code == 200
    b = res.json()
    assert b["intent"] == "accounting_summary"
    assert "Ringkasan Akuntansi & COA" in b["answer"]
    assert "Total Akun COA Aktif:" in b["answer"]


def test_read_only_safety_guarantee(client, tokens):
    for role in ("anggota", "kasir", "manager", "admin"):
        for q in ("Cairkan pinjaman LOAN-001 sekarang", "Bayarkan angsuran Rp 500.000", "Hapus transaksi kasir"):
            res = ask_ai(client, tokens, role, q)
            assert res.status_code == 200
            b = res.json()
            assert b["intent"] == "financial_action_refused"
            assert "kewenangan" in b["answer"].lower()
            assert "workflow resmi" in b["answer"].lower()


# =========================================================================
# 7. TEST IDENTITAS, USER ROLE & JABATAN PENGGUNA SESUAI DATABASE
# =========================================================================

def test_user_identity_itpusat_siapa_saya(client, tokens):
    # IT Pusat bertanya "siapa saya?"
    res = ask_ai(client, tokens, "itpusat", "siapa saya?")
    assert res.status_code == 200
    b = res.json()
    assert b["intent"] == "user_identity"
    assert b["intent_category"] == "PERSONAL_DATA"
    assert "Andi Kurniawan" in b["answer"]
    assert "IT Pusat" in b["answer"]
    assert "Infrastructure Specialist" in b["answer"]
    assert "Information Technology" in b["answer"]
    assert "EMP-007" in b["answer"]
    assert "KSP-2026-0007" in b["answer"]


def test_user_role_and_jabatan_queries_itpusat(client, tokens):
    # IT Pusat bertanya apa role saya
    r_role = ask_ai(client, tokens, "itpusat", "Apa role saya?")
    assert r_role.status_code == 200
    b_role = r_role.json()
    assert b_role["intent"] == "user_identity"
    assert "IT Pusat" in b_role["answer"]
    assert "Infrastructure Specialist" in b_role["answer"]

    # IT Pusat bertanya apa jabatan saya
    r_jabatan = ask_ai(client, tokens, "itpusat", "Apa jabatan saya di database?")
    assert r_jabatan.status_code == 200
    b_jabatan = r_jabatan.json()
    assert b_jabatan["intent"] == "user_identity"
    assert "Infrastructure Specialist" in b_jabatan["answer"]
    assert "Information Technology" in b_jabatan["answer"]


def test_user_identity_admin(client, tokens):
    # Admin bertanya "siapa saya?"
    res = ask_ai(client, tokens, "admin", "Siapa saya?")
    assert res.status_code == 200
    b = res.json()
    assert b["intent"] == "user_identity"
    assert "Administrator Utama AHNRFZI" in b["answer"]
    assert "Admin Koperasi" in b["answer"]
    assert "Head of IT Systems" in b["answer"]
    assert "Direksi & TI" in b["answer"]
    assert "EMP-001" in b["answer"]


def test_user_identity_kasir(client, tokens):
    # Kasir bertanya "apa jabatan saya?"
    res = ask_ai(client, tokens, "kasir", "Apa jabatan saya?")
    assert res.status_code == 200
    b = res.json()
    assert b["intent"] == "user_identity"
    assert "Dewi Lestari" in b["answer"]
    assert "Head Teller" in b["answer"]
    assert "Kasir" in b["answer"]


def test_user_identity_manager(client, tokens):
    # Manager bertanya "siapa saya dan apa jabatan saya?"
    res = ask_ai(client, tokens, "manager", "Siapa saya dan apa jabatan saya?")
    assert res.status_code == 200
    b = res.json()
    assert b["intent"] == "user_identity"
    assert "Budi Santoso, S.E." in b["answer"]
    assert "General Manager" in b["answer"]
    assert "Manager Koperasi" in b["answer"]


def test_user_identity_anggota(client, tokens):
    # Anggota biasa bertanya "siapa saya?"
    res = ask_ai(client, tokens, "anggota", "Siapa saya?")
    assert res.status_code == 200
    b = res.json()
    assert b["intent"] == "user_identity"
    assert "Eko Prasetyo" in b["answer"]
    assert "Anggota Koperasi" in b["answer"]
    assert "Field Specialist" in b["answer"]
    assert "KSP-2026-0009" in b["answer"]


def test_ai_context_endpoint_includes_jabatan_and_greeting(client, tokens):
    # Memeriksa endpoint /api/v1/ai/context untuk IT Pusat
    res = client.get("/api/v1/ai/context", headers=auth_hdr(tokens, "itpusat"))
    assert res.status_code == 200
    ctx = res.json()
    assert ctx["active_role"] == "IT_PUSAT"
    assert ctx["active_role_name"] == "IT Pusat"
    assert ctx["jabatan"] == "Infrastructure Specialist"
    assert ctx["department"] == "Information Technology"
    assert "Andi Kurniawan" in ctx["greeting"]
    assert "Infrastructure Specialist" in ctx["greeting"]
    assert "Siapa saya dan apa jabatan saya?" in ctx["suggested_questions"]

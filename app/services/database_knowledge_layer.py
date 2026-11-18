"""Database Semantic Knowledge Layer for AI Assistant KSP AHNRFZI.

Menawarkan metadata dan akses baca-only ke database secara terstruktur
bersama definisi bisnis lengkap untuk setiap entitas dan metrik.

Tidak mengirimkan isi data mentah ke model AI.
"""

from typing import Dict, Any, List, Optional, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, inspect as sa_inspect
from datetime import datetime, timedelta, timezone


# ============================================================================
# ALLOWED TABLES & METADATA
# ============================================================================

# Semua tabel yang diizinkan untuk dibaca AI Assistant (read-only)
ALLOWED_TABLES: Set[str] = {
    # Dashboard & Sistem
    "user", "User",
    "audit_log", "AuditLog",
    # Simpanan
    "savings_account", "SavingsAccount",
    "savings_product", "SavingsProduct",
    "savings_transaction", "SavingsTransaction",
    # Pinjaman
    "loan", "Loan",
    "loan_product", "LoanProduct",
    "loan_installment", "LoanInstallment",
    # Kasir & Kas
    "cash_transaction", "CashTransaction",
    # Keanggotaan
    "member", "Member",
    # Pegawai
    "employee", "Employee",
}

# Metadata lengkap per tabel: kolom yang diizinkan, tipe, PK status
ALLOWED_COLUMNS: Dict[str, Set[str]] = {
    # Dashboard & Sistem
    "user": {"id", "username", "full_name", "is_active", "created_at", "last_login_at", "username"},
    "audit_log": {"id", "action", "created_at", "user_id", "notes"},
    # Simpanan
    "savings_account": {"id", "account_no", "balance", "status", "product_id", "member_id", "opened_date", "created_at"},
    "savings_product": {"id", "code", "name", "product_type", "min_initial_deposit", "min_monthly_deposit", "annual_interest_rate", "allow_withdrawal", "is_active", "created_at"},
    "savings_transaction": {"id", "account_id", "transaction_no", "transaction_type", "amount", "balance_before", "balance_after", "status", "created_at", "payment_channel", "reference_no", "description", "cashier_user_id"},
    # Pinjaman
    "loan": {"id", "loan_no", "member_id", "product_id", "status", "requested_amount", "approved_amount", "remaining_principal", "interest_rate_percent", "tenor_months", "calculation_type", "admin_fee", "provision_fee", "net_disbursed_amount", "calculation_type", "created_at", "disbursed_at"},
    "loan_product": {"id", "code", "name", "product_type", "min_initial_deposit", "min_monthly_deposit", "annual_interest_rate", "allow_withdrawal", "penalty_rate_daily", "is_active", "created_at"},
    "loan_installment": {"id", "loan_id", "installment_no", "due_date", "principal_due", "interest_due", "total_due", "total_paid", "principal_paid", "interest_paid", "penalty_paid", "days_overdue", "status", "created_at"},
    # Kasir & Kas
    "cash_transaction": {"id", "transaction_no", "receipt_no", "amount", "direction", "created_at", "member_id", "cashier_id", "payment_method", "category", "notes", "is_reversed"},
    # Keanggotaan
    "member": {"id", "member_no", "user_id", "full_name", "nik", "gender", "unit_divisi", "jabatan", "status", "join_date", "resigned_date", "created_at"},
    # Pegawai
    "employee": {"id", "user_id", "nip", "full_name", "id_card_number", "department", "position", "employment_status", "base_salary", "allowances", "hire_date", "resignation_date", "created_at"},
}

# Foreign Key relationships yang diizinkan (untuk relasi lintas tabel)
ALLOWED_RELATIONSHIPS: Dict[str, List[str]] = {
    "loan": ["member_id", "member", "product_id", "product"],
    "savings_account": ["member_id", "member", "product_id", "product"],
    "cash_transaction": ["member_id", "member", "cashier_id", "employee"],
    "savings_transaction": ["account_id", "savings_account", "member_id", "member", "cashier_user_id", "employee"],
    "loan_installment": ["loan_id", "loan", "member_id", "member"],
}

# Definisi metrik dashboard sesuai implementasi aktual
DASHBOARD_METRICS: Dict[str, Dict[str, Any]] = {
    "total_users": {
        "description": "Total pengguna terdaftar di sistem",
        "source": "query User.count() dengan filter is_active jika perlu",
        "table": "user",
        "column": "id",
    },
    "active_users": {
        "description": "Jumlah pengguna dengan status aktif",
        "source": "query User.filter(is_active=True).count()",
        "table": "user",
        "column": "id",
        "filter": "is_active=True",
    },
    "login_7d": {
        "description": "Jumlah kejadian login dalam 7 hari terakhir",
        "source": "query AuditLog.filter(action IN ['LOGIN_SUCCESS','LOGIN','LOGIN_FAILED'], created_at >= now - 7 hari)",
        "table": "audit_log",
        "column": "id",
        "action_filter": ["LOGIN_SUCCESS", "LOGIN", "LOGIN_FAILED"],
        "window_days": 7,
    },
    "error_7d": {
        "description": "Jumlah kejadian error dalam 7 hari terakhir",
        "source": "query AuditLog.filter(action ILIKE '%ERROR%' OR action ILIKE '%FAIL%', created_at >= now - 7 hari)",
        "table": "audit_log",
        "column": "id",
        "action_filter": ["%ERROR%", "%FAIL%"],
        "window_days": 7,
    },
    # Simpanan metrics
    "total_simpanan": {
        "description": "Total simpanan koperasi (semua jenis)",
        "source": "query SavingsAccount.balance SUM",
        "table": "savings_account",
        "column": "balance",
        "aggregation": "SUM",
    },
    "simpanan_pokok": {
        "description": "Total simpanan pokok seluruh anggota",
        "source": "query SavingsAccount.filter(product_type='POKOK').SUM balance",
        "table": "savings_account",
        "column": "balance",
        "filter": "product_type=POKOK",
        "aggregation": "SUM",
    },
    "simpanan_wajib": {
        "description": "Total simpanan wajib seluruh anggota",
        "source": "query SavingsAccount.filter(product_type='WAJIB').SUM balance",
        "table": "savings_account",
        "column": "balance",
        "filter": "product_type=WAJIB",
        "aggregation": "SUM",
    },
    "simpanan_sukarela": {
        "description": "Total simpanan sukarela seluruh anggota",
        "source": "query SavingsAccount.filter(product_type='SUKARELA').SUM balance",
        "table": "savings_account",
        "column": "balance",
        "filter": "product_type=SUKARELA",
        "aggregation": "SUM",
    },
    # Pinjaman metrics
    "portofolio_kredit_aktif": {
        "description": "Total portofolio kredit aktif (remaining principal)",
        "source": "query Loan.filter(status IN ['BERJALAN','ACTIVE']).SUM remaining_principal",
        "table": "loan",
        "column": "remaining_principal",
        "filter": "status IN ['BERJALAN','ACTIVE']",
        "aggregation": "SUM",
    },
    "total_pinjaman": {
        "description": "Total pinjaman koperasi",
        "source": "query Loan COUNT",
        "table": "loan",
        "column": "id",
        "aggregation": "COUNT",
    },
    "pinjaman_menunggu_verifikasi": {
        "description": "Jumlah pinjaman menunggu verifikasi/approve",
        "source": "query Loan.filter(status='MENTGU_VERIFIKASI').COUNT",
        "table": "loan",
        "column": "id",
        "filter": "status='MENTGU_VERIFIKASI'",
        "aggregation": "COUNT",
    },
    "pinjaman_terverifikasi": {
        "description": "Jumlah pinjaman sudah diverifikasi",
        "source": "query Loan.filter(status='BERJALAN').COUNT",
        "table": "loan",
        "column": "id",
        "filter": "status='BERJALAN'",
        "aggregation": "COUNT",
    },
    # Installment metrics
    "total_tagihan_angsuran": {
        "description": "Total tagihan angsuran bulan ini",
        "source": "query LoanInstallment.filter(due >= bulan_ini).SUM total_due",
        "table": "loan_installment",
        "column": "total_due",
        "filter": "due >= bulan_ini",
        "aggregation": "SUM",
    },
    "total_dibayar_angsuran": {
        "description": "Total pembayaran angsuran yang sudah terlaksana",
        "source": "query LoanInstallment.SUM total_paid",
        "table": "loan_installment",
        "column": "total_paid",
        "aggregation": "SUM",
    },
    "tunggakan_angsuran": {
        "description": "Total tagihan angsuran yang tertangguh",
        "source": "query LoanInstallment.filter(total_paid < total_due).SUM (total_due - total_paid)",
        "table": "loan_installment",
        "column": "total_due",
        "filter": "total_paid < total_due",
        "aggregation": "SUM",
    },
    # Kasir metrics
    "saldo_kas": {
        "description": "Saldo kas sistem",
        "source": "query CashTransaction.direction=CASH_IN SUM amount - CASH_OUT SUM amount",
        "table": "cash_transaction",
        "column": "amount",
        "filter": "direction IN ['CASH_IN', 'CASH_OUT']",
        "aggregation": "conditional SUM",
    },
    "kas_masuk_hari_ini": {
        "description": "Total kas masuk hari ini",
        "source": "query CashTransaction.filter(direction='CASH_IN', created_at >= hari_ini).SUM amount",
        "table": "cash_transaction",
        "column": "amount",
        "filter": "direction='CASH_IN' AND created_at >= hari_ini",
        "aggregation": "SUM",
    },
    "kas_keluar_hari_ini": {
        "description": "Total kas keluar hari ini",
        "source": "query CashTransaction.filter(direction='CASH_OUT', created_at >= hari_ini).SUM amount",
        "table": "cash_transaction",
        "column": "amount",
        "filter": "direction='CASH_OUT' AND created_at >= hari_ini",
        "aggregation": "SUM",
    },
    "total_transaksi_hari_ini": {
        "description": "Total transaksi hari ini",
        "source": "query CashTransaction.filter(created_at >= hari_ini).COUNT",
        "table": "cash_transaction",
        "column": "id",
        "filter": "created_at >= hari_ini",
        "aggregation": "COUNT",
    },
}

# Definisi status dan workflow per modul
STATUS_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "user": {
        "is_active": "Status aktif/login terakhir",
        "is_verified": "Status verifikasi email/phone",
    },
    "audit_log": {
        "LOGIN_SUCCESS": "Login berhasil",
        "LOGIN": "Aktivitas login",
        "LOGIN_FAILED": "Login gagal",
        "%ERROR%": "Error sistem",
        "%FAIL%": "Gagal proses",
    },
    "savings_account": {
        "ACTIVE": "Rekening aktif",
        "INACTIVE": "Rekening tidak aktif",
        "CLOSED": "Rekening ditutup",
    },
    "savings_product": {
        "POKOK": "Simpanan Pokok",
        "WAJIB": "Simpanan Wajib",
        "SUKARELA": "Simpanan Sukarela",
        "ACTIVE": "Produk Aktif",
        "INACTIVE": "Produk Tidak Aktif",
    },
    "savings_transaction": {
        "SETOR": "Setoran",
        "TARIK": "Penarikan",
        "INTEREST": "Bunga",
        "COMPLETED": "Selesai",
    },
    "loan": {
        "MENTGU_VERIFIKASI": "Menunggu Verifikasi",
        "DRAFT": "Draft",
        "PENDING": "Menunggu Persetujuan",
        "APPROVED": "Disetujui",
        "VERIFIED": "Verifikasi Selesai",
        "BERJALAN": "Berjalan",
        "SELESAI": "Selesai",
        "DITOLAK": "Ditolak",
    },
    "loan_product": {
        "ACTIVE": "Produk Aktif",
        "INACTIVE": "Produk Tidak Aktif",
    },
    "loan_installment": {
        "ACTIVE": "Aktif",
        "OVERDUE": "Terlambat",
        "COMPLETED": "Selesai",
        "CANCELLED": "Dibatalkan",
    },
    "cash_transaction": {
        "CASH_IN": "Kas Masuk",
        "CASH_OUT": "Kas Keluar",
        "REVERSAL": "Batalkan",
        "COMPLETED": "Selesai",
    },
    "member": {
        "AKTIF": "Anggota Aktif",
        "CALON": "Calon Anggota",
        "NONAKTIF": "Nonaktif/Keluar",
    },
    "employee": {
        "ACTIVE": "Aktif",
        "CUTI": "Cuti",
        "PH": "Pin/Hospital",
        "RESIGNED": "Resign",
    },
}

# Aturan bisnis per modul
BUSINESS_RULES: Dict[str, Dict[str, Any]] = {
    "savings_withdrawal": {
        "allow_withdrawal_aktif": False,
        "allow_withdrawal_keluar": True,
        "minimum_balance_check": True,
        "reconstruction_required": True,
    },
    "loan_status": {
        "mentgra_verifikasi_to_berjalan": "Boleh diubah ke BERJALAN setelah diverifikasi",
        "berjalan_to_selesai": "Boleh diubah ke SELESAI setelah masa tenor berakhir",
    },
    "cash_transaction": {
        "reversal_harus_admin": True,
        "cash_in_harus_tanggal": "Hanya dengan tanggal hari ini",
    },
}

# Label kategori untuk ekspor dan tampilan
CATEGORY_LABELS: Dict[str, str] = {
    "CASH_IN": "KAS MASUK",
    "CASH_OUT": "KAS KELUAR",
    "REVERSAL": "BATALKAN",
    "SETOR": "SETORAN",
    "TARIK": "PENARIKAN",
    "POKOK": "Simpanan Pokok",
    "WAJIB": "Simpanan Wajib",
    "SUKARELA": "Simpanan Sukarela",
    "BERJALAN": "Berjalan",
    "MENTGU_VERIFIKASI": "Menunggu Verifikasi",
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_allowed_tables() -> Set[str]:
    """Daftar tabel yang diizinkan untuk dibaca AI Assistant."""
    return ALLOWED_TABLES.copy()


def get_allowed_columns(table_name: str) -> Set[str]:
    """Daftar kolom yang diizinkan untuk tabel tertentu."""
    table_lower = table_name.lower()
    return ALLOWED_COLUMNS.get(table_lower, set())


def get_relationships() -> Dict[str, List[str]]:
    """Daftar relasi antar-tabel yang diizinkan."""
    return ALLOWED_RELATIONSHIPS.copy()


def get_relationships_for_table(table_name: str) -> List[str]:
    """Daftar relasi untuk tabel tertentu."""
    table_lower = table_name.lower()
    return ALLOWED_RELATIONSHIPS.get(table_lower, [])


def get_metric_definition(metric_name: str) -> Optional[Dict[str, Any]]:
    """Dapatkan definisi metrik dashboard."""
    return DASHBOARD_METRICS.get(metric_name)


def is_table_allowed(table_name: str) -> bool:
    """Cek apakah tabel boleh dibaca AI."""
    return table_name.lower() in ALLOWED_TABLES


def get_status_definition(module: str, status_key: str) -> Optional[Dict[str, Any]]:
    """Dapatkan definisi status untuk modul tertentu."""
    module_def = STATUS_DEFINITIONS.get(module.lower(), {})
    if status_key in module_def:
        return {"key": status_key, "value": module_def[status_key]}
    return None


def get_category_label(key: str) -> str:
    """Dapatkan label kategori untuk tampilan."""
    return CATEGORY_LABELS.get(key, key)


def get_business_rule(rule_name: str) -> Optional[Dict[str, Any]]:
    """Dapatkan aturan bisnis."""
    return BUSINESS_RULES.get(rule_name)


def get_all_metrics() -> Dict[str, Dict[str, Any]]:
    """Dapatkan semua definisi metrik."""
    return DASHBOARD_METRICS.copy()


def get_all_status_definitions() -> Dict[str, Dict[str, Any]]:
    """Dapatkan semua definisi status."""
    return STATUS_DEFINITIONS.copy()


def get_all_business_rules() -> Dict[str, Dict[str, Any]]:
    """Dapatkan semua aturan bisnis."""
    return BUSINESS_RULES.copy()


def get_all_category_labels() -> Dict[str, str]:
    """Dapatkan semua label kategori."""
    return CATEGORY_LABELS.copy()
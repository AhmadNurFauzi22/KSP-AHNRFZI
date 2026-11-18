"""Layanan Konteks Database Terpusat untuk AI Assistant KSP AHNRFZI.

SATU sumber data untuk SELURUH provider AI (Gemini, OpenAI, Anthropic,
NVIDIA NIM). Provider manapun yang aktif, retrieval-nya melewati layanan ini
sehingga kemampuan Assistant identik walau provider diganti.

CONTEXT ROUTING (inti perbaikan):
    Setiap intent hanya menarik data yang benar-benar dibutuhkan.
    Pertanyaan identitas (USER_IDENTITY / USER_ROLE / USER_PROFILE)
    TIDAK PERNAH menarik ringkasan dashboard.

Alur:
    USER QUESTION -> INTENT DETECTION -> SELECT DATA SOURCE -> RBAC CHECK
                 -> FETCH DATA -> BUILD RELEVANT CONTEXT
                 -> ACTIVE AI PROVIDER -> RESPONSE

Aturan keamanan:
- Query memakai SQLAlchemy ORM / service read-only milik aplikasi.
- Otorisasi dicek di backend SEBELUM data dikirim ke provider.
- API key, password hash, token TIDAK PERNAH masuk ke konteks.
- Tidak ada SQL mentah, tidak ada eksekusi perintah dari model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.db.models.user import User
from app.services import ai_tools, user_query_service
from app.services.ai_intent import (
    INTENT_AUDIT_STATUS,
    INTENT_CASH_FLOW,
    INTENT_DASHBOARD_SUMMARY,
    INTENT_GENERAL,
    INTENT_INSTALLMENT,
    INTENT_IT_SYSTEM_STATUS,
    INTENT_LOAN,
    INTENT_MEMBER_COUNT,
    INTENT_MEMBER_INCOMPLETE,
    INTENT_MEMBER_LIST,
    INTENT_SAVINGS,
    INTENT_TRANSACTION,
    INTENT_USER_IDENTITY,
    INTENT_USER_LIST,
    INTENT_USER_PROFILE,
    INTENT_USER_ROLE,
    detect_intent,
)
from app.services.role_synonyms import resolve_role_synonym
from app.services.user_context import get_current_authenticated_user_context


# ======================================================================
# Identitas & hak akses
# ======================================================================

ROLE_LABELS: Dict[str, str] = {
    "ADMIN_KOPERASI": "Admin Koperasi",
    "KETUA_UMUM": "Ketua Umum",
    "MANAGER": "Manager",
    "HRD": "HRD",
    "PENGAWAS_PEMBINA": "Pengawas/Pembina",
    "STAF": "Staf",
    "IT_PUSAT": "IT Pusat",
    "KASIR": "Kasir",
    "ANGGOTA": "Anggota",
}


def _role_label(code: str) -> str:
    return ROLE_LABELS.get(code, code)


def get_active_role(user: User) -> str:
    """Role aktif dari session server (bukan dari input user)."""
    role = getattr(user, "active_role", None)
    if role:
        return role
    roles = getattr(user, "roles", None) or []
    return roles[0].code if roles else "ANGGOTA"


def build_user_context(db: Session, user: User) -> Dict[str, Any]:
    """Identitas + permission user aktif (tanpa data sensitif)."""
    from app.core.permissions import get_user_permissions

    role = get_active_role(user)
    try:
        perms = sorted(str(p) for p in get_user_permissions(user, role))
    except Exception:
        perms = []

    ctx = get_current_authenticated_user_context(db, user)
    identity = {
        "user_id": ctx.get("user_id"),
        "username": getattr(user, "username", ""),
        "full_name": ctx.get("full_name") or getattr(user, "username", ""),
        "role_code": role,
        "role_display": _role_label(role),
        "all_roles": ctx.get("all_roles") or [],
        "permissions": perms,
        "is_active": bool(getattr(user, "is_active", False)),
        "jabatan": ctx.get("jabatan"),
        "is_member": ctx.get("is_member"),
        "member_no": ctx.get("member_no"),
    }
    return identity


# ======================================================================
# Pengambilan data (read-only, via service yang sudah ada)
# ======================================================================

def _safe(call, *args, **kwargs) -> Tuple[Optional[Any], Optional[str]]:
    """Jalankan reader DB. Kembalikan (data, pesan_penolakan).

    Fungsi ``ai_tools`` melempar HTTPException(403) bila user tidak berwenang.
    """
    try:
        return call(*args, **kwargs), None
    except HTTPException as e:
        if e.status_code == 403:
            return None, (e.detail or "Anda tidak memiliki izin untuk data ini.")
        logger.warning(f"[AI_CTX] retrieval error: {type(e).__name__}")
        return None, "Data tidak dapat diakses saat ini."
    except Exception as e:
        logger.warning(f"[AI_CTX] retrieval error: {type(e).__name__}: {e}")
        return None, "Data tidak dapat diakses saat ini."


# ---------------------------------------------------------------------
# Konteks per sumber data
# ---------------------------------------------------------------------

def _ctx_identity(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Konteks HANYA identitas session. TIDAK memuat ringkasan dashboard."""
    lines = [
        f"Nama pengguna : {uc.get('full_name') or '-'}",
        f"Username      : {uc.get('username') or '-'}",
        f"Role aktif    : {uc.get('role_display')} ({uc.get('role_code')})",
        f"Status akun   : {'Aktif' if uc.get('is_active') else 'Nonaktif'}",
    ]
    if uc.get("jabatan"):
        lines.append(f"Jabatan       : {uc['jabatan']}")
    if uc.get("all_roles"):
        roles = ", ".join(f"{_role_label(r)} ({r})" for r in uc["all_roles"])
        lines.append(f"Seluruh role  : {roles}")
    if uc.get("is_member") and uc.get("member_no"):
        lines.append(f"No. anggota    : {uc['member_no']}")
    lines.append(f"Jumlah hak akses aktif: {len(uc.get('permissions') or [])}")
    return "\n".join(lines)


def _ctx_role(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Konteks role + permission (bukan data operasional)."""
    perms = uc.get("permissions") or []
    perms_txt = ", ".join(perms) if perms else "tidak ada"
    return (
        f"Role aktif: {uc.get('role_display')} ({uc.get('role_code')})\n"
        f"Permission aktif ({len(perms)}): {perms_txt}\n"
        f"Seluruh role pengguna: {', '.join(uc.get('all_roles') or []) or '-'}"
    )


def _ctx_user_list(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Daftar pengguna APLIKASI (tabel users) — BUKAN anggota koperasi."""
    data, denied = _safe(user_query_service.get_user_statistics, db)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data pengguna tidak tersedia."
    lines = [f"Total akun pengguna aplikasi: {data.get('total', 0)}"]
    per_role = data.get("by_role") or {}
    if per_role:
        lines.append("Rincian per role:")
        for code, n in sorted(per_role.items()):
            lines.append(f"  - {_role_label(code)} ({code}): {n} pengguna")
    return "\n".join(lines)


def _ctx_member_stats(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Statistik ANGGOTAoleteLepas (tabel members) — bedakan dari pengguna aplikasi."""
    data, denied = _safe(ai_tools.get_membership_info, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data keanggotaan tidak tersedia."
    return (
        f"Total anggota koperasi: {data.get('total', 0)}\n"
        f"Anggota aktif   : {data.get('aktif', 0)}\n"
        f"Anggota calon   : {data.get('calon', 0)}\n"
        f"Anggota nonaktif: {data.get('nonaktif', 0)}\n"
        "(Data anggota. Tidak sama dengan data pengguna aplikasi/RBAC.)"
    )


def _ctx_savings(db: Session, user: User, uc: Dict[str, Any]) -> str:
    data, denied = _safe(ai_tools.get_savings_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data simpanan tidak tersedia."
    return "\n".join(f"{k}: {v}" for k, v in data.items())


def _ctx_loan(db: Session, user: User, uc: Dict[str, Any]) -> str:
    data, denied = _safe(ai_tools.get_loan_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data pinjaman tidak tersedia."
    return "\n".join(f"{k}: {v}" for k, v in data.items())


def _ctx_cash(db: Session, user: User, uc: Dict[str, Any]) -> str:
    data, denied = _safe(ai_tools.get_cash_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data kas tidak tersedia."
    return "\n".join(f"{k}: {v}" for k, v in data.items())


def _ctx_installment(db: Session, user: User, uc: Dict[str, Any]) -> str:
    from app.db.models.loan import LoanInstallment
    from sqlalchemy import func

    try:
        total = db.query(func.count(LoanInstallment.id)).scalar() or 0
    except Exception:
        total = 0
    return (
        f"Total jadwal angsuran tercatat: {total}\n"
        "Rincian per status angsuran dan data jatuh tempo dapat diambil dari modul angsuran."
    )


def _ctx_it_status(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Status sistem - HANYA untuk role IT (permission system.manage / audit.view)."""
    perms = set(uc.get("permissions") or [])
    if not ({"system.manage", "audit.view"} & perms):
        return "[DITOLAK] Anda tidak memiliki hak akses untuk data status sistem IT."
    from app.core.database import engine
    from sqlalchemy import text

    lines = []
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            lines.append("Koneksi database: OK")
    except Exception:
        lines.append("Koneksi database: GAGAL")
    lines.append(f"Provider AI aktif: {uc.get('active_provider', '-')}")
    return "\n".join(lines)


def _ctx_audit(db: Session, user: User, uc: Dict[str, Any]) -> str:
    data, denied = _safe(ai_tools.get_audit_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data audit tidak tersedia."
    return "\n".join(f"{k}: {v}" for k, v in data.items())


def _ctx_dashboard(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Ringkasan dashboard sesuai role (sumber sama dengan frontend)."""
    from app.services.user_role_service import get_dashboard_summary

    role = uc.get("role_code", "ANGGOTA")
    data, denied = _safe(get_dashboard_summary, role, uc.get("user_id"))
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Ringkasan dashboard tidak tersedia."
    if isinstance(data, dict):
        return "\n".join(f"- {k}: {v}" for k, v in data.items())
    return str(data)


def _ctx_general(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Konteks minimal untuk pertanyaan umum/prosedural.

    Sengaja TIDAK menarik ringkasan dashboard penuh supaya model tidak
    mengarang angka yang tidak relevan.
    """
    return (
        f"Pengguna: {uc.get('full_name')} | Role: {uc.get('role_display')}\n"
        "Tidak ada data agregat yang relevan untuk pertanyaan ini; "
        "jawablah berdasarkan pengetahuan sistem dan SOPazasaran koinstall."
    )


# ---------------------------------------------------------------------
# Context router
# ---------------------------------------------------------------------

#: intent -> (builder konteks, ringkasan kategori)
_CONTEXT_ROUTER: Dict[str, Any] = {
    INTENT_USER_IDENTITY: _ctx_identity,
    INTENT_USER_ROLE: _ctx_role,
    INTENT_USER_PROFILE: _ctx_identity,
    INTENT_USER_LIST: _ctx_user_list,
    INTENT_MEMBER_COUNT: _ctx_member_stats,
    INTENT_MEMBER_LIST: _ctx_member_stats,
    INTENT_MEMBER_INCOMPLETE: _ctx_member_stats,
    INTENT_SAVINGS: _ctx_savings,
    INTENT_LOAN: _ctx_loan,
    INTENT_INSTALLMENT: _ctx_installment,
    INTENT_CASH_FLOW: _ctx_cash,
    INTENT_TRANSACTION: _ctx_cash,
    INTENT_IT_SYSTEM_STATUS: _ctx_it_status,
    INTENT_AUDIT_STATUS: _ctx_audit,
    INTENT_DASHBOARD_SUMMARY: _ctx_dashboard,
    INTENT_GENERAL: _ctx_general,
}


def build_database_context(db: Session, user: User, question: str,
                           intent: Optional[str] = None) -> str:
    """Ambil data aktual sesuai intent (context routing terpusat)."""
    intent = intent or detect_intent(question)
    uc = build_user_context(db, user)
    builder = _CONTEXT_ROUTER.get(intent, _ctx_general)
    try:
        return builder(db, user, uc)
    except Exception as e:
        logger.warning(f"[AI_CTX] context builder gagal: {type(e).__name__}: {e}")
        return "Data tidak dapat diakses saat ini."


def build_context_bundle(db: Session, user: User, question: str) -> Dict[str, Any]:
    """Paket lengkap: intent + user context + konteks database yang relevan."""
    intent = detect_intent(question)
    uc = build_user_context(db, user)
    return {
        "intent": intent,
        "user_context": uc,
        "database_context": build_database_context(db, user, question, intent=intent),
    }

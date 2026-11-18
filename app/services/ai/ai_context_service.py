"""Layanan Konteks Database Terpusat untuk AI Assistant KSP AHNRFZI.

SATU sumber data untuk SELURUH provider AI (Gemini, OpenAI, Anthropic,
NVIDIA NIM, OpenAI-compatible). Provider manapun yang aktif, retrieval-nya
melewati layanan ini sehingga kemampuan Assistant identik.

CONTEXT ROUTING (inti):
    Setiap intent hanya menarik data yang benar-benar dibutuhkan.
    Pertanyaan identitas (USER_IDENTITY) TIDAK PERNAH menarik ringkasan dashboard.

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
    INTENT_CASH_FLOW,
    INTENT_DASHBOARD_SUMMARY,
    INTENT_GENERAL,
    INTENT_INSTALLMENTS,
    INTENT_LOANS,
    INTENT_MEMBER_INCOMPLETE,
    INTENT_MEMBER_LIST,
    INTENT_MEMBER_STATISTICS,
    INTENT_PENDING_APPLICATIONS,
    INTENT_AUDIT_STATUS,
    INTENT_ROLE_LIST,
    INTENT_SAVINGS,
    INTENT_SYSTEM_STATUS,
    INTENT_TECHNICAL,
    INTENT_TRANSACTIONS,
    INTENT_USER_COUNT,
    INTENT_USER_IDENTITY,
    INTENT_USER_LIST,
    INTENT_USER_ROLE_LOOKUP,
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
    return {
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


def has_perm(uc: Dict[str, Any], *needed: str) -> bool:
    """Cek permission user aktif. '*' = akses penuh."""
    perms = set(uc.get("permissions") or [])
    if "*" in perms:
        return True
    return bool(perms & set(needed))


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


def _fmt_lines(data: Any) -> str:
    """Format dict/list konteks menjadi teks yang rapi."""
    if data is None:
        return ""
    if isinstance(data, dict):
        return "\n".join(f"{k}: {v}" for k, v in data.items())
    if isinstance(data, list):
        return "\n".join(f"- {item}" for item in data)
    return str(data)


# ---------------------------------------------------------------------
# Builder konteks per intent
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


def _ctx_user_count(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Jumlah akun pengguna APLIKASI (tabel users)."""
    stats, denied = _safe(user_query_service.get_user_statistics, db)
    if denied:
        return f"[DITOLAK] {denied}"
    if not stats:
        return "Data pengguna tidak tersedia."
    return (
        f"Total akun pengguna aplikasi: {stats.get('total_users', 0)}\n"
        f"Pengguna aktif   : {stats.get('active_users', 0)}\n"
        f"Pengguna nonaktif: {stats.get('inactive_users', 0)}\n"
        "(Pengguna APLIKASI = akun sistem/RBAC. BEDA dengan anggota koperasi.)"
    )


def _ctx_user_list(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Daftar pengguna APLIKASI beserta role.

    Daftar akun aplikasi (nama + username + role) adalah kapabilitas admin
    (user.manage / role.manage). Permission ``member.view`` TIDAK cukup karena
    itu hanya untuk data ANGGOTA, bukan akun sistem.
    """
    if not has_perm(uc, "user.manage", "role.manage", "*"):
        return "[DITOLAK] Anda tidak memiliki izin untuk melihat daftar pengguna aplikasi."
    data, denied = _safe(user_query_service.get_all_users, db, False, 50, 0)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data pengguna tidak tersedia."
    users = data.get("users") or []
    lines = [f"Total akun: {data.get('total', 0)} (menampilkan {len(users)})"]
    for u in users:
        roles = ", ".join(u.get("role_codes") or []) or "-"
        status = "aktif" if u.get("is_active") else "nonaktif"
        lines.append(f"- {u.get('full_name', 'N/A')} | username: {u.get('username', '-')} | "
                     f"role: {roles} | status: {status}")
    return "\n".join(lines)


def _ctx_role_list(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Daftar role yang benar-benar ada di database beserta deskripsinya."""
    from app.db.models import Role
    try:
        roles = db.query(Role).order_by(Role.code).all()
    except Exception:
        return "Data role tidak dapat diakses."
    if not roles:
        return "Data role tidak tersedia."
    lines = ["Role yang terdaftar di sistem:"]
    for r in roles:
        lines.append(f"- {r.code} ({r.name}): {r.description}")
    return "\n".join(lines)


def _ctx_user_role_lookup(db: Session, user: User, uc: Dict[str, Any],
                          question: str = "") -> str:
    """Orang-orang yang memegang role tertentu."""
    if not has_perm(uc, "user.manage", "role.manage", "member.view_all", "*"):
        return "[DITOLAK] Anda tidak memiliki izin untuk melihat pemegang role."
    q = (question or "").lower()
    codes: List[str] = []
    for term in ("admin koperasi", "admin", "kasir", "manager", "ketua umum", "ketua",
                 "pengawas", "pembina", "it pusat", "hrd", "staf", "anggota"):
        if term in q:
            resolved = resolve_role_synonym(term)
            codes.extend(resolved if resolved else [term.upper().replace(" ", "_")])
            break
    if not codes:
        codes = ["ADMIN_KOPERASI"]

    data, denied = _safe(user_query_service.get_users_by_role_codes, db, codes, False)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data pengguna tidak tersedia."
    users = (data.get("users_by_role") or {}).get(codes[0], [])
    if not users:
        return f"Tidak ditemukan pengguna dengan role {codes[0]}."
    lines = [f"Total pemegang role {codes[0]}: {len(users)}"]
    for u in users:
        status = "aktif" if u.get("is_active") else "nonaktif"
        lines.append(f"- {u.get('full_name', 'N/A')} | username: {u.get('username', '-')} | {status}")
    return "\n".join(lines)


def _ctx_member_stats(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Statistik ANGGOTA (tabel members) — bedakan dari pengguna aplikasi."""
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
        "(Data anggota. BEDA dengan data pengguna aplikasi/RBAC.)"
    )


def _ctx_member_list(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Daftar anggota’intégrée (nama + nomor anggota + status)."""
    if not has_perm(uc, "member.view_all", "member.view", "report.view", "*"):
        return "[DITOLAK] Anda tidak memiliki izin untuk melihat daftar anggota."
    from app.db.models.member import Member
    try:
        members = db.query(Member).order_by(Member.member_no).limit(50).all()
        total = db.query(Member).count()
    except Exception:
        return "Data anggota tidak dapat diakses."
    lines = [f"Total anggota: {total} (menampilkan {len(members)})"]
    for m in members:
        lines.append(f"- {m.full_name or '-'} | No. anggota: {m.member_no or '-'} | "
                     f"status: {m.status or '-'} | jabatan: {m.jabatan or '-'}")
    return "\n".join(lines)


def _ctx_member_incomplete(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Anggota dengan data profil belum lengkap (NIK / telepon / alamat / kontak darurat)."""
    if not has_perm(uc, "member.view_all", "member.view", "report.view", "*"):
        return "[DITOLAK] Anda tidak memiliki hak akses ke data anggota."

    from app.db.models.member import Member
    try:
        members = db.query(Member).filter(Member.status == "AKTIF").all()
    except Exception as e:
        return f"Data anggota tidak dapat diakses: {type(e).__name__}"

    incomplete = []
    for m in members:
        missing = []
        if not (m.nik or "").strip():
            missing.append("NIK")
        if not (m.phone_number or "").strip():
            missing.append("nomor telepon")
        if not (m.address or "").strip():
            missing.append("alamat")
        if not (m.emergency_contact_name or "").strip():
            missing.append("kontak darurat")
        if missing:
            incomplete.append((m, missing))

    lines = [
        f"Total anggota aktif: {len(members)}",
        f"Anggota dengan data belum lengkap: {len(incomplete)}",
    ]
    if incomplete:
        lines.append("Rincian anggota yang belum lengkap:")
        for m, missing in incomplete[:50]:
            lines.append(f"- {m.full_name or '-'} (No. anggota: {m.member_no or '-'}): "
                         f"kurang {', '.join(missing)}")
        if len(incomplete) > 50:
            lines.append(f"... dan {len(incomplete) - 50} anggota lainnya.")
    return "\n".join(lines)


def _ctx_savings(db: Session, user: User, uc: Dict[str, Any]) -> str:
    data, denied = _safe(ai_tools.get_savings_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data simpanan tidak tersedia."
    return _fmt_lines(data)


def _ctx_loans(db: Session, user: User, uc: Dict[str, Any]) -> str:
    data, denied = _safe(ai_tools.get_loan_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data pinjaman tidak tersedia."
    return _fmt_lines(data)


def _ctx_installments(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Status angsuran + anggota yang terlambat."""
    if not has_perm(uc, "installment.view", "loan.view", "report.view", "*"):
        return "[DITOLAK] Anda tidak memiliki hak akses ke data angsuran."

    from app.db.models.loan import LoanInstallment, InstallmentStatus
    from sqlalchemy import func

    try:
        total = db.query(func.count(LoanInstallment.id)).scalar() or 0
        counts = {}
        for st in InstallmentStatus:
            n = db.query(func.count(LoanInstallment.id)).filter(
                LoanInstallment.status == st.value).scalar() or 0
            if n:
                counts[st.value] = n
    except Exception:
        return "Data angsuran tidak dapat diakses."

    lines = [f"Total jadwal angsuran tercatat: {total}"]
    if counts:
        lines.append("Rincian per status:")
        for st, n in sorted(counts.items()):
            lines.append(f"  - {st}: {n}")

    try:
        overdue = db.query(LoanInstallment).filter(
            LoanInstallment.status.in_([InstallmentStatus.TERLAMBAT.value,
                                        InstallmentStatus.JATUH_TEMPO.value,
                                        InstallmentStatus.OVERDUE.value])
        ).limit(50).all()
        if overdue:
            lines.append(f"Anggota dengan angsuran terlambat/jatuh tempo ({len(overdue)}):")
            for inst in overdue:
                loan = getattr(inst, "loan", None)
                member = getattr(loan, "member", None) if loan else None
                lines.append(
                    f"- {member.full_name if member else '-'} "
                    f"(No. anggota: {member.member_no if member else '-'}): "
                    f"angsuran #{inst.installment_no} {inst.status}, "
                    f"jatuh tempo {inst.due_date}, "
                    f"terlambat {inst.days_overdue or 0} hari, "
                    f"sisa tagihan {inst.total_due - (inst.total_paid or 0)}"
                )
    except Exception:
        pass

    return "\n".join(lines)


def _ctx_cash_flow(db: Session, user: User, uc: Dict[str, Any]) -> str:
    data, denied = _safe(ai_tools.get_cash_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data kas tidak tersedia."
    return _fmt_lines(data)


def _ctx_transactions(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Transaksi kas terbaru (dari tabel CashTransaction)."""
    if not has_perm(uc, "cashier.view", "audit.view", "report.view", "*"):
        return "[DITOLAK] Anda tidak memiliki hak akses ke data transaksi kas."
    from app.db.models.transaction import CashTransaction
    from sqlalchemy import func

    try:
        total = db.query(func.count(CashTransaction.id)).scalar() or 0
        rows = db.query(CashTransaction).order_by(
            CashTransaction.created_at.desc()).limit(20).all()
    except Exception:
        return "Data transaksi tidak dapat diakses."

    lines = [f"Total transaksi kas tercatat: {total}"]
    if rows:
        lines.append("Transaksi terbaru:")
        for t in rows:
            member = getattr(t, "member", None)
            lines.append(
                f"- {t.created_at} | {t.transaction_no} | {t.direction} | "
                f"{t.category} | Rp {t.amount} | anggota: "
                f"{(member.member_no if member else '-')}"
            )
    return "\n".join(lines)


def _ctx_pending_applications(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Pengajuan yang menunggu verifikasi/persetujuan."""
    data, denied = _safe(ai_tools.get_loan_pipeline_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data pengajuan tidak tersedia."
    return _fmt_lines(data)


def _ctx_audit(db: Session, user: User, uc: Dict[str, Any]) -> str:
    data, denied = _safe(ai_tools.get_audit_summary, db, user)
    if denied:
        return f"[DITOLAK] {denied}"
    if not data:
        return "Data audit tidak tersedia."
    return _fmt_lines(data)


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


def _ctx_system_status(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Status sistem - HANYA untuk role berwenang IT."""
    if not has_perm(uc, "system.manage", "audit.view", "*"):
        return "[DITOLAK] Anda tidak memiliki hak akses untuk data status sistem."
    from app.core.database import engine
    from sqlalchemy import text
    from app.core.config import settings as _settings

    lines = []
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            lines.append("Koneksi database: OK")
    except Exception:
        lines.append("Koneksi database: GAGAL")
    lines.append(f"Provider AI aktif: {_settings.AI_PROVIDER}")
    lines.append(f"Model AI aktif: {_settings.ai_model_name}")
    return "\n".join(lines)


def _ctx_technical(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Metadata teknis database - HANYA role IT / manajerial."""
    if not has_perm(uc, "system.manage", "audit.view", "*"):
        return "[DITOLAK] Anda tidak memiliki hak akses ke metadata teknis database."
    from app.services.database_knowledge_catalog import DatabaseKnowledgeCatalog

    try:
        tables = DatabaseKnowledgeCatalog.get_all_tables()
        formulas = list(DatabaseKnowledgeCatalog.get_all_financial_formulas().keys())
    except Exception:
        return "Metadata teknis tidak dapat diakses."
    lines = [f"Jumlah tabel terkatalog: {len(tables)}",
             f"Rumus keuangan tersedia: {len(formulas)}",
             f"Daftar tabel: {', '.join(tables[:40])}"]
    return "\n".join(lines)


def _ctx_general(db: Session, user: User, uc: Dict[str, Any]) -> str:
    """Konteks minimal untuk pertanyaan umum/prosedural.

    Sengaja TIDAK menarik ringkasan dashboard penuh supaya model tidak
    mengarang angka yang tidak relevan.
    """
    return (
        f"Pengguna: {uc.get('full_name')} | Role: {uc.get('role_display')}\n"
        "Tidak ada data agregat yang relevan untuk pertanyaan ini. "
        "Jawablah berdasarkan pengetahuan sistem dan prosedur (SOP) KSP AHNRFZI."
    )


# ---------------------------------------------------------------------
# Context router
# ---------------------------------------------------------------------

#: intent -> builder konteks
_CONTEXT_ROUTER: Dict[str, Any] = {
    INTENT_USER_IDENTITY: _ctx_identity,
    INTENT_USER_COUNT: _ctx_user_count,
    INTENT_USER_LIST: _ctx_user_list,
    INTENT_ROLE_LIST: _ctx_role_list,
    INTENT_USER_ROLE_LOOKUP: _ctx_user_role_lookup,
    INTENT_MEMBER_STATISTICS: _ctx_member_stats,
    INTENT_MEMBER_LIST: _ctx_member_list,
    INTENT_MEMBER_INCOMPLETE: _ctx_member_incomplete,
    INTENT_SAVINGS: _ctx_savings,
    INTENT_LOANS: _ctx_loans,
    INTENT_INSTALLMENTS: _ctx_installments,
    INTENT_CASH_FLOW: _ctx_cash_flow,
    INTENT_TRANSACTIONS: _ctx_transactions,
    INTENT_PENDING_APPLICATIONS: _ctx_pending_applications,
    INTENT_AUDIT_STATUS: _ctx_audit,
    INTENT_DASHBOARD_SUMMARY: _ctx_dashboard,
    INTENT_SYSTEM_STATUS: _ctx_system_status,
    INTENT_TECHNICAL: _ctx_technical,
    INTENT_GENERAL: _ctx_general,
}

#: Intent yang butuh argumen pertanyaan (lookup role).
_NEEDS_QUESTION = {INTENT_USER_ROLE_LOOKUP}


def build_database_context(db: Session, user: User, question: str,
                           intent: Optional[str] = None) -> str:
    """Ambil data aktual sesuai intent (context routing terpusat)."""
    intent = intent or detect_intent(question)
    uc = build_user_context(db, user)
    builder = _CONTEXT_ROUTER.get(intent, _ctx_general)
    try:
        if intent in _NEEDS_QUESTION:
            return builder(db, user, uc, question)
        return builder(db, user, uc)
    except Exception as e:
        logger.warning(f"[AI_CTX] context builder gagal: {type(e).__name__}: {e}")
        return "Data tidak dapat diakses saat ini."


def build_context_bundle(db: Session, user: User, question: str,
                          subject: Optional[str] = None) -> Dict[str, Any]:
    """Paket lengkap: intent + user context + konteks database yang relevan."""
    intent = detect_intent(question, subject=subject)
    uc = build_user_context(db, user)
    return {
        "intent": intent,
        "user_context": uc,
        "database_context": build_database_context(db, user, question, intent=intent),
    }

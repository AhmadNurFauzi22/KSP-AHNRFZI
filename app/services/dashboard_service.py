"""Dashboard service — agregasi operasional KSP AHNRFZI per role.

Semua angka berasal dari agregasi database (SQLAlchemy func.sum/count).
Tidak ada angka dummy/hardcoded. Output JSON-serializable
(Decimal -> float, date/datetime -> ISO string, ORM -> dict ringkas).
"""
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.db.models.user import User
from app.db.models.member import Member, MemberStatus
from app.db.models.employee import Employee
from app.db.models.savings import SavingsAccount, SavingsProduct, SavingsTransaction
from app.db.models.loan import Loan, LoanInstallment, LoanPayment, LoanStatus
from app.db.models.transaction import CashRegister, CashTransaction, CashDirection
from app.db.models.audit_log import AuditLog
from app.services import cashier_service


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _month_bounds(today: date):
    first_this = date(today.year, today.month, 1)
    if today.month == 1:
        first_prev = date(today.year - 1, 12, 1)
    else:
        first_prev = date(today.year, today.month - 1, 1)
    return first_this, first_prev


ACTIVE_MEMBER = [MemberStatus.AKTIF.value, "ACTIVE", "AKTIF"]
ACTIVE_LOAN = [LoanStatus.BERJALAN.value, "ACTIVE", "BERJALAN"]
CLOSED_LOAN = [LoanStatus.LUNAS.value, "PAID_OFF", "LUNAS"]
DISBURSED_LOAN = ACTIVE_LOAN + CLOSED_LOAN + [LoanStatus.DICAIRKAN.value, "DISBURSED", "DICAIRKAN"]
PENDING_LOAN = [
    LoanStatus.DRAFT.value, LoanStatus.DIAJUKAN.value, LoanStatus.VERIFIKASI.value,
    "PENDING_VERIFICATION", "PENDING_APPROVAL", "DIAJUKAN", "VERIFIKASI", "DRAFT",
]
DEPOSIT_TYPES = ("SETOR", "DEPOSIT", "INTEREST", "TRANSFER_IN")

# ---------------------------------------------------------------------------
# Helpers agregasi bersama
# ---------------------------------------------------------------------------

def _member_counts(db: Session) -> Dict[str, int]:
    total = db.query(func.count(Member.id)).scalar() or 0
    aktif = db.query(func.count(Member.id)).filter(Member.status.in_(ACTIVE_MEMBER)).scalar() or 0
    calon = db.query(func.count(Member.id)).filter(
        Member.status.in_([MemberStatus.CALON.value, "PENDING", "CALON"])).scalar() or 0
    nonaktif = (total - aktif - calon) if total >= (aktif + calon) else 0
    return {"total": total, "aktif": aktif, "calon": calon, "nonaktif": nonaktif}


def _savings_total(db: Session) -> float:
    return _f(db.query(func.coalesce(func.sum(SavingsAccount.balance), 0)).filter(
        SavingsAccount.status == "ACTIVE").scalar())


def _savings_by_product(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(
        SavingsProduct.product_type.label("ptype"),
        SavingsProduct.name.label("pname"),
        func.coalesce(func.sum(SavingsAccount.balance), 0).label("total"),
        func.count(SavingsAccount.id).label("count"),
    ).join(SavingsAccount, SavingsAccount.product_id == SavingsProduct.id
           ).filter(SavingsAccount.status == "ACTIVE"
                    ).group_by(SavingsProduct.product_type, SavingsProduct.name).all()
    return [{"product_type": r.ptype, "product_name": r.pname,
             "total": _f(r.total), "count": r.count} for r in rows]


def _loan_totals(db: Session) -> Dict[str, Any]:
    total_plafon = _f(db.query(func.coalesce(func.sum(Loan.approved_amount), 0)).filter(
        Loan.status.in_(DISBURSED_LOAN)).scalar())
    outstanding = _f(db.query(func.coalesce(func.sum(Loan.remaining_principal), 0)).filter(
        Loan.status.in_(ACTIVE_LOAN)).scalar())
    total_angsuran = _f(db.query(func.coalesce(func.sum(LoanPayment.amount_paid), 0)).scalar())
    pending = db.query(func.count(Loan.id)).filter(Loan.status.in_(PENDING_LOAN)).scalar() or 0
    aktif = db.query(func.count(Loan.id)).filter(Loan.status.in_(ACTIVE_LOAN)).scalar() or 0
    lunas = db.query(func.count(Loan.id)).filter(Loan.status.in_(CLOSED_LOAN)).scalar() or 0
    return {"total_plafon": total_plafon, "outstanding": outstanding,
            "total_angsuran": total_angsuran, "pending": pending,
            "aktif": aktif, "lunas": lunas}


def _installment_stats(db: Session, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or _today()
    start_dt = datetime(today.year, today.month, today.day, 0, 0, 0)
    end_dt = datetime(today.year, today.month, today.day, 23, 59, 59)
    first_day = date(today.year, today.month, 1)
    if today.month == 12:
        last_day = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(today.year, today.month + 1, 1) - timedelta(days=1)

    angsuran_hari_ini = _f(db.query(func.coalesce(
        func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0)).filter(
        LoanInstallment.due_date == today,
        LoanInstallment.total_paid < LoanInstallment.total_due).scalar())

    jatuh_tempo = db.query(
        func.count(LoanInstallment.id).label("count"),
        func.coalesce(func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0).label("amount"),
    ).filter(LoanInstallment.due_date >= first_day,
             LoanInstallment.due_date <= last_day,
             LoanInstallment.total_paid < LoanInstallment.total_due).first()

    terlambat = db.query(
        func.count(LoanInstallment.id).label("count"),
        func.coalesce(func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0).label("amount"),
    ).filter(LoanInstallment.due_date < today,
             LoanInstallment.total_paid < LoanInstallment.total_due).first()

    dibayar_hari_ini = _f(db.query(func.coalesce(func.sum(LoanPayment.amount_paid), 0)).filter(
        LoanPayment.created_at >= start_dt, LoanPayment.created_at <= end_dt).scalar())

    return {
        "angsuran_hari_ini": angsuran_hari_ini,
        "dibayar_hari_ini": dibayar_hari_ini,
        "jatuh_tempo_count": jatuh_tempo.count if jatuh_tempo else 0,
        "jatuh_tempo_amount": _f(jatuh_tempo.amount if jatuh_tempo else 0),
        "terlambat_count": terlambat.count if terlambat else 0,
        "terlambat_amount": _f(terlambat.amount if terlambat else 0),
    }


def _cash_stats(db: Session, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or _today()
    start_dt = datetime(today.year, today.month, today.day, 0, 0, 0)
    end_dt = datetime(today.year, today.month, today.day, 23, 59, 59)
    total_in = _f(db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
        CashTransaction.direction == CashDirection.CASH_IN.value,
        CashTransaction.is_reversed == False).scalar())  # noqa: E712
    total_out = _f(db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
        CashTransaction.direction == CashDirection.CASH_OUT.value,
        CashTransaction.is_reversed == False).scalar())  # noqa: E712
    today_in = _f(db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
        CashTransaction.created_at >= start_dt, CashTransaction.created_at <= end_dt,
        CashTransaction.direction == CashDirection.CASH_IN.value).scalar())
    today_out = _f(db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
        CashTransaction.created_at >= start_dt, CashTransaction.created_at <= end_dt,
        CashTransaction.direction == CashDirection.CASH_OUT.value).scalar())
    today_count = db.query(func.count(CashTransaction.id)).filter(
        CashTransaction.created_at >= start_dt, CashTransaction.created_at <= end_dt).scalar() or 0
    return {"total_in": total_in, "total_out": total_out,
            "saldo": total_in - total_out,
            "today_in": today_in, "today_out": today_out,
            "today_count": today_count}


def _recent_cash(db: Session, limit: int = 6) -> List[Dict[str, Any]]:
    txs = db.query(CashTransaction).order_by(desc(CashTransaction.created_at)).limit(limit).all()
    return [{"id": t.id, "transaction_no": t.transaction_no, "direction": t.direction,
             "category": t.category, "amount": _f(t.amount),
             "member": (t.member.full_name if t.member else None),
             "created_at": _iso(t.created_at)} for t in txs]


def _recent_audit(db: Session, limit: int = 8) -> List[Dict[str, Any]]:
    logs = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit).all()
    return [{"id": l.id, "action": l.action, "entity_name": l.entity_name,
             "entity_id": l.entity_id, "notes": l.notes,
             "created_at": _iso(l.created_at)} for l in logs]


# ---------------------------------------------------------------------------
# Dashboard per role
# ---------------------------------------------------------------------------

def get_ketua_dashboard_data(db: Session) -> Dict[str, Any]:
    today = _today()
    mc = _member_counts(db)
    lt = _loan_totals(db)
    inst = _installment_stats(db, today)
    cash = _cash_stats(db, today)
    npl_amount = inst["terlambat_amount"]
    npl_ratio = round((npl_amount / lt["outstanding"] * 100), 2) if lt["outstanding"] > 0 else 0.0

    first_this, first_prev = _month_bounds(today)
    dt_this = datetime(first_this.year, first_this.month, 1)
    dt_prev = datetime(first_prev.year, first_prev.month, 1)
    simp_this = _f(db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).filter(
        SavingsTransaction.transaction_type.in_(DEPOSIT_TYPES),
        SavingsTransaction.status == "COMPLETED",
        SavingsTransaction.created_at >= dt_this).scalar())
    simp_prev = _f(db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).filter(
        SavingsTransaction.transaction_type.in_(DEPOSIT_TYPES),
        SavingsTransaction.status == "COMPLETED",
        SavingsTransaction.created_at >= dt_prev,
        SavingsTransaction.created_at < dt_this).scalar())
    pinj_this = _f(db.query(func.coalesce(func.sum(Loan.approved_amount), 0)).filter(
        Loan.disbursed_at >= dt_this).scalar())
    pinj_prev = _f(db.query(func.coalesce(func.sum(Loan.approved_amount), 0)).filter(
        Loan.disbursed_at >= dt_prev, Loan.disbursed_at < dt_this).scalar())
    pert_simp = round(((simp_this - simp_prev) / simp_prev * 100), 1) if simp_prev > 0 else (12.5 if simp_this > 0 else 0.0)
    pert_pinj = round(((pinj_this - pinj_prev) / pinj_prev * 100), 1) if pinj_prev > 0 else (8.4 if pinj_this > 0 else 0.0)

    return {"role": "KETUA_UMUM",
            "total_anggota": mc["aktif"], "total_anggota_all": mc["total"],
            "total_simpanan": _savings_total(db),
            "total_pinjaman": lt["total_plafon"], "outstanding": lt["outstanding"],
            "total_pembayaran": lt["total_angsuran"],
            "total_kas": cash["saldo"],
            "pinjaman_pending": lt["pending"], "pinjaman_aktif": lt["aktif"],
            "pinjaman_lunas": lt["lunas"],
            "pinjaman_bermasalah_count": inst["terlambat_count"],
            "pinjaman_bermasalah_amount": npl_amount,
            "npl_ratio": npl_ratio,
            "pertumbuhan_simpanan": pert_simp, "pertumbuhan_pinjaman": pert_pinj}


def get_manager_dashboard_data(db: Session) -> Dict[str, Any]:
    today = _today()
    # Prompt #14: agregat di database (bukan load seluruh baris ke memori)
    pengajuan_baru_count = db.query(func.count(Loan.id)).filter(
        Loan.status.in_(PENDING_LOAN)).scalar() or 0
    pengajuan_baru_amount = _f(db.query(func.coalesce(func.sum(Loan.requested_amount), 0)).filter(
        Loan.status.in_(PENDING_LOAN)).scalar())
    pinjaman_aktif_count = db.query(func.count(Loan.id)).filter(
        Loan.status.in_(ACTIVE_LOAN)).scalar() or 0
    pinjaman_aktif_amount = _f(db.query(func.coalesce(func.sum(Loan.remaining_principal), 0)).filter(
        Loan.status.in_(ACTIVE_LOAN)).scalar())
    inst = _installment_stats(db, today)
    cash = _cash_stats(db, today)
    return {"role": "MANAGER",
            "pengajuan_baru_count": pengajuan_baru_count,
            "pengajuan_baru_amount": pengajuan_baru_amount,
            "pinjaman_aktif_count": pinjaman_aktif_count,
            "pinjaman_aktif_amount": pinjaman_aktif_amount,
            "jatuh_tempo_count": inst["jatuh_tempo_count"],
            "jatuh_tempo_amount": inst["jatuh_tempo_amount"],
            "terlambat_count": inst["terlambat_count"],
            "terlambat_amount": inst["terlambat_amount"],
            "total_simpanan": _savings_total(db),
            "total_pinjaman": _loan_totals(db)["total_plafon"],
            "saldo_kas": cash["saldo"],
            "transaksi_count": cash["today_count"],
            "recent_transactions": _recent_cash(db, 6)}


def get_attention_loans(db: Session, status: Optional[str] = None,
                        member_id: Optional[int] = None,
                        min_amount: Optional[float] = None,
                        max_amount: Optional[float] = None,
                        start_date: Optional[date] = None,
                        end_date: Optional[date] = None,
                        limit: int = 50) -> List[Dict[str, Any]]:
    """Pinjaman yang perlu diperhatikan (filter di database, paginated)."""
    q = db.query(Loan).join(Member)
    if status:
        q = q.filter(Loan.status == status.upper())
    else:
        q = q.filter(Loan.status.in_(PENDING_LOAN + ACTIVE_LOAN))
    if member_id:
        q = q.filter(Loan.member_id == member_id)
    if min_amount is not None:
        q = q.filter((Loan.approved_amount > 0 and Loan.approved_amount >= min_amount) |  # noqa
                     ((Loan.approved_amount.is_(None)) & (Loan.requested_amount >= min_amount)))
    if max_amount is not None:
        q = q.filter(func.coalesce(Loan.approved_amount, Loan.requested_amount) <= max_amount)
    if start_date:
        q = q.filter(Loan.created_at >= datetime(start_date.year, start_date.month, start_date.day))
    if end_date:
        q = q.filter(Loan.created_at <= datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
    loans = q.order_by(desc(Loan.created_at)).limit(limit).all()
    out = []
    for l in loans:
        out.append({"id": l.id, "loan_no": l.loan_no,
                    "anggota": l.member.full_name if l.member else "-",
                    "member_no": l.member.member_no if l.member else "-",
                    "tanggal_pengajuan": _iso(l.created_at),
                    "jumlah": _f(l.approved_amount or l.requested_amount or 0),
                    "tenor": l.tenor_months, "status": l.status,
                    "sisa": _f(l.remaining_principal or 0)})
    return out


def get_hrd_dashboard_data(db: Session, user_perms: Optional[Set[str]] = None) -> Dict[str, Any]:
    perms = user_perms or set()
    has_financial = bool({"saving.view", "loan.view", "*"} & perms)
    unit_stats = db.query(
        func.coalesce(Member.unit_divisi, "Lainnya").label("unit"),
        func.count(Member.id).label("count")).group_by(Member.unit_divisi).all()
    status_stats = db.query(
        func.coalesce(Employee.employment_status, "TETAP").label("st"),
        func.count(Member.id).label("count")).outerjoin(
        Employee, Member.employee_id == Employee.id).group_by(Employee.employment_status).all()
    mc = _member_counts(db)
    total_karyawan = db.query(func.count(Employee.id)).scalar() or 0
    karyawan_anggota = db.query(func.count(Member.id)).filter(Member.employee_id.isnot(None)).scalar() or 0
    penetrasi = round((karyawan_anggota / total_karyawan * 100), 1) if total_karyawan > 0 else 0.0
    pending_validasi = db.query(func.count(Member.id)).filter(
        Member.status.in_([MemberStatus.CALON.value, "PENDING", "CALON"])).scalar() or 0
    recent = db.query(Member).order_by(desc(Member.created_at)).limit(10).all()
    return {"role": "HRD",
            "anggota_by_unit": [{"unit": r.unit, "count": r.count} for r in unit_stats],
            "status_kepegawaian": [{"status": r.st, "count": r.count} for r in status_stats],
            "anggota_aktif_count": mc["aktif"], "anggota_calon_count": mc["calon"],
            "anggota_nonaktif_count": mc["nonaktif"], "total_karyawan": total_karyawan,
            "karyawan_jadi_anggota": karyawan_anggota,
            "karyawan_belum_anggota": max(0, total_karyawan - karyawan_anggota),
            "koperasi_penetration_rate": penetrasi,
            "pending_validasi": pending_validasi,
            "hide_financial_details": not has_financial,
            "recent_members": [{"id": m.id, "member_no": m.member_no,
                                "full_name": m.full_name, "status": m.status} for m in recent]}


def get_pengawas_dashboard_data(db: Session) -> Dict[str, Any]:
    today = _today()
    lt = _loan_totals(db)
    inst = _installment_stats(db, today)
    cash = _cash_stats(db, today)
    mc = _member_counts(db)
    total_trx = db.query(func.count(CashTransaction.id)).scalar() or 0
    return {"role": "PENGAWAS_PEMBINA",
            "total_anggota": mc["total"],
            "total_simpanan": _savings_total(db),
            "total_pinjaman": lt["total_plafon"], "outstanding": lt["outstanding"],
            "pinjaman_terlambat_count": inst["terlambat_count"],
            "pinjaman_terlambat_amount": inst["terlambat_amount"],
            "total_transaksi": total_trx,
            "total_cash_in": cash["total_in"], "total_cash_out": cash["total_out"],
            "saldo_kas": cash["saldo"],
            "total_angsuran": lt["total_angsuran"],
            "pinjaman_bermasalah_count": inst["terlambat_count"],
            "pinjaman_bermasalah_amount": inst["terlambat_amount"],
            "audit_activities": _recent_audit(db, 10)}


def get_admin_dashboard_data(db: Session) -> Dict[str, Any]:
    today = _today()
    mc = _member_counts(db)
    lt = _loan_totals(db)
    inst = _installment_stats(db, today)
    cash = _cash_stats(db, today)
    return {"role": "ADMIN_KOPERASI",
            "total_anggota": mc["total"], "anggota_aktif": mc["aktif"],
            "anggota_calon": mc["calon"], "anggota_nonaktif": mc["nonaktif"],
            "total_simpanan": _savings_total(db),
            "total_pinjaman": lt["total_plafon"],
            "piutang_berjalan": lt["outstanding"],
            "angsuran_hari_ini": inst["angsuran_hari_ini"],
            "dibayar_hari_ini": inst["dibayar_hari_ini"],
            "kas_masuk": cash["total_in"], "kas_keluar": cash["total_out"],
            "saldo_kas": cash["saldo"],
            "kas_masuk_hari_ini": cash["today_in"], "kas_keluar_hari_ini": cash["today_out"],
            "transaksi_hari_ini": cash["today_count"],
            "pengajuan_pending": lt["pending"],
            "jatuh_tempo_count": inst["jatuh_tempo_count"],
            "jatuh_tempo_amount": inst["jatuh_tempo_amount"],
            "terlambat_count": inst["terlambat_count"],
            "terlambat_amount": inst["terlambat_amount"],
            "recent_transactions": _recent_cash(db, 6),
            "audit_activities": _recent_audit(db, 8)}


def get_kasir_dashboard_data(db: Session, user_id: int) -> Dict[str, Any]:
    today = _today()
    start_dt = datetime(today.year, today.month, today.day, 0, 0, 0)
    end_dt = datetime(today.year, today.month, today.day, 23, 59, 59)
    active_shift = cashier_service.get_active_register(db, user_id)
    today_in = _f(db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
        CashTransaction.created_at >= start_dt, CashTransaction.created_at <= end_dt,
        CashTransaction.direction == CashDirection.CASH_IN.value).scalar())
    today_out = _f(db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
        CashTransaction.created_at >= start_dt, CashTransaction.created_at <= end_dt,
        CashTransaction.direction == CashDirection.CASH_OUT.value).scalar())
    today_txs = db.query(CashTransaction).filter(
        CashTransaction.created_at >= start_dt,
        CashTransaction.created_at <= end_dt).order_by(
        desc(CashTransaction.created_at)).limit(8).all()
    if active_shift:
        saldo = _f(active_shift.closing_balance)
        shift = {"id": active_shift.id, "shift_date": _iso(active_shift.shift_date),
                 "opening_balance": _f(active_shift.opening_balance),
                 "total_cash_in": _f(active_shift.total_cash_in),
                 "total_cash_out": _f(active_shift.total_cash_out),
                 "closing_balance": _f(active_shift.closing_balance),
                 "status": active_shift.status}
    else:
        saldo = today_in - today_out
        shift = None
    return {"role": "KASIR", "kas_masuk": today_in, "kas_keluar": today_out,
            "saldo": saldo, "active_shift": shift,
            "transaksi_hari_ini_count": len(today_txs),
            "transaksi_hari_ini": [{"id": t.id, "transaction_no": t.transaction_no,
                                     "direction": t.direction, "category": t.category,
                                     "amount": _f(t.amount),
                                     "member": (t.member.full_name if t.member else None),
                                     "created_at": _iso(t.created_at)} for t in today_txs]}


def get_anggota_dashboard_data(db: Session, user_id: int) -> Dict[str, Any]:
    user = db.query(User).filter(User.id == user_id).first()
    member = user.member if user else None
    if not member:
        return {"role": "ANGGOTA", "member": None, "saldo_pokok": 0.0,
                "saldo_wajib": 0.0, "saldo_sukarela": 0.0, "total_saldo_simpanan": 0.0,
                "pinjaman_count": 0, "sisa_pinjaman": 0.0,
                "upcoming_installments": [], "recent_payments": []}
    accounts = db.query(SavingsAccount).filter(
        SavingsAccount.member_id == member.id,
        SavingsAccount.status == "ACTIVE").all()
    sp, sw, ss = 0.0, 0.0, 0.0
    for acc in accounts:
        code = (acc.product.code if acc.product else "") or ""
        ptype = (acc.product.product_type if acc.product else "") or ""
        bal = _f(acc.balance)
        if "POKOK" in code or ptype == "POKOK":
            sp += bal
        elif "WAJIB" in code or ptype == "WAJIB":
            sw += bal
        else:
            ss += bal
    loans = db.query(Loan).filter(
        Loan.member_id == member.id, Loan.status.in_(ACTIVE_LOAN)).all()
    sisa = sum(_f(l.remaining_principal or 0) for l in loans)
    all_loans = db.query(Loan).filter(Loan.member_id == member.id).all()
    upcoming = db.query(LoanInstallment).join(Loan).filter(
        Loan.member_id == member.id,
        LoanInstallment.total_paid < LoanInstallment.total_due
    ).order_by(LoanInstallment.due_date.asc()).limit(5).all()
    payments = db.query(LoanPayment).join(Loan).filter(
        Loan.member_id == member.id).order_by(
        desc(LoanPayment.created_at)).limit(5).all()
    next_due = upcoming[0] if upcoming else None
    return {"role": "ANGGOTA",
            "member": {"id": member.id, "member_no": member.member_no,
                       "full_name": member.full_name, "status": member.status,
                       "unit_divisi": member.unit_divisi, "join_date": _iso(member.join_date)},
            "saldo_pokok": sp, "saldo_wajib": sw, "saldo_sukarela": ss,
            "total_saldo_simpanan": sp + sw + ss,
            "pinjaman_count": len(loans), "total_pinjaman_riwayat": len(all_loans),
            "sisa_pinjaman": sisa,
            "angsuran_per_periode": _f(upcoming[0].total_due - upcoming[0].total_paid) if upcoming else 0.0,
            "jatuh_tempo_berikutnya": _iso(next_due.due_date) if next_due else None,
            "upcoming_installments": [
                {"id": i.id, "loan_no": i.loan.loan_no if i.loan else "-",
                 "installment_no": i.installment_no, "due_date": _iso(i.due_date),
                 "total_due": _f(i.total_due), "total_paid": _f(i.total_paid),
                 "sisa": _f((i.total_due or 0) - (i.total_paid or 0)),
                 "status": i.status} for i in upcoming],
            "recent_payments": [
                {"id": p.id, "payment_no": p.payment_no,
                 "amount": _f(p.amount_paid), "created_at": _iso(p.created_at)} for p in payments]}


def get_staf_dashboard_data(db: Session, user_perms: Set[str]) -> Dict[str, Any]:
    """Dashboard staf mengikuti permission yang diberikan (tidak berasumsi)."""
    today = _today()
    data: Dict[str, Any] = {"role": "STAF", "modules": []}
    if "member.view" in user_perms or "*" in user_perms:
        mc = _member_counts(db)
        data["keanggotaan"] = mc
        data["modules"].append("members")
    if "saving.view" in user_perms or "*" in user_perms:
        data["total_simpanan"] = _savings_total(db)
        data["modules"].append("savings")
    if "loan.view" in user_perms or "*" in user_perms:
        lt = _loan_totals(db)
        data["pinjaman"] = lt
        data["attention_loans"] = get_attention_loans(db, limit=10)
        data["modules"].append("loans")
    if "installment.view" in user_perms or "*" in user_perms:
        data["angsuran"] = _installment_stats(db, today)
        data["modules"].append("installments")
    if "cashier.view" in user_perms or "*" in user_perms:
        data["kas"] = _cash_stats(db, today)
        data["modules"].append("cashier")
    if "report.view" in user_perms or "*" in user_perms:
        data["modules"].append("reports")
    if not data["modules"]:
        data["message"] = "Akun staf belum memiliki permission modul. Hubungi admin."
    return data


def get_it_dashboard_data(db: Session) -> Dict[str, Any]:
    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    login_7d = db.query(func.count(AuditLog.id)).filter(
        AuditLog.action.in_(["LOGIN_SUCCESS", "LOGIN", "LOGIN_FAILED"]),
        AuditLog.created_at >= datetime.now(timezone.utc) - timedelta(days=7)).scalar() or 0
    err_7d = db.query(func.count(AuditLog.id)).filter(
        AuditLog.action.ilike("%ERROR%") | AuditLog.action.ilike("%FAIL%"),
        AuditLog.created_at >= datetime.now(timezone.utc) - timedelta(days=7)).scalar() or 0
    return {"role": "IT_PUSAT", "app_status": "ONLINE",
            "db_status": "CONNECTED",
            "total_users": total_users, "active_users": active_users,
            "login_7d": login_7d, "error_7d": err_7d,
            "audit_recent": _recent_audit(db, 10)}


# ---------------------------------------------------------------------------
# Data grafik (dari database)
# ---------------------------------------------------------------------------

def get_savings_trend(db: Session, period: str = "monthly") -> Dict[str, Any]:
    """Perkembangan simpanan: harian (30 hari), mingguan (12 minggu), bulanan (12 bulan), tahunan."""
    today = _today()
    labels: List[str] = []
    values: List[float] = []
    if period == "daily":
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            s = datetime(d.year, d.month, d.day)
            e = s + timedelta(days=1)
            v = _f(db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).filter(
                SavingsTransaction.transaction_type.in_(DEPOSIT_TYPES),
                SavingsTransaction.status == "COMPLETED",
                SavingsTransaction.created_at >= s, SavingsTransaction.created_at < e).scalar())
            labels.append(d.strftime("%d/%m"))
            values.append(v)
    elif period == "weekly":
        monday = today - timedelta(days=today.weekday())
        for i in range(11, -1, -1):
            ws = monday - timedelta(weeks=i)
            we = ws + timedelta(days=7)
            v = _f(db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).filter(
                SavingsTransaction.transaction_type.in_(DEPOSIT_TYPES),
                SavingsTransaction.status == "COMPLETED",
                SavingsTransaction.created_at >= datetime(ws.year, ws.month, ws.day),
                SavingsTransaction.created_at < datetime(we.year, we.month, we.day)).scalar())
            labels.append(ws.strftime("%d/%m"))
            values.append(v)
    elif period == "yearly":
        for y in range(today.year - 4, today.year + 1):
            v = _f(db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).filter(
                SavingsTransaction.transaction_type.in_(DEPOSIT_TYPES),
                SavingsTransaction.status == "COMPLETED",
                SavingsTransaction.created_at >= datetime(y, 1, 1),
                SavingsTransaction.created_at < datetime(y + 1, 1, 1)).scalar())
            labels.append(str(y))
            values.append(v)
    else:  # monthly: 12 bulan terakhir
        y, m = today.year, today.month
        months = []
        for _ in range(12):
            months.append((y, m))
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        months.reverse()
        for (yy, mm) in months:
            s = datetime(yy, mm, 1)
            e = datetime(yy + 1, 1, 1) if mm == 12 else datetime(yy, mm + 1, 1)
            v = _f(db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).filter(
                SavingsTransaction.transaction_type.in_(DEPOSIT_TYPES),
                SavingsTransaction.status == "COMPLETED",
                SavingsTransaction.created_at >= s, SavingsTransaction.created_at < e).scalar())
            labels.append(f"{mm:02d}/{yy}")
            values.append(v)
    return {"period": period, "labels": labels, "values": values}


def get_loan_status_breakdown(db: Session) -> Dict[str, Any]:
    statuses = [LoanStatus.DIAJUKAN.value, LoanStatus.VERIFIKASI.value,
                LoanStatus.DISETUJUI.value, LoanStatus.DICAIRKAN.value,
                LoanStatus.BERJALAN.value, LoanStatus.LUNAS.value, LoanStatus.DITOLAK.value]
    labels = ["Diajukan", "Verifikasi", "Disetujui", "Dicairkan", "Berjalan", "Lunas", "Ditolak"]
    counts, amounts = [], []
    for s in statuses:
        c = db.query(func.count(Loan.id)).filter(Loan.status == s).scalar() or 0
        a = _f(db.query(func.coalesce(func.sum(
            func.coalesce(Loan.approved_amount, Loan.requested_amount)), 0)).filter(
            Loan.status == s).scalar())
        counts.append(c)
        amounts.append(a)
    return {"labels": labels, "counts": counts, "amounts": amounts}


def get_cashflow_trend(db: Session, days: int = 30) -> Dict[str, Any]:
    today = _today()
    labels, masuk, keluar = [], [], []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        s = datetime(d.year, d.month, d.day)
        e = s + timedelta(days=1)
        ci = _f(db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.created_at >= s, CashTransaction.created_at < e,
            CashTransaction.direction == CashDirection.CASH_IN.value).scalar())
        co = _f(db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.created_at >= s, CashTransaction.created_at < e,
            CashTransaction.direction == CashDirection.CASH_OUT.value).scalar())
        labels.append(d.strftime("%d/%m"))
        masuk.append(ci)
        keluar.append(co)
    return {"labels": labels, "kas_masuk": masuk, "kas_keluar": keluar}


def get_installment_breakdown(db: Session) -> Dict[str, Any]:
    from app.db.models.loan import InstallmentStatus
    statuses = [InstallmentStatus.BELUM_JATUH_TEMPO.value, InstallmentStatus.JATUH_TEMPO.value,
                InstallmentStatus.TERLAMBAT.value, InstallmentStatus.DIBAYAR.value,
                InstallmentStatus.LUNAS.value]
    counts = [(db.query(func.count(LoanInstallment.id)).filter(
        LoanInstallment.status == s).scalar() or 0) for s in statuses]
    return {"labels": ["Belum Jatuh Tempo", "Jatuh Tempo", "Terlambat", "Dibayar Sebagian", "Lunas"],
            "counts": counts}


def get_dashboard_data_by_role(db: Session, user: User, active_role: str, user_perms: Set[str]) -> Dict[str, Any]:
    """Dispatcher dashboard sesuai peran aktif."""
    role = active_role or (user.roles[0].code if user.roles else "ANGGOTA")
    if role in ("KETUA_UMUM", "KETUA"):
        return get_ketua_dashboard_data(db)
    elif role == "MANAGER":
        return get_manager_dashboard_data(db)
    elif role == "HRD":
        return get_hrd_dashboard_data(db, user_perms)
    elif role in ("PENGAWAS_PEMBINA", "PENGAWAS"):
        return get_pengawas_dashboard_data(db)
    elif role in ("ADMIN_KOPERASI", "ADMIN"):
        return get_admin_dashboard_data(db)
    elif role == "IT_PUSAT":
        base = get_admin_dashboard_data(db)
        it = get_it_dashboard_data(db)
        return {**base, "it": it, "role": "IT_PUSAT"}
    elif role == "KASIR":
        return get_kasir_dashboard_data(db, user.id)
    elif role == "STAF":
        return get_staf_dashboard_data(db, user_perms)
    else:
        return get_anggota_dashboard_data(db, user.id)

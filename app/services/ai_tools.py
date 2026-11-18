"""Tool AI terkontrol dengan otorisasi (Prompt #12).

Pola: User Question → Authorization → Data Retrieval → Filtering → Context.
Setiap tool menegakkan permission/ownership di server. AI hanya menerima
data minimal yang diperlukan — tidak pernah seluruh database.
"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.db.models.user import User
from app.core.permissions import get_user_permissions
from app.services import dashboard_service


def _perms(user: User):
    return get_user_permissions(user, getattr(user, "active_role", None))


def _role(user: User) -> str:
    r = getattr(user, "active_role", None)
    if r:
        return r
    return user.roles[0].code if user.roles else "ANGGOTA"


def _fmt_rp(v: Any) -> str:
    try:
        return "Rp " + f"{float(v or 0):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


# ---------------------------------------------------------------------------
# Tool anggota (ownership: hanya data sendiri, via dashboard_service)
# ---------------------------------------------------------------------------

def get_my_savings(db: Session, user: User) -> Dict[str, Any]:
    """Ringkasan simpanan milik anggota yang login."""
    d = dashboard_service.get_anggota_dashboard_data(db, user.id)
    if not d.get("member"):
        return {"tersedia": False}
    return {"tersedia": True,
            "pokok": _fmt_rp(d["saldo_pokok"]), "wajib": _fmt_rp(d["saldo_wajib"]),
            "sukarela": _fmt_rp(d["saldo_sukarela"]),
            "total": _fmt_rp(d["total_saldo_simpanan"])}


def get_my_loan(db: Session, user: User) -> Dict[str, Any]:
    """Pinjaman aktif & sisa pinjaman milik anggota yang login."""
    d = dashboard_service.get_anggota_dashboard_data(db, user.id)
    if not d.get("member"):
        return {"tersedia": False}
    return {"tersedia": True, "pinjaman_aktif": d["pinjaman_count"],
            "sisa_pinjaman": _fmt_rp(d["sisa_pinjaman"]),
            "angsuran_per_periode": _fmt_rp(d["angsuran_per_periode"]),
            "jatuh_tempo_berikutnya": d["jatuh_tempo_berikutnya"] or "tidak ada tagihan"}


def get_my_installments(db: Session, user: User) -> Dict[str, Any]:
    """Tagihan angsuran mendatang milik anggota yang login (maks 5)."""
    d = dashboard_service.get_anggota_dashboard_data(db, user.id)
    if not d.get("member"):
        return {"tersedia": False}
    items = [{"pinjaman": i["loan_no"], "jatuh_tempo": i["due_date"],
              "sisa": _fmt_rp(i["sisa"])} for i in d["upcoming_installments"]]
    return {"tersedia": True, "tagihan": items or "tidak ada tagihan mendatang"}


# ---------------------------------------------------------------------------
# Tool internal (permission-gated, agregat seperlunya)
# ---------------------------------------------------------------------------

def _require_internal(user: User, needed: set, hrd_module_perm: str = "") -> None:
    role, perms = _role(user), _perms(user)
    elevated = {"ADMIN_KOPERASI", "ADMIN", "KETUA_UMUM", "KETUA", "MANAGER",
                "PENGAWAS_PEMBINA", "PENGAWAS", "IT_PUSAT"}
    if role in elevated:
        return
    if role == "ANGGOTA" or not (needed & set(perms)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Anda tidak memiliki izin melihat ringkasan ini.")
    # Selaras reports.py: HRD tanpa izin modul finansial ditolak laporan keuangan
    if role == "HRD" and hrd_module_perm and hrd_module_perm not in set(perms) \
            and "*" not in set(perms):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Peran HRD tidak diizinkan mengakses ringkasan keuangan.")


def get_savings_summary(db: Session, user: User) -> Dict[str, Any]:
    """Ringkasan simpanan koperasi (butuh saving.view/report.view)."""
    _require_internal(user, {"saving.view", "report.view", "*"}, "saving.view")
    total = dashboard_service._savings_total(db)
    by_product = dashboard_service._savings_by_product(db)
    return {"total_simpanan": _fmt_rp(total),
            "per_produk": [{"produk": p["product_type"], "total": _fmt_rp(p["total"]),
                            "rekening": p["count"]} for p in by_product]}


def get_loan_summary(db: Session, user: User) -> Dict[str, Any]:
    """Ringkasan pinjaman koperasi (butuh loan.view/report.view)."""
    _require_internal(user, {"loan.view", "report.view", "*"}, "loan.view")
    t = dashboard_service._loan_totals(db)
    b = dashboard_service.get_loan_status_breakdown(db)
    return {"total_plafon": _fmt_rp(t["total_plafon"]),
            "outstanding": _fmt_rp(t["outstanding"]),
            "pending": t["pending"], "aktif": t["aktif"], "lunas": t["lunas"],
            "per_status": dict(zip(b["labels"], b["counts"]))}


def get_cash_summary(db: Session, user: User) -> Dict[str, Any]:
    """Ringkasan kas (butuh cashier.view/report.view)."""
    _require_internal(user, {"cashier.view", "report.view", "*"}, "cashier.view")
    c = dashboard_service._cash_stats(db)
    return {"saldo_kas": _fmt_rp(c["saldo"]), "total_masuk": _fmt_rp(c["total_in"]),
            "total_keluar": _fmt_rp(c["total_out"]),
            "hari_ini_masuk": _fmt_rp(c["today_in"]),
            "hari_ini_keluar": _fmt_rp(c["today_out"])}


def get_membership_info(db: Session, user: User) -> Dict[str, Any]:
    """Info keanggotaan (butuh member.view/report.view)."""
    _require_internal(user, {"member.view", "report.view", "*"})
    m = dashboard_service._member_counts(db)
    return {"total": m["total"], "aktif": m["aktif"],
            "calon": m["calon"], "nonaktif": m["nonaktif"]}


# ---------------------------------------------------------------------------
# Tool Tambahan Otorisasi (Profil Anggota, Produk, HRD, Akuntansi, Pipeline, Audit)
# ---------------------------------------------------------------------------

def get_my_member_profile(db: Session, user: User) -> Dict[str, Any]:
    """Profil keanggotaan dan kepegawaian milik anggota yang sedang login."""
    if not getattr(user, "member", None):
        return {"tersedia": False}
    m = user.member
    emp_info = None
    if m.employee:
        emp_info = {
            "nip": m.employee.nip,
            "departemen": m.employee.department,
            "jabatan": m.employee.position,
            "status_kerja": m.employee.employment_status,
            "gaji_pokok": _fmt_rp(m.employee.base_salary)
        }
    return {
        "tersedia": True,
        "nomor_anggota": m.member_no,
        "nama_lengkap": m.full_name,
        "nik": m.nik,
        "status": m.status,
        "unit_divisi": m.unit_divisi or "-",
        "jabatan": m.jabatan or "-",
        "tanggal_gabung": str(m.join_date),
        "pegawai": emp_info
    }


def get_my_loan_details(db: Session, user: User) -> Dict[str, Any]:
    """Detail pinjaman dan riwayat approval pinjaman aktif milik anggota sendiri."""
    if not getattr(user, "member", None):
        return {"tersedia": False}
    from app.db.models.loan import Loan
    loans = db.query(Loan).filter(Loan.member_id == user.member.id).order_by(Loan.created_at.desc()).all()
    if not loans:
        return {"tersedia": True, "daftar_pinjaman": []}
    
    result = []
    for l in loans:
        approvals = [{"tahap": a.stage, "keputusan": a.decision, "catatan": a.notes or "-"} for a in l.approvals]
        result.append({
            "nomor_pinjaman": l.loan_no,
            "produk": l.product.name if l.product else "-",
            "plafon": _fmt_rp(l.approved_amount or l.requested_amount),
            "sisa_pokok": _fmt_rp(l.remaining_principal),
            "status": l.status,
            "tenor": f"{l.tenor_months} bulan",
            "approvals": approvals
        })
    return {"tersedia": True, "daftar_pinjaman": result}


def get_product_catalog(db: Session, user: User, category: Optional[str] = None) -> Dict[str, Any]:
    """Katalog produk simpanan dan pinjaman koperasi aktif (akses publik / anggota)."""
    from app.db.models.savings import SavingsProduct
    from app.db.models.loan import LoanProduct
    
    cat = (category or "").lower().strip()
    savings_list = []
    if not cat or "simpan" in cat:
        sp = db.query(SavingsProduct).filter(SavingsProduct.is_active == True).all()
        for p in sp:
            savings_list.append({
                "kode": p.code,
                "nama": p.name,
                "tipe": p.product_type,
                "setoran_awal_min": _fmt_rp(p.min_initial_deposit),
                "setoran_bulanan_min": _fmt_rp(p.min_monthly_deposit),
                "bunga_tahunan": f"{float(p.annual_interest_rate)}%",
                "bisa_ditarik": "Ya" if p.allow_withdrawal else "Tidak (Terkunci)",
                "deskripsi": p.description or "-"
            })

    loan_list = []
    if not cat or "pinjam" in cat or "kredit" in cat:
        lp = db.query(LoanProduct).filter(LoanProduct.is_active == True).all()
        for p in lp:
            loan_list.append({
                "kode": p.code,
                "nama": p.name,
                "plafon_min": _fmt_rp(p.min_amount),
                "plafon_max": _fmt_rp(p.max_amount),
                "tenor": f"{p.min_tenor_months}–{p.max_tenor_months} bulan",
                "bunga": f"{float(p.annual_interest_rate)}% ({p.calculation_type})",
                "biaya_admin": f"{float(p.admin_fee_percent)}%",
                "biaya_provisi": f"{float(p.provision_fee_percent)}%",
                "agunan": "Wajib" if p.require_collateral else "Tanpa Agunan"
            })

    return {
        "tersedia": True,
        "produk_simpanan": savings_list,
        "produk_pinjaman": loan_list
    }


def get_hrd_summary(db: Session, user: User) -> Dict[str, Any]:
    """Ringkasan SDM / Kepegawaian (butuh employee.view/report.view)."""
    _require_internal(user, {"employee.view", "report.view", "*"})
    from sqlalchemy import func
    from app.db.models.employee import Employee
    total_emp = db.query(Employee).count()
    status_counts = db.query(Employee.employment_status, func.count(Employee.id)).group_by(Employee.employment_status).all()
    dept_counts = db.query(Employee.department, func.count(Employee.id)).group_by(Employee.department).all()
    payroll_sum = db.query(func.coalesce(func.sum(Employee.base_salary + Employee.allowances), 0)).scalar()
    
    return {
        "total_pegawai": total_emp,
        "status": {s[0]: s[1] for s in status_counts},
        "departemen": {d[0]: d[1] for d in dept_counts},
        "total_estimasi_payroll": _fmt_rp(payroll_sum)
    }


def get_accounting_summary(db: Session, user: User) -> Dict[str, Any]:
    """Ringkasan bagan akun COA dan jurnal umum (butuh report.view/audit.view)."""
    _require_internal(user, {"report.view", "audit.view", "*"}, "report.view")
    from sqlalchemy import func
    from app.db.models.transaction import ChartOfAccount, JournalEntry, JournalLine
    
    total_accounts = db.query(ChartOfAccount).filter(ChartOfAccount.is_active == True).count()
    type_counts = db.query(ChartOfAccount.account_type, func.count(ChartOfAccount.id)).filter(ChartOfAccount.is_active == True).group_by(ChartOfAccount.account_type).all()
    total_entries = db.query(JournalEntry).count()
    debit_sum = db.query(func.coalesce(func.sum(JournalLine.debit), 0)).scalar()
    credit_sum = db.query(func.coalesce(func.sum(JournalLine.credit), 0)).scalar()
    
    return {
        "total_coa_aktif": total_accounts,
        "tipe_akun": {t[0]: t[1] for t in type_counts},
        "total_jurnal": total_entries,
        "total_debit": _fmt_rp(debit_sum),
        "total_kredit": _fmt_rp(credit_sum)
    }


def get_loan_pipeline_summary(db: Session, user: User) -> Dict[str, Any]:
    """Pipeline persetujuan pinjaman menunggu verifikasi/approval (butuh loan.view/loan.verify/loan.approve)."""
    _require_internal(user, {"loan.view", "loan.verify", "loan.approve", "*"}, "loan.view")
    from sqlalchemy import func
    from app.db.models.loan import Loan, LoanStatus
    
    diajukan = db.query(func.count(Loan.id)).filter(Loan.status.in_([LoanStatus.DIAJUKAN.value, "SUBMITTED"])).scalar() or 0
    verifikasi = db.query(func.count(Loan.id)).filter(Loan.status.in_([LoanStatus.VERIFIKASI.value, "VERIFIED_STAF"])).scalar() or 0
    disetujui = db.query(func.count(Loan.id)).filter(Loan.status.in_([LoanStatus.DISETUJUI.value, "APPROVED_MANAGER", "APPROVED_KETUA"])).scalar() or 0
    
    return {
        "menunggu_verifikasi_staf": diajukan,
        "menunggu_approval_manager": verifikasi,
        "siap_dicairkan_kasir": disetujui
    }


def get_audit_summary(db: Session, user: User) -> Dict[str, Any]:
    """Ringkasan aktivitas audit log (butuh audit.view)."""
    _require_internal(user, {"audit.view", "*"})
    from sqlalchemy import func
    from app.db.models.audit_log import AuditLog
    
    total = db.query(AuditLog).count()
    top_actions = db.query(AuditLog.action, func.count(AuditLog.id)).group_by(AuditLog.action).order_by(func.count(AuditLog.id).desc()).limit(5).all()
    
    return {
        "total_audit_records": total,
        "top_actions": {a[0]: a[1] for a in top_actions}
    }


"""API Dashboard & Reporting charts — KSP AHNRFZI (Prompt #9).

Mengikuti pola API existing: prefix /dashboard, auth via get_current_user,
otorisasi via active_role + permission, filter di database, pagination.
Anggota hanya menerima data miliknya (IDOR-safe via dashboard_service).
"""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, get_user_permissions
from app.db.models.user import User
from app.services import dashboard_service
from app.services.audit_service import AuditService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _perms(user: User):
    return get_user_permissions(user, getattr(user, "active_role", None))


def _role(user: User) -> str:
    r = getattr(user, "active_role", None)
    if r:
        return r
    return user.roles[0].code if user.roles else "ANGGOTA"


# Peran yang boleh melihat agregat global tanpa cek permission granular
# (pimpinan & pengawas sesuai mandatnya).
ELEVATED_VIEW_ROLES = {"ADMIN_KOPERASI", "ADMIN", "KETUA_UMUM", "KETUA",
                       "MANAGER", "PENGAWAS_PEMBINA", "PENGAWAS"}


def _require_module_view(role: str, perms, needed: set, message: str) -> None:
    """Prompt #11: STAF/HRD/KASIR/IT wajib punya permission modul terkait.

    Peran pimpinan/pengawas lolos sesuai mandat; ANGGOTA selalu ditolak
    agregat global (dipaksa jalur personal di tiap endpoint).
    """
    if role in ELEVATED_VIEW_ROLES:
        return
    if role == "ANGGOTA" or not (needed & set(perms)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


@router.get("/summary")
def dashboard_summary(current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Ringkas dashboard sesuai active_role. Anggota otomatis hanya data sendiri."""
    perms = _perms(current_user)
    role = _role(current_user)
    data = dashboard_service.get_dashboard_data_by_role(db, current_user, role, perms)
    return {"role": role, "data": data}


@router.get("/savings")
def dashboard_savings(period: str = Query("monthly", description="daily|weekly|monthly|yearly"),
                      current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    role = _role(current_user)
    perms = _perms(current_user)
    if role == "ANGGOTA":
        # Anggota: kembalikan ringkas miliknya saja (tanpa tren global)
        data = dashboard_service.get_anggota_dashboard_data(db, current_user.id)
        return {"role": role, "personal": True, "data": data}
    if period not in ("daily", "weekly", "monthly", "yearly"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Period harus salah satu: daily, weekly, monthly, yearly.")
    _require_module_view(role, perms, {"saving.view", "report.view", "*"},
                         "Anda tidak memiliki izin melihat tren simpanan.")
    return dashboard_service.get_savings_trend(db, period)


@router.get("/loans")
def dashboard_loans(status: Optional[str] = Query(None),
                    member_id: Optional[int] = Query(None),
                    min_amount: Optional[float] = Query(None, ge=0),
                    max_amount: Optional[float] = Query(None, ge=0),
                    start_date: Optional[date] = Query(None),
                    end_date: Optional[date] = Query(None),
                    limit: int = Query(50, ge=1, le=200),
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    role = _role(current_user)
    perms = _perms(current_user)
    if role == "ANGGOTA":
        data = dashboard_service.get_anggota_dashboard_data(db, current_user.id)
        return {"role": role, "personal": True, "data": data}
    _require_module_view(role, perms, {"loan.view", "report.view", "*"},
                         "Anda tidak memiliki izin melihat data pinjaman.")
    breakdown = dashboard_service.get_loan_status_breakdown(db)
    attention = dashboard_service.get_attention_loans(
        db, status=status, member_id=member_id, min_amount=min_amount,
        max_amount=max_amount, start_date=start_date, end_date=end_date, limit=limit)
    return {"breakdown": breakdown, "attention_loans": attention}


@router.get("/cashflow")
def dashboard_cashflow(days: int = Query(30, ge=7, le=90),
                       current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    role = _role(current_user)
    perms = _perms(current_user)
    allowed = ({"cashier.view", "report.view", "*"} & perms) or role in (
        "ADMIN_KOPERASI", "ADMIN", "KETUA_UMUM", "MANAGER", "PENGAWAS_PEMBINA", "KASIR")
    if role == "ANGGOTA" or (role == "HRD" and not allowed) or (role == "STAF" and not allowed):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Anda tidak memiliki izin melihat arus kas.")
    return dashboard_service.get_cashflow_trend(db, days)


@router.get("/installments")
def dashboard_installments(current_user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    role = _role(current_user)
    perms = _perms(current_user)
    if role == "ANGGOTA":
        data = dashboard_service.get_anggota_dashboard_data(db, current_user.id)
        return {"role": role, "personal": True,
                "upcoming": data.get("upcoming_installments", [])}
    _require_module_view(role, perms, {"loan.view", "installment.view", "report.view", "*"},
                         "Anda tidak memiliki izin melihat data angsuran.")
    return dashboard_service.get_installment_breakdown(db)


@router.get("/audit-recent")
def dashboard_audit_recent(limit: int = Query(10, ge=1, le=50),
                           current_user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    role = _role(current_user)
    perms = _perms(current_user)
    if role == "ANGGOTA":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Anggota tidak dapat mengakses audit log.")
    if role == "HRD" and "audit.view" not in perms and "*" not in perms:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="HRD tidak memiliki izin audit.view.")
    logs = dashboard_service._recent_audit(db, limit)
    AuditService.log_event(db, action="DASHBOARD_AUDIT_VIEW", entity_name="AuditLog",
                           user_id=current_user.id,
                           notes=f"Role {role} melihat {limit} audit terbaru")
    return {"data": logs}

"""
API: Modul Angsuran KSP AHNRFZI
================================
Endpoints pengelolaan tagihan, pembayaran kasir, dan portal anggota:
- Pencatatan pembayaran angsuran (Full/Partial Payment)
- Penegakan Transaksi Database Atomik & Struk Kuitansi Resmi
- Tracking status: BELUM_JATUH_TEMPO, JATUH_TEMPO, TERLAMBAT, DIBAYAR, LUNAS
- Portal mandiri anggota (Jadwal, Riwayat, Sisa Pinjaman)
"""
from typing import Optional, List
from datetime import datetime, date, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.core.permissions import get_current_user, require_permission
from app.db.models.user import User
from app.db.models.member import Member
from app.db.models.loan import Loan, LoanInstallment, LoanPayment, LoanStatus
from app.schemas.installment import (
    InstallmentPaymentRequest, InstallmentItemOut, LoanPaymentOut,
    InstallmentReceiptOut, MemberInstallmentSummaryOut
)
from app.services import installment_service

router = APIRouter(prefix="/installments", tags=["Installments"])


# =============================================================================
# 1. TRANSAKSI PEMBAYARAN KASIR (LOKET ANGSURAN)
# =============================================================================

@router.post("/payments", response_model=InstallmentReceiptOut, status_code=status.HTTP_201_CREATED)
def pay_installment(
    req: InstallmentPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Kasir / Teller mencatat pembayaran angsuran pinjaman (Full atau Partial).
    Membutuhkan izin: installment.payment atau cashier.transaction.
    Proses atomik:
    - Validasi & Alokasi (Denda -> Bunga -> Pokok)
    - Buat LoanPayment & Struk Kuitansi
    - Update saldo pinjaman & jadwal angsuran
    - Catat transaksi kas masuk (CashTransaction)
    - Rollback otomatis jika terjadi kegagalan
    """
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    is_authorized = bool({"installment.payment", "cashier.transaction", "*"} & user_perms)
    is_admin = "ADMIN_KOPERASI" in {r.code for r in current_user.roles} or "ADMIN" in {r.code for r in current_user.roles}

    if not (is_authorized or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: Anda tidak memiliki izin (installment.payment) untuk memproses pembayaran kasir"
        )

    receipt = installment_service.process_installment_payment(
        db=db,
        current_user=current_user,
        data=req
    )
    return receipt


# =============================================================================
# 2. QUERY JADWAL & STATUS ANGSURAN
# =============================================================================

@router.get("", response_model=List[InstallmentItemOut])
def list_installments(
    search: Optional[str] = Query(None, description="Cari No. Pinjaman atau Nama Anggota"),
    status: Optional[str] = Query(None, description="Filter status: BELUM_JATUH_TEMPO, JATUH_TEMPO, TERLAMBAT, DIBAYAR, LUNAS"),
    loan_id: Optional[int] = Query(None, description="Filter ID Pinjaman tertentu"),
    member_id: Optional[int] = Query(None, description="Filter ID Anggota tertentu"),
    is_overdue_only: bool = Query(False, description="Hanya tampilkan tagihan yang terlambat"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Daftar jadwal angsuran pinjaman.
    - Petugas / Kasir: Melihat seluruh tagihan portofolio kredit.
    - Anggota Biasa: Hanya melihat jadwal angsuran pinjamannya sendiri (IDOR safe).
    """
    return installment_service.get_installments_list(
        db=db,
        current_user=current_user,
        search=search,
        status=status,
        loan_id=loan_id,
        member_id=member_id,
        is_overdue_only=is_overdue_only,
        page=page,
        limit=limit
    )


@router.get("/{installment_id}", response_model=InstallmentItemOut)
def get_installment_detail(
    installment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Detail satu baris jadwal angsuran (dengan proteksi IDOR)."""
    installment = db.query(LoanInstallment).filter(LoanInstallment.id == installment_id).first()
    if not installment:
        raise HTTPException(status_code=404, detail="Data angsuran tidak ditemukan")

    loan = installment.loan
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    is_staff = bool({"installment.view", "loan.view", "*"} & user_perms)
    is_admin = "ADMIN_KOPERASI" in {r.code for r in current_user.roles} or "ADMIN" in {r.code for r in current_user.roles}

    if not (is_staff or is_admin):
        if loan.member.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Anda tidak berhak melihat tagihan anggota lain")

    dyn_status, days_late, pen_due, rem_due = installment_service.calculate_installment_overdue_and_status(installment)

    return {
        "id": installment.id,
        "installment_no": installment.installment_no,
        "loan_id": installment.loan_id,
        "loan_no": loan.loan_no if loan else "",
        "member_id": loan.member_id if loan else 0,
        "member_no": loan.member.member_no if (loan and loan.member) else "",
        "member_name": loan.member.full_name if (loan and loan.member) else "",
        "member_department": loan.member.unit_divisi if (loan and loan.member) else None,
        "due_date": installment.due_date,
        "principal_due": installment.principal_due,
        "interest_due": installment.interest_due,
        "penalty_due": pen_due,
        "total_due": installment_service._target_due(installment),
        "principal_paid": installment.principal_paid or Decimal("0.00"),
        "interest_paid": installment.interest_paid or Decimal("0.00"),
        "penalty_paid": installment.penalty_paid or Decimal("0.00"),
        "total_paid": installment.total_paid or Decimal("0.00"),
        "remaining_due": rem_due,
        "status": dyn_status,
        "days_overdue": days_late,
        "paid_at": installment.paid_at
    }


@router.get("/loans/{loan_id}", response_model=List[InstallmentItemOut])
def get_loan_installments_schedule(
    loan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mengambil seluruh jadwal angsuran 1..N untuk satu pinjaman tertentu."""
    return installment_service.get_installments_list(
        db=db,
        current_user=current_user,
        loan_id=loan_id,
        limit=120
    )


# =============================================================================
# 3. RIWAYAT PEMBAYARAN KASIR & STRUK RESMI
# =============================================================================

@router.get("/payments/history", response_model=List[LoanPaymentOut])
def list_payments_history(
    loan_id: Optional[int] = Query(None, description="Filter pinjaman tertentu"),
    member_id: Optional[int] = Query(None, description="Filter anggota tertentu"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Riwayat pembayaran kasir untuk angsuran pinjaman."""
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    is_staff = bool({"installment.view", "cashier.view", "*"} & user_perms)
    is_admin = "ADMIN_KOPERASI" in {r.code for r in current_user.roles} or "ADMIN" in {r.code for r in current_user.roles}

    query = db.query(LoanPayment).join(Loan).join(Member)

    if not (is_staff or is_admin):
        query = query.filter(Member.user_id == current_user.id)
    else:
        if member_id:
            query = query.filter(Loan.member_id == member_id)

    if loan_id:
        query = query.filter(LoanPayment.loan_id == loan_id)

    payments = query.order_by(desc(LoanPayment.created_at)).offset((page - 1) * limit).limit(limit).all()

    items = []
    for p in payments:
        items.append({
            "id": p.id,
            "payment_no": p.payment_no,
            "receipt_no": p.receipt_no,
            "loan_id": p.loan_id,
            "loan_no": p.loan.loan_no if p.loan else "",
            "installment_id": p.installment_id,
            "installment_no": p.installment.installment_no if p.installment else None,
            "member_id": p.member_id,
            "member_no": p.member.member_no if p.member else "",
            "member_name": p.member.full_name if p.member else "",
            "amount_paid": p.amount_paid,
            "principal_portion": p.principal_portion,
            "interest_portion": p.interest_portion,
            "penalty_portion": p.penalty_portion,
            "payment_method": p.payment_method,
            "received_by_user_id": p.received_by_user_id,
            "received_by_name": p.received_by.username if p.received_by else None,
            "notes": p.notes,
            "created_at": p.created_at
        })
    return items


@router.get("/payments/{payment_id}/receipt", response_model=InstallmentReceiptOut)
def get_payment_receipt(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mengambil rincian kuitansi/struk resmi pembayaran angsuran."""
    payment = db.query(LoanPayment).filter(LoanPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Data pembayaran tidak ditemukan")

    loan = payment.loan
    installment = payment.installment

    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    is_staff = bool({"installment.view", "cashier.view", "*"} & user_perms)
    is_admin = "ADMIN_KOPERASI" in {r.code for r in current_user.roles} or "ADMIN" in {r.code for r in current_user.roles}

    if not (is_staff or is_admin):
        if loan.member.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Anda tidak berhak melihat kuitansi pembayaran anggota lain")

    words = installment_service.terbilang(int(payment.amount_paid)).strip()
    words = (words[0].upper() + words[1:]) if words else "Nol"
    words += " Rupiah"

    rem_inst = Decimal("0.00")
    if installment:
        tot_target = (installment.total_due or Decimal("0.00")) + (installment.penalty_due or Decimal("0.00"))
        rem_inst = max(Decimal("0.00"), tot_target - (installment.total_paid or Decimal("0.00")))

    return {
        "receipt_no": payment.receipt_no,
        "payment_no": payment.payment_no,
        "cash_transaction_no": f"TRX-CSH-{payment.payment_no}",
        "cooperative_name": "KSP AHNRFZI",
        "cooperative_address": "Gedung Pusat Koperasi Simpan Pinjam AHNRFZI",
        "cooperative_phone": "(021) 7890-1234",
        "payment_date": payment.created_at,
        "loan_id": loan.id,
        "loan_no": loan.loan_no,
        "product_name": loan.product.name if loan.product else "",
        "installment_id": installment.id if installment else 0,
        "installment_no": installment.installment_no if installment else 0,
        "due_date": installment.due_date if installment else payment.created_at.date(),
        "member_id": loan.member_id,
        "member_no": loan.member.member_no if loan.member else "",
        "member_name": loan.member.full_name if loan.member else "",
        "member_department": loan.member.unit_divisi if loan.member else None,
        "cashier_name": payment.received_by.username if payment.received_by else "Kasir",
        "amount_paid": payment.amount_paid,
        "amount_in_words": words,
        "principal_portion": payment.principal_portion,
        "interest_portion": payment.interest_portion,
        "penalty_portion": payment.penalty_portion,
        "remaining_installment_due": rem_inst,
        "remaining_loan_principal": loan.remaining_principal or Decimal("0.00"),
        "installment_status_after": installment.status if installment else "DIBAYAR",
        "loan_status_after": loan.status,
        "payment_method": payment.payment_method,
        "notes": payment.notes
    }


# =============================================================================
# 4. PORTAL MANDIRI ANGGOTA (SELF-SERVICE & IDOR SAFE)
# =============================================================================

@router.get("/my/schedules", response_model=List[InstallmentItemOut])
def get_my_installment_schedules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Portal Mandiri: Daftar jadwal angsuran pinjaman milik anggota yang sedang login."""
    if not current_user.member:
        raise HTTPException(status_code=400, detail="Akun Anda belum terhubung dengan data anggota koperasi")

    return installment_service.get_installments_list(
        db=db,
        current_user=current_user,
        member_id=current_user.member.id,
        limit=100
    )


@router.get("/my/payments", response_model=List[LoanPaymentOut])
def get_my_payments_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Portal Mandiri: Riwayat pembayaran angsuran yang pernah disetorkan oleh anggota."""
    if not current_user.member:
        raise HTTPException(status_code=400, detail="Akun Anda belum terhubung dengan data anggota koperasi")

    return list_payments_history(
        member_id=current_user.member.id,
        current_user=current_user,
        db=db
    )


@router.get("/my/summary", response_model=MemberInstallmentSummaryOut)
def get_my_installment_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Portal Mandiri: Ringkasan sisa pokok, jatuh tempo terdekat, dan tagihan bulan ini."""
    if not current_user.member:
        raise HTTPException(status_code=400, detail="Akun Anda belum terhubung dengan data anggota koperasi")

    return installment_service.get_member_installment_overview(
        db=db,
        member_id=current_user.member.id
    )

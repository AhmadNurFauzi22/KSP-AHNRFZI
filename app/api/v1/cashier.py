"""
API: Modul Kasir KSP AHNRFZI
=============================
Endpoints pengelolaan kasir, arus kas masuk/keluar, tutup kas, rekapitulasi harian,
dan pembalikan transaksi (Reversal/Adjustment tanpa DELETE).
"""
from typing import Optional, List
from datetime import datetime, date, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, and_

from app.core.database import get_db
from app.core.permissions import get_current_user, get_user_permissions, require_permission
from app.db.models.user import User
from app.db.models.member import Member
from app.db.models.transaction import CashRegister, CashTransaction, CashDirection, CashCategory
from app.schemas.cashier import (
    CashTransactionCreate, CashReversalRequest, CashRegisterOpenRequest,
    CashRegisterCloseRequest, CashTransactionOut, CashRegisterOut,
    DailyRecapOut, CashReceiptOut
)
from app.services import cashier_service

router = APIRouter(prefix="/cashier", tags=["Cashier"])


def _check_cashier_view_perm(current_user: User):
    """Verifikasi hak akses melihat data kasir."""
    user_roles = set(current_user.role_codes)
    perms = get_user_permissions(current_user, getattr(current_user, "active_role", None))
    allowed_roles = {"ADMIN_KOPERASI", "KASIR", "MANAGER", "KETUA_UMUM", "PENGAWAS_PEMBINA"}
    if not (bool(allowed_roles & user_roles) or "cashier.view" in perms or "*" in perms):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Diperlukan hak akses 'cashier.view'."
        )


def _check_cashier_transaction_perm(current_user: User):
    """Verifikasi hak akses transaksi kasir."""
    user_roles = set(current_user.role_codes)
    perms = get_user_permissions(current_user, getattr(current_user, "active_role", None))
    allowed_roles = {"ADMIN_KOPERASI", "KASIR", "MANAGER"}
    if not (bool(allowed_roles & user_roles) or "cashier.transaction" in perms or "*" in perms):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Kasir, Manager, atau Admin yang dapat mengeksekusi transaksi kas."
        )


def _check_cashier_close_perm(current_user: User):
    """Verifikasi hak akses tutup shift kasir."""
    user_roles = set(current_user.role_codes)
    perms = get_user_permissions(current_user, getattr(current_user, "active_role", None))
    allowed_roles = {"ADMIN_KOPERASI", "KASIR", "MANAGER"}
    if not (bool(allowed_roles & user_roles) or "cashier.close" in perms or "*" in perms):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Diperlukan hak akses 'cashier.close'."
        )


# =============================================================================
# 1. TRANSAKSI KAS (CASH TRANSACTIONS)
# =============================================================================

@router.post("/transactions", response_model=CashTransactionOut, status_code=status.HTTP_201_CREATED)
def create_cash_transaction(
    req: CashTransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Input transaksi kas loket:
    - KAS MASUK: Pendapatan lainnya, modal, dll.
    - KAS KELUAR: Pengeluaran operasional, pengeluaran lainnya, dll.
    """
    _check_cashier_transaction_perm(current_user)
    trx = cashier_service.record_cash_transaction(db, req, current_user)
    
    # Map output
    return CashTransactionOut(
        id=trx.id,
        transaction_no=trx.transaction_no,
        receipt_no=trx.receipt_no,
        cash_register_id=trx.cash_register_id,
        cashier_user_id=trx.cashier_user_id,
        cashier_name=trx.cashier.full_name if trx.cashier else None,
        direction=trx.direction,
        category=trx.category,
        category_label=cashier_service.CATEGORY_LABELS.get(trx.category, trx.category),
        amount=trx.amount,
        member_id=trx.member_id,
        member_name=trx.member.full_name if trx.member else None,
        member_no=trx.member.member_no if trx.member else None,
        reference_no=trx.reference_no,
        payment_method=trx.payment_method,
        notes=trx.notes,
        is_reversed=trx.is_reversed,
        reversed_at=trx.reversed_at,
        reversed_by_id=trx.reversed_by_user_id,
        reversed_by_name=trx.reversed_by.full_name if trx.reversed_by else None,
        reversal_of_id=trx.reversal_of_id,
        reversal_reason=trx.reversal_reason,
        created_at=trx.created_at
    )


@router.get("/transactions", response_model=List[CashTransactionOut])
def list_cash_transactions(
    search: Optional[str] = Query(None, description="Cari no transaksi, kuitansi, referensi, atau catatan"),
    start_date: Optional[date] = Query(None, description="Tanggal mulai (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Tanggal akhir (YYYY-MM-DD)"),
    direction: Optional[str] = Query(None, description="Filter arah: CASH_IN / CASH_OUT"),
    category: Optional[str] = Query(None, description="Filter kategori transaksi"),
    cashier_user_id: Optional[int] = Query(None, description="Filter kasir user ID"),
    is_reversed: Optional[bool] = Query(None, description="Filter status reversal"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Daftar histori transaksi kasir dengan fitur pencarian dan multi-filter.
    """
    _check_cashier_view_perm(current_user)

    query = db.query(CashTransaction)

    if search:
        s = f"%{search}%"
        query = query.outerjoin(Member, CashTransaction.member_id == Member.id).filter(
            or_(
                CashTransaction.transaction_no.ilike(s),
                CashTransaction.receipt_no.ilike(s),
                CashTransaction.reference_no.ilike(s),
                CashTransaction.notes.ilike(s),
                Member.full_name.ilike(s),
                Member.member_no.ilike(s)
            )
        )

    if start_date:
        start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
        query = query.filter(CashTransaction.created_at >= start_dt)

    if end_date:
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
        query = query.filter(CashTransaction.created_at <= end_dt)

    if direction:
        query = query.filter(CashTransaction.direction == direction.upper())

    if category:
        query = query.filter(CashTransaction.category == category.upper())

    if cashier_user_id:
        query = query.filter(CashTransaction.cashier_user_id == cashier_user_id)

    if is_reversed is not None:
        query = query.filter(CashTransaction.is_reversed == is_reversed)

    results = query.order_by(desc(CashTransaction.created_at)).offset(skip).limit(limit).all()

    out = []
    for tx in results:
        out.append(
            CashTransactionOut(
                id=tx.id,
                transaction_no=tx.transaction_no,
                receipt_no=tx.receipt_no,
                cash_register_id=tx.cash_register_id,
                cashier_user_id=tx.cashier_user_id,
                cashier_name=tx.cashier.full_name if tx.cashier else None,
                direction=tx.direction,
                category=tx.category,
                category_label=cashier_service.CATEGORY_LABELS.get(tx.category, tx.category),
                amount=tx.amount,
                member_id=tx.member_id,
                member_name=tx.member.full_name if tx.member else None,
                member_no=tx.member.member_no if tx.member else None,
                reference_no=tx.reference_no,
                payment_method=tx.payment_method,
                notes=tx.notes,
                is_reversed=tx.is_reversed,
                reversed_at=tx.reversed_at,
                reversed_by_id=tx.reversed_by_user_id,
                reversed_by_name=tx.reversed_by.full_name if tx.reversed_by else None,
                reversal_of_id=tx.reversal_of_id,
                reversal_reason=tx.reversal_reason,
                created_at=tx.created_at
            )
        )
    return out


@router.get("/transactions/{id}", response_model=CashTransactionOut)
def get_cash_transaction_detail(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Detail satu transaksi kas."""
    _check_cashier_view_perm(current_user)
    tx = db.query(CashTransaction).filter(CashTransaction.id == id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaksi kas dengan ID {id} tidak ditemukan."
        )

    return CashTransactionOut(
        id=tx.id,
        transaction_no=tx.transaction_no,
        receipt_no=tx.receipt_no,
        cash_register_id=tx.cash_register_id,
        cashier_user_id=tx.cashier_user_id,
        cashier_name=tx.cashier.full_name if tx.cashier else None,
        direction=tx.direction,
        category=tx.category,
        category_label=cashier_service.CATEGORY_LABELS.get(tx.category, tx.category),
        amount=tx.amount,
        member_id=tx.member_id,
        member_name=tx.member.full_name if tx.member else None,
        member_no=tx.member.member_no if tx.member else None,
        reference_no=tx.reference_no,
        payment_method=tx.payment_method,
        notes=tx.notes,
        is_reversed=tx.is_reversed,
        reversed_at=tx.reversed_at,
        reversed_by_id=tx.reversed_by_user_id,
        reversed_by_name=tx.reversed_by.full_name if tx.reversed_by else None,
        reversal_of_id=tx.reversal_of_id,
        reversal_reason=tx.reversal_reason,
        created_at=tx.created_at
    )


@router.post("/transactions/{id}/reverse", response_model=CashTransactionOut)
def reverse_transaction(
    id: int,
    req: CashReversalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Eksekusi REVERSAL / ADJUSTMENT transaksi kas:
    - Tidak menghapus record transaksi (No Hard Delete).
    - Membentuk transaksi penyeimbang berlawanan arah.
    - Menandai transaksi asli sebagai is_reversed.
    """
    _check_cashier_transaction_perm(current_user)
    counter_tx = cashier_service.reverse_cash_transaction(db, id, current_user, req.reason)

    return CashTransactionOut(
        id=counter_tx.id,
        transaction_no=counter_tx.transaction_no,
        receipt_no=counter_tx.receipt_no,
        cash_register_id=counter_tx.cash_register_id,
        cashier_user_id=counter_tx.cashier_user_id,
        cashier_name=counter_tx.cashier.full_name if counter_tx.cashier else None,
        direction=counter_tx.direction,
        category=counter_tx.category,
        category_label=cashier_service.CATEGORY_LABELS.get(counter_tx.category, counter_tx.category),
        amount=counter_tx.amount,
        member_id=counter_tx.member_id,
        member_name=counter_tx.member.full_name if counter_tx.member else None,
        member_no=counter_tx.member.member_no if counter_tx.member else None,
        reference_no=counter_tx.reference_no,
        payment_method=counter_tx.payment_method,
        notes=counter_tx.notes,
        is_reversed=counter_tx.is_reversed,
        reversed_at=counter_tx.reversed_at,
        reversed_by_id=counter_tx.reversed_by_user_id,
        reversed_by_name=counter_tx.reversed_by.full_name if counter_tx.reversed_by else None,
        reversal_of_id=counter_tx.reversal_of_id,
        reversal_reason=counter_tx.reversal_reason,
        created_at=counter_tx.created_at
    )


@router.delete("/transactions/{id}", status_code=status.HTTP_400_BAD_REQUEST)
def delete_transaction(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Penolakan penghapusan transaksi demi menjaga Financial Integrity.
    """
    cashier_service.assert_financial_integrity_no_delete()


@router.get("/transactions/{id}/receipt", response_model=CashReceiptOut)
def get_transaction_receipt(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cetak kuitansi transaksi kasir dengan kalimat Terbilang Rupiah."""
    _check_cashier_view_perm(current_user)
    return cashier_service.format_cash_receipt(db, id)


# =============================================================================
# 2. TUTUP KAS & MANAJEMEN SHIFT (CASH REGISTERS)
# =============================================================================

@router.post("/registers/open", response_model=CashRegisterOut, status_code=status.HTTP_201_CREATED)
def open_cash_register(
    req: CashRegisterOpenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Membuka shift kasir baru dengan modal kas awal."""
    _check_cashier_transaction_perm(current_user)
    reg = cashier_service.get_or_create_open_register(
        db, current_user.id, req.opening_balance, req.notes
    )
    return CashRegisterOut(
        id=reg.id,
        cashier_user_id=reg.cashier_user_id,
        cashier_name=reg.cashier.full_name if reg.cashier else None,
        shift_date=reg.shift_date,
        opening_balance=reg.opening_balance,
        total_cash_in=reg.total_cash_in,
        total_cash_out=reg.total_cash_out,
        closing_balance=reg.closing_balance,
        physical_balance=reg.physical_balance,
        discrepancy=reg.discrepancy,
        status=reg.status,
        opened_at=reg.opened_at,
        closed_at=reg.closed_at,
        closed_by_name=reg.closed_by.full_name if reg.closed_by else None,
        notes=reg.notes
    )


@router.post("/registers/{id}/close", response_model=CashRegisterOut)
def close_cash_register(
    id: int,
    req: CashRegisterCloseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Tutup shift kasir (Tutup Kas):
    - Merekonsiliasi saldo sistem vs saldo fisik di kasir.
    - Menghitung nilai selisih (discrepancy).
    - Status shift ditutup (CLOSED).
    """
    _check_cashier_close_perm(current_user)
    # Prompt #11: kasir hanya boleh menutup shift OPEN miliknya sendiri;
    # penutupan shift kasir lain wajib oleh ADMIN/MANAGER. Register yang
    # sudah CLOSED tetap 400 dari service (dicek setelah ini).
    from app.db.models.transaction import CashRegister as _Reg
    reg_check = db.query(_Reg).filter(_Reg.id == id).first()
    if reg_check and reg_check.status == "OPEN":
        roles = {r.code for r in current_user.roles}
        if reg_check.cashier_user_id != current_user.id and not (
                roles & {"ADMIN_KOPERASI", "ADMIN", "MANAGER"}):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda hanya dapat menutup shift kasir milik sendiri."
            )
    reg = cashier_service.close_cash_register(
        db, id, current_user, req.physical_balance, req.notes
    )
    return CashRegisterOut(
        id=reg.id,
        cashier_user_id=reg.cashier_user_id,
        cashier_name=reg.cashier.full_name if reg.cashier else None,
        shift_date=reg.shift_date,
        opening_balance=reg.opening_balance,
        total_cash_in=reg.total_cash_in,
        total_cash_out=reg.total_cash_out,
        closing_balance=reg.closing_balance,
        physical_balance=reg.physical_balance,
        discrepancy=reg.discrepancy,
        status=reg.status,
        opened_at=reg.opened_at,
        closed_at=reg.closed_at,
        closed_by_name=reg.closed_by.full_name if reg.closed_by else None,
        notes=reg.notes
    )


@router.get("/registers/current", response_model=Optional[CashRegisterOut])
def get_current_shift(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mengecek apakah kasir saat ini memiliki shift yang sedang aktif (OPEN)."""
    _check_cashier_view_perm(current_user)
    reg = cashier_service.get_active_register(db, current_user.id)
    if not reg:
        return None

    return CashRegisterOut(
        id=reg.id,
        cashier_user_id=reg.cashier_user_id,
        cashier_name=reg.cashier.full_name if reg.cashier else None,
        shift_date=reg.shift_date,
        opening_balance=reg.opening_balance,
        total_cash_in=reg.total_cash_in,
        total_cash_out=reg.total_cash_out,
        closing_balance=reg.closing_balance,
        physical_balance=reg.physical_balance,
        discrepancy=reg.discrepancy,
        status=reg.status,
        opened_at=reg.opened_at,
        closed_at=reg.closed_at,
        closed_by_name=reg.closed_by.full_name if reg.closed_by else None,
        notes=reg.notes
    )


@router.get("/registers", response_model=List[CashRegisterOut])
def list_cash_registers(
    shift_date: Optional[date] = Query(None, description="Filter tanggal shift"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter OPEN / CLOSED"),
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Daftar riwayat shift buku kasir."""
    _check_cashier_view_perm(current_user)
    query = db.query(CashRegister)
    if shift_date:
        query = query.filter(CashRegister.shift_date == shift_date)
    if status_filter:
        query = query.filter(CashRegister.status == status_filter.upper())

    results = query.order_by(desc(CashRegister.id)).offset(skip).limit(limit).all()
    out = []
    for reg in results:
        out.append(
            CashRegisterOut(
                id=reg.id,
                cashier_user_id=reg.cashier_user_id,
                cashier_name=reg.cashier.full_name if reg.cashier else None,
                shift_date=reg.shift_date,
                opening_balance=reg.opening_balance,
                total_cash_in=reg.total_cash_in,
                total_cash_out=reg.total_cash_out,
                closing_balance=reg.closing_balance,
                physical_balance=reg.physical_balance,
                discrepancy=reg.discrepancy,
                status=reg.status,
                opened_at=reg.opened_at,
                closed_at=reg.closed_at,
                closed_by_name=reg.closed_by.full_name if reg.closed_by else None,
                notes=reg.notes
            )
        )
    return out


# =============================================================================
# 3. REKAPITULASI KAS HARIAN (DAILY CASH RECAP)
# =============================================================================

@router.get("/daily-recap", response_model=DailyRecapOut)
def get_daily_cash_recap(
    target_date: Optional[date] = Query(None, description="Tanggal rekap (default hari ini)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mendapatkan rekapitulasi arus kas harian per kategori transaksi."""
    _check_cashier_view_perm(current_user)
    query_date = target_date or datetime.now(timezone.utc).date()
    return cashier_service.get_daily_recap(db, query_date)

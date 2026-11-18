"""
API: Modul Simpanan KSP AHNRFZI
=================================
Endpoints untuk pengelolaan simpanan koperasi:
- Transaksi Setoran & Penarikan (Loket Kasir)
- Transaction Ledger & Rekonstruksi Saldo
- Bukti Transaksi (Struk / Kuitansi Kasir)
- Portal Mandiri Anggota (IDOR Protected)
- Master Produk & Ringkasan Saldo
"""
import math
from typing import Optional, List
from datetime import datetime, date, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.core.database import get_db
from app.core.permissions import (
    get_current_user, get_user_permissions
)
from app.db.models.user import User
from app.db.models.member import Member
from app.db.models.savings import (
    SavingsProduct, SavingsAccount, SavingsTransaction,
    SavingsProductType, SavingsTransactionType, SavingsTransactionStatus
)
from app.schemas.savings import (
    SavingsProductOut, SavingsDepositRequest, SavingsWithdrawRequest,
    SavingsTransactionOut, SavingsReceiptOut, SavingsTransactionListResponse,
    SavingsAccountOut, SavingsAccountListResponse, SavingsSummaryOut
)
from app.services import savings_service

router = APIRouter(prefix="/savings", tags=["Simpanan Koperasi"])


# ============================================================================
# HELPER FUNCTIONS & ACCESS GUARDS
# ============================================================================

def _is_staff_or_admin(user: User) -> bool:
    """Cek apakah pengguna adalah staf pengelola (bukan sekedar anggota biasa)."""
    elevated_roles = {
        "ADMIN_KOPERASI", "KETUA_UMUM", "MANAGER",
        "KASIR", "HRD", "STAF", "PENGAWAS_PEMBINA", "IT_PUSAT"
    }
    user_roles = set(user.role_codes)
    return bool(elevated_roles & user_roles)


def _is_cashier_authorized(user: User) -> bool:
    """Cek apakah pengguna berwenang mengeksekusi transaksi kasir (Setor/Tarik)."""
    cashier_roles = {"ADMIN_KOPERASI", "KASIR", "MANAGER"}
    user_roles = set(user.role_codes)
    perms = get_user_permissions(user, getattr(user, "active_role", None))
    return bool(cashier_roles & user_roles) or "saving.transaction" in perms or "cashier.transaction" in perms


def _map_tx_to_out(tx: SavingsTransaction) -> SavingsTransactionOut:
    """Konversi ORM SavingsTransaction ke Pydantic Schema SavingsTransactionOut."""
    account = tx.account
    member = account.member if account else None
    product = account.product if account else None
    cashier = tx.created_by

    return SavingsTransactionOut(
        id=tx.id,
        transaction_no=tx.transaction_no,
        account_id=tx.account_id,
        member_id=member.id if member else None,
        member_no=member.member_no if member else None,
        member_name=member.full_name if member else None,
        product_code=product.code if product else None,
        product_name=product.name if product else None,
        product_type=product.product_type if product else None,
        transaction_type=tx.transaction_type,
        amount=tx.amount,
        balance_before=tx.balance_before,
        balance_after=tx.balance_after,
        payment_channel=tx.payment_channel,
        reference_no=tx.reference_no,
        status=tx.status,
        description=tx.description,
        created_by_user_id=tx.created_by_user_id,
        created_by_name=cashier.full_name if cashier else None,
        created_at=tx.created_at
    )


# ============================================================================
# 1. MASTER PRODUCTS
# ============================================================================

@router.get("/products", response_model=List[SavingsProductOut], summary="Daftar Master Produk Simpanan")
def list_savings_products(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mendapatkan katalog produk simpanan koperasi beserta aturan penarikannya."""
    products = db.query(SavingsProduct).filter(SavingsProduct.is_active == True).all()
    return products


# ============================================================================
# 2. TRANSAKSI LOKET KASIR (SETORAN & PENARIKAN)
# ============================================================================

@router.post("/transactions/deposit", response_model=SavingsTransactionOut, status_code=status.HTTP_201_CREATED, summary="Setor Simpanan di Loket")
def deposit_savings(
    payload: SavingsDepositRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Eksekusi setoran simpanan (Simpanan Pokok, Wajib, Sukarela):
    - Wajib role Kasir / Admin / Manager
    - Mencegah nominal <= 0
    - Mencegah transaksi ganda (idempotency check)
    - Mencatat buku besar dan audit trail
    """
    if not _is_cashier_authorized(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Kasir Loket atau Admin yang dapat memproses transaksi setoran."
        )

    client_ip = request.client.host if request.client else None

    tx = savings_service.process_deposit(
        db=db,
        amount=payload.amount,
        cashier_user_id=current_user.id,
        account_id=payload.account_id,
        member_id=payload.member_id,
        product_type=payload.product_type,
        payment_channel=payload.payment_channel or "CASHIER",
        reference_no=payload.reference_no,
        description=payload.description,
        ip_address=client_ip
    )

    return _map_tx_to_out(tx)


@router.post("/transactions/withdraw", response_model=SavingsTransactionOut, status_code=status.HTTP_201_CREATED, summary="Tarik Simpanan Sesuai Kebijakan")
def withdraw_savings(
    payload: SavingsWithdrawRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Eksekusi penarikan simpanan:
    - Simpanan Sukarela: BEBAS ditarik selama saldo mencukupi
    - Simpanan Pokok & Wajib: DITOLAK selama anggota aktif (hanya dicairkan jika KELUAR)
    - Validasi saldo ledger & pencegahan saldo minus
    """
    if not _is_cashier_authorized(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Kasir Loket atau Admin yang dapat memproses transaksi penarikan."
        )

    client_ip = request.client.host if request.client else None

    tx = savings_service.process_withdrawal(
        db=db,
        amount=payload.amount,
        cashier_user_id=current_user.id,
        account_id=payload.account_id,
        member_id=payload.member_id,
        product_type=payload.product_type,
        payment_channel=payload.payment_channel or "CASHIER",
        reference_no=payload.reference_no,
        description=payload.description,
        ip_address=client_ip
    )

    return _map_tx_to_out(tx)


def _fetch_transactions_response(
    db: Session,
    page: int = 1,
    per_page: int = 15,
    search: Optional[str] = None,
    product_type: Optional[str] = None,
    transaction_type: Optional[str] = None,
    member_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    sort_order: str = "desc"
) -> SavingsTransactionListResponse:
    q = db.query(SavingsTransaction).join(SavingsAccount).join(Member).join(SavingsProduct)

    if member_id is not None:
        q = q.filter(SavingsAccount.member_id == member_id)

    # Filter pencarian
    if isinstance(search, str) and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(or_(
            SavingsTransaction.transaction_no.ilike(term),
            SavingsTransaction.reference_no.ilike(term),
            SavingsTransaction.description.ilike(term),
            Member.full_name.ilike(term),
            Member.member_no.ilike(term),
            Member.nik.ilike(term),
        ))

    # Filter produk
    if isinstance(product_type, str) and product_type.strip():
        q = q.filter(SavingsProduct.product_type == product_type.strip().upper())

    # Filter tipe transaksi (SETOR / TARIK)
    if isinstance(transaction_type, str) and transaction_type.strip():
        tt = transaction_type.strip().upper()
        if tt == "SETOR":
            q = q.filter(SavingsTransaction.transaction_type.in_(("SETOR", "DEPOSIT")))
        elif tt == "TARIK":
            q = q.filter(SavingsTransaction.transaction_type.in_(("TARIK", "WITHDRAWAL")))
        else:
            q = q.filter(SavingsTransaction.transaction_type == tt)

    # Filter tanggal
    if isinstance(start_date, date):
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        q = q.filter(SavingsTransaction.created_at >= start_dt)
    if isinstance(end_date, date):
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        q = q.filter(SavingsTransaction.created_at <= end_dt)

    total = q.count()
    total_pages = math.ceil(total / per_page) if total > 0 else 1

    if sort_order == "asc":
        q = q.order_by(SavingsTransaction.created_at.asc(), SavingsTransaction.id.asc())
    else:
        q = q.order_by(SavingsTransaction.created_at.desc(), SavingsTransaction.id.desc())

    transactions = q.offset((page - 1) * per_page).limit(per_page).all()
    items = [_map_tx_to_out(t) for t in transactions]

    return SavingsTransactionListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1
    )


# ============================================================================
# 3. RIWAYAT TRANSAKSI & BUKTI CETAK (RECEIPT)
# ============================================================================

@router.get("/transactions", response_model=SavingsTransactionListResponse, summary="Riwayat Buku Besar Simpanan")
def list_savings_transactions(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=15, ge=1, le=100),
    search: Optional[str] = Query(default=None, description="Cari no transaksi, no anggota, nama"),
    product_type: Optional[str] = Query(default=None, description="POKOK, WAJIB, SUKARELA"),
    transaction_type: Optional[str] = Query(default=None, description="SETOR, TARIK"),
    member_id: Optional[int] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    sort_order: Optional[str] = Query(default="desc"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Daftar buku besar (transaction ledger) simpanan dengan filter, pencarian, dan paginasi.
    - Admin / Kasir: dapat melihat seluruh transaksi.
    - Anggota biasa: hanya dapat melihat transaksinya sendiri (auto-filter).
    """
    is_staff = _is_staff_or_admin(current_user)
    target_member_id = None
    if not is_staff:
        if not current_user.member:
            return SavingsTransactionListResponse(
                items=[], total=0, page=page, per_page=per_page,
                total_pages=0, has_next=False, has_prev=False
            )
        target_member_id = current_user.member.id
    else:
        target_member_id = member_id

    return _fetch_transactions_response(
        db=db,
        page=page,
        per_page=per_page,
        search=search,
        product_type=product_type,
        transaction_type=transaction_type,
        member_id=target_member_id,
        start_date=start_date,
        end_date=end_date,
        sort_order=sort_order or "desc"
    )


@router.get("/transactions/{id}", response_model=SavingsTransactionOut, summary="Detail Transaksi Simpanan")
def get_savings_transaction_detail(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Detail transaksi simpanan spesifik dengan proteksi IDOR:
    Anggota biasa hanya dapat melihat transaksi miliknya sendiri.
    """
    tx = db.query(SavingsTransaction).filter(SavingsTransaction.id == id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaksi simpanan dengan ID {id} tidak ditemukan."
        )

    is_staff = _is_staff_or_admin(current_user)
    if not is_staff:
        if not current_user.member or tx.account.member_id != current_user.member.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak: Anda tidak memiliki wewenang untuk melihat transaksi anggota lain."
            )

    return _map_tx_to_out(tx)


@router.get("/transactions/{id}/receipt", response_model=SavingsReceiptOut, summary="Bukti Transaksi / Struk Resmi")
def get_savings_receipt(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mendapatkan bukti transaksi resmi lengkap (informasi kop koperasi, nomor transaksi,
    data anggota, terbilang rupiah, saldo sebelum dan sesudah).
    """
    tx = db.query(SavingsTransaction).filter(SavingsTransaction.id == id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaksi dengan ID {id} tidak ditemukan."
        )

    is_staff = _is_staff_or_admin(current_user)
    if not is_staff:
        if not current_user.member or tx.account.member_id != current_user.member.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak: Anda tidak dapat mencetak bukti transaksi anggota lain."
            )

    receipt_data = savings_service.build_receipt_data(tx, db)
    return receipt_data


@router.delete("/transactions/{id}", summary="Hapus Transaksi (Dilarang)")
def delete_savings_transaction(
    id: int,
    current_user: User = Depends(get_current_user),
):
    """
    Keamanan Finansial: Transaksi buku besar final TIDAK BOLEH dihapus.
    Setiap perubahan harus melalui transaksi koreksi / pembalik.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Operasi ditolak: Transaksi buku besar bersifat immutable (kekal) dan tidak dapat dihapus."
    )


# ============================================================================
# 4. REKENING & AUDIT INTEGRITAS SALDO
# ============================================================================

@router.get("/accounts", response_model=SavingsAccountListResponse, summary="Daftar Rekening Simpanan Anggota")
def list_savings_accounts(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=15, ge=1, le=100),
    search: Optional[str] = Query(default=None),
    product_type: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Melihat daftar seluruh rekening simpanan (Khusus Admin/Kasir/Manager)."""
    if not _is_staff_or_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Diperlukan hak akses pengelola untuk melihat daftar seluruh rekening."
        )

    q = db.query(SavingsAccount).join(Member).join(SavingsProduct)

    if search:
        term = f"%{search.strip()}%"
        q = q.filter(or_(
            SavingsAccount.account_no.ilike(term),
            Member.full_name.ilike(term),
            Member.member_no.ilike(term),
            Member.nik.ilike(term)
        ))

    if product_type:
        q = q.filter(SavingsProduct.product_type == product_type.upper())

    total = q.count()
    total_pages = math.ceil(total / per_page) if total > 0 else 1

    accounts = q.order_by(SavingsAccount.id.asc()).offset((page - 1) * per_page).limit(per_page).all()

    items = []
    for acc in accounts:
        # Rekonstruksi saldo untuk verifikasi integritas
        recon_bal = savings_service.reconstruct_balance(acc.id, db)
        items.append(SavingsAccountOut(
            id=acc.id,
            member_id=acc.member_id,
            member_no=acc.member.member_no if acc.member else None,
            member_name=acc.member.full_name if acc.member else None,
            product_id=acc.product_id,
            product_code=acc.product.code if acc.product else None,
            product_name=acc.product.name if acc.product else None,
            product_type=acc.product.product_type if acc.product else None,
            account_no=acc.account_no,
            balance=acc.balance,
            reconstructed_balance=recon_bal,
            is_balance_valid=(Decimal(str(acc.balance)) == recon_bal),
            status=acc.status,
            allow_withdrawal=acc.product.allow_withdrawal if acc.product else True,
            opened_date=acc.opened_date
        ))

    return SavingsAccountListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1
    )


@router.get("/accounts/{id}/audit-balance", summary="Audit Rekonstruksi Saldo dari Ledger")
def audit_account_balance(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Prinsip Buku Besar: Buktikan bahwa saldo akun dapat direkonstruksi 100%
    dari histori transaksi (sum(SETOR) - sum(TARIK)).
    """
    if not _is_staff_or_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak.")

    return savings_service.verify_account_integrity(id, db)


# ============================================================================
# 5. PORTAL MANDIRI ANGGOTA (SELF-SERVICE & IDOR PROTECTION)
# ============================================================================

@router.get("/my-summary", response_model=SavingsSummaryOut, summary="Ringkasan Saldo Simpanan Saya")
def get_my_savings_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Anggota melihat rincian saldo miliknya sendiri:
    - Saldo Simpanan Pokok
    - Saldo Simpanan Wajib
    - Saldo Simpanan Sukarela
    - Total Saldo
    """
    if not current_user.member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Akun pengguna ini belum terdaftar sebagai anggota koperasi."
        )

    summary = savings_service.get_member_savings_summary(current_user.member.id, db)
    return summary


@router.get("/my-transactions", response_model=SavingsTransactionListResponse, summary="Mutasi Simpanan Saya")
def get_my_savings_transactions(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=50),
    product_type: Optional[str] = Query(default=None),
    transaction_type: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Anggota melihat riwayat mutasi rekening simpanan miliknya sendiri."""
    if not current_user.member:
        return SavingsTransactionListResponse(
            items=[], total=0, page=page, per_page=per_page,
            total_pages=0, has_next=False, has_prev=False
        )

    return _fetch_transactions_response(
        db=db,
        page=page,
        per_page=per_page,
        product_type=product_type,
        transaction_type=transaction_type,
        member_id=current_user.member.id,
        sort_order="desc"
    )


@router.get("/members/{member_id}/summary", response_model=SavingsSummaryOut, summary="Ringkasan Simpanan per Anggota")
def get_member_savings_summary_endpoint(
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ringkasan saldo simpanan per anggota.
    - Admin, Kasir, Staf: dapat melihat saldo anggota manapun.
    - Anggota biasa: DITOLAK jika ID != ID miliknya sendiri (IDOR Protection).
    """
    is_staff = _is_staff_or_admin(current_user)
    if not is_staff:
        if not current_user.member or current_user.member.id != member_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak (IDOR): Anda tidak memiliki izin untuk melihat saldo simpanan anggota lain."
            )

    return savings_service.get_member_savings_summary(member_id, db)


# ============================================================================
# 6. STATISTIK MODUL SIMPANAN
# ============================================================================

@router.get("/stats/summary", summary="Statistik Agregat Simpanan Koperasi")
def get_savings_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mendapatkan statistik total saldo per jenis produk simpanan."""
    if not _is_staff_or_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak.")

    # Hitung total saldo per jenis produk — Prompt #14: satu GROUP BY
    rows = db.query(
        SavingsProduct.product_type,
        func.coalesce(func.sum(SavingsAccount.balance), 0)
    ).outerjoin(SavingsAccount,
                SavingsAccount.product_id == SavingsProduct.id
                ).group_by(SavingsProduct.product_type).all()
    stats_by_type = {}
    grand_total = Decimal("0.00")
    for ptype, total_p in rows:
        stats_by_type[ptype] = Decimal(str(total_p or 0))
        grand_total += Decimal(str(total_p or 0))

    # Total transaksi hari ini
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_tx_count = db.query(SavingsTransaction).filter(
        SavingsTransaction.created_at >= today_start
    ).count()

    today_deposit_sum = db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).filter(
        SavingsTransaction.created_at >= today_start,
        SavingsTransaction.transaction_type.in_(("SETOR", "DEPOSIT")),
        SavingsTransaction.status == "COMPLETED"
    ).scalar()

    today_withdraw_sum = db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).filter(
        SavingsTransaction.created_at >= today_start,
        SavingsTransaction.transaction_type.in_(("TARIK", "WITHDRAWAL")),
        SavingsTransaction.status == "COMPLETED"
    ).scalar()

    return {
        "grand_total": grand_total,
        "total_pokok": stats_by_type.get("POKOK", Decimal("0.00")),
        "total_wajib": stats_by_type.get("WAJIB", Decimal("0.00")),
        "total_sukarela": stats_by_type.get("SUKARELA", Decimal("0.00")),
        "total_berjangka": stats_by_type.get("BERJANGKA", Decimal("0.00")),
        "today_transactions_count": today_tx_count,
        "today_deposit_total": Decimal(str(today_deposit_sum)),
        "today_withdraw_total": Decimal(str(today_withdraw_sum)),
    }

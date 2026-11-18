"""
Service: Modul Simpanan KSP AHNRFZI
====================================
Implementasi transaction ledger, rekonstruksi saldo dari histori,
kebijakan penarikan simpanan, anti-duplikasi, serta proteksi transaksi database.
"""
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import threading

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_

from app.db.models.savings import (
    SavingsProduct, SavingsAccount, SavingsTransaction,
    SavingsProductType, SavingsTransactionType, SavingsTransactionStatus
)
from app.db.models.member import Member, MemberStatus
from app.db.models.user import User
from app.services.audit_service import AuditService
from app.schemas.savings import terbilang_rupiah

# Thread lock for concurrent transaction protection
_savings_lock = threading.Lock()


# ============================================================================
# LEDGER & BALANCE RECONSTRUCTION FUNCTIONS
# ============================================================================

def reconstruct_balance(account_id: int, db: Session) -> Decimal:
    """
    Rekonstruksi saldo dari buku besar transaksi (ledger) secara deterministik.
    Prinsip perbankan/koperasi: saldo harus dapat dihitung ulang dari seluruh histori.
    sum(SETOR/DEPOSIT/INTEREST/TRANSFER_IN) - sum(TARIK/WITHDRAWAL/FEE/TRANSFER_OUT)
    """
    transactions = db.query(SavingsTransaction).filter(
        SavingsTransaction.account_id == account_id,
        SavingsTransaction.status == SavingsTransactionStatus.COMPLETED.value
    ).order_by(SavingsTransaction.created_at.asc(), SavingsTransaction.id.asc()).all()

    total = Decimal("0.00")
    for tx in transactions:
        tx_type = tx.transaction_type.upper()
        amount = Decimal(str(tx.amount))
        if tx_type in ("SETOR", "DEPOSIT", "INTEREST", "TRANSFER_IN"):
            total += amount
        elif tx_type in ("TARIK", "WITHDRAWAL", "FEE", "TRANSFER_OUT"):
            total -= amount

    return total


def verify_account_integrity(account_id: int, db: Session) -> Dict[str, Any]:
    """
    Memverifikasi integritas akun dengan membandingkan saldo tersimpan vs saldo ledger.
    """
    account = db.query(SavingsAccount).filter(SavingsAccount.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rekening simpanan dengan ID {account_id} tidak ditemukan."
        )

    stored_balance = Decimal(str(account.balance))
    ledger_balance = reconstruct_balance(account_id, db)
    is_valid = (stored_balance == ledger_balance)

    return {
        "account_id": account.id,
        "account_no": account.account_no,
        "stored_balance": stored_balance,
        "reconstructed_balance": ledger_balance,
        "is_valid": is_valid,
        "discrepancy": stored_balance - ledger_balance,
        "total_transactions": len(account.transactions),
    }


def reconcile_account(account_id: int, db: Session, user_id: int) -> Dict[str, Any]:
    """
    Sinkronisasi saldo akun dengan nilai ledger jika terjadi selisih (discrepancy).
    """
    account = db.query(SavingsAccount).filter(SavingsAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rekening tidak ditemukan.")

    old_bal = Decimal(str(account.balance))
    correct_bal = reconstruct_balance(account_id, db)

    if old_bal != correct_bal:
        account.balance = correct_bal
        db.flush()

        AuditService.log_event(
            db=db,
            action="RECONCILE_SAVINGS_BALANCE",
            entity_name="SavingsAccount",
            entity_id=str(account.id),
            user_id=user_id,
            old_values={"balance": float(old_bal)},
            new_values={"balance": float(correct_bal)},
            notes=f"Rekonsiliasi saldo rekening {account.account_no} dari buku besar (ledger)"
        )
        db.commit()

    return {
        "account_id": account.id,
        "account_no": account.account_no,
        "old_balance": old_bal,
        "new_balance": correct_bal,
        "synced": old_bal != correct_bal
    }


# ============================================================================
# HELPER: NO TRANSAKSI & CEK DUPLIKASI
# ============================================================================

def generate_savings_transaction_no(db: Session, prefix: str = "TRX-SAV") -> str:
    """
    Generate nomor transaksi unik format: TRX-SAV-YYYYMMDD-XXXX
    """
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix_today = f"{prefix}-{today_str}-"

    # Cari nomor terakhir hari ini
    last = db.query(SavingsTransaction).filter(
        SavingsTransaction.transaction_no.like(f"{prefix_today}%")
    ).order_by(SavingsTransaction.id.desc()).first()

    if last and last.transaction_no:
        try:
            seq = int(last.transaction_no.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1

    return f"{prefix_today}{seq:04d}"


def check_duplicate_transaction(
    account_id: int,
    amount: Decimal,
    transaction_type: str,
    reference_no: Optional[str],
    db: Session
) -> None:
    """
    Cegah transaksi ganda:
    1. Cek nomor referensi eksternal yang sama (jika diisi).
    2. Cek idempotency transaksi identik pada rekening yang sama dalam jeda 30 detik.
    """
    if reference_no and reference_no.strip():
        existing_ref = db.query(SavingsTransaction).filter(
            SavingsTransaction.reference_no == reference_no.strip()
        ).first()
        if existing_ref:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transaksi dengan nomor referensi '{reference_no}' sudah pernah diproses sebelumnya (No: {existing_ref.transaction_no})."
            )

    # Deteksi double-click / duplikasi cepat dalam 30 detik terakhir
    cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    recent_dup = db.query(SavingsTransaction).filter(
        SavingsTransaction.account_id == account_id,
        SavingsTransaction.amount == amount,
        SavingsTransaction.transaction_type == transaction_type,
        SavingsTransaction.created_at >= cutoff_time
    ).first()

    if recent_dup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Terdeteksi transaksi duplikat dalam jeda waktu singkat (< 30 detik). Mohon periksa riwayat mutasi sebelum mengulang."
        )


def get_or_create_account(
    member_id: int,
    product_type: str,
    db: Session
) -> SavingsAccount:
    """
    Mendapatkan rekening simpanan anggota untuk jenis produk tertentu,
    atau otomatis membukanya jika belum ada.
    """
    product = db.query(SavingsProduct).filter(
        SavingsProduct.product_type == product_type.upper(),
        SavingsProduct.is_active == True
    ).first()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Produk simpanan '{product_type}' tidak ditemukan dalam master produk."
        )

    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Anggota dengan ID {member_id} tidak ditemukan."
        )

    account = db.query(SavingsAccount).filter(
        SavingsAccount.member_id == member_id,
        SavingsAccount.product_id == product.id
    ).first()

    if not account:
        prefix_code = product_type[:3].upper()
        account_no = f"SA-{prefix_code}-{member.member_no}"
        account = SavingsAccount(
            member_id=member.id,
            product_id=product.id,
            account_no=account_no,
            balance=Decimal("0.00"),
            status="ACTIVE",
            opened_date=datetime.now(timezone.utc)
        )
        db.add(account)
        db.flush()

    return account


# ============================================================================
# PROCESS DEPOSIT (SETORAN)
# ============================================================================

def process_deposit(
    db: Session,
    amount: Decimal,
    cashier_user_id: int,
    account_id: Optional[int] = None,
    member_id: Optional[int] = None,
    product_type: Optional[str] = "SUKARELA",
    payment_channel: str = "CASHIER",
    reference_no: Optional[str] = None,
    description: Optional[str] = None,
    ip_address: Optional[str] = None
) -> SavingsTransaction:
    """
    Proses transaksi setoran simpanan:
    - Atomik (database transaction)
    - Validasi nominal > 0
    - Cek duplikasi transaksi
    - Update saldo rekening dan catat entri buku besar (ledger)
    - Perekaman audit trail
    """
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nominal setoran harus lebih besar dari 0 (tidak boleh negatif atau nol)."
        )

    with _savings_lock:
        try:
            # 1. Resolusi Akun Simpanan
            if account_id:
                account = db.query(SavingsAccount).filter(SavingsAccount.id == account_id).first()
                if not account:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rekening tidak ditemukan.")
            elif member_id:
                account = get_or_create_account(member_id, product_type or "SUKARELA", db)
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Harus menyertakan account_id atau member_id."
                )

            # Cek status anggota: hanya anggota aktif atau calon (untuk simpanan pokok)
            member = account.member
            if member and member.status == "KELUAR":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tidak dapat menerima setoran: Anggota telah berstatus KELUAR."
                )

            # 2. Cek Duplikasi Transaksi
            check_duplicate_transaction(
                account_id=account.id,
                amount=amount,
                transaction_type="SETOR",
                reference_no=reference_no,
                db=db
            )

            # 3. Hitung Saldo Sebelum & Sesudah
            balance_before = Decimal(str(account.balance))
            balance_after = balance_before + amount

            # 4. Generate Nomor Transaksi
            tx_no = generate_savings_transaction_no(db)

            # 5. Buat Entri Buku Besar (Ledger)
            desc_final = description or f"Setoran {account.product.name} di loket kasir"
            tx = SavingsTransaction(
                account_id=account.id,
                transaction_no=tx_no,
                transaction_type="SETOR",
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                payment_channel=payment_channel or "CASHIER",
                reference_no=reference_no.strip() if reference_no else None,
                status=SavingsTransactionStatus.COMPLETED.value,
                description=desc_final,
                created_by_user_id=cashier_user_id,
                created_at=datetime.now(timezone.utc)
            )
            db.add(tx)

            # 6. Mutasikan Saldo Akun
            account.balance = balance_after
            account.updated_at = datetime.now(timezone.utc)
            db.flush()

            # 7. Audit Trail
            AuditService.log_event(
                db=db,
                action="SAVINGS_DEPOSIT",
                entity_name="SavingsTransaction",
                entity_id=tx.transaction_no,
                user_id=cashier_user_id,
                old_values={"balance": float(balance_before)},
                new_values={"balance": float(balance_after), "amount": float(amount)},
                ip_address=ip_address,
                notes=f"Setor {account.product.name} Rp {amount:,.2f} untuk {member.full_name if member else account.account_no}"
            )

            db.commit()
            db.refresh(tx)
            return tx

        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Terjadi kesalahan saat memproses setoran simpanan: {str(e)}"
            )


# ============================================================================
# PROCESS WITHDRAWAL (PENARIKAN SESUAI KEBIJAKAN)
# ============================================================================

def process_withdrawal(
    db: Session,
    amount: Decimal,
    cashier_user_id: int,
    account_id: Optional[int] = None,
    member_id: Optional[int] = None,
    product_type: Optional[str] = "SUKARELA",
    payment_channel: str = "CASHIER",
    reference_no: Optional[str] = None,
    description: Optional[str] = None,
    ip_address: Optional[str] = None
) -> SavingsTransaction:
    """
    Proses transaksi penarikan simpanan:
    - Atomik (database transaction)
    - Validasi nominal > 0
    - Penegakan Kebijakan Penarikan:
      * Simpanan Pokok & Wajib DILARANG ditarik selama anggota masih berstatus aktif
      * Simpanan Sukarela BEBAS ditarik selama saldo mencukupi
    - Verifikasi saldo ledger (tidak boleh minus / insufficient funds)
    - Perekaman entri buku besar (ledger) dan audit trail
    """
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nominal penarikan harus lebih besar dari 0 (tidak boleh negatif atau nol)."
        )

    with _savings_lock:
        try:
            # 1. Resolusi Akun Simpanan
            if account_id:
                account = db.query(SavingsAccount).filter(SavingsAccount.id == account_id).first()
                if not account:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rekening tidak ditemukan.")
            elif member_id:
                account = get_or_create_account(member_id, product_type or "SUKARELA", db)
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Harus menyertakan account_id atau member_id."
                )

            product = account.product
            member = account.member

            # 2. PENEGAKAN KEBIJAKAN PENARIKAN (WITHDRAWAL POLICY)
            if not product.allow_withdrawal:
                # Simpanan Pokok dan Wajib hanya boleh ditarik jika anggota berstatus KELUAR
                if member and member.status != "KELUAR":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Kebijakan Koperasi: {product.name} tidak dapat ditarik selama anggota masih berstatus "
                            f"{member.status}. Penarikan hanya diizinkan apabila anggota resmi mengundurkan diri/keluar."
                        )
                    )

            # 3. VERIFIKASI SALDO (INSUFFICIENT FUNDS CHECK)
            current_balance = Decimal(str(account.balance))
            ledger_balance = reconstruct_balance(account.id, db)

            # Pakai nilai terkecil antara stored balance dan ledger balance demi kehati-hatian
            effective_available = min(current_balance, ledger_balance)

            if amount > effective_available:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Saldo tidak mencukupi untuk melakukan penarikan. "
                        f"Saldo tersedia: Rp {effective_available:,.2f}, permohonan penarikan: Rp {amount:,.2f}"
                    )
                )

            # 4. Cek Duplikasi Transaksi
            check_duplicate_transaction(
                account_id=account.id,
                amount=amount,
                transaction_type="TARIK",
                reference_no=reference_no,
                db=db
            )

            # 5. Hitung Saldo Sebelum & Sesudah
            balance_before = current_balance
            balance_after = balance_before - amount

            if balance_after < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Operasi ditolak: Saldo rekening tidak boleh menjadi negatif."
                )

            # 6. Generate Nomor Transaksi
            tx_no = generate_savings_transaction_no(db)

            # 7. Buat Entri Buku Besar (Ledger)
            desc_final = description or f"Penarikan {product.name} di loket kasir"
            tx = SavingsTransaction(
                account_id=account.id,
                transaction_no=tx_no,
                transaction_type="TARIK",
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                payment_channel=payment_channel or "CASHIER",
                reference_no=reference_no.strip() if reference_no else None,
                status=SavingsTransactionStatus.COMPLETED.value,
                description=desc_final,
                created_by_user_id=cashier_user_id,
                created_at=datetime.now(timezone.utc)
            )
            db.add(tx)

            # 8. Mutasikan Saldo Akun
            account.balance = balance_after
            account.updated_at = datetime.now(timezone.utc)
            db.flush()

            # 9. Audit Trail
            AuditService.log_event(
                db=db,
                action="SAVINGS_WITHDRAWAL",
                entity_name="SavingsTransaction",
                entity_id=tx.transaction_no,
                user_id=cashier_user_id,
                old_values={"balance": float(balance_before)},
                new_values={"balance": float(balance_after), "amount": float(amount)},
                ip_address=ip_address,
                notes=f"Tarik {product.name} Rp {amount:,.2f} untuk {member.full_name if member else account.account_no}"
            )

            db.commit()
            db.refresh(tx)
            return tx

        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Terjadi kesalahan saat memproses penarikan simpanan: {str(e)}"
            )


# ============================================================================
# SUMMARY & RECEIPT GENERATORS
# ============================================================================

def get_member_savings_summary(member_id: int, db: Session) -> Dict[str, Any]:
    """
    Mengambil ringkasan saldo simpanan anggota:
    - Simpanan Pokok
    - Simpanan Wajib
    - Simpanan Sukarela
    - Total Saldo Akumulasi
    """
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Anggota dengan ID {member_id} tidak ditemukan."
        )

    # Pastikan akun ada untuk tiap jenis produk standar
    pokok_acc = get_or_create_account(member_id, "POKOK", db)
    wajib_acc = get_or_create_account(member_id, "WAJIB", db)
    sukarela_acc = get_or_create_account(member_id, "SUKARELA", db)

    # Rekonstruksi saldo untuk akurasi mutlak
    pokok_bal = Decimal(str(pokok_acc.balance))
    wajib_bal = Decimal(str(wajib_acc.balance))
    sukarela_bal = Decimal(str(sukarela_acc.balance))
    total_balance = pokok_bal + wajib_bal + sukarela_bal

    return {
        "member_id": member.id,
        "member_no": member.member_no,
        "full_name": member.full_name,
        "nik": member.nik,
        "status": member.status,
        "unit_divisi": member.unit_divisi,
        "jabatan": member.jabatan,
        "pokok": {
            "account_id": pokok_acc.id,
            "account_no": pokok_acc.account_no,
            "product_type": "POKOK",
            "product_name": "Simpanan Pokok",
            "balance": pokok_bal,
            "allow_withdrawal": pokok_acc.product.allow_withdrawal
        },
        "wajib": {
            "account_id": wajib_acc.id,
            "account_no": wajib_acc.account_no,
            "product_type": "WAJIB",
            "product_name": "Simpanan Wajib",
            "balance": wajib_bal,
            "allow_withdrawal": wajib_acc.product.allow_withdrawal
        },
        "sukarela": {
            "account_id": sukarela_acc.id,
            "account_no": sukarela_acc.account_no,
            "product_type": "SUKARELA",
            "product_name": "Simpanan Sukarela",
            "balance": sukarela_bal,
            "allow_withdrawal": sukarela_acc.product.allow_withdrawal
        },
        "total_balance": total_balance
    }


def build_receipt_data(tx: SavingsTransaction, db: Session) -> Dict[str, Any]:
    """
    Menyiapkan data terstruktur untuk bukti transaksi / struk cetak resmi.
    """
    account = tx.account
    member = account.member if account else None
    product = account.product if account else None
    cashier = tx.created_by

    amount_int = int(Decimal(str(tx.amount)))
    terbilang_str = f"{terbilang_rupiah(amount_int)} Rupiah"

    return {
        "koperasi_name": "KOPERASI SIMPAN PINJAM AHNRFZI",
        "koperasi_address": "Komp. Perumahan AHNRFZI Graha No. 12, Jakarta",
        "koperasi_phone": "(021) 8899-7766",
        "transaction_no": tx.transaction_no,
        "date": tx.created_at,
        "cashier_name": cashier.full_name if cashier else "Kasir Loket",
        "member_id": member.id if member else 0,
        "member_no": member.member_no if member else "-",
        "member_name": member.full_name if member else "-",
        "nik": member.nik if member else "-",
        "unit_divisi": member.unit_divisi if member else "-",
        "jabatan": member.jabatan if member else "-",
        "account_no": account.account_no if account else "-",
        "product_type": product.product_type if product else "-",
        "product_name": product.name if product else "-",
        "transaction_type": tx.transaction_type,
        "amount": tx.amount,
        "amount_terbilang": terbilang_str,
        "balance_before": tx.balance_before,
        "balance_after": tx.balance_after,
        "payment_channel": tx.payment_channel,
        "reference_no": tx.reference_no,
        "description": tx.description,
        "status": tx.status
    }

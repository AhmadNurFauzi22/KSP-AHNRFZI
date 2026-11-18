from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from fastapi import HTTPException, status

from app.db.models.transaction import (
    CashRegister, CashTransaction, CashDirection, CashCategory
)
from app.db.models.user import User
from app.db.models.member import Member
from app.db.models.audit_log import AuditLog
from app.schemas.cashier import (
    CashTransactionCreate, CashRegisterOpenRequest, CashRegisterCloseRequest,
    CashTransactionOut, CashRegisterOut, DailyRecapOut, DailyRecapCategoryBreakdown,
    CashReceiptOut
)


CATEGORY_LABELS: Dict[str, str] = {
    CashCategory.SAVINGS_DEPOSIT.value: "Setoran Simpanan",
    CashCategory.SAVINGS_WITHDRAWAL.value: "Penarikan Simpanan",
    CashCategory.LOAN_DISBURSEMENT.value: "Pencairan Pinjaman",
    CashCategory.LOAN_PAYMENT.value: "Pembayaran Angsuran",
    CashCategory.OPERATIONAL_EXPENSE.value: "Pengeluaran Operasional",
    CashCategory.OTHER_INCOME.value: "Pendapatan Lainnya",
    CashCategory.OTHER_EXPENSE.value: "Pengeluaran Lainnya",
    CashCategory.CAPITAL_INJECTION.value: "Penyertaan / Injeksi Modal",
    CashCategory.REVERSAL.value: "Pembalik Transaksi (Reversal)",
    CashCategory.ADJUSTMENT.value: "Penyesuaian Saldo Kas",
    CashCategory.OTHER.value: "Lain-lain",
}


def terbilang(n: int) -> str:
    """Mengubah bilangan integer menjadi teks terbilang bahasa Indonesia."""
    satuan = ["", "Satu", "Dua", "Tiga", "Empat", "Lima", "Enam", "Tujuh", "Delapan", "Sembilan", "Sepuluh", "Sebelas"]
    n = int(n)
    if n < 0:
        return "Minus " + terbilang(-n)
    if n < 12:
        return satuan[n]
    elif n < 20:
        return terbilang(n - 10) + " Belas"
    elif n < 100:
        return terbilang(n // 10) + " Puluh " + terbilang(n % 10)
    elif n < 200:
        return "Seratus " + terbilang(n - 100)
    elif n < 1000:
        return terbilang(n // 10) + " Ratus " + terbilang(n % 100)
    elif n < 2000:
        return "Seribu " + terbilang(n - 1000)
    elif n < 1000000:
        return terbilang(n // 1000) + " Ribu " + terbilang(n % 1000)
    elif n < 1000000000:
        return terbilang(n // 1000000) + " Juta " + terbilang(n % 1000000)
    elif n < 1000000000000:
        return terbilang(n // 1000000000) + " Miliar " + terbilang(n % 1000000000)
    else:
        return terbilang(n // 1000000000000) + " Triliun " + terbilang(n % 1000000000000)


def generate_cash_transaction_no(db: Session) -> str:
    """Generate nomor transaksi kas otomatis: TRX-CSH-YYYYMMDD-XXXX."""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"TRX-CSH-{today_str}-"
    last_trx = db.query(CashTransaction).filter(
        CashTransaction.transaction_no.like(f"{prefix}%")
    ).order_by(CashTransaction.id.desc()).first()
    
    if last_trx:
        try:
            seq = int(last_trx.transaction_no.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


def generate_cash_receipt_no(db: Session) -> str:
    """Generate nomor bukti kuitansi kasir: RCP-CSH-YYYYMMDD-XXXX."""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"RCP-CSH-{today_str}-"
    last_trx = db.query(CashTransaction).filter(
        CashTransaction.receipt_no.like(f"{prefix}%")
    ).order_by(CashTransaction.id.desc()).first()
    
    if last_trx:
        try:
            seq = int(last_trx.receipt_no.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


def format_currency_idr(amount: Decimal) -> str:
    """Format nominal ke format standar mata uang Rupiah Indonesia."""
    try:
        val = float(amount or 0)
        formatted = f"Rp {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return formatted
    except Exception:
        return f"Rp {amount}"


def get_active_register(db: Session, cashier_user_id: int) -> Optional[CashRegister]:
    """Mencari register shift aktif (OPEN) untuk user kasir."""
    return db.query(CashRegister).filter(
        CashRegister.cashier_user_id == cashier_user_id,
        CashRegister.status == "OPEN"
    ).order_by(CashRegister.id.desc()).first()


def get_or_create_open_register(
    db: Session,
    cashier_user_id: int,
    opening_balance: Decimal = Decimal("0.0"),
    notes: Optional[str] = None
) -> CashRegister:
    """
    Mengambil register shift kasir aktif, atau membukanya jika belum ada.
    """
    register = get_active_register(db, cashier_user_id)
    if register:
        return register

    today = datetime.now(timezone.utc).date()
    op_balance = Decimal(str(opening_balance or 0))
    if op_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Saldo awal kas shift tidak boleh bernilai negatif."
        )

    register = CashRegister(
        cashier_user_id=cashier_user_id,
        shift_date=today,
        opening_balance=op_balance,
        total_cash_in=Decimal("0.0"),
        total_cash_out=Decimal("0.0"),
        closing_balance=op_balance,
        physical_balance=None,
        discrepancy=None,
        status="OPEN",
        opened_at=datetime.now(timezone.utc),
        notes=notes or "Pembukaan shift kasir harian"
    )
    db.add(register)
    db.flush()

    # Log Audit
    audit = AuditLog(
        user_id=cashier_user_id,
        action="CASH_REGISTER_OPENED",
        entity_name="CashRegister",
        entity_id=str(register.id),
        new_values={
            "register_id": register.id,
            "cashier_user_id": cashier_user_id,
            "shift_date": str(today),
            "opening_balance": float(op_balance)
        }
    )
    db.add(audit)
    db.commit()
    db.refresh(register)
    return register


def record_cash_transaction(
    db: Session,
    payload: CashTransactionCreate,
    cashier_user: User
) -> CashTransaction:
    """
    Mencatat transaksi kas masuk (CASH_IN) atau kas keluar (CASH_OUT).
    Terintegrasi dengan shift kasir aktif dan pencatatan audit log atomik.
    """
    if payload.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nominal transaksi kas wajib lebih besar dari 0."
        )

    # Validasi anggota jika diberikan
    member_obj = None
    if payload.member_id:
        member_obj = db.query(Member).filter(Member.id == payload.member_id).first()
        if not member_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Anggota dengan ID {payload.member_id} tidak ditemukan."
            )

    # Dapatkan atau buka shift kasir aktif
    register = get_active_register(db, cashier_user.id)
    if not register:
        register = get_or_create_open_register(db, cashier_user.id)

    trx_no = generate_cash_transaction_no(db)
    rcp_no = generate_cash_receipt_no(db)

    cash_trx = CashTransaction(
        transaction_no=trx_no,
        cash_register_id=register.id,
        cashier_user_id=cashier_user.id,
        direction=payload.direction.value,
        category=payload.category.value,
        amount=payload.amount,
        member_id=payload.member_id,
        reference_no=payload.reference_no,
        receipt_no=rcp_no,
        payment_method=payload.payment_method or "CASH",
        notes=payload.notes,
        is_reversed=False,
        created_at=datetime.now(timezone.utc)
    )
    db.add(cash_trx)

    # Update akumulasi saldo register
    if payload.direction == CashDirection.CASH_IN:
        register.total_cash_in = Decimal(str(register.total_cash_in or 0)) + payload.amount
    else:
        register.total_cash_out = Decimal(str(register.total_cash_out or 0)) + payload.amount

    register.closing_balance = (
        Decimal(str(register.opening_balance or 0))
        + Decimal(str(register.total_cash_in or 0))
        - Decimal(str(register.total_cash_out or 0))
    )

    # Log Audit
    audit = AuditLog(
        user_id=cashier_user.id,
        action="CASH_TRANSACTION_CREATED",
        entity_name="CashTransaction",
        entity_id=trx_no,
        new_values={
            "transaction_no": trx_no,
            "receipt_no": rcp_no,
            "direction": payload.direction.value,
            "category": payload.category.value,
            "amount": float(payload.amount),
            "cashier": cashier_user.username,
            "payment_method": payload.payment_method,
            "member_id": payload.member_id
        }
    )
    db.add(audit)
    db.commit()
    db.refresh(cash_trx)
    return cash_trx


def reverse_cash_transaction(
    db: Session,
    transaction_id: int,
    user: User,
    reason: str
) -> CashTransaction:
    """
    Mengeksekusi pembatalan transaksi kas menggunakan prinsip REVERSAL / ADJUSTMENT (Zero Hard Delete).
    Membentuk transaksi pembalik berlawanan arah dan menandai transaksi asli.
    """
    orig_trx = db.query(CashTransaction).filter(CashTransaction.id == transaction_id).first()
    if not orig_trx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaksi kas dengan ID {transaction_id} tidak ditemukan."
        )

    if orig_trx.is_reversed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transaksi {orig_trx.transaction_no} sudah pernah di-reversal sebelumnya pada {orig_trx.reversed_at}."
        )

    if orig_trx.category == CashCategory.REVERSAL.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaksi pembalik (Reversal) tidak dapat dibalik ulang."
        )

    # Tentukan arah lawan transaksi
    counter_direction = (
        CashDirection.CASH_OUT.value
        if orig_trx.direction == CashDirection.CASH_IN.value
        else CashDirection.CASH_IN.value
    )

    # Dapatkan shift kasir aktif
    register = get_active_register(db, user.id)
    if not register:
        register = get_or_create_open_register(db, user.id)

    reversal_trx_no = generate_cash_transaction_no(db)
    reversal_rcp_no = generate_cash_receipt_no(db)

    # Buat record transaksi pembalik (Counter Transaction)
    counter_trx = CashTransaction(
        transaction_no=reversal_trx_no,
        cash_register_id=register.id,
        cashier_user_id=user.id,
        direction=counter_direction,
        category=CashCategory.REVERSAL.value,
        amount=orig_trx.amount,
        member_id=orig_trx.member_id,
        reference_no=orig_trx.transaction_no,
        receipt_no=reversal_rcp_no,
        payment_method=orig_trx.payment_method,
        notes=f"Reversal atas transaksi {orig_trx.transaction_no}. Alasan: {reason}",
        is_reversed=False,
        reversal_of_id=orig_trx.id,
        created_at=datetime.now(timezone.utc)
    )
    db.add(counter_trx)

    # Tandai transaksi asal sebagai reversed
    orig_trx.is_reversed = True
    orig_trx.reversed_at = datetime.now(timezone.utc)
    orig_trx.reversed_by_user_id = user.id
    orig_trx.reversal_reason = reason

    # Perbarui shift register kasir
    if counter_direction == CashDirection.CASH_IN.value:
        register.total_cash_in = Decimal(str(register.total_cash_in or 0)) + Decimal(str(orig_trx.amount))
    else:
        register.total_cash_out = Decimal(str(register.total_cash_out or 0)) + Decimal(str(orig_trx.amount))

    register.closing_balance = (
        Decimal(str(register.opening_balance or 0))
        + Decimal(str(register.total_cash_in or 0))
        - Decimal(str(register.total_cash_out or 0))
    )

    # Audit Trail
    audit = AuditLog(
        user_id=user.id,
        action="CASH_TRANSACTION_REVERSED",
        entity_name="CashTransaction",
        entity_id=orig_trx.transaction_no,
        old_values={
            "transaction_no": orig_trx.transaction_no,
            "is_reversed": False
        },
        new_values={
            "transaction_no": orig_trx.transaction_no,
            "is_reversed": True,
            "reversal_counter_trx": reversal_trx_no,
            "reversal_reason": reason,
            "reversed_by": user.username
        }
    )
    db.add(audit)
    # Prompt #13: reversal → beritahu pimpinan (nominal dari record resmi)
    from app.services.notification_service import NotificationService as _RNS
    _RNS.notify_roles(
        db, ["ADMIN_KOPERASI", "MANAGER"],
        title=f"Reversal kas {orig_trx.transaction_no}",
        message=(f"Transaksi {orig_trx.transaction_no} senilai Rp {float(orig_trx.amount):,.0f} "
                 f"dibalik oleh {user.username}. Alasan: {reason}"),
        ntype="WARNING", link_url="/cashier",
        entity_name="CashTransaction", entity_id=str(orig_trx.id),
        event=f"CashReversed:{orig_trx.id}", actor_id=user.id)
    db.commit()
    db.refresh(counter_trx)
    return counter_trx


def close_cash_register(
    db: Session,
    register_id: int,
    user: User,
    physical_balance: Decimal,
    notes: Optional[str] = None
) -> CashRegister:
    """
    Menutup shift register kasir (Tutup Kas) & menghitung selisih fisik vs sistem.
    """
    register = db.query(CashRegister).filter(CashRegister.id == register_id).first()
    if not register:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shift register kasir dengan ID {register_id} tidak ditemukan."
        )

    if register.status == "CLOSED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Shift register ini sudah ditutup pada {register.closed_at}."
        )

    if physical_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Saldo fisik kas tidak boleh bernilai negatif."
        )

    # Hitung saldo sistem secara presisi
    system_bal = (
        Decimal(str(register.opening_balance or 0))
        + Decimal(str(register.total_cash_in or 0))
        - Decimal(str(register.total_cash_out or 0))
    )
    phys_bal = Decimal(str(physical_balance))
    discrepancy = phys_bal - system_bal

    register.closing_balance = system_bal
    register.physical_balance = phys_bal
    register.discrepancy = discrepancy
    register.status = "CLOSED"
    register.closed_at = datetime.now(timezone.utc)
    register.closed_by_user_id = user.id

    if notes:
        existing_notes = register.notes or ""
        register.notes = f"{existing_notes}\n[Tutup Kas]: {notes}".strip()

    # Log Audit
    audit = AuditLog(
        user_id=user.id,
        action="CASH_REGISTER_CLOSED",
        entity_name="CashRegister",
        entity_id=str(register.id),
        new_values={
            "register_id": register.id,
            "opening_balance": float(register.opening_balance),
            "total_cash_in": float(register.total_cash_in),
            "total_cash_out": float(register.total_cash_out),
            "system_balance": float(system_bal),
            "physical_balance": float(phys_bal),
            "discrepancy": float(discrepancy),
            "closed_by": user.username,
            "notes": register.notes
        }
    )
    db.add(audit)
    # Prompt #13: tutup kas BERSELISIH → beritahu pimpinan (nominal resmi)
    if discrepancy != 0:
        from app.services.notification_service import NotificationService as _CNS
        _CNS.notify_roles(
            db, ["ADMIN_KOPERASI", "MANAGER"],
            title=f"Selisih tutup kas register #{register.id}",
            message=(f"Shift {register.shift_date} ditutup dengan selisih "
                     f"Rp {float(discrepancy):,.0f} oleh {user.username}."),
            ntype="WARNING", link_url="/cashier",
            entity_name="CashRegister", entity_id=str(register.id),
            event=f"CashDiscrepancy:{register.id}", actor_id=user.id)
    db.commit()
    db.refresh(register)
    return register


def get_daily_recap(db: Session, query_date: date) -> DailyRecapOut:
    """
    Menghasilkan rekapitulasi arus kas harian koperasi untuk tanggal tertentu.
    """
    start_dt = datetime(query_date.year, query_date.month, query_date.day, 0, 0, 0)
    end_dt = datetime(query_date.year, query_date.month, query_date.day, 23, 59, 59)

    transactions = db.query(CashTransaction).filter(
        CashTransaction.created_at >= start_dt,
        CashTransaction.created_at <= end_dt
    ).all()

    total_in = Decimal("0.0")
    total_out = Decimal("0.0")
    cat_stats: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for tx in transactions:
        amt = Decimal(str(tx.amount))
        key = (tx.category, tx.direction)
        if key not in cat_stats:
            cat_stats[key] = {
                "category": tx.category,
                "category_name": CATEGORY_LABELS.get(tx.category, tx.category),
                "direction": tx.direction,
                "count": 0,
                "total_amount": Decimal("0.0")
            }
        cat_stats[key]["count"] += 1
        cat_stats[key]["total_amount"] += amt

        if tx.direction == CashDirection.CASH_IN.value:
            total_in += amt
        else:
            total_out += amt

    # Registers status on this day
    registers = db.query(CashRegister).filter(CashRegister.shift_date == query_date).all()
    open_regs = sum(1 for r in registers if r.status == "OPEN")
    closed_regs = sum(1 for r in registers if r.status == "CLOSED")

    categories_list = [
        DailyRecapCategoryBreakdown(
            category=item["category"],
            category_name=item["category_name"],
            direction=item["direction"],
            count=item["count"],
            total_amount=item["total_amount"]
        )
        for item in cat_stats.values()
    ]

    return DailyRecapOut(
        date=query_date,
        total_cash_in=total_in,
        total_cash_out=total_out,
        net_cash_flow=total_in - total_out,
        total_transactions=len(transactions),
        categories=categories_list,
        registers_open=open_regs,
        registers_closed=closed_regs
    )


def format_cash_receipt(db: Session, transaction_id: int) -> CashReceiptOut:
    """
    Menyiapkan payload struk kuitansi kasir dengan format slip thermal dan Terbilang Rupiah.
    """
    trx = db.query(CashTransaction).filter(CashTransaction.id == transaction_id).first()
    if not trx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaksi kas dengan ID {transaction_id} tidak ditemukan."
        )

    cashier_name = trx.cashier.full_name if trx.cashier else "Kasir Loket"
    member_name = trx.member.full_name if trx.member else None
    member_no = trx.member.member_no if trx.member else None
    category_label = CATEGORY_LABELS.get(trx.category, trx.category)

    amount_val = Decimal(str(trx.amount))
    amount_int = int(amount_val)
    amount_words = f"{terbilang(amount_int)} Rupiah"

    # Format date: 17 September 2026 14:30 WIB
    date_str = trx.created_at.strftime("%d/%m/%Y %H:%M WIB")

    return CashReceiptOut(
        receipt_no=trx.receipt_no,
        transaction_no=trx.transaction_no,
        transaction_date=date_str,
        cashier_name=cashier_name,
        member_name=member_name,
        member_no=member_no,
        direction=trx.direction,
        category=trx.category,
        category_label=category_label,
        amount=amount_val,
        amount_formatted=format_currency_idr(amount_val),
        amount_terbilang=amount_words,
        payment_method=trx.payment_method,
        reference_no=trx.reference_no,
        notes=trx.notes,
        is_reversed=trx.is_reversed
    )


def assert_financial_integrity_no_delete():
    """
    Aturan keras: Transaksi kas tidak boleh dihapus.
    Setiap pemanggilan fungsi ini akan melempar exception 400 Bad Request.
    """
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "FINANCIAL INTEGRITY VIOLATION: Transaksi kas yang telah dibukukan bersifat final "
            "dan mutlak tidak dapat dihapus. Untuk membatalkan kesalahan pembukuan, gunakan fitur "
            "REVERSAL / ADJUSTMENT."
        )
    )

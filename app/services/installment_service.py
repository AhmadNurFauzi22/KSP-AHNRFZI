from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc, and_
from fastapi import HTTPException, status

from app.db.models.loan import Loan, LoanInstallment, LoanPayment, LoanStatus, InstallmentStatus
from app.db.models.member import Member
from app.db.models.user import User
from app.db.models.transaction import CashTransaction, CashDirection, CashCategory
from app.schemas.installment import InstallmentPaymentRequest
from app.services.audit_service import AuditService
from app.core.logging import logger


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


def generate_payment_number(db: Session) -> str:
    """Generate running nomor pembayaran angsuran: PAY-LOAN-YYYYMMDD-XXXX."""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"PAY-LOAN-{today_str}-"
    last_pay = db.query(LoanPayment).filter(LoanPayment.payment_no.like(f"{prefix}%")).order_by(LoanPayment.id.desc()).first()
    if last_pay:
        try:
            seq = int(last_pay.payment_no.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


def generate_receipt_number(db: Session) -> str:
    """Generate running nomor kuitansi kasir angsuran: RCP-LOAN-YYYYMMDD-XXXX."""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"RCP-LOAN-{today_str}-"
    last_rcp = db.query(LoanPayment).filter(LoanPayment.receipt_no.like(f"{prefix}%")).order_by(LoanPayment.id.desc()).first()
    if last_rcp:
        try:
            seq = int(last_rcp.receipt_no.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


def _target_due(installment: LoanInstallment) -> Decimal:
    """Total tagihan sebenarnya: denda dihitung tepat SATU kali.

    Invarian: total_due sudah mencakup denda sejak dihitung di
    process_installment_payment (P+I+penalti), sedangkan penalty_due
    menyimpan komponen denda secara terpisah. Menjumlahkan keduanya akan
    menagih denda 2x (overcharge), sehingga target = nilai maksimum
    yang konsisten.
    """
    total = installment.total_due or Decimal("0.00")
    parts = (installment.principal_due or Decimal("0.00")) \
        + (installment.interest_due or Decimal("0.00")) \
        + (installment.penalty_due or Decimal("0.00"))
    return max(total, parts)


def calculate_installment_overdue_and_status(installment: LoanInstallment, as_of_date: Optional[date] = None) -> tuple:
    """
    Menghitung status dinamis, hari keterlambatan, dan denda.
    Returns (status, days_overdue, penalty_due, remaining_due)
    """
    as_of = as_of_date or datetime.now(timezone.utc).date()
    tot_due = _target_due(installment)
    tot_paid = installment.total_paid or Decimal("0.00")
    rem_due = max(Decimal("0.00"), tot_due - tot_paid)

    if tot_paid >= tot_due and tot_due > Decimal("0.00"):
        return InstallmentStatus.LUNAS.value, 0, installment.penalty_due or Decimal("0.00"), Decimal("0.00")

    if tot_paid > Decimal("0.00"):
        # Sebagian terbayar
        curr_status = InstallmentStatus.DIBAYAR.value
    elif installment.due_date > as_of:
        curr_status = InstallmentStatus.BELUM_JATUH_TEMPO.value
    elif installment.due_date == as_of:
        curr_status = InstallmentStatus.JATUH_TEMPO.value
    else:
        curr_status = InstallmentStatus.TERLAMBAT.value

    days_late = 0
    if installment.due_date < as_of and tot_paid < tot_due:
        days_late = (as_of - installment.due_date).days

    return curr_status, days_late, installment.penalty_due or Decimal("0.00"), rem_due


def process_installment_payment(
    db: Session,
    current_user: User,
    data: InstallmentPaymentRequest
) -> Dict[str, Any]:
    """
    Eksekusi pembayaran angsuran oleh Kasir/Admin secara atomik:
    1. Validasi nominal, status pinjaman, dan tagihan
    2. Transaksi database (Atomic ACID):
       - Alokasi: Denda -> Bunga -> Pokok
       - Simpan LoanPayment
       - Update akumulasi LoanInstallment
       - Kurangi saldo Loan (remaining_principal & remaining_interest)
       - Update Loan status ke LUNAS jika seluruh tagihan beres
       - Catat CashTransaction kas masuk loket (CASH_IN)
       - Catat AuditLog
    3. Kembalikan data kuitansi resmi (InstallmentReceiptOut)
    """
    # 1. Validasi Input
    amount = Decimal(str(data.amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Nominal pembayaran angsuran harus lebih dari Rp 0")

    installment = db.query(LoanInstallment).filter(LoanInstallment.id == data.installment_id).first()
    if not installment:
        raise HTTPException(status_code=404, detail="Data tagihan angsuran tidak ditemukan")

    loan = installment.loan
    if not loan:
        raise HTTPException(status_code=404, detail="Data pinjaman tidak ditemukan")

    # Status pinjaman harus aktif berjalan
    if loan.status not in [LoanStatus.BERJALAN.value, "ACTIVE"]:
        if loan.status in [LoanStatus.LUNAS.value, "PAID_OFF"]:
            raise HTTPException(status_code=400, detail=f"Pembayaran ditolak: Pinjaman {loan.loan_no} sudah lunas")
        raise HTTPException(
            status_code=400, 
            detail=f"Pembayaran ditolak: Status pinjaman saat ini adalah '{loan.status}' (Hanya pinjaman BERJALAN yang dapat dibayar)"
        )

    # Cek keterlambatan & denda
    today = datetime.now(timezone.utc).date()
    if installment.due_date < today and (installment.total_paid or Decimal("0.00")) < (installment.total_due or Decimal("0.00")):
        installment.days_overdue = (today - installment.due_date).days
        # Hitung denda jika ada penalty rate di produk dan penalty_due masih 0
        if loan.product and loan.product.penalty_rate_daily > Decimal("0.00") and (installment.penalty_due or Decimal("0.00")) == Decimal("0.00"):
            daily_rate = loan.product.penalty_rate_daily / Decimal("100")
            calc_pen = (installment.principal_due * daily_rate * Decimal(installment.days_overdue)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            installment.penalty_due = calc_pen
            installment.total_due = installment.principal_due + installment.interest_due + calc_pen

    tot_target = _target_due(installment)
    tot_paid = installment.total_paid or Decimal("0.00")
    rem_due = max(Decimal("0.00"), tot_target - tot_paid)

    if rem_due <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail=f"Angsuran #{installment.installment_no} pada pinjaman {loan.loan_no} sudah lunas")

    if amount > rem_due:
        raise HTTPException(
            status_code=400,
            detail=f"Nominal pembayaran (Rp {amount:,.0f}) melebihi sisa tagihan angsuran ini (Rp {rem_due:,.0f})"
        )

    # 2. Database Transaction Atomik
    try:
        # Hitung alokasi porsi: Denda -> Bunga -> Pokok
        rem_penalty = max(Decimal("0.00"), (installment.penalty_due or Decimal("0.00")) - (installment.penalty_paid or Decimal("0.00")))
        pen_portion = min(amount, rem_penalty)
        rem_after_pen = amount - pen_portion

        rem_interest = max(Decimal("0.00"), (installment.interest_due or Decimal("0.00")) - (installment.interest_paid or Decimal("0.00")))
        int_portion = min(rem_after_pen, rem_interest)
        prin_portion = rem_after_pen - int_portion

        # Generate nomor pembayaran dan kuitansi
        pay_no = generate_payment_number(db)
        rcp_no = generate_receipt_number(db)

        # A. Buat record LoanPayment
        payment = LoanPayment(
            payment_no=pay_no,
            loan_id=loan.id,
            installment_id=installment.id,
            member_id=loan.member_id,
            amount_paid=amount,
            principal_portion=prin_portion,
            interest_portion=int_portion,
            penalty_portion=pen_portion,
            payment_method=data.payment_method,
            receipt_no=rcp_no,
            received_by_user_id=current_user.id,
            notes=data.notes
        )
        db.add(payment)

        # B. Update LoanInstallment
        installment.principal_paid = (installment.principal_paid or Decimal("0.00")) + prin_portion
        installment.interest_paid = (installment.interest_paid or Decimal("0.00")) + int_portion
        installment.penalty_paid = (installment.penalty_paid or Decimal("0.00")) + pen_portion
        installment.total_paid = (installment.total_paid or Decimal("0.00")) + amount

        new_total_paid = installment.total_paid
        if new_total_paid >= tot_target:
            installment.status = InstallmentStatus.LUNAS.value
            installment.paid_at = datetime.now(timezone.utc)
        else:
            installment.status = InstallmentStatus.DIBAYAR.value

        # C. Update Saldo Loan Induk
        loan.remaining_principal = max(Decimal("0.00"), (loan.remaining_principal or Decimal("0.00")) - prin_portion)
        loan.remaining_interest = max(Decimal("0.00"), (loan.remaining_interest or Decimal("0.00")) - int_portion)

        # Cek apakah seluruh jadwal angsuran pinjaman ini telah LUNAS
        all_insts = db.query(LoanInstallment).filter(LoanInstallment.loan_id == loan.id).all()
        is_loan_fully_paid = True
        for inst in all_insts:
            inst_target = _target_due(inst)
            # Perhitungkan angsuran yang sedang diupdate
            inst_paid = installment.total_paid if inst.id == installment.id else (inst.total_paid or Decimal("0.00"))
            if inst_paid < inst_target:
                is_loan_fully_paid = False
                break

        if is_loan_fully_paid:
            loan.status = LoanStatus.LUNAS.value

        # D. Catat Transaksi Kas Masuk (CashTransaction: CASH_IN)
        cash_trx_no = f"TRX-CSH-{pay_no}"
        cash_trx = CashTransaction(
            transaction_no=cash_trx_no,
            cashier_user_id=current_user.id,
            direction=CashDirection.CASH_IN.value,
            category=CashCategory.LOAN_PAYMENT.value,
            amount=amount,
            member_id=loan.member_id,
            reference_no=loan.loan_no,
            receipt_no=rcp_no,
            payment_method=data.payment_method,
            notes=f"Penerimaan Angsuran #{installment.installment_no} Pinjaman {loan.loan_no} Anggota {loan.member.full_name}"
        )
        db.add(cash_trx)

        # Commit atomik
        db.commit()
        db.refresh(installment)
        db.refresh(loan)
        db.refresh(payment)

        # E. Audit Trail
        AuditService.log_event(
            db=db,
            action="PAY_LOAN_INSTALLMENT",
            entity_name="LoanInstallment",
            entity_id=str(installment.id),
            user_id=current_user.id,
            new_values={
                "payment_no": pay_no,
                "receipt_no": rcp_no,
                "amount_paid": float(amount),
                "principal_portion": float(prin_portion),
                "interest_portion": float(int_portion),
                "penalty_portion": float(pen_portion),
                "installment_status": installment.status,
                "loan_remaining_principal": float(loan.remaining_principal),
                "loan_status": loan.status
            },
            notes=f"Penerimaan Kas Angsuran #{installment.installment_no} Pinjaman {loan.loan_no} sebesar Rp {amount:,.0f} ({installment.status})"
        )

        # E2. Prompt #13: notifikasi pembayaran ke pemilik pinjaman
        # (nominal dari record resmi payment, bukan input frontend)
        from app.services.notification_service import NotificationService as _INS
        _owner = loan.member.user_id if loan.member else None
        if _owner:
            _INS.send(db, _owner,
                      title=f"Pembayaran angsuran #{installment.installment_no} diterima",
                      message=(f"Pembayaran {loan.loan_no} sebesar Rp {payment.amount_paid:,.0f} "
                               f"diterima (kuitansi {payment.receipt_no})." +
                               (" Pinjaman Anda LUNAS." if loan.status == LoanStatus.LUNAS.value else "")),
                      ntype="SUCCESS", link_url="/installments",
                      entity_name="LoanPayment", entity_id=str(payment.id),
                      event=f"InstallmentPaid:{payment.id}", actor_id=current_user.id)

        # F. Buat Struk / Kuitansi Resmi
        words = terbilang(int(amount)).strip()
        words = (words[0].upper() + words[1:]) if words else "Nol"
        words += " Rupiah"

        rem_inst_after = max(Decimal("0.00"), tot_target - installment.total_paid)

        receipt_data = {
            "receipt_no": rcp_no,
            "payment_no": pay_no,
            "cash_transaction_no": cash_trx_no,
            "cooperative_name": "KSP AHNRFZI",
            "cooperative_address": "Gedung Pusat Koperasi Simpan Pinjam AHNRFZI",
            "cooperative_phone": "(021) 7890-1234",
            "payment_date": payment.created_at,
            "loan_id": loan.id,
            "loan_no": loan.loan_no,
            "product_name": loan.product.name if loan.product else "",
            "installment_id": installment.id,
            "installment_no": installment.installment_no,
            "due_date": installment.due_date,
            "member_id": loan.member_id,
            "member_no": loan.member.member_no if loan.member else "",
            "member_name": loan.member.full_name if loan.member else "",
            "member_department": loan.member.unit_divisi if loan.member else None,
            "cashier_name": current_user.username,
            "amount_paid": amount,
            "amount_in_words": words,
            "principal_portion": prin_portion,
            "interest_portion": int_portion,
            "penalty_portion": pen_portion,
            "remaining_installment_due": rem_inst_after,
            "remaining_loan_principal": loan.remaining_principal,
            "installment_status_after": installment.status,
            "loan_status_after": loan.status,
            "payment_method": data.payment_method,
            "notes": data.notes
        }

        return receipt_data

    except Exception as e:
        db.rollback()
        logger.error(f"[INSTALLMENT PAYMENT ERROR] Failed to process payment for installment {installment.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Terjadi kegagalan transaksi pembayaran angsuran: {str(e)}"
        )


def get_installments_list(
    db: Session,
    current_user: User,
    search: Optional[str] = None,
    status: Optional[str] = None,
    loan_id: Optional[int] = None,
    member_id: Optional[int] = None,
    is_overdue_only: bool = False,
    page: int = 1,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Mengambil daftar angsuran dengan kalkulasi status dinamis dan proteksi otorisasi / IDOR.
    """
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    is_staff = bool({"installment.view", "loan.view", "cashier.view", "*"} & user_perms)
    is_admin = "ADMIN_KOPERASI" in {r.code for r in current_user.roles} or "ADMIN" in {r.code for r in current_user.roles}

    query = db.query(LoanInstallment).join(Loan).join(Member)

    # Proteksi IDOR: Anggota biasa hanya melihat angsurannya sendiri
    if not (is_staff or is_admin):
        query = query.filter(Member.user_id == current_user.id)
    else:
        if member_id:
            query = query.filter(Loan.member_id == member_id)

    if loan_id:
        query = query.filter(LoanInstallment.loan_id == loan_id)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Loan.loan_no.ilike(s),
                Member.full_name.ilike(s),
                Member.member_no.ilike(s)
            )
        )

    today = datetime.now(timezone.utc).date()

    if is_overdue_only:
        query = query.filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        )

    if status:
        stat_upper = status.upper()
        if stat_upper == InstallmentStatus.LUNAS.value or stat_upper == "PAID":
            query = query.filter(LoanInstallment.total_paid >= LoanInstallment.total_due)
        elif stat_upper == InstallmentStatus.DIBAYAR.value or stat_upper == "PARTIAL":
            query = query.filter(
                LoanInstallment.total_paid > Decimal("0.00"),
                LoanInstallment.total_paid < LoanInstallment.total_due
            )
        elif stat_upper == InstallmentStatus.TERLAMBAT.value or stat_upper == "OVERDUE":
            query = query.filter(
                LoanInstallment.due_date < today,
                LoanInstallment.total_paid < LoanInstallment.total_due
            )
        elif stat_upper == InstallmentStatus.JATUH_TEMPO.value:
            query = query.filter(
                LoanInstallment.due_date == today,
                LoanInstallment.total_paid < LoanInstallment.total_due
            )
        elif stat_upper == InstallmentStatus.BELUM_JATUH_TEMPO.value or stat_upper == "UNPAID":
            query = query.filter(
                LoanInstallment.due_date > today,
                LoanInstallment.total_paid == Decimal("0.00")
            )
        else:
            query = query.filter(LoanInstallment.status == status)

    installments = query.order_by(LoanInstallment.due_date.asc(), LoanInstallment.installment_no.asc()).offset((page - 1) * limit).limit(limit).all()

    items = []
    for inst in installments:
        dyn_status, days_late, pen_due, rem_due = calculate_installment_overdue_and_status(inst, today)
        items.append({
            "id": inst.id,
            "installment_no": inst.installment_no,
            "loan_id": inst.loan_id,
            "loan_no": inst.loan.loan_no if inst.loan else "",
            "member_id": inst.loan.member_id if inst.loan else 0,
            "member_no": inst.loan.member.member_no if (inst.loan and inst.loan.member) else "",
            "member_name": inst.loan.member.full_name if (inst.loan and inst.loan.member) else "",
            "member_department": inst.loan.member.unit_divisi if (inst.loan and inst.loan.member) else None,
            "due_date": inst.due_date,
            "principal_due": inst.principal_due,
            "interest_due": inst.interest_due,
            "penalty_due": pen_due,
            "total_due": _target_due(inst),
            "principal_paid": inst.principal_paid or Decimal("0.00"),
            "interest_paid": inst.interest_paid or Decimal("0.00"),
            "penalty_paid": inst.penalty_paid or Decimal("0.00"),
            "total_paid": inst.total_paid or Decimal("0.00"),
            "remaining_due": rem_due,
            "status": dyn_status,
            "days_overdue": days_late,
            "paid_at": inst.paid_at
        })

    return items


def get_member_installment_overview(db: Session, member_id: int) -> Dict[str, Any]:
    """Ringkasan portofolio cicilan dan tagihan bagi anggota."""
    today = datetime.now(timezone.utc).date()
    first_day_month = date(today.year, today.month, 1)
    if today.month == 12:
        last_day_month = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day_month = date(today.year, today.month + 1, 1) - timedelta(days=1)

    active_loans = db.query(Loan).filter(
        Loan.member_id == member_id,
        Loan.status.in_([LoanStatus.BERJALAN.value, "ACTIVE"])
    ).all()

    total_out_prin = sum(Decimal(str(l.remaining_principal or 0)) for l in active_loans)
    total_out_int = sum(Decimal(str(l.remaining_interest or 0)) for l in active_loans)

    # Ambil seluruh angsuran aktif yang belum lunas
    active_loan_ids = [l.id for l in active_loans]
    unpaid_installments = db.query(LoanInstallment).filter(
        LoanInstallment.loan_id.in_(active_loan_ids),
        LoanInstallment.total_paid < LoanInstallment.total_due
    ).order_by(LoanInstallment.due_date.asc()).all() if active_loan_ids else []

    total_due_this_month = Decimal("0.00")
    total_overdue = Decimal("0.00")
    overdue_count = 0
    next_due_date = None
    next_due_amt = None
    next_due_loan_no = None

    for inst in unpaid_installments:
        _, days_late, pen_due, rem_due = calculate_installment_overdue_and_status(inst, today)
        if first_day_month <= inst.due_date <= last_day_month:
            total_due_this_month += rem_due
        if inst.due_date < today:
            total_overdue += rem_due
            overdue_count += 1
        if next_due_date is None and inst.due_date >= today:
            next_due_date = inst.due_date
            next_due_amt = rem_due
            next_due_loan_no = inst.loan.loan_no if inst.loan else None

    # Jika tidak ada yang jatuh tempo di masa depan, gunakan yang overdue pertama
    if next_due_date is None and unpaid_installments:
        first_unpaid = unpaid_installments[0]
        next_due_date = first_unpaid.due_date
        _, _, _, rem = calculate_installment_overdue_and_status(first_unpaid, today)
        next_due_amt = rem
        next_due_loan_no = first_unpaid.loan.loan_no if first_unpaid.loan else None

    return {
        "total_active_loans": len(active_loans),
        "total_outstanding_principal": total_out_prin,
        "total_outstanding_interest": total_out_int,
        "total_due_this_month": total_due_this_month,
        "total_overdue_amount": total_overdue,
        "overdue_installments_count": overdue_count,
        "next_due_date": next_due_date,
        "next_due_amount": next_due_amt,
        "next_due_loan_no": next_due_loan_no
    }

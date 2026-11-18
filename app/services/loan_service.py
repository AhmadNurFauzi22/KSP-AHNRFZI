from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from app.db.models.loan import (
    Loan, LoanProduct, LoanApproval, LoanInstallment, 
    LoanStatus, LoanCalculationType, InstallmentStatus
)
from app.db.models.member import Member, MemberStatus
from app.db.models.user import User
from app.db.models.transaction import CashTransaction, CashDirection, CashCategory
from app.schemas.loan import (
    LoanSimulationRequest, LoanSimulationResponse, LoanSimulationInstallmentItem,
    LoanCreateRequest, LoanVerifyRequest, LoanApproveRequest, 
    LoanRejectRequest, LoanDisburseRequest
)
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.core.logging import logger


# ---------------------------------------------------------------------------
# Prompt #10 — helpers workflow: stage aktor, riwayat transisi, notifikasi
# ---------------------------------------------------------------------------
# Event yang dipancarkan (integration point untuk Prompt #13 / notifikasi):
# LoanSubmitted, LoanVerified, LoanApproved, LoanRejected, LoanDisbursed.

def _actor_stage(user: User) -> str:
    """Tentukan stage approval dari peran aktif aktor (tanpa hardcode tunggal)."""
    codes = {r.code for r in (user.roles or [])}
    active = getattr(user, "active_role", None) or (user.roles[0].code if user.roles else "")
    for candidate in (active, *sorted(codes)):
        if candidate in ("ADMIN_KOPERASI", "ADMIN"):
            return "ADMIN"
        if candidate in ("KETUA_UMUM", "KETUA"):
            return "KETUA_UMUM"
        if candidate == "MANAGER":
            return "MANAGER"
        if candidate == "STAF":
            return "STAF"
        if candidate == "KASIR":
            return "KASIR"
        if candidate == "HRD":
            return "HRD"
        if candidate in ("PENGAWAS_PEMBINA", "PENGAWAS"):
            return "PENGAWAS"
    return active or "SISTEM"


def _record_approval(db: Session, loan: Loan, user: User, decision: str,
                     from_status: str, to_status: str,
                     amount: Optional[Decimal] = None,
                     notes: Optional[str] = None) -> LoanApproval:
    """Catat riwayat approval beserta transisi status (tidak menghapus history)."""
    rec = LoanApproval(
        loan_id=loan.id,
        approver_user_id=user.id,
        stage=_actor_stage(user),
        decision=decision,
        from_status=from_status,
        to_status=to_status,
        approved_amount=amount if amount is not None else Decimal("0.00"),
        notes=notes,
    )
    db.add(rec)
    return rec


def _notify_loan_event(db: Session, loan: Loan, event: str, title: str,
                       message: str, ntype: str = "APPROVAL") -> None:
    """Hook notifikasi in-app untuk pemilik pinjaman via layanan terpusat.

    Nominal finansial memakai record resmi loan; dedup per event+pinjaman.
    """
    owner_id = loan.member.user_id if loan.member else None
    if not owner_id:
        return
    NotificationService.send(
        db, owner_id, title, message, ntype=ntype, link_url="/loans",
        entity_name="Loan", entity_id=str(loan.id), event=f"{event}:{loan.id}")


def calculate_loan_simulation(
    principal: Decimal,
    tenor_months: int,
    annual_interest_rate: Decimal,
    calculation_type: str = "FLAT",
    admin_fee_percent: Decimal = Decimal("1.0"),
    provision_fee_percent: Decimal = Decimal("0.5")
) -> Dict[str, Any]:
    """
    Perhitungan simulasi pinjaman presisi tinggi (Decimal).
    Mendukung metode FLAT, ANUITAS, dan SLIDING.
    """
    principal = Decimal(str(principal)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    annual_rate = Decimal(str(annual_interest_rate)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    admin_pct = Decimal(str(admin_fee_percent or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    prov_pct = Decimal(str(provision_fee_percent or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tenor = int(tenor_months)

    if principal <= Decimal("0"):
        raise ValueError("Nominal pokok pinjaman harus lebih besar dari 0")
    if tenor <= 0:
        raise ValueError("Tenor pinjaman minimal 1 bulan")

    admin_fee = (principal * (admin_pct / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    provision_fee = (principal * (prov_pct / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    net_disbursed = principal - admin_fee - provision_fee

    monthly_rate = (annual_rate / Decimal("100")) / Decimal("12")
    schedule = []
    total_interest = Decimal("0.00")

    calc_upper = calculation_type.upper()

    if calc_upper == LoanCalculationType.FLAT.value or calc_upper == "FLAT":
        base_monthly_prin = (principal / Decimal(tenor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        base_monthly_int = (principal * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        rem_prin = principal
        for m in range(1, tenor + 1):
            if m < tenor:
                p_due = base_monthly_prin
                i_due = base_monthly_int
            else:
                p_due = rem_prin
                i_due = base_monthly_int

            rem_prin -= p_due
            total_inst = p_due + i_due
            total_interest += i_due

            schedule.append({
                "installment_no": m,
                "due_month": m,
                "principal_portion": p_due,
                "interest_portion": i_due,
                "total_installment": total_inst,
                "remaining_principal": max(Decimal("0.00"), rem_prin)
            })

        monthly_principal = base_monthly_prin
        monthly_interest = base_monthly_int
        monthly_installment_total = schedule[0]["total_installment"]

    elif calc_upper == LoanCalculationType.ANUITAS.value or calc_upper == "ANUITAS":
        rate_f = float(annual_rate) / 100.0 / 12.0
        if rate_f > 0:
            annuity_factor = (rate_f * ((1.0 + rate_f) ** tenor)) / (((1.0 + rate_f) ** tenor) - 1.0)
            target_monthly_inst = (Decimal(str(round(float(principal) * annuity_factor, 2)))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            target_monthly_inst = (principal / Decimal(tenor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        rem_prin = principal
        for m in range(1, tenor + 1):
            i_due = (rem_prin * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if m < tenor:
                p_due = target_monthly_inst - i_due
                if p_due > rem_prin:
                    p_due = rem_prin
            else:
                p_due = rem_prin

            rem_prin -= p_due
            total_inst = p_due + i_due
            total_interest += i_due

            schedule.append({
                "installment_no": m,
                "due_month": m,
                "principal_portion": p_due,
                "interest_portion": i_due,
                "total_installment": total_inst,
                "remaining_principal": max(Decimal("0.00"), rem_prin)
            })

        monthly_principal = schedule[0]["principal_portion"]
        monthly_interest = schedule[0]["interest_portion"]
        monthly_installment_total = target_monthly_inst

    elif calc_upper == LoanCalculationType.SLIDING.value or calc_upper == "SLIDING":
        base_monthly_prin = (principal / Decimal(tenor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rem_prin = principal

        for m in range(1, tenor + 1):
            if m < tenor:
                p_due = base_monthly_prin
            else:
                p_due = rem_prin

            i_due = (rem_prin * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            rem_prin -= p_due
            total_inst = p_due + i_due
            total_interest += i_due

            schedule.append({
                "installment_no": m,
                "due_month": m,
                "principal_portion": p_due,
                "interest_portion": i_due,
                "total_installment": total_inst,
                "remaining_principal": max(Decimal("0.00"), rem_prin)
            })

        monthly_principal = base_monthly_prin
        monthly_interest = schedule[0]["interest_portion"]
        monthly_installment_total = schedule[0]["total_installment"]

    else:
        raise ValueError(f"Metode perhitungan bunga '{calculation_type}' tidak didukung. Pilih FLAT, ANUITAS, atau SLIDING.")

    total_payable = principal + total_interest

    return {
        "principal": principal,
        "tenor_months": tenor,
        "annual_interest_rate": annual_rate,
        "calculation_type": calc_upper,
        "monthly_principal": monthly_principal,
        "monthly_interest": monthly_interest,
        "monthly_installment_total": monthly_installment_total,
        "total_interest": total_interest,
        "total_payable": total_payable,
        "admin_fee": admin_fee,
        "provision_fee": provision_fee,
        "net_disbursement": net_disbursed,
        "schedule": schedule
    }


def generate_loan_number(db: Session) -> str:
    """Generate running nomor pinjaman: LOAN-YYYY-XXXX"""
    current_year = datetime.now(timezone.utc).year
    prefix = f"LOAN-{current_year}-"
    last_loan = db.query(Loan).filter(Loan.loan_no.like(f"{prefix}%")).order_by(Loan.id.desc()).first()
    if last_loan:
        try:
            last_seq = int(last_loan.loan_no.split("-")[-1])
            seq = last_seq + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


def create_loan_application(
    db: Session,
    current_user: User,
    data: LoanCreateRequest,
    document_path: Optional[str] = None
) -> Loan:
    """Buat pengajuan pinjaman baru (status DRAFT atau DIAJUKAN)."""
    # 1. Tentukan Member
    if data.member_id:
        member = db.query(Member).filter(Member.id == data.member_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Anggota tidak ditemukan")
    else:
        member = db.query(Member).filter(Member.user_id == current_user.id).first()
        if not member:
            raise HTTPException(status_code=400, detail="Akun Anda belum terhubung dengan data anggota koperasi")

    # 2. Cek status keaktifan anggota
    if member.status != MemberStatus.AKTIF.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Pengajuan pinjaman ditolak: Status anggota saat ini adalah {member.status} (Hanya anggota AKTIF yang dapat mengajukan pinjaman)"
        )

    # 3. Validasi Produk Pinjaman
    product = db.query(LoanProduct).filter(LoanProduct.id == data.product_id).first()
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="Produk pinjaman tidak ditemukan atau sedang tidak aktif")

    # 4. Validasi Batas Nominal & Tenor
    req_amt = Decimal(str(data.requested_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if req_amt < product.min_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Nominal pengajuan (Rp {req_amt:,.0f}) kurang dari batas minimum produk (Rp {product.min_amount:,.0f})"
        )
    if req_amt > product.max_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Nominal pengajuan (Rp {req_amt:,.0f}) melebihi batas maksimum plafon produk (Rp {product.max_amount:,.0f})"
        )

    if data.tenor_months < product.min_tenor_months:
        raise HTTPException(
            status_code=400,
            detail=f"Tenor pinjaman ({data.tenor_months} bln) kurang dari tenor minimum produk ({product.min_tenor_months} bln)"
        )
    if data.tenor_months > product.max_tenor_months:
        raise HTTPException(
            status_code=400,
            detail=f"Tenor pinjaman ({data.tenor_months} bln) melebihi tenor maksimum produk ({product.max_tenor_months} bln)"
        )

    # 5. Jalankan Simulasi Kalkulasi
    sim = calculate_loan_simulation(
        principal=req_amt,
        tenor_months=data.tenor_months,
        annual_interest_rate=product.annual_interest_rate,
        calculation_type=product.calculation_type,
        admin_fee_percent=product.admin_fee_percent,
        provision_fee_percent=product.provision_fee_percent
    )

    loan_no = generate_loan_number(db)
    init_status = LoanStatus.DRAFT.value if data.is_draft else LoanStatus.DIAJUKAN.value

    loan = Loan(
        loan_no=loan_no,
        member_id=member.id,
        product_id=product.id,
        requested_amount=req_amt,
        approved_amount=None,
        interest_rate_percent=product.annual_interest_rate,
        tenor_months=data.tenor_months,
        calculation_type=product.calculation_type,
        admin_fee=sim["admin_fee"],
        provision_fee=sim["provision_fee"],
        net_disbursed_amount=sim["net_disbursement"],
        monthly_principal=sim["monthly_principal"],
        monthly_interest=sim["monthly_interest"],
        monthly_installment_total=sim["monthly_installment_total"],
        total_interest=sim["total_interest"],
        total_payable=sim["total_payable"],
        remaining_principal=req_amt,
        remaining_interest=sim["total_interest"],
        purpose=data.purpose.strip(),
        collateral_info=data.collateral_info.strip() if data.collateral_info else None,
        status=init_status,
        document_path=document_path
    )

    db.add(loan)
    db.commit()
    db.refresh(loan)

    # Prompt #13: pengajuan langsung DIAJUKAN juga memberitahu pemilik +
    # verifikator (DRAFT menunggu submit dan belum perlu notifikasi)
    if init_status == LoanStatus.DIAJUKAN.value:
        _notify_loan_event(db, loan, event="LoanSubmitted",
                           title=f"Pinjaman {loan.loan_no} diajukan",
                           message=f"Pengajuan pinjaman {loan.loan_no} telah masuk dan menunggu verifikasi.",
                           ntype="INFO")
        NotificationService.notify_users_with_permission(
            db, ["loan.verify", "*"],
            title=f"Perlu verifikasi: {loan.loan_no}",
            message=f"Pengajuan {loan.loan_no} menunggu verifikasi berkas.",
            ntype="APPROVAL", link_url="/loans",
            entity_name="Loan", entity_id=str(loan.id),
            event=f"LoanNeedsVerify:{loan.id}", actor_id=current_user.id)
        db.commit()
        db.refresh(loan)

    # Audit Log
    AuditService.log_event(
        db=db,
        action="CREATE_LOAN_APPLICATION",
        entity_name="Loan",
        entity_id=str(loan.id),
        user_id=current_user.id,
        new_values={
            "loan_no": loan.loan_no,
            "member_id": member.id,
            "status": loan.status,
            "requested_amount": float(req_amt),
            "tenor_months": data.tenor_months
        },
        notes=f"Pengajuan pinjaman {loan.loan_no} senilai Rp {req_amt:,.0f} dibuat dengan status {loan.status}"
    )

    return loan


def submit_draft_loan(db: Session, current_user: User, loan_id: int, notes: Optional[str] = None) -> Loan:
    """Submit pinjaman dari status DRAFT menjadi DIAJUKAN."""
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Pinjaman tidak ditemukan")

    if loan.status != LoanStatus.DRAFT.value:
        raise HTTPException(status_code=400, detail=f"Hanya pinjaman berstatus DRAFT yang dapat diajukan (status saat ini: {loan.status})")

    # Cek hak kepemilikan jika anggota biasa
    if loan.member.user_id != current_user.id:
        user_perms = {p.code for r in current_user.roles for p in r.permissions}
        if "loan.create" not in user_perms and "admin" not in {r.code for r in current_user.roles}:
            raise HTTPException(status_code=403, detail="Anda tidak berhak men-submit draf pengajuan anggota lain")

    loan.status = LoanStatus.DIAJUKAN.value

    _record_approval(db, loan, current_user, decision="SUBMITTED",
                     from_status=LoanStatus.DRAFT.value,
                     to_status=LoanStatus.DIAJUKAN.value,
                     amount=loan.requested_amount,
                     notes=notes or "Draf diajukan ke koperasi")
    _notify_loan_event(db, loan, event="LoanSubmitted",
                       title=f"Pinjaman {loan.loan_no} diajukan",
                       message=f"Pengajuan pinjaman {loan.loan_no} telah masuk dan menunggu verifikasi.",
                       ntype="INFO")
    # Fan-out peran: verifikator perlu bertindak (tanpa data sensitif berlebih)
    NotificationService.notify_users_with_permission(
        db, ["loan.verify", "*"],
        title=f"Perlu verifikasi: {loan.loan_no}",
        message=f"Pengajuan {loan.loan_no} menunggu verifikasi berkas.",
        ntype="APPROVAL", link_url="/loans",
        entity_name="Loan", entity_id=str(loan.id),
        event=f"LoanNeedsVerify:{loan.id}", actor_id=current_user.id)
    db.commit()
    db.refresh(loan)

    AuditService.log_event(
        db=db,
        action="SUBMIT_LOAN",
        entity_name="Loan",
        entity_id=str(loan.id),
        user_id=current_user.id,
        old_values={"status": LoanStatus.DRAFT.value},
        new_values={"status": LoanStatus.DIAJUKAN.value},
        notes=f"Draf pinjaman {loan.loan_no} resmi diajukan ke koperasi. {notes or ''}"
    )

    return loan


def verify_loan(db: Session, current_user: User, loan_id: int, notes: Optional[str] = None) -> Loan:
    """
    Verifikasi berkas & kelayakan pinjaman oleh Staf/Manager (DIAJUKAN -> VERIFIKASI).
    Menerapkan aturan tata kelola Koperasi: Anggota dilarang verifikasi pinjamannya sendiri.
    """
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Pinjaman tidak ditemukan")

    if loan.status != LoanStatus.DIAJUKAN.value and loan.status != "SUBMITTED":
        raise HTTPException(
            status_code=400, 
            detail=f"Pinjaman tidak dapat diverifikasi pada status '{loan.status}'. Status harus DIAJUKAN."
        )

    # ANTI-SELF-APPROVAL / VERIFICATION RULE (dicek sebelum transisi agar
    # pelanggaran tata kelola selalu 403 terlepas dari status)
    if loan.member.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pelanggaran Tata Kelola Koperasi: Anda tidak diperkenankan memverifikasi pengajuan pinjaman Anda sendiri."
        )

    from_status = loan.status
    loan.status = LoanStatus.VERIFIKASI.value

    # Rekam riwayat approval stage + transisi
    _record_approval(db, loan, current_user, decision="VERIFIED",
                     from_status=from_status,
                     to_status=LoanStatus.VERIFIKASI.value,
                     amount=loan.requested_amount,
                     notes=notes or "Berkas dan kelayakan pengajuan telah diverifikasi")
    _notify_loan_event(db, loan, event="LoanVerified",
                       title=f"Pinjaman {loan.loan_no} terverifikasi",
                       message=f"Pinjaman {loan.loan_no} lolos verifikasi dan menunggu persetujuan.",
                       ntype="APPROVAL")
    # Fan-out peran: approver perlu bertindak
    NotificationService.notify_users_with_permission(
        db, ["loan.approve", "*"],
        title=f"Perlu persetujuan: {loan.loan_no}",
        message=f"Pinjaman {loan.loan_no} terverifikasi dan menunggu persetujuan.",
        ntype="APPROVAL", link_url="/loans",
        entity_name="Loan", entity_id=str(loan.id),
        event=f"LoanNeedsApprove:{loan.id}", actor_id=current_user.id)
    db.commit()
    db.refresh(loan)

    AuditService.log_event(
        db=db,
        action="VERIFY_LOAN",
        entity_name="Loan",
        entity_id=str(loan.id),
        user_id=current_user.id,
        old_values={"status": from_status},
        new_values={"status": LoanStatus.VERIFIKASI.value},
        notes=f"Pinjaman {loan.loan_no} diverifikasi oleh {current_user.username}. {notes or ''}"
    )

    return loan


def approve_loan(
    db: Session, 
    current_user: User, 
    loan_id: int, 
    approved_amount: Decimal, 
    notes: Optional[str] = None
) -> Loan:
    """
    Persetujuan pinjaman oleh Manager/Ketua (VERIFIKASI -> DISETUJUI).
    Transisi DIAJUKAN -> DISETUJUI langsung DITOLAK agar verifikasi
    tidak dapat dilompati (segregation of duties).
    Menerapkan aturan tata kelola Koperasi: Anggota dilarang approve pinjamannya sendiri.
    """
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Pinjaman tidak ditemukan")

    # ANTI-SELF-APPROVAL RULE (CRITICAL) — dicek dulu sebelum transisi
    if loan.member.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pelanggaran Tata Kelola Koperasi: Anda dilarang memberikan persetujuan (approval) atas pengajuan pinjaman Anda sendiri."
        )

    # Workflow transition check (ketat: wajib sudah VERIFIKASI)
    valid_pre_statuses = [LoanStatus.VERIFIKASI.value, "VERIFIED_STAF"]
    if loan.status not in valid_pre_statuses:
        raise HTTPException(
            status_code=400, 
            detail=f"Pinjaman tidak dapat disetujui pada status '{loan.status}'. Status harus VERIFIKASI."
        )

    appr_amt = Decimal(str(approved_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if appr_amt <= Decimal("0"):
        raise HTTPException(status_code=400, detail="Nominal pinjaman yang disetujui harus lebih dari 0")
    if appr_amt > loan.product.max_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Nominal disetujui (Rp {appr_amt:,.0f}) melebihi batas maksimum produk (Rp {loan.product.max_amount:,.0f})"
        )

    # Hitung ulang amortisasi pinjaman berdasarkan nominal yang disetujui
    sim = calculate_loan_simulation(
        principal=appr_amt,
        tenor_months=loan.tenor_months,
        annual_interest_rate=loan.interest_rate_percent,
        calculation_type=loan.calculation_type,
        admin_fee_percent=loan.product.admin_fee_percent,
        provision_fee_percent=loan.product.provision_fee_percent
    )

    loan.approved_amount = appr_amt
    loan.admin_fee = sim["admin_fee"]
    loan.provision_fee = sim["provision_fee"]
    loan.net_disbursed_amount = sim["net_disbursement"]
    loan.monthly_principal = sim["monthly_principal"]
    loan.monthly_interest = sim["monthly_interest"]
    loan.monthly_installment_total = sim["monthly_installment_total"]
    loan.total_interest = sim["total_interest"]
    loan.total_payable = sim["total_payable"]
    loan.remaining_principal = appr_amt
    loan.remaining_interest = sim["total_interest"]

    from_status = loan.status
    loan.status = LoanStatus.DISETUJUI.value
    loan.approved_by_user_id = current_user.id
    loan.approved_at = datetime.now(timezone.utc)

    # Rekam riwayat approval + transisi
    _record_approval(db, loan, current_user, decision="APPROVED",
                     from_status=from_status,
                     to_status=LoanStatus.DISETUJUI.value,
                     amount=appr_amt,
                     notes=notes or f"Disetujui dengan plafon Rp {appr_amt:,.0f}")
    _notify_loan_event(db, loan, event="LoanApproved",
                       title=f"Pinjaman {loan.loan_no} disetujui",
                       message=f"Pinjaman {loan.loan_no} disetujui senilai Rp {appr_amt:,.0f}.",
                       ntype="SUCCESS")
    # Fan-out peran: kasir perlu mencairkan (nominal dari record resmi)
    NotificationService.notify_users_with_permission(
        db, ["loan.disburse", "*"],
        title=f"Siap dicairkan: {loan.loan_no}",
        message=f"Pinjaman {loan.loan_no} disetujui dan menunggu pencairan di loket.",
        ntype="APPROVAL", link_url="/cashier",
        entity_name="Loan", entity_id=str(loan.id),
        event=f"LoanNeedsDisburse:{loan.id}", actor_id=current_user.id)
    db.commit()
    db.refresh(loan)

    AuditService.log_event(
        db=db,
        action="APPROVE_LOAN",
        entity_name="Loan",
        entity_id=str(loan.id),
        user_id=current_user.id,
        old_values={"status": from_status},
        new_values={"approved_amount": float(appr_amt), "status": loan.status},
        notes=f"Pinjaman {loan.loan_no} disetujui senilai Rp {appr_amt:,.0f} oleh {current_user.username}"
    )

    return loan


def reject_loan(db: Session, current_user: User, loan_id: int, reason: str) -> Loan:
    """Penolakan pengajuan pinjaman (DIAJUKAN / VERIFIKASI -> DITOLAK)."""
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Pinjaman tidak ditemukan")

    valid_pre_statuses = [LoanStatus.DIAJUKAN.value, LoanStatus.VERIFIKASI.value, "SUBMITTED", "VERIFIED_STAF"]

    # ANTI-SELF-APPROVAL / REJECTION (dicek dulu sebelum transisi)
    if loan.member.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pelanggaran Tata Kelola Koperasi: Anda tidak diperkenankan memproses penolakan pengajuan pinjaman Anda sendiri."
        )

    if loan.status not in valid_pre_statuses:
        raise HTTPException(
            status_code=400, 
            detail=f"Pinjaman pada status '{loan.status}' tidak dapat ditolak."
        )

    clean_reason = (reason or "").strip()
    if len(clean_reason) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Alasan penolakan wajib diisi (minimal 3 karakter)."
        )

    from_status = loan.status
    loan.status = LoanStatus.DITOLAK.value
    loan.rejection_reason = clean_reason

    _record_approval(db, loan, current_user, decision="REJECTED",
                     from_status=from_status,
                     to_status=LoanStatus.DITOLAK.value,
                     amount=Decimal("0.00"),
                     notes=clean_reason)
    _notify_loan_event(db, loan, event="LoanRejected",
                       title=f"Pinjaman {loan.loan_no} ditolak",
                       message=f"Pinjaman {loan.loan_no} ditolak. Alasan: {clean_reason}",
                       ntype="DANGER")
    db.commit()
    db.refresh(loan)

    AuditService.log_event(
        db=db,
        action="REJECT_LOAN",
        entity_name="Loan",
        entity_id=str(loan.id),
        user_id=current_user.id,
        old_values={"status": from_status},
        new_values={"status": LoanStatus.DITOLAK.value, "rejection_reason": clean_reason},
        notes=f"Pinjaman {loan.loan_no} ditolak oleh {current_user.username}. Alasan: {clean_reason}"
    )

    return loan


def disburse_loan(
    db: Session, 
    current_user: User, 
    loan_id: int, 
    payment_method: str = "CASH", 
    notes: Optional[str] = None
) -> Loan:
    """
    Pencairan pinjaman (DISETUJUI -> DICAIRKAN -> BERJALAN).
    Mengeksekusi transaksi database atomik:
    1. Catat waktu dan kasir pencairan
    2. Buat CashTransaction pengeluaran kas
    3. Bangkitkan N jadwal angsuran (LoanInstallment)
    4. Buat AuditLog
    """
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Pinjaman tidak ditemukan")

    # ANTI-SELF-DISBURSE RULE: kasir dilarang mencairkan pinjamannya sendiri
    # (dicek dulu sebelum transisi agar pelanggaran selalu 403)
    if loan.member.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pelanggaran Tata Kelola Koperasi: Anda dilarang mencairkan pinjaman Anda sendiri."
        )

    if loan.status != LoanStatus.DISETUJUI.value and loan.status != "APPROVED_MANAGER" and loan.status != "APPROVED_KETUA":
        raise HTTPException(
            status_code=400,
            detail=f"Pencairan gagal: Pinjaman harus berstatus DISETUJUI (status saat ini: {loan.status})"
        )

    from_status = loan.status

    disbursed_now = datetime.now(timezone.utc)
    appr_amt = loan.approved_amount or loan.requested_amount

    # Jalankan simulasi ulang untuk mendapatkan jadwal amortisasi presisi
    sim = calculate_loan_simulation(
        principal=appr_amt,
        tenor_months=loan.tenor_months,
        annual_interest_rate=loan.interest_rate_percent,
        calculation_type=loan.calculation_type,
        admin_fee_percent=loan.product.admin_fee_percent,
        provision_fee_percent=loan.product.provision_fee_percent
    )

    # 1. Update data pinjaman
    loan.status = LoanStatus.BERJALAN.value
    loan.disbursed_at = disbursed_now
    loan.disbursed_by_user_id = current_user.id

    # 2. Buat Transaksi Pengeluaran Kas (CASH_OUT)
    trx_no = f"TRX-DISB-{loan.loan_no}-{int(disbursed_now.timestamp())}"
    rcp_no = f"RCP-DISB-{loan.loan_no}"
    
    cash_trx = CashTransaction(
        transaction_no=trx_no,
        cashier_user_id=current_user.id,
        direction=CashDirection.CASH_OUT.value,
        category=CashCategory.LOAN_DISBURSEMENT.value,
        amount=loan.net_disbursed_amount if loan.net_disbursed_amount > 0 else appr_amt,
        member_id=loan.member_id,
        reference_no=loan.loan_no,
        receipt_no=rcp_no,
        payment_method=payment_method,
        notes=f"Pencairan Pinjaman {loan.loan_no} kepada Anggota {loan.member.full_name}. {notes or ''}"
    )
    db.add(cash_trx)

    # 3. Bangkitkan Jadwal Angsuran (LoanInstallment)
    start_date = disbursed_now.date()
    for item in sim["schedule"]:
        # Jatuh tempo tiap 30 hari
        due_d = start_date + timedelta(days=30 * item["installment_no"])
        status_initial = InstallmentStatus.BELUM_JATUH_TEMPO.value
        installment = LoanInstallment(
            loan_id=loan.id,
            installment_no=item["installment_no"],
            due_date=due_d,
            principal_due=item["principal_portion"],
            interest_due=item["interest_portion"],
            penalty_due=Decimal("0.00"),
            total_due=item["total_installment"],
            principal_paid=Decimal("0.00"),
            interest_paid=Decimal("0.00"),
            penalty_paid=Decimal("0.00"),
            total_paid=Decimal("0.00"),
            status=status_initial
        )
        db.add(installment)

    # Set tanggal jatuh tempo akhir
    if sim["schedule"]:
        loan.due_date = start_date + timedelta(days=30 * sim["schedule"][-1]["installment_no"])

    # Rekam riwayat pencairan + transisi (atomik dalam transaksi yang sama)
    _record_approval(db, loan, current_user, decision="DISBURSED",
                     from_status=from_status,
                     to_status=LoanStatus.BERJALAN.value,
                     amount=appr_amt,
                     notes=notes or f"Dicairkan senilai Rp {appr_amt:,.0f} via {payment_method}")
    _notify_loan_event(db, loan, event="LoanDisbursed",
                       title=f"Pinjaman {loan.loan_no} dicairkan",
                       message=f"Dana pinjaman {loan.loan_no} telah dicairkan dan jadwal angsuran terbentuk.",
                       ntype="SUCCESS")

    # Commit transaksi atomik
    db.commit()
    db.refresh(loan)

    # 4. Rekam Audit Log
    AuditService.log_event(
        db=db,
        action="DISBURSE_LOAN",
        entity_name="Loan",
        entity_id=str(loan.id),
        user_id=current_user.id,
        old_values={"status": from_status},
        new_values={
            "status": loan.status,
            "disbursed_at": disbursed_now.isoformat(),
            "net_disbursed_amount": float(loan.net_disbursed_amount),
            "cash_transaction_no": trx_no
        },
        notes=f"Pencairan pinjaman {loan.loan_no} berhasil dilakukan senilai Rp {loan.net_disbursed_amount:,.0f} oleh Kasir {current_user.username}"
    )

    return loan


def get_loan_by_id(db: Session, current_user: User, loan_id: int) -> Loan:
    """Mengambil detail pinjaman dengan proteksi otorisasi dan IDOR."""
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Data pinjaman tidak ditemukan")

    # Proteksi IDOR: Anggota biasa hanya dapat melihat pinjamannya sendiri
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    is_staff_or_monitoring = bool({"loan.view", "loan.approve", "loan.verify", "loan.disburse", "*"} & user_perms)
    
    if not is_staff_or_monitoring and "admin" not in {r.code for r in current_user.roles}:
        if loan.member.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Anda tidak memiliki hak akses melihat rincian pinjaman anggota lain")

    return loan

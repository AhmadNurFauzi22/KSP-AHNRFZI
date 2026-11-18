"""
API: Modul Pinjaman KSP AHNRFZI
================================
Endpoints lengkap untuk workflow pinjaman koperasi:
- DRAFT -> DIAJUKAN -> VERIFIKASI -> DISETUJUI/DITOLAK -> DICAIRKAN -> BERJALAN -> LUNAS
- Simulasi pinjaman backend terpisah (FLAT, ANUITAS, SLIDING)
- Pengajuan pinjaman & upload berkas
- Verifikasi & Persetujuan berjenjang dengan aturan ANTI-SELF-APPROVAL
- Pencairan pinjaman & pembentukan jadwal angsuran atomik
- Monitoring portofolio kredit koperasi
"""
import os
from typing import Optional, List
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from app.core.database import get_db
from app.core.permissions import get_current_user, require_permission
from app.db.models.user import User
from app.db.models.member import Member
from app.db.models.loan import Loan, LoanProduct, LoanApproval, LoanInstallment, LoanStatus
from app.schemas.loan import (
    LoanProductOut, LoanSimulationRequest, LoanSimulationResponse,
    LoanCreateRequest, LoanSubmitRequest, LoanVerifyRequest,
    LoanApproveRequest, LoanRejectRequest, LoanDisburseRequest,
    LoanListItemOut, LoanDetailOut, LoanApprovalOut, LoanInstallmentOut
)
from app.services import loan_service
from app.services.audit_service import AuditService

router = APIRouter(prefix="/loans", tags=["Loans"])

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads", "loans")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _serialize_loan_detail(loan: Loan) -> dict:
    """Helper serialisasi detail pinjaman secara aman dan lengkap."""
    approvals_list = []
    for app_rec in loan.approvals:
        approvals_list.append({
            "id": app_rec.id,
            "stage": app_rec.stage,
            "decision": app_rec.decision,
            "from_status": getattr(app_rec, "from_status", None),
            "to_status": getattr(app_rec, "to_status", None),
            "approved_amount": app_rec.approved_amount,
            "notes": app_rec.notes,
            "approver_user_id": app_rec.approver_user_id,
            "approver_name": app_rec.approver.username if app_rec.approver else None,
            "created_at": app_rec.created_at
        })

    installments_list = []
    for inst in sorted(loan.installments, key=lambda x: x.installment_no):
        installments_list.append({
            "id": inst.id,
            "installment_no": inst.installment_no,
            "due_date": inst.due_date,
            "principal_due": inst.principal_due,
            "interest_due": inst.interest_due,
            "penalty_due": inst.penalty_due,
            "total_due": inst.total_due,
            "principal_paid": inst.principal_paid,
            "interest_paid": inst.interest_paid,
            "penalty_paid": inst.penalty_paid,
            "total_paid": inst.total_paid,
            "status": inst.status,
            "paid_at": inst.paid_at,
            "days_overdue": inst.days_overdue
        })

    return {
        "id": loan.id,
        "loan_no": loan.loan_no,
        "member_id": loan.member_id,
        "member_user_id": loan.member.user_id if loan.member else None,
        "member_no": loan.member.member_no if loan.member else "",
        "member_name": loan.member.full_name if loan.member else "",
        "member_nik": loan.member.nik if loan.member else None,
        "member_phone": loan.member.phone_number if loan.member else None,
        "member_department": loan.member.unit_divisi if loan.member else None,
        "product_id": loan.product_id,
        "product_code": loan.product.code if loan.product else "",
        "product_name": loan.product.name if loan.product else "",
        "requested_amount": loan.requested_amount,
        "approved_amount": loan.approved_amount,
        "interest_rate_percent": loan.interest_rate_percent,
        "tenor_months": loan.tenor_months,
        "calculation_type": loan.calculation_type,
        "admin_fee": loan.admin_fee,
        "provision_fee": loan.provision_fee,
        "net_disbursed_amount": loan.net_disbursed_amount,
        "monthly_principal": loan.monthly_principal,
        "monthly_interest": loan.monthly_interest,
        "monthly_installment_total": loan.monthly_installment_total,
        "total_interest": loan.total_interest,
        "total_payable": loan.total_payable,
        "remaining_principal": loan.remaining_principal,
        "remaining_interest": loan.remaining_interest,
        "purpose": loan.purpose,
        "collateral_info": loan.collateral_info,
        "status": loan.status,
        "document_path": loan.document_path,
        "rejection_reason": loan.rejection_reason,
        "approved_by_user_id": loan.approved_by_user_id,
        "approved_by_name": loan.approved_by.username if loan.approved_by else None,
        "approved_at": loan.approved_at,
        "disbursed_by_user_id": loan.disbursed_by_user_id,
        "disbursed_by_name": loan.disbursed_by.username if loan.disbursed_by else None,
        "disbursed_at": loan.disbursed_at,
        "due_date": loan.due_date,
        "created_at": loan.created_at,
        "updated_at": loan.updated_at,
        "approvals": approvals_list,
        "installments": installments_list
    }


# =============================================================================
# 1. PRODUK & SIMULASI PINJAMAN (SERVICE TERPISAH)
# =============================================================================

@router.get("/products", response_model=List[LoanProductOut])
def list_loan_products(db: Session = Depends(get_db)):
    """Mengambil daftar seluruh produk pinjaman yang aktif."""
    return db.query(LoanProduct).filter(LoanProduct.is_active == True).all()


@router.post("/simulation", response_model=LoanSimulationResponse)
def simulate_loan(req: LoanSimulationRequest, db: Session = Depends(get_db)):
    """
    Kalkulator simulasi pinjaman terpisah (backend service).
    Mendukung konfigurasi Pokok, Bunga, Tenor, dan Metode perhitungan (FLAT, ANUITAS, SLIDING).
    Frontend dilarang keras meng-hardcode formula matematika.
    """
    annual_rate = req.annual_interest_rate
    calc_type = req.calculation_type or "FLAT"
    admin_pct = req.admin_fee_percent
    prov_pct = req.provision_fee_percent

    # Jika memilih produk, ambil default rate & method dari produk jika tidak dispesifikasi
    if req.product_id:
        product = db.query(LoanProduct).filter(LoanProduct.id == req.product_id).first()
        if product:
            if annual_rate is None:
                annual_rate = product.annual_interest_rate
            if not req.calculation_type:
                calc_type = product.calculation_type
            if admin_pct is None:
                admin_pct = product.admin_fee_percent
            if prov_pct is None:
                prov_pct = product.provision_fee_percent

    if annual_rate is None:
        annual_rate = Decimal("12.0")

    try:
        sim = loan_service.calculate_loan_simulation(
            principal=req.principal,
            tenor_months=req.tenor_months,
            annual_interest_rate=annual_rate,
            calculation_type=calc_type,
            admin_fee_percent=admin_pct if admin_pct is not None else Decimal("1.0"),
            provision_fee_percent=prov_pct if prov_pct is not None else Decimal("0.5")
        )
        return sim
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# 2. PENGAJUAN PINJAMAN OLEH ANGGOTA
# =============================================================================

@router.post("/apply", response_model=LoanDetailOut, status_code=status.HTTP_201_CREATED)
def apply_loan(
    req: LoanCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Anggota membuat pengajuan pinjaman baru.
    Dapat disimpan sebagai draf (DRAFT) atau langsung diajukan (DIAJUKAN).
    """
    loan = loan_service.create_loan_application(
        db=db,
        current_user=current_user,
        data=req
    )
    return _serialize_loan_detail(loan)


@router.post("/{loan_id}/upload-document", response_model=LoanDetailOut)
def upload_loan_document(
    loan_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload dokumen pendukung (KTP, Slip Gaji, Agunan) untuk pengajuan pinjaman."""
    loan = loan_service.get_loan_by_id(db, current_user, loan_id)
    
    # Hanya boleh upload dokumen jika status belum dicairkan / belum disetujui
    if loan.status in [LoanStatus.BERJALAN.value, LoanStatus.LUNAS.value, LoanStatus.DITOLAK.value]:
        raise HTTPException(status_code=400, detail=f"Tidak dapat mengunggah dokumen pada status {loan.status}")

    # Simpan berkas — Prompt #11: sanitasi nama, whitelist ekstensi/MIME,
    # batasi ukuran (anti path traversal, executable, dan disk-DoS).
    ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
    ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
    MAX_UPLOAD_BYTES = 5 * 1024 * 1024
    orig_name = (file.filename or "").strip()
    base = os.path.basename(orig_name).replace(" ", "_")
    base = "".join(c for c in base if c.isalnum() or c in ("-", "_", "."))
    ext = os.path.splitext(base)[1].lower()
    if not base or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Jenis berkas tidak diizinkan. Hanya PDF/JPG/PNG/WebP."
        )
    if (file.content_type or "").split(";")[0].strip().lower() not in ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipe konten berkas tidak valid."
        )
    clean_filename = f"loan_{loan.id}_{int(datetime.now(timezone.utc).timestamp())}_{base}"
    file_path = os.path.join(UPLOAD_DIR, clean_filename)

    size = 0
    with open(file_path, "wb") as buffer:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                buffer.close()
                try:
                    os.remove(file_path)
                except OSError:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Ukuran berkas melebihi batas 5 MB."
                )
            buffer.write(chunk)
    if size == 0:
        try:
            os.remove(file_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="Berkas kosong tidak dapat diunggah.")

    loan.document_path = f"/uploads/loans/{clean_filename}"
    db.commit()
    db.refresh(loan)

    AuditService.log_event(
        db=db,
        action="UPLOAD_LOAN_DOCUMENT",
        entity_name="Loan",
        entity_id=str(loan.id),
        user_id=current_user.id,
        notes=f"Dokumen {file.filename} diunggah untuk pinjaman {loan.loan_no}"
    )

    return _serialize_loan_detail(loan)


@router.post("/{loan_id}/submit", response_model=LoanDetailOut)
def submit_draft(
    loan_id: int,
    req: Optional[LoanSubmitRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit draf pinjaman (DRAFT -> DIAJUKAN)."""
    notes = req.notes if req else None
    loan = loan_service.submit_draft_loan(db, current_user, loan_id, notes)
    return _serialize_loan_detail(loan)


# =============================================================================
# 3. VERIFIKASI & APPROVAL DENGAN ATURAN ANTI-SELF-APPROVAL
# =============================================================================

@router.post("/{loan_id}/verify", response_model=LoanDetailOut)
def verify_loan_application(
    loan_id: int,
    req: Optional[LoanVerifyRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verifikasi berkas & kelayakan pinjaman (DIAJUKAN -> VERIFIKASI).
    Membutuhkan izin: loan.verify (Staf/Manager).
    DILARANG: Anggota tidak boleh memverifikasi pinjamannya sendiri.
    """
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    if not ({"loan.verify", "*"} & user_perms) and "admin" not in {r.code for r in current_user.roles}:
        raise HTTPException(status_code=403, detail="Anda tidak memiliki izin (loan.verify) untuk memverifikasi pinjaman")

    notes = req.notes if req else None
    loan = loan_service.verify_loan(db, current_user, loan_id, notes)
    return _serialize_loan_detail(loan)


@router.post("/{loan_id}/approve", response_model=LoanDetailOut)
def approve_loan_application(
    loan_id: int,
    req: LoanApproveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Persetujuan pinjaman oleh Manager / Ketua Umum (VERIFIKASI -> DISETUJUI).
    Membutuhkan izin: loan.approve.
    DILARANG: Anggota tidak boleh menyetujui pinjamannya sendiri (Anti-Self-Approval).
    """
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    if not ({"loan.approve", "*"} & user_perms) and "admin" not in {r.code for r in current_user.roles}:
        raise HTTPException(status_code=403, detail="Anda tidak memiliki izin (loan.approve) untuk menyetujui pinjaman")

    loan = loan_service.approve_loan(
        db=db,
        current_user=current_user,
        loan_id=loan_id,
        approved_amount=req.approved_amount,
        notes=req.notes
    )
    return _serialize_loan_detail(loan)


@router.post("/{loan_id}/reject", response_model=LoanDetailOut)
def reject_loan_application(
    loan_id: int,
    req: LoanRejectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Penolakan pengajuan pinjaman (DIAJUKAN/VERIFIKASI -> DITOLAK).
    Membutuhkan izin: loan.verify atau loan.approve.
    DILARANG: Anggota tidak boleh memproses penolakan pengajuannya sendiri.
    """
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    if not ({"loan.verify", "loan.approve", "*"} & user_perms) and "admin" not in {r.code for r in current_user.roles}:
        raise HTTPException(status_code=403, detail="Anda tidak memiliki izin untuk menolak pinjaman ini")

    loan = loan_service.reject_loan(
        db=db,
        current_user=current_user,
        loan_id=loan_id,
        reason=req.reason
    )
    return _serialize_loan_detail(loan)


# =============================================================================
# 4. PENCAIRAN PINJAMAN (DISBURSEMENT) DENGAN DATABASE TRANSACTION
# =============================================================================

@router.post("/{loan_id}/disburse", response_model=LoanDetailOut)
def disburse_loan_fund(
    loan_id: int,
    req: Optional[LoanDisburseRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Pencairan pinjaman yang telah disetujui (DISETUJUI -> DICAIRKAN / BERJALAN).
    Mengeksekusi transaksi database atomik:
    - Update status dan tanggal pencairan
    - Buat bukti transaksi kas keluar (CashTransaction)
    - Bentuk jadwal angsuran (LoanInstallment) bulan 1..N
    - Catat audit trail
    Membutuhkan izin: loan.disburse (Kasir / Admin).
    """
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    if not ({"loan.disburse", "*"} & user_perms) and "admin" not in {r.code for r in current_user.roles}:
        raise HTTPException(status_code=403, detail="Anda tidak memiliki izin (loan.disburse) untuk mencairkan pinjaman")

    payment_method = req.payment_method if req else "CASH"
    notes = req.notes if req else None

    loan = loan_service.disburse_loan(
        db=db,
        current_user=current_user,
        loan_id=loan_id,
        payment_method=payment_method,
        notes=notes
    )
    return _serialize_loan_detail(loan)


# =============================================================================
# 5. QUERY, LIST & DETAIL DENGAN MONITORING & IDOR PROTECTION
# =============================================================================

@router.get("", response_model=List[LoanListItemOut])
def list_loans(
    search: Optional[str] = Query(None, description="Cari nomor pinjaman atau nama anggota"),
    status: Optional[str] = Query(None, description="Filter status alur pinjaman"),
    product_id: Optional[int] = Query(None, description="Filter produk pinjaman"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Daftar pinjaman koperasi.
    - Admin, Manager, Staf, Kasir, Pengawas/Pembina: Dapat melihat portofolio pinjaman sesuai hak monitoring.
    - Anggota Biasa: Hanya dapat melihat daftar pengajuan dan pinjaman miliknya sendiri.
    """
    user_perms = {p.code for r in current_user.roles for p in r.permissions}
    is_staff_or_monitoring = bool({"loan.view", "loan.approve", "loan.verify", "loan.disburse", "*"} & user_perms)
    is_admin = "ADMIN_KOPERASI" in {r.code for r in current_user.roles} or "ADMIN" in {r.code for r in current_user.roles}

    query = db.query(Loan).join(Member).join(LoanProduct)

    # Proteksi: Jika bukan staf/pengawas, batasi hanya pinjaman milik user sendiri
    if not (is_staff_or_monitoring or is_admin):
        query = query.filter(Member.user_id == current_user.id)
    else:
        # Jika anggota biasa ingin memfilter pinjamannya sendiri via query
        pass

    if status:
        stat_upper = status.upper()
        if stat_upper == "BERJALAN":
            query = query.filter(Loan.status.in_([LoanStatus.BERJALAN.value, "ACTIVE"]))
        elif stat_upper == "DIAJUKAN":
            query = query.filter(Loan.status.in_([LoanStatus.DIAJUKAN.value, "SUBMITTED"]))
        elif stat_upper == "DISETUJUI":
            query = query.filter(Loan.status.in_([LoanStatus.DISETUJUI.value, "APPROVED_MANAGER", "APPROVED_KETUA"]))
        elif stat_upper == "VERIFIKASI":
            query = query.filter(Loan.status.in_([LoanStatus.VERIFIKASI.value, "VERIFIED_STAF"]))
        elif stat_upper == "DITOLAK":
            query = query.filter(Loan.status.in_([LoanStatus.DITOLAK.value, "REJECTED"]))
        elif stat_upper == "LUNAS":
            query = query.filter(Loan.status.in_([LoanStatus.LUNAS.value, "PAID_OFF"]))
        else:
            query = query.filter(Loan.status == status)

    if product_id:
        query = query.filter(Loan.product_id == product_id)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Loan.loan_no.ilike(s),
                Member.full_name.ilike(s),
                Member.member_no.ilike(s)
            )
        )

    loans = query.order_by(desc(Loan.created_at)).offset((page - 1) * limit).limit(limit).all()

    items = []
    for l in loans:
        items.append({
            "id": l.id,
            "loan_no": l.loan_no,
            "member_id": l.member_id,
            "member_user_id": l.member.user_id if l.member else None,
            "member_no": l.member.member_no if l.member else "",
            "member_name": l.member.full_name if l.member else "",
            "product_id": l.product_id,
            "product_code": l.product.code if l.product else "",
            "product_name": l.product.name if l.product else "",
            "requested_amount": l.requested_amount,
            "approved_amount": l.approved_amount,
            "tenor_months": l.tenor_months,
            "interest_rate_percent": l.interest_rate_percent,
            "calculation_type": l.calculation_type,
            "monthly_installment_total": l.monthly_installment_total,
            "status": l.status,
            "created_at": l.created_at,
            "approved_at": l.approved_at,
            "approved_by_name": l.approved_by.username if l.approved_by else None,
            "disbursed_at": l.disbursed_at
        })
    return items


@router.get("/{loan_id}", response_model=LoanDetailOut)
def get_loan_detail(
    loan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Detail pinjaman lengkap (dengan proteksi IDOR)."""
    loan = loan_service.get_loan_by_id(db, current_user, loan_id)
    return _serialize_loan_detail(loan)


@router.get("/{loan_id}/installments", response_model=List[LoanInstallmentOut])
def get_loan_installments(
    loan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Jadwal angsuran pinjaman (1 s/d N)."""
    loan = loan_service.get_loan_by_id(db, current_user, loan_id)
    return sorted(loan.installments, key=lambda x: x.installment_no)

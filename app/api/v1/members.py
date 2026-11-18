"""
API: Modul Keanggotaan KSP AHNRFZI
=====================================
Endpoint CRUD anggota koperasi dengan:
- RBAC granular (member.view, member.create, member.update, member.view_all)
- IDOR Protection (anggota hanya bisa akses datanya sendiri)
- Pagination, Search, Filter
- Master data Unit/Jabatan/Status
- Aktivasi & Nonaktifkan anggota
"""
import math
import re
from datetime import date, datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    get_current_user, get_user_permissions,
    PermissionChecker, require_permission, require_role,
    SystemRole
)
from app.db.models.user import User
from app.db.models.member import Member, MemberStatus
from app.schemas.member import (
    MemberCreate, MemberUpdate, MemberSelfUpdate, MemberStatusChange,
    MemberOut, MemberListItem, MemberListResponse, MemberStatusEnum
)

router = APIRouter(prefix="/members", tags=["Keanggotaan Koperasi"])


# ============================================================================
# MASTER DATA ENDPOINTS
# ============================================================================

MASTER_UNIT_DIVISI = [
    {"code": "DIREKSI",     "name": "Direksi & TI"},
    {"code": "PENGURUS",    "name": "Pengurus Koperasi"},
    {"code": "OPERASIONAL", "name": "Operasional KSP"},
    {"code": "HR",          "name": "Human Resources"},
    {"code": "PENGAWAS",    "name": "Badan Pengawas"},
    {"code": "CS",          "name": "Customer Service"},
    {"code": "IT",          "name": "Information Technology"},
    {"code": "KASIR",       "name": "Kasir & Perbendaharaan"},
    {"code": "LAPANGAN",    "name": "Operasional Lapangan"},
    {"code": "KEUANGAN",    "name": "Keuangan & Akuntansi"},
    {"code": "UMUM",        "name": "Bagian Umum & Administrasi"},
    {"code": "LAINNYA",     "name": "Lainnya"},
]

MASTER_JABATAN = [
    {"code": "KETUA",           "name": "Ketua KSP"},
    {"code": "WAKIL_KETUA",     "name": "Wakil Ketua"},
    {"code": "SEKRETARIS",      "name": "Sekretaris"},
    {"code": "BENDAHARA",       "name": "Bendahara"},
    {"code": "PENGAWAS",        "name": "Ketua Pengawas"},
    {"code": "GM",              "name": "General Manager"},
    {"code": "MANAGER",         "name": "Manager"},
    {"code": "SUPERVISOR",      "name": "Supervisor"},
    {"code": "STAF_SENIOR",     "name": "Staf Senior"},
    {"code": "STAF",            "name": "Staf Operasional"},
    {"code": "KASIR",           "name": "Head Teller / Kasir"},
    {"code": "HR_SPECIALIST",   "name": "HR Specialist"},
    {"code": "IT_INFRA",        "name": "Infrastructure Specialist"},
    {"code": "IT_DEV",          "name": "Software Developer"},
    {"code": "FIELD",           "name": "Field Specialist"},
    {"code": "FRONT_OFFICE",    "name": "Front Office Officer"},
    {"code": "ANGGOTA_BIASA",   "name": "Anggota Biasa"},
    {"code": "LAINNYA",         "name": "Lainnya"},
]


@router.get("/master/unit-divisi", summary="Master Data Unit/Divisi")
def get_master_unit_divisi(current_user: User = Depends(get_current_user)):
    """Mendapatkan daftar master unit/divisi kerja."""
    return {"success": True, "data": MASTER_UNIT_DIVISI}


@router.get("/master/jabatan", summary="Master Data Jabatan")
def get_master_jabatan(current_user: User = Depends(get_current_user)):
    """Mendapatkan daftar master jabatan/posisi."""
    return {"success": True, "data": MASTER_JABATAN}


@router.get("/master/status", summary="Master Data Status Keanggotaan")
def get_master_status(current_user: User = Depends(get_current_user)):
    """Mendapatkan daftar status keanggotaan koperasi."""
    status_list = [
        {"code": "CALON",    "name": "Calon Anggota",    "color": "warning",  "desc": "Menunggu verifikasi keanggotaan"},
        {"code": "AKTIF",    "name": "Anggota Aktif",    "color": "success",  "desc": "Anggota aktif dapat bertransaksi"},
        {"code": "NONAKTIF", "name": "Anggota Nonaktif", "color": "secondary","desc": "Dibekukan sementara"},
        {"code": "KELUAR",   "name": "Keluar",           "color": "danger",   "desc": "Mengundurkan diri dari koperasi"},
    ]
    return {"success": True, "data": status_list}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _auto_generate_member_no(db: Session) -> str:
    """Auto-generate nomor anggota format KSP-YYYY-XXXX."""
    year = datetime.now().year
    prefix = f"KSP-{year}-"
    last = db.query(Member).filter(
        Member.member_no.like(f"{prefix}%")
    ).order_by(Member.id.desc()).first()
    
    if last and last.member_no:
        try:
            seq = int(last.member_no.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    
    return f"{prefix}{seq:04d}"


def _is_elevated_user(current_user: User) -> bool:
    """Cek apakah user memiliki akses elevated (bukan sekedar ANGGOTA)."""
    active_role = getattr(current_user, "active_role", None)
    effective_perms = get_user_permissions(current_user, active_role)
    
    elevated_roles = {"ADMIN_KOPERASI", "KETUA_UMUM", "MANAGER", "HRD", "STAF", "PENGAWAS_PEMBINA", "IT_PUSAT"}
    user_roles = set(current_user.role_codes)
    
    return (
        "member.view_all" in effective_perms
        or bool(elevated_roles & user_roles)
    )


def _get_member_or_404(member_id: int, db: Session) -> Member:
    """Get member by ID or raise 404."""
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data anggota dengan ID {member_id} tidak ditemukan."
        )
    return member


# ============================================================================
# ANGGOTA: SELF-SERVICE ENDPOINTS
# ============================================================================

@router.get("/me", response_model=MemberOut, summary="Profil Keanggotaan Saya")
def get_my_member_profile(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.view")),
    db: Session = Depends(get_db),
):
    """
    Anggota melihat profil keanggotaan dirinya sendiri.
    Tidak perlu member.view_all – setiap anggota bisa lihat profil sendiri.
    """
    if not current_user.member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profil keanggotaan koperasi tidak ditemukan untuk akun Anda."
        )
    return current_user.member


@router.patch("/me", response_model=MemberOut, summary="Update Profil Saya (Mandiri)")
def update_my_member_profile(
    payload: MemberSelfUpdate,
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("profile.update")),
    db: Session = Depends(get_db),
):
    """
    Anggota mengupdate data terbatas (alamat, HP, email, kontak darurat).
    Field lain (NIK, nama, status, dll) tidak bisa diubah mandiri.
    """
    if not current_user.member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profil keanggotaan koperasi tidak ditemukan untuk akun Anda."
        )
    
    member = current_user.member
    update_data = payload.dict(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(member, field, value)
    
    member.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(member)
    return member


# ============================================================================
# ADMIN: LIST ANGGOTA (WITH SEARCH, FILTER, PAGINATION)
# ============================================================================

@router.get("/", response_model=MemberListResponse, summary="Daftar Anggota Koperasi")
def list_members(
    # Pagination
    page: int = Query(default=1, ge=1, description="Halaman saat ini"),
    per_page: int = Query(default=15, ge=1, le=100, description="Jumlah item per halaman"),
    # Search
    search: Optional[str] = Query(default=None, max_length=100, description="Cari nama, NIK, atau nomor anggota"),
    # Filters
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter status: CALON, AKTIF, NONAKTIF, KELUAR"),
    unit_filter: Optional[str] = Query(default=None, alias="unit", description="Filter unit/divisi"),
    gender_filter: Optional[str] = Query(default=None, alias="gender", description="Filter jenis kelamin: L atau P"),
    # Sort
    sort_by: Optional[str] = Query(default="id", description="Kolom urutan: id, full_name, member_no, join_date"),
    sort_order: Optional[str] = Query(default="desc", description="Arah urutan: asc atau desc"),
    # Auth
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.view")),
    db: Session = Depends(get_db),
):
    """
    Daftar anggota koperasi dengan paginasi, pencarian, dan filter.
    - Admin, Manager, HRD, Staf: dapat melihat semua anggota.
    - Anggota biasa: diarahkan ke endpoint /me.
    """
    if not _is_elevated_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Diperlukan izin: member.view_all untuk melihat daftar seluruh anggota."
        )

    q = db.query(Member)

    # Search filter (nama, NIK, nomor anggota)
    if search:
        search_term = f"%{search.strip()}%"
        q = q.filter(or_(
            Member.full_name.ilike(search_term),
            Member.nik.ilike(search_term),
            Member.member_no.ilike(search_term),
            Member.phone_number.ilike(search_term),
        ))

    # Status filter
    if status_filter:
        if status_filter.upper() not in MemberStatusEnum.ALL:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Status filter tidak valid. Pilihan: {', '.join(MemberStatusEnum.ALL)}"
            )
        q = q.filter(Member.status == status_filter.upper())

    # Unit/divisi filter
    if unit_filter:
        q = q.filter(Member.unit_divisi.ilike(f"%{unit_filter}%"))

    # Gender filter
    if gender_filter and gender_filter.upper() in ("L", "P"):
        q = q.filter(Member.gender == gender_filter.upper())

    # Sorting
    sort_col_map = {
        "id": Member.id,
        "full_name": Member.full_name,
        "member_no": Member.member_no,
        "join_date": Member.join_date,
        "status": Member.status,
    }
    sort_col = sort_col_map.get(sort_by, Member.id)
    if sort_order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    total = q.count()
    total_pages = math.ceil(total / per_page) if total > 0 else 1
    offset = (page - 1) * per_page
    items = q.offset(offset).limit(per_page).all()

    return MemberListResponse(
        items=[MemberListItem.from_orm(m) for m in items],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


# ============================================================================
# ADMIN: DETAIL ANGGOTA (DENGAN IDOR PROTECTION)
# ============================================================================

@router.get("/{member_id}", response_model=MemberOut, summary="Detail Anggota")
def get_member_detail(
    member_id: int,
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.view")),
    db: Session = Depends(get_db),
):
    """
    Mendapatkan detail anggota berdasarkan ID.
    IDOR Protection: Anggota biasa hanya bisa lihat profil sendiri.
    """
    is_elevated = _is_elevated_user(current_user)

    if not is_elevated:
        # Pastikan anggota hanya bisa akses datanya sendiri
        if not current_user.member or current_user.member.id != member_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak: Anda tidak memiliki izin untuk melihat profil anggota lain. (IDOR Protection)"
            )

    return _get_member_or_404(member_id, db)


# ============================================================================
# ADMIN: CREATE ANGGOTA BARU
# ============================================================================

@router.post("/", response_model=MemberOut, status_code=status.HTTP_201_CREATED, summary="Daftarkan Anggota Baru")
def create_member(
    payload: MemberCreate,
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.create")),
    db: Session = Depends(get_db),
):
    """
    Mendaftarkan anggota koperasi baru.
    Memerlukan izin: member.create (Admin, Manager, HRD, Staf).
    """
    # Validasi NIK unik
    existing_nik = db.query(Member).filter(Member.nik == payload.nik).first()
    if existing_nik:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"NIK '{payload.nik}' sudah terdaftar sebagai anggota (No. {existing_nik.member_no})."
        )

    # Validasi member_no unik (jika di-supply manual)
    if payload.member_no:
        existing_no = db.query(Member).filter(Member.member_no == payload.member_no).first()
        if existing_no:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Nomor anggota '{payload.member_no}' sudah digunakan."
            )
    
    # Validasi email unik (jika ada)
    if payload.email:
        existing_email = db.query(Member).filter(Member.email == payload.email.lower()).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{payload.email}' sudah terdaftar sebagai anggota lain."
            )

    # Validasi user_id (jika dikaitkan)
    if payload.user_id:
        from app.db.models.user import User as UserModel
        user = db.query(UserModel).filter(UserModel.id == payload.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Akun pengguna dengan ID {payload.user_id} tidak ditemukan."
            )
        # Cek apakah user sudah punya member record
        if user.member:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Pengguna '{user.username}' sudah memiliki record keanggotaan (No. {user.member.member_no})."
            )

    # Validasi keterkaitan pegawai: harus ada & aktif (Prompt #10)
    if payload.employee_id:
        from app.services import employee_service
        emp = employee_service.validate_employee_link(db, payload.employee_id)
        if emp.member and emp.member.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Pegawai {emp.nip} sudah tertaut ke anggota {emp.member.member_no}."
            )

    # Auto-generate nomor anggota jika tidak di-supply
    member_no = payload.member_no or _auto_generate_member_no(db)

    new_member = Member(
        user_id=payload.user_id,
        employee_id=payload.employee_id,
        member_no=member_no,
        nik=payload.nik,
        full_name=payload.full_name.strip(),
        birth_place=payload.birth_place,
        birth_date=payload.birth_date,
        gender=payload.gender,
        address=payload.address,
        phone_number=payload.phone_number.strip(),
        email=payload.email.lower().strip() if payload.email else None,
        unit_divisi=payload.unit_divisi,
        jabatan=payload.jabatan,
        emergency_contact_name=payload.emergency_contact_name,
        emergency_contact_phone=payload.emergency_contact_phone,
        emergency_contact_relation=payload.emergency_contact_relation,
        status=payload.status or MemberStatus.CALON.value,
        join_date=payload.join_date or date.today(),
        notes=payload.notes,
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)

    # Prompt #13: notifikasi keanggotaan (pemilik akun + HRD bila perlu validasi)
    from app.services.notification_service import NotificationService as _MNS
    if new_member.user_id:
        _MNS.send(db, new_member.user_id,
                  title=f"Keanggotaan {new_member.member_no} dibuat",
                  message=f"Data keanggotaan Anda ({new_member.member_no}) telah didaftarkan dengan status {new_member.status}.",
                  ntype="SUCCESS", link_url="/members",
                  entity_name="Member", entity_id=str(new_member.id),
                  event=f"MemberCreated:{new_member.id}", actor_id=current_user.id)
    if (new_member.status or "").upper() in ("CALON", "PENDING"):
        _MNS.notify_roles(db, ["HRD"],
                          title=f"Validasi anggota baru: {new_member.member_no}",
                          message=f"Calon anggota {new_member.full_name} ({new_member.member_no}) membutuhkan validasi.",
                          ntype="APPROVAL", link_url="/members",
                          entity_name="Member", entity_id=str(new_member.id),
                          event=f"MemberNeedsValidation:{new_member.id}",
                          actor_id=current_user.id)
    return new_member


# ============================================================================
# ADMIN: UPDATE DATA ANGGOTA
# ============================================================================

@router.put("/{member_id}", response_model=MemberOut, summary="Update Data Anggota")
def update_member(
    member_id: int,
    payload: MemberUpdate,
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.update")),
    db: Session = Depends(get_db),
):
    """
    Mengupdate data anggota oleh Admin/Manager/HRD/Staf.
    Memerlukan izin: member.update.
    """
    member = _get_member_or_404(member_id, db)
    update_data = payload.dict(exclude_unset=True)

    # Prompt #11: whitelist eksplisit anti mass-assignment. Field sensitif
    # (nik, member_no, status, user_id, join_date) hanya via endpoint khusus.
    ALLOWED_UPDATE_FIELDS = {
        "employee_id", "full_name", "birth_place", "birth_date", "gender",
        "address", "phone_number", "email", "unit_divisi", "jabatan",
        "emergency_contact_name", "emergency_contact_phone",
        "emergency_contact_relation", "notes",
    }
    update_data = {k: v for k, v in update_data.items() if k in ALLOWED_UPDATE_FIELDS}

    # Validasi keterkaitan pegawai bila diubah: harus ada & aktif
    if "employee_id" in update_data and update_data["employee_id"]:
        from app.services import employee_service
        employee_service.validate_employee_link(db, update_data["employee_id"])

    # Validasi email unik (jika diubah)
    if "email" in update_data and update_data["email"]:
        new_email = update_data["email"].lower().strip()
        conflict = db.query(Member).filter(
            Member.email == new_email,
            Member.id != member_id
        ).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{new_email}' sudah digunakan anggota lain (No. {conflict.member_no})."
            )
        update_data["email"] = new_email

    for field, value in update_data.items():
        setattr(member, field, value)

    member.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(member)
    return member


# ============================================================================
# ADMIN: PERUBAHAN STATUS ANGGOTA
# ============================================================================

@router.patch("/{member_id}/status", response_model=MemberOut, summary="Ubah Status Keanggotaan")
def change_member_status(
    member_id: int,
    payload: MemberStatusChange,
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.update")),
    db: Session = Depends(get_db),
):
    """
    Mengubah status keanggotaan:
    - CALON → AKTIF: Aktivasi anggota
    - AKTIF → NONAKTIF: Pembekuan sementara
    - AKTIF / NONAKTIF → KELUAR: Pengunduran diri
    Memerlukan izin: member.update
    """
    member = _get_member_or_404(member_id, db)
    old_status = member.status

    member.status = payload.status
    if payload.notes:
        member.notes = payload.notes
    if payload.resigned_date:
        member.resigned_date = payload.resigned_date
    if payload.resignation_reason:
        member.resignation_reason = payload.resignation_reason
    
    # Set resigned_date jika status KELUAR dan belum diisi
    if payload.status == "KELUAR" and not member.resigned_date:
        member.resigned_date = date.today()

    member.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(member)

    # Prompt #13: notifikasi perubahan status ke pemilik akun
    if member.user_id and old_status != member.status:
        from app.services.notification_service import NotificationService as _MNS2
        _MNS2.send(db, member.user_id,
                   title=f"Status keanggotaan berubah: {member.status}",
                   message=f"Status keanggotaan Anda ({member.member_no}) berubah dari {old_status} menjadi {member.status}.",
                   ntype="INFO", link_url="/members",
                   entity_name="Member", entity_id=str(member.id),
                   event=f"MemberStatus:{member.id}:{member.status}",
                   actor_id=current_user.id)
    return member


@router.patch("/{member_id}/activate", response_model=MemberOut, summary="Aktivasi Anggota")
def activate_member(
    member_id: int,
    notes: Optional[str] = Query(default=None, description="Catatan aktivasi"),
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.update")),
    db: Session = Depends(get_db),
):
    """
    Shortcut untuk aktivasi anggota (status → AKTIF).
    Biasanya digunakan setelah verifikasi kelengkapan dokumen.
    """
    member = _get_member_or_404(member_id, db)
    member.status = MemberStatus.AKTIF.value
    if notes:
        member.notes = notes
    member.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(member)
    return member


@router.patch("/{member_id}/deactivate", response_model=MemberOut, summary="Nonaktifkan Anggota")
def deactivate_member(
    member_id: int,
    notes: Optional[str] = Query(default=None, description="Alasan nonaktif"),
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.update")),
    db: Session = Depends(get_db),
):
    """
    Shortcut untuk menonaktifkan anggota (status → NONAKTIF).
    """
    member = _get_member_or_404(member_id, db)
    member.status = MemberStatus.NONAKTIF.value
    if notes:
        member.notes = notes
    member.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(member)
    return member


# ============================================================================
# ADMIN: STATISTIK ANGGOTA (UNTUK DASHBOARD)
# ============================================================================

@router.get("/stats/summary", summary="Statistik Ringkas Anggota")
def get_member_stats(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("member.view")),
    db: Session = Depends(get_db),
):
    """Statistik ringkas jumlah anggota per status."""
    if not _is_elevated_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: Diperlukan izin member.view_all."
        )
    
    total = db.query(Member).count()
    aktif = db.query(Member).filter(Member.status == "AKTIF").count()
    calon = db.query(Member).filter(Member.status == "CALON").count()
    nonaktif = db.query(Member).filter(Member.status == "NONAKTIF").count()
    keluar = db.query(Member).filter(Member.status == "KELUAR").count()
    
    return {
        "success": True,
        "data": {
            "total": total,
            "aktif": aktif,
            "calon": calon,
            "nonaktif": nonaktif,
            "keluar": keluar,
        }
    }

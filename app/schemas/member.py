"""
Schemas: Modul Keanggotaan KSP AHNRFZI
=========================================
Pydantic schemas untuk validasi dan serialisasi data anggota koperasi.
"""
from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel, EmailStr, validator, Field
import re


# ============================================================================
# MASTER DATA SCHEMAS (Unit/Divisi, Jabatan, Status)
# ============================================================================

class UnitDivisi(BaseModel):
    """Master data unit/divisi kerja."""
    code: str
    name: str

    class Config:
        from_attributes = True


class JabatanItem(BaseModel):
    """Master data jabatan/posisi."""
    code: str
    name: str
    unit_code: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================================================
# MEMBER STATUS CONSTANTS
# ============================================================================

class MemberStatusEnum:
    CALON = "CALON"          # Calon anggota / pending verifikasi
    AKTIF = "AKTIF"          # Anggota aktif (dapat bertransaksi)
    NONAKTIF = "NONAKTIF"    # Dibekukan / ditangguhkan
    KELUAR = "KELUAR"        # Mengundurkan diri / keluar

    ALL = [CALON, AKTIF, NONAKTIF, KELUAR]


# ============================================================================
# MEMBER SCHEMAS
# ============================================================================

class MemberBase(BaseModel):
    """Basis data anggota koperasi (field umum)."""
    full_name: str = Field(..., min_length=2, max_length=120, description="Nama lengkap anggota")
    nik: str = Field(..., min_length=16, max_length=16, description="NIK KTP 16 digit")
    birth_place: Optional[str] = Field(None, max_length=60, description="Tempat lahir")
    birth_date: Optional[date] = Field(None, description="Tanggal lahir")
    gender: Optional[str] = Field(None, description="Jenis kelamin: L atau P")
    address: Optional[str] = Field(None, description="Alamat lengkap")
    phone_number: str = Field(..., min_length=8, max_length=20, description="Nomor HP aktif")
    email: Optional[str] = Field(None, max_length=120, description="Alamat email")
    unit_divisi: Optional[str] = Field(None, max_length=100, description="Unit/Divisi kerja")
    jabatan: Optional[str] = Field(None, max_length=100, description="Jabatan di organisasi")
    emergency_contact_name: Optional[str] = Field(None, max_length=100)
    emergency_contact_phone: Optional[str] = Field(None, max_length=25)
    emergency_contact_relation: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None, description="Catatan tambahan")

    @validator("nik")
    def validate_nik(cls, v):
        v = v.strip()
        if not re.fullmatch(r"\d{16}", v):
            raise ValueError("NIK harus terdiri dari 16 digit angka")
        return v

    @validator("phone_number")
    def validate_phone(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[\d\+\-\s]{8,20}", v):
            raise ValueError("Format nomor HP tidak valid")
        return v

    @validator("gender")
    def validate_gender(cls, v):
        if v is not None and v not in ("L", "P"):
            raise ValueError("Jenis kelamin harus 'L' (Laki-laki) atau 'P' (Perempuan)")
        return v

    @validator("email")
    def validate_email(cls, v):
        if v is not None and v.strip():
            v = v.strip().lower()
            if not re.fullmatch(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", v):
                raise ValueError("Format email tidak valid")
            return v
        return v


class MemberCreate(MemberBase):
    """Schema untuk pendaftaran anggota baru."""
    user_id: Optional[int] = Field(None, description="Referensi ke akun User (opsional)")
    employee_id: Optional[int] = Field(None, description="Referensi ke data pegawai (opsional, harus aktif)")
    member_no: Optional[str] = Field(
        None, max_length=40,
        description="Nomor anggota (opsional, auto-generate jika kosong)"
    )
    join_date: Optional[date] = Field(None, description="Tanggal bergabung koperasi")
    status: Optional[str] = Field(
        default="CALON",
        description="Status awal anggota: CALON, AKTIF, NONAKTIF, KELUAR"
    )

    @validator("status")
    def validate_status(cls, v):
        if v and v not in MemberStatusEnum.ALL:
            raise ValueError(f"Status tidak valid. Pilihan: {', '.join(MemberStatusEnum.ALL)}")
        return v or "CALON"

    @validator("member_no")
    def validate_member_no(cls, v):
        if v:
            v = v.strip().upper()
        return v


class MemberUpdate(BaseModel):
    """Schema untuk update data anggota (semua field opsional)."""
    employee_id: Optional[int] = Field(None, description="Referensi ke data pegawai (harus aktif)")
    full_name: Optional[str] = Field(None, min_length=2, max_length=120)
    birth_place: Optional[str] = Field(None, max_length=60)
    birth_date: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    phone_number: Optional[str] = Field(None, min_length=8, max_length=20)
    email: Optional[str] = Field(None, max_length=120)
    unit_divisi: Optional[str] = Field(None, max_length=100)
    jabatan: Optional[str] = Field(None, max_length=100)
    emergency_contact_name: Optional[str] = Field(None, max_length=100)
    emergency_contact_phone: Optional[str] = Field(None, max_length=25)
    emergency_contact_relation: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None

    @validator("gender")
    def validate_gender(cls, v):
        if v is not None and v not in ("L", "P"):
            raise ValueError("Jenis kelamin harus 'L' atau 'P'")
        return v

    @validator("phone_number")
    def validate_phone(cls, v):
        if v:
            v = v.strip()
            if not re.fullmatch(r"[\d\+\-\s]{8,20}", v):
                raise ValueError("Format nomor HP tidak valid")
        return v

    @validator("email")
    def validate_email(cls, v):
        if v is not None and v.strip():
            v = v.strip().lower()
            if not re.fullmatch(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", v):
                raise ValueError("Format email tidak valid")
        return v


class MemberSelfUpdate(BaseModel):
    """
    Schema untuk anggota mengupdate data dirinya sendiri.
    Hanya field yang diperbolehkan untuk diubah mandiri.
    """
    address: Optional[str] = Field(None, description="Alamat tempat tinggal")
    phone_number: Optional[str] = Field(None, min_length=8, max_length=20)
    email: Optional[str] = Field(None, max_length=120)
    emergency_contact_name: Optional[str] = Field(None, max_length=100)
    emergency_contact_phone: Optional[str] = Field(None, max_length=25)
    emergency_contact_relation: Optional[str] = Field(None, max_length=50)

    @validator("phone_number")
    def validate_phone(cls, v):
        if v:
            v = v.strip()
            if not re.fullmatch(r"[\d\+\-\s]{8,20}", v):
                raise ValueError("Format nomor HP tidak valid")
        return v

    @validator("email")
    def validate_email(cls, v):
        if v is not None and v.strip():
            v = v.strip().lower()
            if not re.fullmatch(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", v):
                raise ValueError("Format email tidak valid")
        return v


class MemberStatusChange(BaseModel):
    """Schema untuk perubahan status keanggotaan."""
    status: str = Field(..., description="Status baru: CALON, AKTIF, NONAKTIF, KELUAR")
    notes: Optional[str] = Field(None, description="Alasan / catatan perubahan status")
    resigned_date: Optional[date] = Field(None, description="Tanggal keluar (untuk status KELUAR)")
    resignation_reason: Optional[str] = Field(None, description="Alasan keluar koperasi")

    @validator("status")
    def validate_status(cls, v):
        if v not in MemberStatusEnum.ALL:
            raise ValueError(f"Status tidak valid. Pilihan: {', '.join(MemberStatusEnum.ALL)}")
        return v


# ============================================================================
# OUTPUT SCHEMAS
# ============================================================================

class MemberOut(BaseModel):
    """Schema output detail anggota koperasi."""
    id: int
    user_id: Optional[int] = None
    employee_id: Optional[int] = None
    member_no: str
    nik: str
    full_name: str
    birth_place: Optional[str] = None
    birth_date: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    phone_number: str
    email: Optional[str] = None
    unit_divisi: Optional[str] = None
    jabatan: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    status: str
    join_date: date
    resigned_date: Optional[date] = None
    resignation_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemberListItem(BaseModel):
    """Schema ringkas untuk list/tabel anggota."""
    id: int
    member_no: str
    nik: str
    full_name: str
    phone_number: str
    email: Optional[str] = None
    unit_divisi: Optional[str] = None
    jabatan: Optional[str] = None
    status: str
    join_date: date
    gender: Optional[str] = None

    class Config:
        from_attributes = True


class MemberListResponse(BaseModel):
    """Schema paginasi untuk list anggota."""
    items: List[MemberListItem]
    total: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_prev: bool

from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username atau email terdaftar")
    password: str = Field(..., description="Kata sandi akun")
    preferred_role: Optional[str] = Field(None, description="Pilihan peran awal jika multi-role")
    captcha_id: Optional[str] = Field(None, description="ID Sesi CAPTCHA")
    captcha_code: Optional[str] = Field(None, description="Jawaban kode keamanan CAPTCHA")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: int
    username: str
    full_name: str
    active_role: str
    roles: List[str]
    permissions: List[str]


class SwitchRoleRequest(BaseModel):
    target_role: str = Field(..., description="Kode peran tujuan (e.g. ANGGOTA, MANAGER)")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=6, description="Kata sandi saat ini")
    new_password: str = Field(..., min_length=8, description="Kata sandi baru (minimal 8 karakter)")
    confirm_password: str = Field(..., min_length=8, description="Konfirmasi kata sandi baru")


class ResetPasswordRequest(BaseModel):
    user_id: int = Field(..., description="ID Pengguna yang akan direset kata sandinya")
    new_password: str = Field(..., min_length=8, description="Kata sandi baru sementara")


class RoleInfo(BaseModel):
    id: int
    name: str
    code: str


class EmployeeProfile(BaseModel):
    id: int
    nip: str
    department: str
    position: str
    employment_status: str
    base_salary: float
    allowances: float
    total_income: float
    hire_date: str


class MemberProfile(BaseModel):
    id: int
    member_no: str
    nik: str
    full_name: str
    status: str
    join_date: str


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    phone_number: Optional[str] = None
    is_active: bool
    active_role: Optional[str] = None
    roles: List[RoleInfo]
    permissions: List[str]
    employee_profile: Optional[EmployeeProfile] = None
    member_profile: Optional[MemberProfile] = None

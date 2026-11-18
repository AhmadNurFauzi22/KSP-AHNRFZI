"""User context service untuk AI Assistant KSP AHNRFZI.

Mengambil identitas, role, permission, dan data profil pengguna
dari sesi terotentikasi server (bukan dari input user).
Fungsi ini digunakan oleh AI Assistant untuk menjawab pertanyaan
tentang identitas pengguna, role, dan akses data.
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.db.models.user import User
from app.core.permissions import get_user_permissions


def get_current_authenticated_user_context(db: Session, user: User) -> Dict[str, Any]:
    """Mendapatkan konteks otentikasi pengguna dari server-side session.
    
    Mengembalikan dictionary berisi:
    - full_name: Nama lengkap pengguna
    - active_role: Role aktif yang sedang login
    - is_member: Apakah pengguna adalah anggota koperasi
    - member_no: Nomor anggota (jika applicable)
    - jabatan: Jabatan/position pengguna
    - permissions: Himpunan izin efektif
    - all_roles: Daftar semua role yang dimiliki pengguna
    - user_id: ID pengguna
    """
    # Ambil role aktif dari user object
    active_role = getattr(user, "active_role", None)
    if not active_role and user.roles:
        active_role = user.roles[0].code
    
    # Ambil daftar semua role
    all_roles: List[str] = []
    if user.roles:
        all_roles = [r.code for r in user.roles]
    
    # Ambil permission efektif
    perms = get_user_permissions(user, active_role)
    
    # Cek apakah anggota koperasi
    is_member = False
    member_no = None
    jabatan = None
    
    # Cek member profile
    member = getattr(user, "member", None)
    if member:
        is_member = True
        member_no = getattr(member, "member_no", None)
        jabatan = getattr(member, "jabatan", None)
    
    # Cek employee profile
    employee = getattr(user, "employee", None)
    if employee:
        if not jabatan:
            jabatan = getattr(employee, "position", None)
    
    # Build context dictionary
    ctx: Dict[str, Any] = {
        "user_id": user.id,
        "full_name": getattr(user, "full_name", None) or getattr(user, "username", "Unknown"),
        "active_role": active_role or "ANGGOTA",
        "is_member": is_member,
        "member_no": member_no,
        "jabatan": jabatan,
        "permissions": perms,
        "all_roles": all_roles,
    }
    
    return ctx
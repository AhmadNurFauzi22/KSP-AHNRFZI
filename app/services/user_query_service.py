"""Service Terpusat untuk Query Database Pengguna.

Menyediakan operasi read-only terkait data pengguna menggunakan SQLAlchemy ORM.
Semua query hanyalah pembacaan (SELECT), tidak ada operasi WRITE (INSERT/UPDATE/DELETE).

Dibuat untuk digunakan oleh AI Assistant dan dashboard dengan konsistensi data.
"""

from typing import Dict, Any, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.db.models.user import User
from app.db.models import Role
from app.services.database_knowledge_layer import is_table_allowed, get_allowed_columns


def get_user_count(db: Session, active_only: bool = False, status_filter: str = None) -> Dict[str, int]:
    """Mengembalikan jumlah pengguna dari database.
    
    Args:
        db: Session SQLAlchemy
        active_only: Jika True, hanya count pengguna aktif (is_active=True)
        status_filter: Filter tambahan berdasarkan status (e.g., "ACTIVE", "NONAKTIF")
    
    Returns:
        Dict dengan kunci 'total' berisi jumlah pengguna
    """
    query = db.query(User)
    
    if active_only:
        query = query.filter(User.is_active.is_(True))
    
    if status_filter:
        # Map status filter ke kolom is_active atau status anggota
        if status_filter.upper() in ("ACTIVE", "AKTIF"):
            query = query.filter(User.is_active.is_(True))
        elif status_filter.upper() in ("INACTIVE", "NONAKTIF", "TIDAK AKTIF"):
            query = query.filter(User.is_active.is_(False))
    
    count = query.count() or 0
    return {"total": count}


def get_user_count_by_role(db: Session, role_code: str) -> Dict[str, int]:
    """Mengembalikan jumlah pengguna dengan role tertentu.
    
    Args:
        db: Session SQLAlchemy
        role_code: Kode role (e.g., "ADMIN", "KASIR", "ANGGOTA")
    
    Returns:
        Dict dengan kunci 'count' berisi jumlah pengguna dengan role tersebut
    """
    from app.db.models import user_roles
    from sqlalchemy import select
    
    # Query users that have the specified role
    count = db.query(User).join(user_roles).filter(
        user_roles.c.role_id == Role.id,
        Role.code == role_code
    ).count() or 0
    
    return {"count": count}


def get_all_users(
    db: Session,
    active_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Mengembalikan daftar pengguna dari database.
    
    Args:
        db: Session SQLAlchemy
        active_only: Jika True, hanya ambil pengguna aktif
        limit: Batas maksimum hasil
        offset: Offset untuk paging
    
    Returns:
        Dict dengan daftar pengguna dan total count
    """
    query = db.query(User).options(
        # Eager load roles untuk menghindari N+1 queries
    )
    
    if active_only:
        query = query.filter(User.is_active.is_(True))
    
    users = query.offset(offset).limit(limit).all()
    total = query.count() or 0
    
    user_list = []
    for user in users:
        # Ambil role codes untuk user ini
        role_codes = [role.code for role in user.roles] if user.roles else []
        user_list.append({
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role_codes": role_codes,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        })
    
    return {
        "total": total,
        "users": user_list,
        "limit": limit,
        "offset": offset,
    }


def get_users_by_role_codes(
    db: Session,
    role_codes: List[str],
    active_only: bool = False,
) -> Dict[str, Any]:
    """Mengambil pengguna yang memiliki role codes tertentu.
    
    Args:
        db: Session SQLAlchemy
        role_codes: Daftar kode role (e.g., ["ADMIN", "KASIR"])
        active_only: Jika True, hanya ambil pengguna aktif
    
    Returns:
        Dict dengan pengguna yang dikelompokkan per role
    """
    from app.db.models import user_roles
    from sqlalchemy import select
    
    # Build query untuk users dengan role codes tertentu
    query = db.query(User).join(
        user_roles, User.id == user_roles.c.user_id
    ).join(
        Role, user_roles.c.role_id == Role.id
    )
    
    if active_only:
        query = query.filter(User.is_active.is_(True))
    
    if role_codes:
        query = query.filter(Role.code.in_(role_codes))
    
    users = query.all()
    
    # Kelompokkan per role
    users_by_role: Dict[str, List[Dict[str, Any]]] = {code: [] for code in role_codes}
    
    for user in users:
        role_codes = [role.code for role in user.roles] if user.roles else []
        user_data = {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        }
        
        for code in role_codes:
            if code in users_by_role:
                users_by_role[code].append(user_data)
    
    # Tambahkan pengguna tanpa role yang cocok
    all_role_codes = set()
    for user in users:
        all_role_codes.update([role.code for role in user.roles] if user.roles else [])
    
    for code in all_role_codes:
        if code not in users_by_role:
            users_by_role[code] = []
    
    return {
        "total_users": len(users),
        "users_by_role": users_by_role,
    }


def get_user_statistics(db: Session) -> Dict[str, Any]:
    """Mengambil statistik lengkap tentang pengguna dari database.
    
    Menggunakan query read-only dengan SQLAlchemy ORM.
    Tidak ada operasi WRITE.
    
    Returns:
        Dict dengan statistik pengguna:
        - total_users: Total semua akun
        - active_users: Pengguna aktif
        - inactive_users: Pengguna nonaktif
        - users_by_role: Pengelompokkan per role
    """
    # Total pengguna semua
    total_users = get_user_count(db, active_only=False)["total"]
    
    # Pengguna aktif
    active_users = get_user_count(db, active_only=True)["total"]
    
    # Pengguna nonaktif (is_active=False)
    inactive_users = get_user_count(db, active_only=True, status_filter="INACTIVE")["total"]
    # Hitung manual nonaktif = total - aktif (jika is_active adalah kolom utama)
    # Atau bisa langsung query
    from app.db.models.user import User as UserModel
    manual_inactive = db.query(UserModel).filter(UserModel.is_active.is_(False)).count() or 0
    
    # Kelompokkan per role
    role_stats = get_users_by_role_codes(db, [
        "ADMIN", "ADMIN_KOPERASI", "IT_PUSAT", "MANAGER", 
        "KASIR", "PENGAWAS_PEMBINA", "ANGGOTA", "KETUA_UMUM"
    ], active_only=False)
    
    # Hitakak count per role dari hasil
    users_by_role_summary = {}
    for role_code, users in role_stats["users_by_role"].items():
        users_by_role_summary[role_code] = {
            "total": len(users),
            "active": len([u for u in users if u["is_active"]]),
            "inactive": len([u for u in users if not u["is_active"]]),
        }
    
    # Pastikan semua role ada dalam ringkasan (meski 0)
    all_role_codes = ["ADMIN", "ADMIN_KOPERASI", "IT_PUSAT", "MANAGER", 
                      "KASIR", "PENGAWAS_PEMBINA", "ANGGOTA", "KETUA_UMUM"]
    for code in all_role_codes:
        if code not in users_by_role_summary:
            users_by_role_summary[code] = {"total": 0, "active": 0, "inactive": 0}
    
    return {
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": manual_inactive,
        "users_by_role": users_by_role_summary,
    }


def get_user_full_info(
    db: Session,
    user_id: int = None,
    username: str = None,
) -> Optional[Dict[str, Any]]:
    """Mendapatkan informasi lengkap satu pengguna dari database.
    
    HANYA untuk membaca data, tidak mengubah.
    Tidak mengembalikan data sensitif seperti password, hash, token.
    
    Args:
        db: Session SQLAlchemy
        user_id: ID pengguna (opsional, mutual exclusive dengan username)
        username: Username pengguna (opsional, mutual exclusive dengan user_id)
    
    Returns:
        Dict dengan informasi pengguna atau None jika tidak ditemukan
    """
    from app.db.models.user import User as UserModel
    
    query = db.query(UserModel)
    
    if user_id is not None:
        query = query.filter(UserModel.id == user_id)
    elif username is not None:
        query = query.filter(UserModel.username == username)
    else:
        return None
    
    user = query.first()
    if user is None:
        return None
    
    # Ambil role codes
    role_codes = [role.code for role in user.roles] if user.roles else []
    role_names = [role.name for role in user.roles] if user.roles else []
    
    # Pastikan tidak mengembalikan data sensitif
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,  # Bisa dinonaktifkan jika terlalu sensitif
        "phone_number": user.phone_number,  # Bisa dinonaktifkan jika terlalu sensitif
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "role_codes": role_codes,
        "role_names": role_names,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


# Export fungsi-fungsi utama
__all__ = [
    "get_user_count",
    "get_user_count_by_role",
    "get_all_users",
    "get_users_by_role_codes",
    "get_user_statistics",
    "get_user_full_info",
]
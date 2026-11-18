"""Service untuk retriever database user, role, dan jabatan.

Fungsi yang tersedia untuk AI Assistant:
- get_all_roles(): Daftar semua role di database
- get_users_by_role(role_code): Dapatkan users dengan role tertentu
- get_users_by_position(position): Dapatkan users berdasarkan jabatan
- get_active_users(): Dapatkan users yang aktif
- get_user_count_by_role(role_code): Hitung users per role
- get_available_positions(): Dapatkan posisi yang tersedia
- get_user_role_details(user_id): Detail role pengguna
- get_all_users_summary(): Ringkasan semua users
- get_dashboard_data(role_code, user_id): Dapatkan data dashboard berdasarkan role
- get_dashboard_stats(role_code, user_id): Dapatkan statistik dashboard berdasarkan role
- get_dashboard_summary(role_code, user_id): Dapatkan ringkasan dashboard berdasarkan role
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.core.database import SessionLocal
from app.db.models import User, Role, Employee
from app.services.dashboard_service import (
    get_admin_dashboard_data,
    get_manager_dashboard_data,
    get_ketua_dashboard_data,
    get_pengawas_dashboard_data,
    get_kasir_dashboard_data,
    get_staf_dashboard_data,
    get_it_dashboard_data,
)


def get_all_roles(db: Session = None) -> list:
    """Dapatkan semua role dari database.

    Returns:
        List of role objects with code, name, and is_system_role
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.roles import Roles
        roles = db.query(Roles).all()
        return [
            {
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "description": r.description,
                "is_system_role": r.is_system_role,
            }
            for r in roles
        ]
    except Exception as e:
        print(f"Error getting roles: {e}")
        return []
    finally:
        if db is None:
            db.close()


def get_users_by_role(role_code: str, db: Session = None) -> list:
    """Dapatkan users berdasarkan kode role.

    Args:
        role_code: Kode role (misal: 'ADMIN_KOPERASI', 'MANAGER', 'KETUA_UMUM')

    Returns:
        List of user objects with their role information
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.roles import Roles
        from app.db.models.user_roles import UserRoles

        # Cari role berdasarkan code
        role = db.query(Roles).filter(Roles.code == role_code.upper()).first()
        if not role:
            return []

        # Dapatkan users dengan role ini
        users = (
            db.query(User)
            .join(UserRoles, User.id == UserRoles.user_id)
            .filter(UserRoles.role_id == role.id, User.is_active == True)
            .all()
        )

        result = []
        for u in users:
            result.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "full_name": u.full_name,
                    "email": u.email,
                    "phone_number": u.phone_number,
                    "is_active": u.is_active,
                    "is_verified": u.is_verified,
                    "role_code": role.code,
                    "role_name": role.name,
                }
            )
        return result
    except Exception as e:
        print(f"Error getting users by role: {e}")
        return []
    finally:
        if db is None:
            db.close()


def get_users_by_position(position: str, db: Session = None) -> list:
    """Dapatkan users berdasarkan jabatan/position.

    Args:
        position: Jabatan/position (misal: 'Ketua KSP', 'Head of IT Systems', 'Kasir')

    Returns:
        List of employee/user objects matching the position
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.employees import Employees
        from app.db.models.users import User as UserModel

        employees = (
            db.query(Employee, UserModel)
            .join(Employee.user)
            .filter(
                func.lower(Employee.position).like(func.lower(f"%{position}%"))
                or func.lower(UserModel.full_name).like(func.lower(f"%{position}%"))
                or func.lower(UserModel.username).like(func.lower(f"%{position}%"))
            )
            .filter(UserModel.is_active == True)
            .all()
        )

        result = []
        for emp, user in employees:
            result.append(
                {
                    "id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "email": user.email,
                    "phone_number": user.phone_number,
                    "position": emp.position,
                    "department": emp.department,
                    "employment_status": emp.employment_status,
                    "nip": emp.nip,
                }
            )
        return result
    except Exception as e:
        print(f"Error getting users by position: {e}")
        return []
    finally:
        if db is None:
            db.close()


def get_active_users(db: Session = None) -> list:
    """Dapatkan semua users yang aktif.

    Returns:
        List of active user objects
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.users import User

        users = db.query(User).filter(User.is_active == True).all()

        result = []
        for u in users:
            result.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "full_name": u.full_name,
                    "email": u.email,
                    "phone_number": u.phone_number,
                    "is_active": u.is_active,
                    "is_verified": u.is_verified,
                }
            )
        return result
    except Exception as e:
        print(f"Error getting active users: {e}")
        return []
    finally:
        if db is None:
            db.close()


def get_user_count_by_role(role_code: str, db: Session = None) -> int:
    """Hitung jumlah users per role.

    Args:
        role_code: Kode role

    Returns:
        Jumlah users dengan role tersebut
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.roles import Roles

        role = db.query(Roles).filter(Roles.code == role_code.upper()).first()
        if not role:
            return 0

        count = (
            db.query(User)
            .join(User.roles)
            .filter(Role.id == role.id, User.is_active == True)
            .count()
        )
        return count
    except Exception as e:
        print(f"Error counting users by role: {e}")
        return 0
    finally:
        if db is None:
            db.close()


def get_available_positions(db: Session = None) -> list:
    """Dapatkan posisi unik yang tersedia di database.

    Returns:
        List of unique positions
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.employees import Employees

        positions = (
            db.query(Employee.position)
            .filter(Employee.position.isnot(None))
            .distinct()
            .all()
        )

        return [p[0] for p in positions if p[0]]
    except Exception as e:
        print(f"Error getting available positions: {e}")
        return []
    finally:
        if db is None:
            db.close()


def get_user_role_details(user_id: int, db: Session = None) -> dict:
    """Dapatkan detail role untuk pengguna tertentu.

    Args:
        user_id: ID user

    Returns:
        Dict dengan role dan permission user
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.roles import Roles
        from app.db.models.permissions import Permissions
        from app.db.models.role_permissions import RolePermissions

        # Dapatkan role user melalui relasi
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {}

        # Dapatkan permission untuk role user
        permissions = user.all_permissions

        role_codes = [role.code for role in user.roles]

        return {
            "user_id": user_id,
            "username": user.username,
            "full_name": user.full_name,
            "role_codes": role_codes,
            "role_names": [role.name for role in user.roles],
            "permission_codes": permissions,
        }
    except Exception as e:
        print(f"Error getting user role details: {e}")
        return {}
    finally:
        if db is None:
            db.close()


def get_all_users_summary(db: Session = None) -> dict:
    """Dapatkan ringkasan lengkap semua users dan role.

    Returns:
        Dict dengan statistik dan data users
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.users import User
        from app.db.models.roles import Roles

        # Semua users aktif
        active_users = db.query(User).filter(User.is_active == True).all()

        # Semua role
        all_roles = db.query(Roles).all()

        # User per role (via user_roles relasi)
        user_role_data = (
            db.query(User.full_name, User.username, Role.name.label("role_name"))
            .join(UserRoles, User.id == UserRoles.user_id)
            .join(Roles, UserRoles.role_id == Roles.id)
            .filter(User.is_active == True)
            .all()
        )

        # Statistik per role
        role_stats = {}
        for role in all_roles:
            count = (
                db.query(User)
                .join(User.roles)
                .filter(Role.id == role.id, User.is_active == True)
                .count()
            )
            role_stats[role.code] = {
                "name": role.name,
                "description": role.description,
                "user_count": count,
            }

        return {
            "total_active_users": len(active_users),
            "total_roles": len(all_roles),
            "role_statistics": role_stats,
            "users_by_role": [
                {
                    "full_name": ur.full_name or ur.username,
                    "username": ur.username,
                    "role_name": ur.role_name,
                }
                for ur in user_role_data
            ],
        }
    except Exception as e:
        print(f"Error getting all users summary: {e}")
        return {}
    finally:
        if db is None:
            db.close()


def search_users_by_name(name_query: str, db: Session = None) -> list:
    """Cari users berdasarkan nama lengkap atau username (case-insensitive).

    Args:
        name_query: Kata kunci nama atau username

    Returns:
        List of matching users
    """
    if db is None:
        db = SessionLocal()
    try:
        from app.db.models.users import User

        users = (
            db.query(User)
            .filter(
                or_(
                    User.full_name.ilike(f"%{name_query}%"),
                    User.username.ilike(f"%{name_query}%"),
                )
            )
            .filter(User.is_active == True)
            .all()
        )

        result = []
        for u in users:
            result.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "full_name": u.full_name,
                    "email": u.email,
                    "phone_number": u.phone_number,
                    "is_active": u.is_active,
                }
            )
        return result
    except Exception as e:
        print(f"Error searching users by name: {e}")
        return []
    finally:
        if db is None:
            db.close()


# ============================================================
# DASHBOARD INTEGRATION FUNCTIONS
# ============================================================

def _get_user_dashboard_info(user_id: int) -> tuple:
    """Helper to get user, active_role, and user_perms for dashboard service."""
    from app.core.database import SessionLocal
    from app.db.models import User
    from app.db.models.user import user_roles as user_roles_table

    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        db.close()
        return None, None, None

    # Get user's roles via relationship
    active_role = user.roles[0].code if user.roles else None

    # Get user's permissions through role relationship
    user_perms = set()
    for role in user.roles:
        for perm in role.permissions:
            user_perms.add(perm.code)

    db.close()
    return user, active_role, user_perms


def get_dashboard_data(role_code: str, user_id: int = None) -> dict:
    """Dapatkan data dashboard berdasarkan role.

    Args:
        role_code: Kode role (misal: 'ADMIN_KOPERASI', 'MANAGER', 'KETUA_UMUM')
        user_id: ID user (opsional, akan diasosiasikan dari user_id yang diberikan)

    Returns:
        Dict dengan data dashboard untuk role tersebut
    """
    from app.core.database import SessionLocal

    # Get user info for permission checks
    user, active_role, user_perms = _get_user_dashboard_info(user_id) if user_id else (None, None, None)

    if not role_code:
        return {}

    role_upper = role_code.upper()
    db = SessionLocal()

    try:
        # Dispatch to appropriate dashboard function based on role
        if role_upper in ("KETUA_UMUM", "KETUA"):
            return get_ketua_dashboard_data(db=db)
        elif role_upper == "MANAGER":
            return get_manager_dashboard_data(db=db)
        elif role_upper == "HRD":
            return get_hrd_dashboard_data(db=db, user_perms=user_perms or set())
        elif role_upper in ("PENGAWAS_PEMBINA", "PENGAWAS"):
            return get_pengawas_dashboard_data(db=db)
        elif role_upper == "ADMIN_KOPERASI":
            return get_admin_dashboard_data(db=db)
        elif role_upper == "ADMIN":
            return get_admin_dashboard_data(db=db)
        elif role_upper == "IT_PUSAT":
            base = get_admin_dashboard_data(db=db)
            it = get_it_dashboard_data(db=db)
            return {**base, "it": it, "role": "IT_PUSAT"}
        elif role_upper == "KASIR":
            return get_kasir_dashboard_data(db=db, user_id=user_id if user_id else 1)
        elif role_upper == "STAF":
            return get_staf_dashboard_data(db=db, user_perms=user_perms or set())
        else:
            # Default: coba ambil data admin jika role tidak dikenal
            return get_admin_dashboard_data(db=db)
    except Exception as e:
        print(f"Error getting dashboard data: {e}")
        import traceback
        traceback.print_exc()
        return {}
    finally:
        db.close()


def get_dashboard_stats(role_code: str, user_id: int = None) -> dict:
    """Dapatkan statistik dashboard berdasarkan role.

    Args:
        role_code: Kode role
        user_id: ID user (opsional)

    Returns:
        Dict dengan statistik dashboard
    """
    user, active_role, user_perms = _get_user_dashboard_info(user_id) if user_id else (None, None, None)

    role_upper = role_code.upper()

    # Extract stats from dashboard data
    data = get_dashboard_data(role_code, user_id)

    # Extract common stat fields
    stats = {}
    for key in ["total_anggota", "total_simpanan", "total_pinjaman", "total_angsuran",
                "total_transaksi", "terakhir_update"]:
        if key in data:
            stats[key] = data[key]
    return stats


def get_dashboard_summary(role_code: str, user_id: int = None) -> dict:
    """Dapatkan ringkasan dashboard berdasarkan role.

    Args:
        role_code: Kode role
        user_id: ID user (opsional)

    Returns:
        Dict dengan ringkasan dashboard
    """
    user, active_role, user_perms = _get_user_dashboard_info(user_id) if user_id else (None, None, None)

    role_upper = role_code.upper()

    # Combine data and stats
    data = get_dashboard_data(role_code, user_id)
    stats = get_dashboard_stats(role_code, user_id)
    combined = {**data, **stats}
    return combined
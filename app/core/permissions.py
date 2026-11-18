from enum import Enum
from typing import List, Optional, Union, Set
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_access_token


class SystemRole(str, Enum):
    ADMIN_KOPERASI = "ADMIN_KOPERASI"
    KETUA_UMUM = "KETUA_UMUM"
    MANAGER = "MANAGER"
    HRD = "HRD"
    PENGAWAS_PEMBINA = "PENGAWAS_PEMBINA"
    STAF = "STAF"
    IT_PUSAT = "IT_PUSAT"
    KASIR = "KASIR"
    ANGGOTA = "ANGGOTA"
    
    # Backward compatibility aliases
    ADMIN = "ADMIN_KOPERASI"
    PENGAWAS = "PENGAWAS_PEMBINA"


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_token_from_request(request: Request, header_token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    """Extract token from Authorization header or HTTP-only cookie."""
    if header_token:
        return header_token
    # Fallback to cookie
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        if cookie_token.startswith("Bearer "):
            return cookie_token.split(" ")[1]
        return cookie_token
    return None


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(get_token_from_request),
    db: Session = Depends(get_db)
):
    """Retrieve currently authenticated user and active role context."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi diperlukan. Silakan login terlebih dahulu.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi telah kedaluwarsa atau token tidak valid.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kredensial token tidak valid."
        )
        
    from app.db.models.user import User
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pengguna tidak ditemukan."
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akun pengguna dinonaktifkan. Hubungi IT Pusat / Administrator."
        )
        
    # Active role context (can be switched if user has multiple roles)
    active_role = payload.get("active_role")
    if not active_role and user.roles:
        active_role = user.roles[0].code
    setattr(user, "active_role", active_role)
    
    return user


def get_user_permissions(user, active_role: Optional[str] = None) -> Set[str]:
    """Calculate effective permissions for user based on active_role or all assigned roles."""
    perms = set()
    if not user or not hasattr(user, "roles"):
        return perms

    for role in user.roles:
        # If an active role is set, only include permissions of that active role
        # Unless user is superadmin ADMIN_KOPERASI
        if active_role and role.code != active_role and role.code not in ["ADMIN_KOPERASI", "ADMIN"]:
            continue
        for p in role.permissions:
            perms.add(p.code)
            
    return perms


class RoleChecker:
    """Dependency validator for checking if user has any of the allowed roles."""
    def __init__(self, allowed_roles: List[Union[SystemRole, str]]):
        self.allowed_roles = [r.value if isinstance(r, SystemRole) else str(r) for r in allowed_roles]

    def __call__(self, user=Depends(get_current_user)) -> bool:
        user_role_codes = [r.code for r in user.roles]
        
        # Superadmin bypass
        if "ADMIN_KOPERASI" in user_role_codes or "ADMIN" in user_role_codes:
            return True

        # Check active context role or any assigned role
        active_role = getattr(user, "active_role", None)
        if active_role and (active_role in self.allowed_roles):
            return True
            
        has_role = any(code in self.allowed_roles for code in user_role_codes)
        if not has_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses ditolak. Diperlukan peran: {', '.join(self.allowed_roles)}"
            )
        return True


class PermissionChecker:
    """Dependency validator for checking granular permission codes."""
    def __init__(self, required_permissions: List[str], require_all: bool = False):
        self.required_permissions = required_permissions
        self.require_all = require_all

    def __call__(self, user=Depends(get_current_user)) -> bool:
        user_role_codes = [r.code for r in user.roles]
        # Superadmin bypass
        if "ADMIN_KOPERASI" in user_role_codes or "ADMIN" in user_role_codes:
            return True

        active_role = getattr(user, "active_role", None)
        effective_permissions = get_user_permissions(user, active_role)

        if self.require_all:
            has_perm = all(p in effective_permissions for p in self.required_permissions)
        else:
            has_perm = any(p in effective_permissions for p in self.required_permissions)

        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses ditolak. Diperlukan izin: {', '.join(self.required_permissions)}"
            )
        return True


def require_permission(permission_code: str):
    """Clean dependency factory for checking a single granular permission."""
    return PermissionChecker([permission_code])


def require_role(role: Union[SystemRole, str]):
    """Clean dependency factory for checking a single system role."""
    return RoleChecker([role])

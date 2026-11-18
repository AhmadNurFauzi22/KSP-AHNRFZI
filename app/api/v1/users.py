from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.permissions import (
    RoleChecker, PermissionChecker, SystemRole, 
    get_current_user, require_permission, require_role, get_user_permissions
)
from app.db.models.user import User, Role
from app.db.models.member import Member
from app.schemas.user import UserOut, RoleOut

router = APIRouter(tags=["User & Member RBAC"])


# =========================================================================
# USER MANAGEMENT (Admin, IT Pusat, Manager)
# =========================================================================
@router.get("/users", response_model=List[UserOut])
def get_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    authorized: bool = Depends(RoleChecker([SystemRole.ADMIN_KOPERASI, SystemRole.IT_PUSAT, SystemRole.MANAGER]))
):
    """Retrieve list of system users (Admin, IT Pusat, Manager only)."""
    users = db.query(User).offset(skip).limit(limit).all()
    return users


@router.get("/roles", response_model=List[RoleOut])
def get_all_roles(
    db: Session = Depends(get_db),
    authorized: bool = Depends(RoleChecker([SystemRole.ADMIN_KOPERASI, SystemRole.IT_PUSAT]))
):
    """Retrieve all available system roles."""
    roles = db.query(Role).all()
    return roles


# =========================================================================
# MEMBER PROFILE & IDOR PROTECTION ENDPOINTS
# =========================================================================
@router.get("/members/me")
def get_my_member_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    authorized: bool = Depends(require_permission("member.view"))
):
    """Get current logged in user's own cooperative member profile."""
    if not current_user.member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profil keanggotaan koperasi tidak ditemukan untuk akun ini."
        )
    m = current_user.member
    return {
        "id": m.id,
        "member_no": m.member_no,
        "nik": m.nik,
        "full_name": m.full_name,
        "phone_number": m.phone_number,
        "email": m.email,
        "address": m.address,
        "status": m.status,
        "join_date": str(m.join_date)
    }


@router.get("/members/{member_id}")
def get_member_by_id(
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    authorized: bool = Depends(require_permission("member.view"))
):
    """
    Retrieve member details by ID with strict IDOR (Insecure Direct Object Reference) Protection.
    - Staff / Manager / Admin / HRD with 'member.view_all' can view any member.
    - Regular Anggota can ONLY view their own member record.
    """
    active_role = getattr(current_user, "active_role", None)
    effective_perms = get_user_permissions(current_user, active_role)

    # Check elevated permission or role
    is_elevated = (
        "member.view_all" in effective_perms 
        or "ADMIN_KOPERASI" in current_user.role_codes
        or "MANAGER" in current_user.role_codes
        or "STAF" in current_user.role_codes
        or "HRD" in current_user.role_codes
        or "PENGAWAS_PEMBINA" in current_user.role_codes
    )

    # If not elevated, enforce IDOR protection
    if not is_elevated:
        if not current_user.member or current_user.member.id != member_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak: Anda tidak memiliki izin untuk melihat profil anggota lain (IDOR Protection)."
            )

    target_member = db.query(Member).filter(Member.id == member_id).first()
    if not target_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data anggota dengan ID {member_id} tidak ditemukan."
        )

    return {
        "id": target_member.id,
        "member_no": target_member.member_no,
        "nik": target_member.nik,
        "full_name": target_member.full_name,
        "phone_number": target_member.phone_number,
        "email": target_member.email,
        "address": target_member.address,
        "status": target_member.status,
        "join_date": str(target_member.join_date)
    }


# =========================================================================
# RBAC VERIFICATION CHECKPOINTS (FOR TESTING & GUARD VERIFICATION)
# =========================================================================
@router.get("/rbac-check/admin-only")
def check_admin_access(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_role(SystemRole.ADMIN_KOPERASI))
):
    """Endpoint accessible only by ADMIN_KOPERASI."""
    return {"status": "SUCCESS", "message": f"Akses diizinkan untuk Admin Koperasi ({current_user.username})"}


@router.get("/rbac-check/cashier-desk")
def check_cashier_access(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("cashier.transaction"))
):
    """Endpoint accessible only by users with 'cashier.transaction' permission."""
    return {"status": "SUCCESS", "message": f"Akses diizinkan untuk Kasir Loket ({current_user.username})"}


@router.get("/rbac-check/loan-approval")
def check_loan_approval_access(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("loan.approve"))
):
    """Endpoint accessible only by users with 'loan.approve' permission (Ketua, Manager)."""
    return {"status": "SUCCESS", "message": f"Akses persetujuan kredit diizinkan ({current_user.username})"}


@router.get("/rbac-it-pusat", include_in_schema=False)
def rbac_it_pusat_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("rbac_it_pusat.html", {"request": request})


@router.get("/ai-config", include_in_schema=False)
def ai_config_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("ai_config.html", {"request": request})

@router.get("/rbac-koperasi", include_in_schema=False)
def rbac_koperasi_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("rbac_koperasi.html", {"request": request})

@router.get("/rbac-it-pusat", include_in_schema=False)
def rbac_it_pusat_page(request: Request):
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    from jinja2 import TemplateResponse
    return TemplateResponse("rbac_it_pusat.html", {"request": request})

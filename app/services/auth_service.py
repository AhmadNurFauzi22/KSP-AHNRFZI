from datetime import timedelta, datetime, timezone
from threading import Lock
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings
from app.core.permissions import get_user_permissions
from app.db.models.user import User
from app.services.audit_service import AuditService


# Prompt #11: throttle login in-memory per (username, ip).
# Batasan: efektif per proses; untuk multi-worker gunakan store eksternal.
_login_attempts: Dict[Tuple[str, str], Tuple[int, datetime]] = {}
_login_lock = Lock()


def _login_throttle_check(username: str, ip: str) -> None:
    key = ((username or "").lower(), ip or "unknown")
    now = datetime.now(timezone.utc)
    with _login_lock:
        fails, first = _login_attempts.get(key, (0, now))
        if fails >= settings.LOGIN_MAX_ATTEMPTS:
            elapsed = (now - first).total_seconds()
            if elapsed < settings.LOGIN_LOCKOUT_SECONDS:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Terlalu banyak percobaan login. Coba lagi beberapa menit."
                )
            _login_attempts.pop(key, None)


def _login_throttle_record(username: str, ip: str, success: bool) -> None:
    key = ((username or "").lower(), ip or "unknown")
    now = datetime.now(timezone.utc)
    with _login_lock:
        if success:
            _login_attempts.pop(key, None)
        else:
            fails, first = _login_attempts.get(key, (0, now))
            _login_attempts[key] = (fails + 1, first)


def _validate_password_strength(new_password: str) -> None:
    """Prompt #11: kompleksitas minimal tanpa merusak password existing yang kuat."""
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kata sandi baru minimal harus 8 karakter."
        )
    has_letter = any(c.isalpha() for c in new_password)
    has_digit = any(c.isdigit() for c in new_password)
    if not (has_letter and has_digit):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kata sandi harus mengandung huruf dan angka."
        )


class AuthService:
    @staticmethod
    def authenticate_user(
        db: Session,
        username: str,
        password: str,
        preferred_role: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> dict:
        """Authenticate user credentials, assign active role context, and issue JWT."""
        _login_throttle_check(username, ip_address or "unknown")
        user = db.query(User).filter(
            (User.username == username) | (User.email == username)
        ).first()

        if not user or not verify_password(password, user.hashed_password):
            _login_throttle_record(username, ip_address or "unknown", False)
            AuditService.log_event(
                db=db,
                action="LOGIN_FAILED",
                entity_name="Auth",
                entity_id=username,
                ip_address=ip_address,
                user_agent=user_agent,
                notes=f"Percobaan login gagal untuk akun: {username}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Username atau password tidak sesuai."
            )
            
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akun Anda dinonaktifkan. Hubungi Administrator KSP."
            )
            
        user_role_codes = [r.code for r in user.roles]
        if not user_role_codes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akun belum memiliki peran (role) yang valid."
            )
            
        # Determine active role
        if preferred_role and preferred_role in user_role_codes:
            active_role = preferred_role
        else:
            # If user has multiple roles, prioritize non-ANGGOTA role as primary working desk
            non_anggota = [r for r in user_role_codes if r != "ANGGOTA"]
            if non_anggota:
                active_role = non_anggota[0]
            else:
                active_role = user_role_codes[0] # Default to primary role
            
        effective_permissions = list(get_user_permissions(user, active_role))
            
        # Generate token payload
        token_payload = {
            "sub": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "roles": user_role_codes,
            "active_role": active_role
        }
        
        access_token = create_access_token(
            data=token_payload,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        # Update last login info
        user.last_login_ip = ip_address
        db.commit()
        _login_throttle_record(username, ip_address or "unknown", True)
        
        AuditService.log_event(
            db=db,
            action="LOGIN_SUCCESS",
            entity_name="Auth",
            entity_id=str(user.id),
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            notes=f"User {user.username} login sukses dengan active_role={active_role}"
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "active_role": active_role,
            "roles": user_role_codes,
            "permissions": effective_permissions
        }

    @staticmethod
    def switch_active_role(
        db: Session,
        user: User,
        target_role: str,
        ip_address: Optional[str] = None
    ) -> str:
        """Switch active role context for multi-role users (e.g. Manager -> Anggota)."""
        user_role_codes = [r.code for r in user.roles]
        if target_role not in user_role_codes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Anda tidak memiliki hak akses untuk role: {target_role}"
            )
            
        token_payload = {
            "sub": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "roles": user_role_codes,
            "active_role": target_role
        }
        
        new_token = create_access_token(
            data=token_payload,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        AuditService.log_event(
            db=db,
            action="ROLE_SWITCH",
            entity_name="User",
            entity_id=str(user.id),
            user_id=user.id,
            ip_address=ip_address,
            notes=f"Pengguna beralih peran ke: {target_role}"
        )
        
        return new_token

    @staticmethod
    def change_password(
        db: Session,
        user: User,
        current_password: str,
        new_password: str,
        confirm_password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Change user password after verifying current password and strength."""
        if not verify_password(current_password, user.hashed_password):
            AuditService.log_event(
                db=db,
                action="PASSWORD_CHANGE_FAILED",
                entity_name="User",
                entity_id=str(user.id),
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                notes="Percobaan ubah kata sandi gagal: Kata sandi saat ini salah."
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Kata sandi saat ini tidak cocok."
            )
            
        if new_password != confirm_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Konfirmasi kata sandi baru tidak sesuai."
            )
            
        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Kata sandi baru minimal harus 8 karakter."
            )

        _validate_password_strength(new_password)

        if current_password == new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Kata sandi baru tidak boleh sama dengan kata sandi lama."
            )

        user.hashed_password = get_password_hash(new_password)
        db.commit()

        AuditService.log_event(
            db=db,
            action="PASSWORD_CHANGED",
            entity_name="User",
            entity_id=str(user.id),
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            notes="Kata sandi pengguna berhasil diperbarui."
        )
        return True

    @staticmethod
    def admin_reset_password(
        db: Session,
        admin_user: User,
        target_user_id: int,
        new_password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Reset password for any user by administrator / IT Pusat."""
        target_user = db.query(User).filter(User.id == target_user_id).first()
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pengguna sasaran tidak ditemukan."
            )

        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Kata sandi baru minimal harus 8 karakter."
            )

        _validate_password_strength(new_password)

        target_user.hashed_password = get_password_hash(new_password)
        db.commit()

        AuditService.log_event(
            db=db,
            action="PASSWORD_RESET_BY_ADMIN",
            entity_name="User",
            entity_id=str(target_user.id),
            user_id=admin_user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            notes=f"Admin {admin_user.username} mereset kata sandi akun {target_user.username} (ID: {target_user.id})"
        )
        return True

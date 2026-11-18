"""Router Integrasi Telegram Bot KSP AHNRFZI.

Endpoint:
- GET  /api/v1/integrations/telegram/status           (auth) - Status koneksi & konfigurasi bot
- POST /api/v1/integrations/telegram/link-token       (auth) - Generate linking token & deep link
- POST /api/v1/integrations/telegram/unlink           (auth) - Putuskan koneksi Telegram pengguna
- GET  /api/v1/integrations/telegram/preferences      (auth) - Ambil preferensi notifikasi
- PUT  /api/v1/integrations/telegram/preferences      (auth) - Simpan preferensi notifikasi
- POST /api/v1/integrations/telegram/test-notification (auth) - Kirim notifikasi uji coba ke akun sendiri
- POST /api/v1/integrations/telegram/webhook          (public/secret) - Webhook Telegram API
"""
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.core.permissions import get_current_user
from app.db.models.user import User
from app.services.telegram_service import TelegramService

router = APIRouter(prefix="/integrations/telegram", tags=["Telegram Integration"])


class PreferenceUpdateSchema(BaseModel):
    telegram_enabled: Optional[bool] = None
    notify_loans: Optional[bool] = None
    notify_installments: Optional[bool] = None
    notify_cashier: Optional[bool] = None
    notify_hrd: Optional[bool] = None
    notify_system: Optional[bool] = None


@router.get("/status")
def get_telegram_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mendapatkan status koneksi Telegram milik akun yang sedang login."""
    status_data = TelegramService.get_link_status(db, current_user.id)
    return {
        "success": True,
        "data": status_data,
    }


@router.post("/link-token")
def generate_linking_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Menghasilkan linking token acak ber-entropi tinggi (32-bytes urlsafe) dan deep-link.

    Token berlaku 10 menit dan hanya dapat digunakan 1 kali.
    """
    if not settings.telegram_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Integrasi Telegram Bot belum dikonfigurasi oleh administrator sistem.",
        )

    token, expires_at, err = TelegramService.create_linking_token(db, current_user.id)
    if err:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=err)

    deep_link = TelegramService.build_deep_link(token)
    return {
        "success": True,
        "data": {
            "token": token,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "deep_link": deep_link,
            "bot_username": settings.TELEGRAM_BOT_USERNAME,
        },
    }


@router.post("/unlink")
def unlink_telegram(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Memutuskan koneksi Telegram akun pengguna yang sedang login."""
    ok, message = TelegramService.unlink_user(db, current_user.id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return {
        "success": True,
        "message": message,
    }


@router.get("/preferences")
def get_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mengambil preferensi saluran dan kategori notifikasi pengguna."""
    pref = TelegramService.get_preferences(db, current_user.id)
    return {
        "success": True,
        "data": {
            "in_app_enabled": pref.in_app_enabled,
            "telegram_enabled": pref.telegram_enabled,
            "notify_loans": pref.notify_loans,
            "notify_installments": pref.notify_installments,
            "notify_cashier": pref.notify_cashier,
            "notify_hrd": pref.notify_hrd,
            "notify_system": pref.notify_system,
        },
    }


@router.put("/preferences")
def update_preferences(
    payload: PreferenceUpdateSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Memperbarui preferensi notifikasi pengguna yang sedang login."""
    pref = TelegramService.update_preferences(db, current_user.id, payload.model_dump(exclude_unset=True))
    return {
        "success": True,
        "message": "Preferensi notifikasi berhasil diperbarui.",
        "data": {
            "in_app_enabled": pref.in_app_enabled,
            "telegram_enabled": pref.telegram_enabled,
            "notify_loans": pref.notify_loans,
            "notify_installments": pref.notify_installments,
            "notify_cashier": pref.notify_cashier,
            "notify_hrd": pref.notify_hrd,
            "notify_system": pref.notify_system,
        },
    }


@router.post("/test-notification")
def send_test_notification(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mengirim pesan notifikasi uji coba HANYA ke Telegram yang terhubung dengan akun login."""
    if not settings.telegram_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Integrasi Telegram Bot belum dikonfigurasi.",
        )

    from app.db.models.telegram import TelegramUserLink
    user_link = db.query(TelegramUserLink).filter(
        TelegramUserLink.user_id == current_user.id,
        TelegramUserLink.is_active.is_(True),
    ).first()

    if not user_link or not user_link.chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Akun Anda belum terhubung dengan Telegram. Silakan hubungkan Telegram terlebih dahulu.",
        )

    pref = TelegramService.get_preferences(db, current_user.id)
    if not pref.telegram_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notifikasi Telegram sedang dimatikan di pengaturan akun Anda.",
        )

    test_message = (
        "Halo! Integrasi Telegram Anda berhasil.\n"
        "Notifikasi koperasi akan dikirim ke akun Telegram ini sesuai pengaturan Anda."
    )
    formatted = TelegramService.format_notification_message(
        title="Tes Notifikasi KSP AHNRFZI",
        message=test_message,
        ntype="SUCCESS",
        category="SYSTEM",
    )

    success, err_msg = TelegramService.send_telegram_api(
        chat_id=user_link.chat_id,
        text=formatted,
        user_id=current_user.id,
        category="SYSTEM",
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gagal mengirim pesan ke Telegram: {err_msg}",
        )

    return {
        "success": True,
        "message": "Pesan uji coba berhasil dikirim ke akun Telegram Anda.",
    }


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """Webhook Telegram API untuk menerima updates secara HTTPS aman.

    - Validasi header X-Telegram-Bot-Api-Secret-Token secara constant-time.
    - Idempotensi update_id.
    - Penanganan /start <linking_token>.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    secret_hdr = (
        x_telegram_bot_api_secret_token
        or request.headers.get("x-telegram-bot-api-secret-token")
        or request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    )

    ok, message, status_code = TelegramService.process_webhook_update(
        db=db,
        update=payload,
        secret_token_header=secret_hdr,
    )

    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=message)

    return {
        "ok": ok,
        "description": message,
    }

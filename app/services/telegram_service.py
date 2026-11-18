"""Layanan Integrasi Telegram Bot KSP AHNRFZI (Prompt #14).

Menangani:
1. Pembuatan & validasi linking token berkadaluwarsa (10 menit, single-use, hash SHA-256).
2. Hubungkan & putuskan akun Telegram (private chat only, anti-hijack).
3. Pemrosesan webhook Telegram dengan validasi secret header constant-time & idempotensi update_id.
4. Pengiriman pesan HTTPS asinkron (ThreadPoolExecutor), timeout, retry terbatas (backoff),
   penanganan HTTP 429 retry_after, pencatatan delivery log tanpa membocorkan rahasia.
5. Manajemen preferensi notifikasi per pengguna.
"""
import hmac
import json
import secrets
import hashlib
import html
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.config import settings
from app.core.logging import logger
from app.core.database import SessionLocal
from app.db.models.telegram import (
    TelegramUserLink,
    TelegramLinkingToken,
    NotificationPreference,
    TelegramWebhookUpdate,
    TelegramDeliveryLog,
)
from app.db.models.user import User

# Thread pool untuk pengiriman pesan Telegram di background tanpa memblokir thread HTTP
_telegram_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tg_worker")

TOKEN_EXPIRY_MINUTES = 10
MAX_TOKENS_PER_WINDOW = 5
RATE_LIMIT_WINDOW_MINUTES = 10
MAX_RETRY_ATTEMPTS = 3


class TelegramService:
    # ------------------------------------------------------------------
    # 1. LINKING TOKEN & DEEP-LINK
    # ------------------------------------------------------------------
    @staticmethod
    def create_linking_token(db: Session, user_id: int) -> Tuple[Optional[str], Optional[datetime], Optional[str]]:
        """Menghasilkan linking token acak ber-entropi tinggi (32 bytes urlsafe).

        Disimpan dalam bentuk SHA-256 hash. Berlaku 10 menit dan hanya dapat digunakan 1 kali.
        Mengembalikan (token, expires_at, error_message).
        """
        now = datetime.now(timezone.utc)
        since_window = now - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)

        # Rate limiting: cegah pembuatan token berlebihan
        recent_count = db.query(TelegramLinkingToken).filter(
            TelegramLinkingToken.user_id == user_id,
            TelegramLinkingToken.created_at >= since_window,
        ).count()

        if recent_count >= MAX_TOKENS_PER_WINDOW:
            return None, None, f"Batas pembuatan token tercapai. Maksimal {MAX_TOKENS_PER_WINDOW} per {RATE_LIMIT_WINDOW_MINUTES} menit."

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = now + timedelta(minutes=TOKEN_EXPIRY_MINUTES)

        token_record = TelegramLinkingToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=now,
        )
        db.add(token_record)
        db.commit()

        return raw_token, expires_at, None

    @staticmethod
    def verify_and_consume_token(db: Session, raw_token: str) -> Tuple[Optional[int], str]:
        """Memvalidasi dan mengonsumsi linking token.

        Mengembalikan (user_id, status_message).
        """
        if not raw_token or not raw_token.strip():
            return None, "Token kosong atau tidak valid."

        token_clean = raw_token.strip()
        token_hash = hashlib.sha256(token_clean.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)

        record = db.query(TelegramLinkingToken).filter(
            TelegramLinkingToken.token_hash == token_hash
        ).first()

        if not record:
            return None, "Token penghubung tidak ditemukan."

        if record.used_at is not None:
            return None, "Token ini sudah pernah digunakan sebelumnya."

        # Cek kedaluwarsa
        exp = record.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        if exp < now:
            return None, "Token penghubung sudah kedaluwarsa. Silakan buat tautan baru di aplikasi."

        # Tandai token telah digunakan (single-use)
        record.used_at = now
        db.commit()

        return record.user_id, "Token valid."

    @staticmethod
    def build_deep_link(raw_token: str) -> str:
        """Membuat URL deep-link Telegram."""
        bot_username = (settings.TELEGRAM_BOT_USERNAME or "").strip().lstrip("@")
        if not bot_username:
            return ""
        return f"https://t.me/{bot_username}?start={raw_token}"

    # ------------------------------------------------------------------
    # 2. HUBUNGKAN & PUTUSKAN KONEKSI TELEGRAM
    # ------------------------------------------------------------------
    @staticmethod
    def link_user(db: Session, user_id: int, chat_id: str,
                  username: Optional[str] = None, first_name: Optional[str] = None) -> Tuple[bool, str]:
        """Menghubungkan akun pengguna dengan chat Telegram (private chat only).

        Mencegah satu chat_id membajak atau mengklaim akun milik pengguna lain.
        """
        user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        if not user:
            return False, "Pengguna KSP AHNRFZI tidak ditemukan atau sudah tidak aktif."

        clean_chat_id = str(chat_id).strip()

        # Cek apakah chat_id ini sudah terhubung ke akun LAIN yang aktif
        existing_chat_link = db.query(TelegramUserLink).filter(
            TelegramUserLink.chat_id == clean_chat_id
        ).first()

        if existing_chat_link and existing_chat_link.user_id != user_id:
            if existing_chat_link.is_active:
                # Cegah pengambilalihan akun aktif (anti-hijack)
                return False, "Akun Telegram ini telah terhubung dengan akun koperasi lain. Putuskan koneksi terlebih dahulu dari akun tersebut."
            else:
                # Link lama sudah non-aktif, bersihkan agar unique constraint chat_id tidak bentrok
                db.delete(existing_chat_link)
                db.flush()

        now = datetime.now(timezone.utc)
        user_link = db.query(TelegramUserLink).filter(
            TelegramUserLink.user_id == user_id
        ).first()

        if user_link:
            user_link.chat_id = clean_chat_id
            user_link.telegram_username = username
            user_link.first_name = first_name
            user_link.is_active = True
            user_link.updated_at = now
        else:
            user_link = TelegramUserLink(
                user_id=user_id,
                chat_id=clean_chat_id,
                telegram_username=username,
                first_name=first_name,
                is_active=True,
                connected_at=now,
                updated_at=now,
            )
            db.add(user_link)

        # Pastikan preference pengguna tersedia
        TelegramService.get_preferences(db, user_id)

        db.commit()
        logger.info(f"[TELEGRAM] User #{user_id} ({user.username}) berhasil terhubung dengan Telegram chat #{clean_chat_id}")
        return True, "Akun Telegram berhasil terhubung dengan akun KSP AHNRFZI Anda."

    @staticmethod
    def unlink_user(db: Session, user_id: int) -> Tuple[bool, str]:
        """Memutuskan koneksi Telegram akun pengguna yang sedang login."""
        user_link = db.query(TelegramUserLink).filter(
            TelegramUserLink.user_id == user_id
        ).first()

        if not user_link:
            return False, "Akun Telegram belum terhubung."

        db.delete(user_link)
        db.commit()
        logger.info(f"[TELEGRAM] User #{user_id} memutuskan koneksi Telegram.")
        return True, "Koneksi Telegram berhasil diputuskan."

    @staticmethod
    def get_link_status(db: Session, user_id: int) -> Dict[str, Any]:
        """Mendapatkan status koneksi Telegram pengguna."""
        user_link = db.query(TelegramUserLink).filter(
            TelegramUserLink.user_id == user_id,
            TelegramUserLink.is_active.is_(True),
        ).first()

        masked_chat_id = None
        if user_link and user_link.chat_id:
            cid = str(user_link.chat_id)
            if len(cid) > 4:
                masked_chat_id = cid[:2] + ("*" * (len(cid) - 4)) + cid[-2:]
            else:
                masked_chat_id = "***"

        connected_at_str = None
        if user_link and user_link.connected_at:
            if hasattr(user_link.connected_at, "isoformat"):
                connected_at_str = user_link.connected_at.isoformat()
            else:
                connected_at_str = str(user_link.connected_at)

        return {
            "is_connected": bool(user_link and user_link.is_active),
            "connected_at": connected_at_str,
            "telegram_username": user_link.telegram_username if user_link else None,
            "first_name": user_link.first_name if user_link else None,
            "masked_chat_id": masked_chat_id,
            "bot_username": settings.TELEGRAM_BOT_USERNAME,
            "is_bot_configured": settings.telegram_configured,
        }

    # ------------------------------------------------------------------
    # 3. PREFERENSI NOTIFIKASI
    # ------------------------------------------------------------------
    @staticmethod
    def get_preferences(db: Session, user_id: int) -> NotificationPreference:
        """Mengambil atau menginisialisasi default preferensi notifikasi pengguna."""
        pref = db.query(NotificationPreference).filter(
            NotificationPreference.user_id == user_id
        ).first()

        if not pref:
            pref = NotificationPreference(
                user_id=user_id,
                in_app_enabled=True,
                telegram_enabled=True,
                notify_loans=True,
                notify_installments=True,
                notify_cashier=True,
                notify_hrd=True,
                notify_system=True,
            )
            db.add(pref)
            db.commit()
            db.refresh(pref)

        return pref

    @staticmethod
    def update_preferences(db: Session, user_id: int, updates: Dict[str, Any]) -> NotificationPreference:
        """Memperbarui preferensi notifikasi milik pengguna yang sedang login."""
        pref = TelegramService.get_preferences(db, user_id)

        allowed_fields = [
            "telegram_enabled",
            "notify_loans",
            "notify_installments",
            "notify_cashier",
            "notify_hrd",
            "notify_system",
        ]

        for field in allowed_fields:
            if field in updates and isinstance(updates[field], bool):
                setattr(pref, field, updates[field])

        # In-app notification selalu ON sebagai saluran utama
        pref.in_app_enabled = True
        pref.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(pref)
        return pref

    @staticmethod
    def is_category_allowed(pref: NotificationPreference, category: Optional[str]) -> bool:
        """Mengecek apakah preferensi mengizinkan kategori tertentu."""
        if not pref.telegram_enabled:
            return False

        if not category:
            return True

        cat = category.upper()
        if cat in ("LOAN", "LOANS"):
            return pref.notify_loans
        elif cat in ("INSTALLMENT", "INSTALLMENTS", "PAYMENT"):
            return pref.notify_installments
        elif cat in ("CASHIER", "CASH", "REGISTER"):
            return pref.notify_cashier
        elif cat in ("HRD", "EMPLOYEE"):
            return pref.notify_hrd
        elif cat in ("SYSTEM", "INFO", "TEST"):
            return pref.notify_system

        return True

    # ------------------------------------------------------------------
    # 4. TEMPLATE & SANITISASI PESAN
    # ------------------------------------------------------------------
    @staticmethod
    def escape_html(text: str) -> str:
        """Escape teks dinamis agar format HTML Telegram aman."""
        if not text:
            return ""
        return html.escape(str(text))

    @staticmethod
    def format_notification_message(title: str, message: str,
                                   ntype: str = "INFO", category: Optional[str] = None,
                                   link_url: Optional[str] = None) -> str:
        """Membuat pesan Telegram terformat rapi sesuai Simple PRD KSP AHNRFZI."""
        icon_map = {
            "APPROVAL": "📌",
            "SUCCESS": "✅",
            "WARNING": "⚠️",
            "DANGER": "🚨",
            "INFO": "🔔",
        }
        icon = icon_map.get(ntype.upper(), "🔔")
        now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

        safe_title = TelegramService.escape_html(title)
        safe_message = TelegramService.escape_html(message)

        lines = [
            "🏦 <b>KSP AHNRFZI</b>",
            "",
            f"{icon} <b>{safe_title}</b>",
            f"📅 Tanggal: {now_str}",
            "",
            safe_message,
            "",
            "Silakan login ke aplikasi resmi KSP AHNRFZI untuk melihat detail.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 5. PENGIRIMAN HTTP TELEGRAM API & ASYNC DISPATCH
    # ------------------------------------------------------------------
    @staticmethod
    def send_telegram_api(chat_id: str, text: str,
                          user_id: Optional[int] = None,
                          notification_id: Optional[int] = None,
                          category: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Mengirim pesan HTTPS langsung ke Telegram Bot API sendMessage.

        Terapkan timeout, validasi respons HTTP, retry backoff, dan logging aman.
        """
        token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
        if not token:
            return False, "TELEGRAM_BOT_TOKEN belum dikonfigurasi."

        base_url = (getattr(settings, "TELEGRAM_API_BASE_URL", None) or "https://api.telegram.org").rstrip("/")
        api_url = f"{base_url}/bot{token}/sendMessage"

        payload = {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "KSP-AHNRFZI-TelegramBot/1.0",
        }

        attempts = 0
        success = False
        error_msg = None
        now = datetime.now(timezone.utc)

        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            attempts = attempt
            try:
                req = urllib.request.Request(api_url, data=data_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=8) as response:
                    res_body = response.read().decode("utf-8")
                    res_json = json.loads(res_body)
                    if res_json.get("ok"):
                        success = True
                        error_msg = None
                        break
                    else:
                        error_msg = res_json.get("description", "Respons Telegram ok=false")
            except urllib.error.HTTPError as e:
                status_code = e.code
                error_body = ""
                retry_after = None
                try:
                    error_body = e.read().decode("utf-8")
                    err_json = json.loads(error_body)
                    error_msg = err_json.get("description", f"HTTP {status_code}")
                    # Cek HTTP 429 Too Many Requests
                    if status_code == 429:
                        params = err_json.get("parameters", {})
                        retry_after = params.get("retry_after")
                except Exception:
                    error_msg = f"HTTP {status_code}"

                # 403 Forbidden: Chat ID tidak ditemukan / bot diblokir oleh user
                if status_code in (403, 400) and "blocked" in (error_msg or "").lower():
                    logger.warning(f"[TELEGRAM] Bot diblokir atau chat invalid untuk chat_id={chat_id}: {error_msg}")
                    # Otomatis tandai link nonaktif jika ada user_id
                    TelegramService._handle_bot_blocked(chat_id)
                    break

                # HTTP 429 Backoff
                if status_code == 429 and attempt < MAX_RETRY_ATTEMPTS:
                    wait_sec = min(int(retry_after) if retry_after else (2 ** attempt), 10)
                    time.sleep(wait_sec)
                    continue

                if attempt < MAX_RETRY_ATTEMPTS:
                    time.sleep(2 ** (attempt - 1))  # 1s, 2s
            except Exception as ex:
                error_msg = str(ex)
                if attempt < MAX_RETRY_ATTEMPTS:
                    time.sleep(2 ** (attempt - 1))

        # Catat delivery log di DB secara aman (tanpa token)
        # user_id=0 berarti bot menjawab tanpa konteks user spesifik, jangan dicatat ke FK tabel
        if user_id and int(user_id) > 0:
            TelegramService._record_delivery_log(
                user_id=user_id,
                notification_id=notification_id,
                chat_id=str(chat_id),
                category=category,
                status="SENT" if success else "FAILED",
                attempts=attempts,
                error_message=error_msg,
                sent_at=now if success else None,
            )

        return success, error_msg

    @staticmethod
    def _record_delivery_log(user_id: int, chat_id: str, status: str, attempts: int,
                             notification_id: Optional[int] = None,
                             category: Optional[str] = None,
                             error_message: Optional[str] = None,
                             sent_at: Optional[datetime] = None) -> None:
        """Pencatatan riwayat pengiriman menggunakan sesi database mandiri."""
        try:
            with SessionLocal() as db:
                # Cek apakah notification_id masih valid di DB (cegah FK violation dari sesi/data lama)
                if notification_id is not None:
                    from app.db.models.notification import Notification as _Notif
                    notif_exists = db.query(_Notif.id).filter(_Notif.id == notification_id).scalar() is not None
                    if not notif_exists:
                        notification_id = None

                log = TelegramDeliveryLog(
                    user_id=user_id,
                    notification_id=notification_id,
                    chat_id=chat_id,
                    category=category,
                    status=status,
                    attempts=attempts,
                    error_message=error_message[:500] if error_message else None,
                    sent_at=sent_at,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(log)
                db.commit()
        except Exception as e:
            logger.error(f"[TELEGRAM] Gagal mencatat delivery log: {e}")

    @staticmethod
    def _handle_bot_blocked(chat_id: str) -> None:
        """Tandai user_link tidak aktif jika bot diblokir oleh user."""
        try:
            with SessionLocal() as db:
                link = db.query(TelegramUserLink).filter(TelegramUserLink.chat_id == str(chat_id)).first()
                if link:
                    link.is_active = False
                    link.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"[TELEGRAM] Chat {chat_id} dinonaktifkan karena bot diblokir.")
        except Exception as e:
            logger.error(f"[TELEGRAM] Gagal menonaktifkan link bot blocked: {e}")

    @staticmethod
    def dispatch_async(chat_id: str, text: str, user_id: int,
                       notification_id: Optional[int] = None,
                       category: Optional[str] = None) -> None:
        """Memicu pengiriman pesan secara asinkron di background thread pool."""
        _telegram_executor.submit(
            TelegramService.send_telegram_api,
            chat_id=chat_id,
            text=text,
            user_id=user_id,
            notification_id=notification_id,
            category=category,
        )

    # ------------------------------------------------------------------
    # 6. PEMROSESAN WEBHOOK TELEGRAM
    # ------------------------------------------------------------------
    @staticmethod
    def process_webhook_update(db: Session, update: Dict[str, Any], secret_token_header: Optional[str] = None) -> Tuple[bool, str, int]:
        """Memproses webhook update dari Telegram.

        Verifikasi header X-Telegram-Bot-Api-Secret-Token secara constant-time.
        Validasi idempotensi update_id.
        Penanganan /start <linking_token>.
        Mengembalikan (success, message, http_status_code).
        """
        # 1. Validasi secret webhook
        configured_secret = (settings.TELEGRAM_WEBHOOK_SECRET or "").strip()
        if configured_secret:
            if not secret_token_header or not hmac.compare_digest(secret_token_header.strip(), configured_secret):
                logger.warning("[TELEGRAM-WEBHOOK] Unauthorized webhook call: secret token mismatch.")
                return False, "Unauthorized webhook secret", 401
        elif settings.is_production:
            logger.error("[TELEGRAM-WEBHOOK] Secret webhook belum dikonfigurasi di lingkungan produksi.")
            return False, "Webhook secret not configured in production", 403

        # 2. Validasi struktur payload update
        if not isinstance(update, dict):
            return False, "Payload harus berupa JSON object", 400

        update_id = update.get("update_id")
        if update_id is None:
            return False, "Field update_id tidak ditemukan", 400

        str_update_id = str(update_id)

        # 3. Idempotensi update_id
        existing_update = db.query(TelegramWebhookUpdate).filter(
            TelegramWebhookUpdate.update_id == str_update_id
        ).first()

        if existing_update:
            # Update sudah pernah diproses, kembalikan 200 OK segera agar Telegram tidak mengulang
            return True, "Update already processed (idempotent)", 200

        # Catat update_id
        db.add(TelegramWebhookUpdate(
            update_id=str_update_id,
            processed_at=datetime.now(timezone.utc)
        ))
        db.commit()

        # 4. Ambil objek message
        message = update.get("message")
        if not message:
            # Update jenis lain (edited_message, channel_post, callback_query, dll)
            return True, "Ignored non-message update", 200

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        chat_type = chat.get("type", "")
        from_user = message.get("from", {})
        telegram_username = from_user.get("username")
        first_name = from_user.get("first_name")
        text = (message.get("text") or "").strip()

        # 5. Validasi tipe chat (hanya private chat yang diizinkan untuk notifikasi personal)
        if chat_type != "private":
            if text.startswith("/start"):
                # Beritahu di grup bahwa notifikasi hanya private chat
                TelegramService.dispatch_async(
                    chat_id=chat_id,
                    text="⚠️ Notifikasi personal KSP AHNRFZI hanya dapat dihubungkan melalui <b>Private Chat</b> langsung dengan Bot.",
                    user_id=0,
                )
            return True, "Chat type non-private rejected", 200

        # 6. Tangani perintah /start
        cmd_first = text.split()[0].lower() if text else ""
        if cmd_first == "/start" or cmd_first.startswith("/start@"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                raw_token = parts[1].strip().split()[0]
                user_id, token_status = TelegramService.verify_and_consume_token(db, raw_token)

                if user_id:
                    ok, link_msg = TelegramService.link_user(
                        db=db,
                        user_id=user_id,
                        chat_id=chat_id,
                        username=telegram_username,
                        first_name=first_name,
                    )
                    if ok:
                        welcome_msg = (
                            "✅ <b>Telegram berhasil terhubung dengan KSP AHNRFZI.</b>\n\n"
                            "Anda sekarang dapat menerima notifikasi koperasi sesuai pengaturan akun Anda."
                        )
                        TelegramService.dispatch_async(chat_id=chat_id, text=welcome_msg, user_id=user_id, category="SYSTEM")
                        return True, "Linking successful", 200
                    else:
                        fail_msg = f"⚠️ <b>Gagal Menghubungkan Akun:</b>\n{link_msg}"
                        TelegramService.dispatch_async(chat_id=chat_id, text=fail_msg, user_id=user_id)
                        return True, link_msg, 200
                else:
                    fail_msg = (
                        "⚠️ <b>Tautan Penghubung Tidak Valid</b>\n\n"
                        f"{token_status}\n\n"
                        "Silakan buka menu <b>Profil / Pengaturan Notifikasi</b> di aplikasi KSP AHNRFZI "
                        "lalu klik tombol <b>Hubungkan Telegram</b> untuk mendapatkan tautan baru."
                    )
                    TelegramService.dispatch_async(chat_id=chat_id, text=fail_msg, user_id=0)
                    return True, "Invalid or expired token", 200
            else:
                # /start tanpa parameter token
                help_msg = (
                    "🏦 <b>Selamat datang di Bot Notifikasi KSP AHNRFZI!</b>\n\n"
                    "Bot ini berfungsi mengirimkan notifikasi resmi transaksi koperasi Anda.\n\n"
                    "Untuk menghubungkan bot ini dengan akun KSP AHNRFZI Anda:\n"
                    "1. Login ke aplikasi web resmi KSP AHNRFZI.\n"
                    "2. Buka menu <b>Profil / Pengaturan Notifikasi</b>.\n"
                    "3. Klik tombol <b>Hubungkan Telegram</b>.\n"
                    "4. Ikuti tautan deep-link yang disediakan.\n\n"
                    "<i>Demi keamanan, jangan bagikan akun Telegram Anda kepada orang lain.</i>"
                )
                TelegramService.dispatch_async(chat_id=chat_id, text=help_msg, user_id=0)
                return True, "Start command handled without token", 200

        # 7. Penanganan pesan tidak dikenal / pesan umum
        reply_info = (
            "🏦 <b>KSP AHNRFZI Bot</b>\n\n"
            "Halo! Bot ini hanya digunakan untuk transmisi notifikasi resmi satu arah dari KSP AHNRFZI.\n"
            "Untuk melakukan transaksi keuangan, pengajuan pinjaman, atau pembayaran, silakan gunakan "
            "aplikasi web resmi KSP AHNRFZI."
        )
        TelegramService.dispatch_async(chat_id=chat_id, text=reply_info, user_id=0)
        return True, "Unknown message received", 200

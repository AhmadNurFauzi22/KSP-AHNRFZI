from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, backref
from app.core.database import Base


class TelegramUserLink(Base):
    """Koneksi Telegram Chat ID resmi pengguna KSP AHNRFZI (Prompt #14 Telegram Integration)."""
    __tablename__ = "telegram_user_links"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    chat_id = Column(String(64), unique=True, nullable=False, index=True)
    telegram_username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    connected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", backref=backref("telegram_link", uselist=False))

    def __repr__(self):
        return f"<TelegramUserLink user_id={self.user_id} chat_id={self.chat_id} active={self.is_active}>"


class TelegramLinkingToken(Base):
    """Token sekali pakai dengan masa berlaku singkat (10 menit) untuk deep-link linking Telegram."""
    __tablename__ = "telegram_linking_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User")

    def __repr__(self):
        return f"<TelegramLinkingToken user_id={self.user_id} used={self.used_at is not None}>"


class NotificationPreference(Base):
    """Preferensi saluran notifikasi dan kategori event pengguna."""
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    in_app_enabled = Column(Boolean, default=True, nullable=False)       # In-App saluran utama
    telegram_enabled = Column(Boolean, default=True, nullable=False)     # Telegram saluran opsional
    notify_loans = Column(Boolean, default=True, nullable=False)         # Notifikasi pengajuan & status pinjaman
    notify_installments = Column(Boolean, default=True, nullable=False)  # Pengingat & pembayaran angsuran
    notify_cashier = Column(Boolean, default=True, nullable=False)       # Transaksi & tutup kas
    notify_hrd = Column(Boolean, default=True, nullable=False)           # Perubahan kepegawaian
    notify_system = Column(Boolean, default=True, nullable=False)        # Pengumuman sistem & uji coba

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", backref=backref("notification_preference", uselist=False))

    def __repr__(self):
        return f"<NotificationPreference user_id={self.user_id} telegram={self.telegram_enabled}>"


class TelegramWebhookUpdate(Base):
    """Tabel idempotensi untuk mencegah proses ganda update dari Telegram."""
    __tablename__ = "telegram_webhook_updates"

    id = Column(Integer, primary_key=True, index=True)
    update_id = Column(String(64), unique=True, nullable=False, index=True)
    processed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<TelegramWebhookUpdate update_id={self.update_id}>"


class TelegramDeliveryLog(Base):
    """Catatan riwayat pengiriman pesan Telegram tanpa mencatat token atau secret."""
    __tablename__ = "telegram_delivery_logs"

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, nullable=True, index=True)  # Referensi lunak ke notifications.id (no FK untuk hindari constraint saat retry/async)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(String(64), nullable=False)
    category = Column(String(50), nullable=True)
    status = Column(String(20), default="PENDING", nullable=False, index=True) # PENDING, SENT, FAILED
    attempts = Column(Integer, default=1, nullable=False)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<TelegramDeliveryLog id={self.id} user_id={self.user_id} status={self.status}>"

"""Layanan notifikasi terpusat (Prompt #13).

Satu pintu untuk semua event: NotificationService.send() + fan-out peran.
- In-app selalu dikirim (tak dapat dimatikan user).
- Email: integration point; hanya dikirim jika provider dikonfigurasi
  DAN preferensi user mengizinkan. Tanpa credential asli di kode.
- Dedup: kunci unik per (user, event, entitas) dalam 24 jam terakhir.
- Nominal finansial selalu dari record resmi (parameter amount resmi),
  bukan dari input frontend.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.models.notification import Notification
from app.db.models.user import User, Role, Permission, user_roles, role_permissions
from app.core.config import settings
from app.core.logging import logger
from app.services.audit_service import AuditService

DEDUP_WINDOW_HOURS = 24


class NotificationService:
    @staticmethod
    def send(db: Session, user_id: int, title: str, message: str,
             ntype: str = "INFO", link_url: Optional[str] = None,
             entity_name: Optional[str] = None, entity_id: Optional[str] = None,
             event: Optional[str] = None,
             actor_id: Optional[int] = None) -> Optional[Notification]:
        """Kirim satu notifikasi in-app (+email bila layak). Idempoten per event."""
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            return None

        # Dedup: event sama untuk user+entitas yang sama dalam 24 jam → pakai yg ada
        if event:
            from sqlalchemy import and_ as _and
            since = datetime.now(timezone.utc) - timedelta(hours=DEDUP_WINDOW_HOURS)
            link = link_url or None
            eid = str(entity_id) if entity_id is not None else None
            dup = db.query(Notification).filter(
                Notification.user_id == user_id,
                Notification.title == title[:100],
                Notification.link_url.is_(None) if link is None
                else Notification.link_url == link,
                Notification.entity_name.is_(None) if entity_name is None
                else Notification.entity_name == entity_name,
                Notification.entity_id.is_(None) if eid is None
                else Notification.entity_id == eid,
                Notification.created_at >= since,
            ).first()
            if dup:
                return dup

        notif = Notification(
            user_id=user_id,
            title=title[:100],
            message=message,
            type=ntype,
            is_read=False,
            link_url=link_url,
            entity_name=entity_name,
            entity_id=str(entity_id) if entity_id is not None else None,
        )
        db.add(notif)
        db.flush()

        # Audit tanpa commit sendiri: ikut transaksi caller (atomic).
        # PENTING: jangan panggil AuditService.log_event di sini karena ia
        # melakukan commit dan akan memecah transaksi bisnis pemanggil.
        from app.db.models.audit_log import AuditLog as _AuditLog
        db.add(_AuditLog(
            user_id=actor_id,
            action="NOTIFICATION_SENT",
            entity_name="Notification",
            entity_id=str(notif.id),
            notes=f"[{event or ntype}] ke user_id={user_id}: {title[:100]}",
        ))
        db.flush()

        # Email (non-blocking best-effort; gagal → log, request tetap sukses)
        try:
            NotificationService._maybe_send_email(user, title, message, ntype)
        except Exception as e:  # noqa: BLE001 — channel eksternal tak boleh gagalkan request
            logger.warning(f"[NOTIF] email gagal untuk user_id={user_id}: {e}")

        # Telegram Bot (non-blocking best-effort; gagal → log, transaksi tetap sukses & in-app tersimpan)
        try:
            NotificationService._maybe_send_telegram(db, user, notif, title, message, ntype, entity_name, link_url)
        except Exception as e:
            logger.warning(f"[NOTIF] Telegram gagal untuk user_id={user_id}: {e}")

        return notif

    @staticmethod
    def notify_users_with_permission(db: Session, permission_codes: List[str],
                                     title: str, message: str, **kwargs) -> int:
        """Fan-out ke semua user aktif yang memiliki salah satu permission.

        Dipakai untuk: pengajuan → verifikator, verifikasi → approver,
        approval → kasir, CALON anggota → HRD, tutup-kas selisih → manager.
        """
        user_ids = db.query(User.id).join(
            user_roles, user_roles.c.user_id == User.id).join(
            Role, Role.id == user_roles.c.role_id).join(
            role_permissions, role_permissions.c.role_id == Role.id).join(
            Permission, Permission.id == role_permissions.c.permission_id).filter(
            User.is_active.is_(True),
            Permission.code.in_(permission_codes)).distinct().all()
        sent = 0
        for (uid,) in user_ids:
            if NotificationService.send(db, uid, title, message, **kwargs):
                sent += 1
        return sent

    @staticmethod
    def notify_roles(db: Session, role_codes: List[str], title: str,
                     message: str, **kwargs) -> int:
        """Fan-out ke semua user aktif dengan kode role tertentu."""
        user_ids = db.query(User.id).join(
            user_roles, user_roles.c.user_id == User.id).join(
            Role, Role.id == user_roles.c.role_id).filter(
            User.is_active.is_(True), Role.code.in_(role_codes)).distinct().all()
        sent = 0
        for (uid,) in user_ids:
            if NotificationService.send(db, uid, title, message, **kwargs):
                sent += 1
        return sent

    # ------------------------------------------------------------------
    # Email integration point (stub aman — tanpa credential nyata)
    # ------------------------------------------------------------------
    @staticmethod
    def email_configured() -> bool:
        return bool(getattr(settings, "SMTP_HOST", "") and getattr(settings, "SMTP_USER", ""))

    @staticmethod
    def _maybe_send_email(user: User, title: str, message: str, ntype: str) -> None:
        # Kritis (DANGER/APPROVAL) + preferensi user menentukan; default mati
        # bila provider belum dikonfigurasi.
        if not NotificationService.email_configured():
            return
        if not getattr(user, "notif_email_enabled", True):
            return
        if ntype not in ("DANGER", "APPROVAL", "WARNING", "SUCCESS", "INFO"):
            return
        logger.info(f"[NOTIF-EMAIL] to={user.email} title={title[:80]} "
                    f"(provider stub — hubungkan SMTP di .env)")

    # ------------------------------------------------------------------
    # Telegram Bot integration point (non-blocking, opt-in per preferensi)
    # ------------------------------------------------------------------
    @staticmethod
    def _maybe_send_telegram(db: Session, user: User, notif: Notification,
                             title: str, message: str, ntype: str,
                             entity_name: Optional[str] = None,
                             link_url: Optional[str] = None) -> None:
        """Kirim notifikasi Telegram jika user terhubung dan preferensi aktif."""
        if not getattr(settings, "telegram_configured", False):
            return
        if not user or not user.is_active:
            return

        from app.services.telegram_service import TelegramService
        from app.db.models.telegram import TelegramUserLink

        user_link = db.query(TelegramUserLink).filter(
            TelegramUserLink.user_id == user.id,
            TelegramUserLink.is_active.is_(True),
        ).first()

        if not user_link or not user_link.chat_id:
            return

        pref = TelegramService.get_preferences(db, user.id)
        if not pref.telegram_enabled:
            return

        # Tentukan kategori event
        category = "SYSTEM"
        if entity_name in ("Loan", "LoanProduct", "LoanApproval"):
            category = "LOANS"
        elif entity_name in ("LoanPayment", "LoanInstallment", "Installment"):
            category = "INSTALLMENTS"
        elif entity_name in ("CashRegister", "CashTransaction", "Transaction"):
            category = "CASHIER"
        elif entity_name in ("Employee",):
            category = "HRD"

        if not TelegramService.is_category_allowed(pref, category):
            return

        formatted = TelegramService.format_notification_message(
            title=title,
            message=message,
            ntype=ntype,
            category=category,
            link_url=link_url,
        )

        TelegramService.dispatch_async(
            chat_id=user_link.chat_id,
            text=formatted,
            user_id=user.id,
            notification_id=notif.id,
            category=category,
        )

    # ------------------------------------------------------------------
    # Baca / ubah status (ownership selalu user login)
    # ------------------------------------------------------------------
    @staticmethod
    def list_for_user(db: Session, user_id: int, unread_only: bool = False,
                      skip: int = 0, limit: int = 20) -> List[Notification]:
        q = db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            q = q.filter(Notification.is_read.is_(False))
        return q.order_by(desc(Notification.created_at)).offset(skip).limit(limit).all()

    @staticmethod
    def unread_count(db: Session, user_id: int) -> int:
        from sqlalchemy import func
        return db.query(func.count(Notification.id)).filter(
            Notification.user_id == user_id,
            Notification.is_read.is_(False)).scalar() or 0

    @staticmethod
    def mark_read(db: Session, user_id: int, notif_id: int) -> Optional[Notification]:
        """Tandai dibaca — milik user lain → None (caller balas 404, anti-IDOR)."""
        notif = db.query(Notification).filter(
            Notification.id == notif_id, Notification.user_id == user_id).first()
        if not notif:
            return None
        if not notif.is_read:
            notif.is_read = True
            notif.read_at = datetime.now(timezone.utc)
            db.commit()
        db.refresh(notif)
        return notif

    @staticmethod
    def mark_all_read(db: Session, user_id: int) -> int:
        now = datetime.now(timezone.utc)
        rows = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read.is_(False)).all()
        for n in rows:
            n.is_read = True
            n.read_at = now
        db.commit()
        return len(rows)

    # ------------------------------------------------------------------
    # WhatsApp Template & History Methods (Prompt #14)
    # ------------------------------------------------------------------
    @staticmethod
    def create_history(db: Session, user_id: int, data) -> bool:
        """Catat riwayat pengiriman notifikasi WhatsApp ke database."""
        from app.db.models.whatsapp_history import WhatsAppHistory
        try:
            hist = WhatsAppHistory(
                notification_type=getattr(data, "notification_type", "system_alert"),
                phone_number=getattr(data, "phone_number", ""),
                message=getattr(data, "message", ""),
                reference_id=getattr(data, "reference_id", None),
                status=getattr(data, "status", "pending"),
                fonnte_message_id=getattr(data, "fonnte_message_id", None),
                error_message=getattr(data, "error_message", None),
            )
            db.add(hist)
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False

    @staticmethod
    def delete_history(db: Session, hist_id: int) -> bool:
        """Hapus entri riwayat pengiriman WhatsApp."""
        from app.db.models.whatsapp_history import WhatsAppHistory
        row = db.query(WhatsAppHistory).filter(WhatsAppHistory.id == hist_id).first()
        if not row:
            return False
        try:
            db.delete(row)
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False

    @staticmethod
    def get_whatsapp_templates(db: Session) -> List[Dict[str, Any]]:
        """Ambil daftar template notifikasi WhatsApp dari database."""
        from app.db.models.whatsapp_template import WhatsAppTemplate
        templates = db.query(WhatsAppTemplate).order_by(
            WhatsAppTemplate.notification_type
        ).all()
        return [t.to_dict() for t in templates] if templates else []

    @staticmethod
    def save_whatsapp_template(db: Session, template_data: dict) -> bool:
        """Simpan atau update template notifikasi WhatsApp."""
        from app.db.models.whatsapp_template import WhatsAppTemplate
        from sqlalchemy import exc as _exc

        notif_type = template_data.get("notification_type", "")
        name = template_data.get("name", "")
        message = template_data.get("message", "")
        placeholders = template_data.get("placeholders", [])

        if not notif_type or not name:
            return False

        try:
            # Cek apakah template sudah ada
            existing = db.query(WhatsAppTemplate).filter(
                WhatsAppTemplate.notification_type == notif_type
            ).first()

            placeholders_json = None
            if placeholders:
                placeholders_json = str(placeholders)

            if existing:
                existing.template_name = name
                existing.message_template = message
                existing.placeholders = placeholders_json
                existing.updated_at = func.now()
            else:
                existing = WhatsAppTemplate(
                    notification_type=notif_type,
                    template_name=name,
                    message_template=message,
                    placeholders=placeholders_json,
                )
                db.add(existing)

            db.commit()
            return True
        except _exc.SQLAlchemyError:
            db.rollback()
            return False

    @staticmethod
    def get_whatsapp_history(
        db: Session,
        status_filter: Optional[str] = None,
        notification_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ambil riwayat pengiriman notifikasi WhatsApp dengan filter opsional."""
        from app.db.models.whatsapp_history import WhatsAppHistory
        from sqlalchemy import func as _func

        q = db.query(WhatsAppHistory)

        if status_filter:
            q = q.filter(WhatsAppHistory.status == status_filter)
        if notification_type:
            q = q.filter(WhatsAppHistory.notification_type == notification_type)

        total = q.count()
        history = q.order_by(WhatsAppHistory.sent_at.desc()).limit(50).all()

        return {
            "total_records": total,
            "data": [h.to_dict() for h in history],
        }

    @staticmethod
    def serialize(n: Notification) -> Dict[str, Any]:
        return {"id": n.id, "title": n.title, "message": n.message,
                "type": n.type, "is_read": n.is_read, "read_at": n.read_at,
                "link_url": n.link_url, "entity_name": n.entity_name,
                "entity_id": n.entity_id, "created_at": n.created_at}

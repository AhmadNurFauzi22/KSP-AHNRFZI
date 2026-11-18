"""API Notification Center — KSP AHNRFZI (Prompt #13).

Strict ownership: user hanya dapat membaca/mengubah notifikasi miliknya
sendiri. ID milik user lain → 404 (tidak membocorkan keberadaan).
Halaman tujuan deep-link tetap menegakkan authorization sendiri.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user
from app.db.models.user import User
from app.schemas.notification import (NotificationOut, NotificationListResponse,
                                      NotificationPreferencesOut,
                                      NotificationPreferencesUpdate)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationListResponse)
def list_notifications(unread_only: bool = Query(False),
                       page: int = Query(1, ge=1),
                       limit: int = Query(20, ge=1, le=100),
                       current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    skip = (page - 1) * limit
    rows = NotificationService.list_for_user(db, current_user.id,
                                            unread_only=unread_only,
                                            skip=skip, limit=limit)
    total = NotificationService.unread_count(db, current_user.id) if unread_only else None
    if total is None:
        from sqlalchemy import func
        from app.db.models.notification import Notification
        total = db.query(func.count(Notification.id)).filter(
            Notification.user_id == current_user.id).scalar() or 0
    return {"metadata": {"total_records": total, "current_page": page,
                         "total_pages": (total + limit - 1) // limit if total else 1,
                         "limit": limit,
                         "unread_count": NotificationService.unread_count(db, current_user.id)},
            "data": [NotificationService.serialize(n) for n in rows]}


@router.get("/unread-count")
def get_unread_count(current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    return {"unread_count": NotificationService.unread_count(db, current_user.id)}


@router.get("/preferences", response_model=NotificationPreferencesOut)
def get_preferences(current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    db.refresh(current_user)
    return {"email_enabled": bool(getattr(current_user, "notif_email_enabled", True)),
            "inapp_always_on": True}


@router.put("/preferences", response_model=NotificationPreferencesOut)
def update_preferences(payload: NotificationPreferencesUpdate,
                       current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    current_user.notif_email_enabled = payload.email_enabled
    db.commit()
    db.refresh(current_user)
    return {"email_enabled": bool(current_user.notif_email_enabled),
            "inapp_always_on": True}


@router.post("/read-all")
def mark_all_read(current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    count = NotificationService.mark_all_read(db, current_user.id)
    return {"success": True, "marked_read": count}


@router.patch("/{notif_id}/read", response_model=NotificationOut)
def mark_read(notif_id: int,
              current_user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    notif = NotificationService.mark_read(db, current_user.id, notif_id)
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Notifikasi tidak ditemukan.")
    return NotificationService.serialize(notif)

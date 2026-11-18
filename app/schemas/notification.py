from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: int
    title: str
    message: str
    type: str
    is_read: bool
    read_at: Optional[datetime] = None
    link_url: Optional[str] = None
    entity_name: Optional[str] = None
    entity_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    metadata: dict
    data: List[NotificationOut]


class NotificationPreferencesOut(BaseModel):
    email_enabled: bool
    inapp_always_on: bool = True


class NotificationPreferencesUpdate(BaseModel):
    email_enabled: bool = Field(..., description="Aktif/nonaktif notifikasi email")

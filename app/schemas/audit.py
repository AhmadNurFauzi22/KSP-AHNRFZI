from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    action: str
    entity_name: str
    entity_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.permissions import RoleChecker, SystemRole
from app.db.models.audit_log import AuditLog
from app.schemas.audit import AuditLogOut

router = APIRouter(prefix="/audit", tags=["Audit Log"])


@router.get("", response_model=List[AuditLogOut])
def get_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    entity_name: str = None,
    db: Session = Depends(get_db),
    authorized: bool = Depends(RoleChecker([SystemRole.ADMIN, SystemRole.PENGAWAS, SystemRole.IT_PUSAT]))
):
    """Retrieve immutable audit logs (Admin, Pengawas, IT Pusat only)."""
    query = db.query(AuditLog)
    if entity_name:
        query = query.filter(AuditLog.entity_name == entity_name)
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return logs

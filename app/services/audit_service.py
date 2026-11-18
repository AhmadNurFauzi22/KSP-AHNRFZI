from typing import Optional, Any, Dict
from sqlalchemy.orm import Session
from app.db.models.audit_log import AuditLog
from app.core.config import settings
from app.core.logging import logger


class AuditService:
    @staticmethod
    def log_event(
        db: Session,
        action: str,
        entity_name: str,
        entity_id: Optional[str] = None,
        user_id: Optional[int] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Optional[AuditLog]:
        """Record an immutable audit log entry."""
        if not settings.ENABLE_AUDIT_LOG:
            return None
            
        try:
            audit = AuditLog(
                user_id=user_id,
                action=action,
                entity_name=entity_name,
                entity_id=str(entity_id) if entity_id else None,
                old_values=old_values,
                new_values=new_values,
                ip_address=ip_address,
                user_agent=user_agent,
                notes=notes
            )
            db.add(audit)
            db.commit()
            db.refresh(audit)
            logger.info(f"[AUDIT] {action} on {entity_name}:{entity_id} by User={user_id}")
            return audit
        except Exception as e:
            db.rollback()
            logger.error(f"[AUDIT ERROR] Failed to record audit log: {e}")
            return None

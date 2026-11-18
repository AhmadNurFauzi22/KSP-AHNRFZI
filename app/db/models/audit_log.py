from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)      # CREATE, UPDATE, DELETE, LOGIN, APPROVE, DISBURSE, etc.
    entity_name = Column(String(50), nullable=False, index=True) # User, Loan, SavingsAccount, Member, etc.
    entity_id = Column(String(50), nullable=True)                # ID or Code of affected entity
    
    old_values = Column(JSON, nullable=True)                     # Snapshot before change
    new_values = Column(JSON, nullable=True)                     # Snapshot after change
    
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    user = relationship("User", back_populates="audit_logs")

    def __repr__(self):
        return f"<AuditLog {self.action} on {self.entity_name}:{self.entity_id} by User={self.user_id}>"

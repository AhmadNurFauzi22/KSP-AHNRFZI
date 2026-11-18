from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(30), default="INFO", nullable=False) # INFO, SUCCESS, WARNING, DANGER, APPROVAL
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime, nullable=True)                              # Prompt #13: waktu dibaca
    link_url = Column(String(255), nullable=True)
    entity_name = Column(String(50), nullable=True)                        # Prompt #13: entitas terkait
    entity_id = Column(String(50), nullable=True)                          # Prompt #13: ID entitas terkait
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="notifications")

    def __repr__(self):
        return f"<Notification to User={self.user_id} read={self.is_read}: {self.title}>"

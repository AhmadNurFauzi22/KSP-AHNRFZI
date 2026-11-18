from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Table, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base

# Association Table: User <-> Role (Many-to-Many)
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("assigned_at", DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
)

# Association Table: Role <-> Permission (Many-to-Many)
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("granted_at", DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
)


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(80), unique=True, nullable=False, index=True)  # E.g. "savings:deposit", "loans:approve_manager"
    name = Column(String(100), nullable=False)
    module = Column(String(50), nullable=False, index=True)           # E.g. "SAVINGS", "LOANS", "CASHIER", "HRD", "AUDIT"
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

    def __repr__(self):
        return f"<Permission {self.code} [{self.module}]>"


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(40), unique=True, nullable=False, index=True)  # E.g. ADMIN, KETUA_UMUM, MANAGER, HRD, KASIR, ANGGOTA
    name = Column(String(80), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    is_system_role = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles", lazy="joined")

    def __repr__(self):
        return f"<Role {self.code}: {self.name}>"

    @property
    def permission_codes(self):
        return [p.code for p in self.permissions]


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(120), nullable=False)
    phone_number = Column(String(25), nullable=True, index=True)
    
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    avatar_url = Column(String(255), nullable=True)
    # Prompt #13: preferensi channel email (in-app selalu dikirim & tak bisa dimatikan)
    notif_email_enabled = Column(Boolean, default=True, nullable=False)
    
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships - Separating User Account, Role, Employee, Member
    roles = relationship("Role", secondary=user_roles, back_populates="users", lazy="joined")
    employee = relationship("Employee", back_populates="user", uselist=False)
    member = relationship("Member", back_populates="user", uselist=False)
    audit_logs = relationship("AuditLog", back_populates="user")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User id={self.id} username='{self.username}'>"

    @property
    def role_codes(self):
        return [role.code for role in self.roles]

    @property
    def all_permissions(self):
        """Aggregate unique permissions from all assigned roles."""
        perms = set()
        for role in self.roles:
            for perm in role.permissions:
                perms.add(perm.code)
        return list(perms)

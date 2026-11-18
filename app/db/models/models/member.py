from datetime import datetime, date, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Date, Text, Enum as SQLEnum, Index
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base


class MemberStatus(str, enum.Enum):
    CALON = "CALON"          # Calon anggota (menunggu verifikasi)
    AKTIF = "AKTIF"          # Anggota aktif (dapat bertransaksi & meminjam)
    NONAKTIF = "NONAKTIF"    # Dibekukan / ditangguhkan sementara
    KELUAR = "KELUAR"        # Mengundurkan diri / keluar dari koperasi
    
    # Backward compatibility aliases (seeded data uses ACTIVE)
    PENDING = "CALON"        # alias for CALON
    ACTIVE = "AKTIF"         # alias for AKTIF
    SUSPENDED = "NONAKTIF"   # alias for NONAKTIF
    RESIGNED = "KELUAR"      # alias for KELUAR


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), unique=True, nullable=True, index=True)
    
    # Cooperative Membership Identity
    member_no = Column(String(40), unique=True, nullable=False, index=True)  # E.g. KSP-2026-0001
    nik = Column(String(25), unique=True, nullable=False, index=True)        # NIK KTP (Wajib & Unik)
    full_name = Column(String(120), nullable=False, index=True)
    
    gender = Column(String(10), nullable=True)                              # L / P
    birth_place = Column(String(60), nullable=True)
    birth_date = Column(Date, nullable=True)
    address = Column(Text, nullable=True)
    phone_number = Column(String(25), nullable=False, index=True)
    email = Column(String(120), nullable=True)
    
    emergency_contact_name = Column(String(100), nullable=True)
    emergency_contact_phone = Column(String(25), nullable=True)
    emergency_contact_relation = Column(String(50), nullable=True)
    
    # Organizational assignment (unit/divisi dan jabatan dalam organisasi AHNRFZI)
    unit_divisi = Column(String(100), nullable=True, index=True)   # Unit / Divisi kerja
    jabatan = Column(String(100), nullable=True)                   # Jabatan dalam organisasi

    status = Column(String(30), default=MemberStatus.AKTIF.value, nullable=False, index=True)
    join_date = Column(Date, default=lambda: datetime.now(timezone.utc).date(), nullable=False)
    resigned_date = Column(Date, nullable=True)
    resignation_reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", back_populates="member")
    employee = relationship("Employee", back_populates="member")
    savings_accounts = relationship("SavingsAccount", back_populates="member", cascade="all, delete-orphan")
    loans = relationship("Loan", back_populates="member")
    cash_transactions = relationship("CashTransaction", back_populates="member")

    def __repr__(self):
        return f"<Member {self.member_no} - {self.full_name} [{self.status}]>"

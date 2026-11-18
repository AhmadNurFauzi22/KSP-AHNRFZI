from datetime import datetime, date, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Date, Text, Numeric, Enum as SQLEnum, Index
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base


class EmploymentStatus(str, enum.Enum):
    TETAP = "TETAP"          # Karyawan Tetap
    KONTRAK = "KONTRAK"      # Karyawan Kontrak
    PROBATION = "PROBATION"  # Masa Percobaan
    MAGANG = "MAGANG"        # Intern
    RESIGNED = "RESIGNED"    # Mantan Karyawan


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True, index=True)
    
    nip = Column(String(50), unique=True, nullable=False, index=True)           # Nomor Induk Pegawai AHNRFZI
    full_name = Column(String(120), nullable=False)
    id_card_number = Column(String(30), unique=True, nullable=True)            # NIK KTP
    
    department = Column(String(100), nullable=False, index=True)               # Divisi / Unit Kerja
    position = Column(String(100), nullable=False)                             # Jabatan di AHNRFZI
    employment_status = Column(String(30), default=EmploymentStatus.TETAP.value, nullable=False)
    
    # Financial HR Data for Payroll Deduction & Loan Ceilings
    base_salary = Column(Numeric(18, 2), default=0.0, nullable=False)          # Gaji Pokok
    allowances = Column(Numeric(18, 2), default=0.0, nullable=False)           # Tunjangan Tetap
    payroll_bank_name = Column(String(50), nullable=True)                      # Bank Payroll
    payroll_bank_account = Column(String(50), nullable=True)                   # No Rekening Bank Payroll
    
    email_corporate = Column(String(120), nullable=True)
    phone_number = Column(String(25), nullable=True)
    hire_date = Column(Date, nullable=False)
    resignation_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships - Separated identity
    user = relationship("User", back_populates="employee")
    member = relationship("Member", back_populates="employee", uselist=False)

    def __repr__(self):
        return f"<Employee {self.nip} - {self.full_name} ({self.department})>"

    @property
    def total_income(self):
        return (self.base_salary or 0) + (self.allowances or 0)

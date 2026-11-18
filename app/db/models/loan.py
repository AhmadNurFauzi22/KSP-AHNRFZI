from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Text, Date, Boolean, Index
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base


class LoanCalculationType(str, enum.Enum):
    FLAT = "FLAT"          # Bunga flat (Pokok dan bunga tetap setiap bulan)
    ANUITAS = "ANUITAS"    # Bunga anuitas efektif (Total angsuran tetap, proporsi pokok & bunga berubah)
    SLIDING = "SLIDING"    # Bunga menurun / sliding rate (Pokok tetap, bunga menurun seiring sisa pinjaman)


class LoanStatus(str, enum.Enum):
    DRAFT = "DRAFT"                        # Draf pengajuan oleh anggota
    DIAJUKAN = "DIAJUKAN"                  # Diajukan ke sistem koperasi
    VERIFIKASI = "VERIFIKASI"              # Berkas diverifikasi oleh Staf/Manager
    DISETUJUI = "DISETUJUI"                # Disetujui (siap dicairkan)
    DITOLAK = "DITOLAK"                    # Ditolak
    DICAIRKAN = "DICAIRKAN"                # Telah dicairkan oleh Kasir
    BERJALAN = "BERJALAN"                  # Pinjaman berjalan
    LUNAS = "LUNAS"                        # Lunas

    # Backward compatibility aliases
    SUBMITTED = "DIAJUKAN"
    VERIFIED_STAF = "VERIFIKASI"
    APPROVED_MANAGER = "DISETUJUI"
    APPROVED_KETUA = "DISETUJUI"
    REJECTED = "DITOLAK"
    REVISION = "REVISI"
    DISBURSED = "DICAIRKAN"
    ACTIVE = "BERJALAN"
    PAID_OFF = "LUNAS"
    DEFAULTED = "MACET"


class LoanProduct(Base):
    __tablename__ = "loan_products"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, nullable=False, index=True)   # E.g. "PINJ-REGULER", "PINJ-DARURAT"
    name = Column(String(100), nullable=False)
    
    min_amount = Column(Numeric(18, 2), default=500000.0, nullable=False)
    max_amount = Column(Numeric(18, 2), default=50000000.0, nullable=False)
    min_tenor_months = Column(Integer, default=1, nullable=False)
    max_tenor_months = Column(Integer, default=36, nullable=False)
    
    annual_interest_rate = Column(Numeric(6, 3), default=12.0, nullable=False) # Bunga per tahun (%)
    calculation_type = Column(String(20), default=LoanCalculationType.FLAT.value, nullable=False)
    
    admin_fee_percent = Column(Numeric(5, 2), default=1.0, nullable=False)     # Biaya Administrasi (%)
    provision_fee_percent = Column(Numeric(5, 2), default=0.5, nullable=False) # Biaya Provisi (%)
    penalty_rate_daily = Column(Numeric(5, 3), default=0.1, nullable=False)    # Denda keterlambatan per hari (%)
    
    require_collateral = Column(Boolean, default=False, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    loans = relationship("Loan", back_populates="product")

    def __repr__(self):
        return f"<LoanProduct {self.code}: {self.name}>"


class Loan(Base):
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True, index=True)
    loan_no = Column(String(40), unique=True, nullable=False, index=True)  # E.g. LOAN-2026-0001
    member_id = Column(Integer, ForeignKey("members.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("loan_products.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    # Financial Terms
    requested_amount = Column(Numeric(18, 2), nullable=False)              # Jumlah diajukan
    approved_amount = Column(Numeric(18, 2), nullable=True)                # Jumlah disetujui
    interest_rate_percent = Column(Numeric(6, 3), nullable=False)          # Suku bunga disepakati (%/thn)
    tenor_months = Column(Integer, nullable=False)                        # Durasi cicilan (bulan)
    calculation_type = Column(String(20), default=LoanCalculationType.FLAT.value, nullable=False)
    
    admin_fee = Column(Numeric(18, 2), default=0.0, nullable=False)        # Biaya admin
    provision_fee = Column(Numeric(18, 2), default=0.0, nullable=False)    # Biaya provisi
    net_disbursed_amount = Column(Numeric(18, 2), default=0.0, nullable=False) # Dana cair bersih
    
    monthly_principal = Column(Numeric(18, 2), default=0.0, nullable=False) # Pokok per bulan (estimasi)
    monthly_interest = Column(Numeric(18, 2), default=0.0, nullable=False)  # Bunga per bulan (estimasi)
    monthly_installment_total = Column(Numeric(18, 2), default=0.0, nullable=False) # Total angsuran/bulan
    
    total_interest = Column(Numeric(18, 2), default=0.0, nullable=False)   # Total bunga seluruh tenor
    total_payable = Column(Numeric(18, 2), default=0.0, nullable=False)    # Total pinjaman (Pokok + Bunga)
    
    remaining_principal = Column(Numeric(18, 2), default=0.0, nullable=False) # Sisa pokok terutang
    remaining_interest = Column(Numeric(18, 2), default=0.0, nullable=False)  # Sisa bunga terutang
    
    purpose = Column(Text, nullable=False)                                 # Keperluan peminjaman
    collateral_info = Column(Text, nullable=True)                          # Agunan / Jaminan
    status = Column(String(30), default=LoanStatus.DIAJUKAN.value, nullable=False, index=True)
    
    document_path = Column(String(255), nullable=True)                     # Path file dokumen pendukung
    rejection_reason = Column(Text, nullable=True)                         # Alasan penolakan jika ditolak
    
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    
    disbursed_at = Column(DateTime, nullable=True)
    disbursed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(Date, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    member = relationship("Member", back_populates="loans")
    product = relationship("LoanProduct", back_populates="loans")
    approvals = relationship("LoanApproval", back_populates="loan", cascade="all, delete-orphan")
    installments = relationship("LoanInstallment", back_populates="loan", cascade="all, delete-orphan")
    payments = relationship("LoanPayment", back_populates="loan")
    approved_by = relationship("User", foreign_keys=[approved_by_user_id])
    disbursed_by = relationship("User", foreign_keys=[disbursed_by_user_id])

    def __repr__(self):
        return f"<Loan {self.loan_no} [{self.status}] Principal: {self.approved_amount or self.requested_amount}>"


class LoanApproval(Base):
    __tablename__ = "loan_approvals"

    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    stage = Column(String(30), nullable=False, index=True)                 # STAF, MANAGER, KETUA_UMUM, PENGAWAS
    decision = Column(String(25), nullable=False)                          # SUBMITTED, VERIFIED, APPROVED, REJECTED, DISBURSED, REVISION
    from_status = Column(String(30), nullable=True)                       # Status pinjaman sebelum aksi (Prompt #10)
    to_status = Column(String(30), nullable=True)                         # Status pinjaman sesudah aksi (Prompt #10)
    approved_amount = Column(Numeric(18, 2), nullable=True)                # Plafon yang disetujui oleh level ini
    notes = Column(Text, nullable=True)                                    # Catatan / Syarat dari approver
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    loan = relationship("Loan", back_populates="approvals")
    approver = relationship("User", foreign_keys=[approver_user_id])

    def __repr__(self):
        return f"<LoanApproval Loan={self.loan_id} Stage={self.stage} Decision={self.decision}>"


class InstallmentStatus(str, enum.Enum):
    BELUM_JATUH_TEMPO = "BELUM_JATUH_TEMPO"  # Belum jatuh tempo
    JATUH_TEMPO = "JATUH_TEMPO"              # Jatuh tempo hari ini
    TERLAMBAT = "TERLAMBAT"                  # Lewat jatuh tempo (overdue)
    DIBAYAR = "DIBAYAR"                      # Dibayar sebagian (partial)
    LUNAS = "LUNAS"                          # Lunas penuh

    # Backward compatibility
    UNPAID = "BELUM_JATUH_TEMPO"
    PARTIAL = "DIBAYAR"
    PAID = "LUNAS"
    OVERDUE = "TERLAMBAT"


class LoanInstallment(Base):
    __tablename__ = "loan_installments"

    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True)
    installment_no = Column(Integer, nullable=False)                       # Angsuran ke-1, 2, ... N
    due_date = Column(Date, nullable=False, index=True)                    # Tanggal jatuh tempo
    
    principal_due = Column(Numeric(18, 2), nullable=False)                 # Pokok harus dibayar
    interest_due = Column(Numeric(18, 2), nullable=False)                  # Bunga harus dibayar
    penalty_due = Column(Numeric(18, 2), default=0.0, nullable=False)      # Denda keterlambatan
    total_due = Column(Numeric(18, 2), nullable=False)                     # Total tagihan (Pokok + Bunga + Denda)
    
    principal_paid = Column(Numeric(18, 2), default=0.0, nullable=False)   # Pokok telah dibayar
    interest_paid = Column(Numeric(18, 2), default=0.0, nullable=False)    # Bunga telah dibayar
    penalty_paid = Column(Numeric(18, 2), default=0.0, nullable=False)     # Denda telah dibayar
    total_paid = Column(Numeric(18, 2), default=0.0, nullable=False)       # Total uang masuk
    
    status = Column(String(30), default=InstallmentStatus.BELUM_JATUH_TEMPO.value, nullable=False, index=True)
    paid_at = Column(DateTime, nullable=True)
    days_overdue = Column(Integer, default=0, nullable=False)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    loan = relationship("Loan", back_populates="installments")
    payments = relationship("LoanPayment", back_populates="installment")

    @property
    def remaining_due(self):
        tot = max((self.total_due or 0),
                  (self.principal_due or 0) + (self.interest_due or 0) + (self.penalty_due or 0))
        paid = self.total_paid or 0
        return max(0, tot - paid)

    def get_current_status(self, as_of_date=None) -> str:
        """Kalkulasi status angsuran dinamis berbasis tanggal dan pelunasan."""
        tot = float(max((self.total_due or 0),
                        (self.principal_due or 0) + (self.interest_due or 0) + (self.penalty_due or 0)))
        paid = float(self.total_paid or 0)

        if paid >= tot and tot > 0:
            return InstallmentStatus.LUNAS.value
        if paid > 0:
            return InstallmentStatus.DIBAYAR.value

        as_of = as_of_date or datetime.now(timezone.utc).date()
        if self.due_date > as_of:
            return InstallmentStatus.BELUM_JATUH_TEMPO.value
        elif self.due_date == as_of:
            return InstallmentStatus.JATUH_TEMPO.value
        else:
            return InstallmentStatus.TERLAMBAT.value

    def __repr__(self):
        return f"<LoanInstallment Loan={self.loan_id} #{self.installment_no} Status={self.status}>"


class LoanPayment(Base):
    __tablename__ = "loan_payments"

    id = Column(Integer, primary_key=True, index=True)
    payment_no = Column(String(50), unique=True, nullable=False, index=True) # E.g. PAY-LOAN-20260828-00001
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="RESTRICT"), nullable=False, index=True)
    installment_id = Column(Integer, ForeignKey("loan_installments.id", ondelete="SET NULL"), nullable=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    amount_paid = Column(Numeric(18, 2), nullable=False)
    principal_portion = Column(Numeric(18, 2), default=0.0, nullable=False)
    interest_portion = Column(Numeric(18, 2), default=0.0, nullable=False)
    penalty_portion = Column(Numeric(18, 2), default=0.0, nullable=False)
    
    payment_method = Column(String(30), default="CASHIER", nullable=False)   # CASHIER, HRD_PAYROLL, BANK_TRANSFER
    receipt_no = Column(String(50), unique=True, nullable=False, index=True) # Nomor Kuitansi Kasir
    received_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    loan = relationship("Loan", back_populates="payments")
    installment = relationship("LoanInstallment", back_populates="payments")
    member = relationship("Member")
    received_by = relationship("User", foreign_keys=[received_by_user_id])

    def __repr__(self):
        return f"<LoanPayment {self.payment_no} Amount={self.amount_paid}>"

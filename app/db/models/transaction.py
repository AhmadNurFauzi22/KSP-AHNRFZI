from datetime import datetime, date, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Text, Date, Boolean, Index
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base


class CashDirection(str, enum.Enum):
    CASH_IN = "CASH_IN"      # Kas Masuk (Setor tabungan, bayar angsuran, pendapatan lain)
    CASH_OUT = "CASH_OUT"    # Kas Keluar (Tarik tabungan, pencairan pinjaman, biaya operasional)


class CashCategory(str, enum.Enum):
    SAVINGS_DEPOSIT = "SAVINGS_DEPOSIT"
    SAVINGS_WITHDRAWAL = "SAVINGS_WITHDRAWAL"
    LOAN_DISBURSEMENT = "LOAN_DISBURSEMENT"
    LOAN_PAYMENT = "LOAN_PAYMENT"
    OPERATIONAL_EXPENSE = "OPERATIONAL_EXPENSE"
    OTHER_INCOME = "OTHER_INCOME"
    OTHER_EXPENSE = "OTHER_EXPENSE"
    CAPITAL_INJECTION = "CAPITAL_INJECTION"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"
    OTHER = "OTHER"


class AccountType(str, enum.Enum):
    ASSET = "ASSET"          # Harta / Aktiva (Kas, Bank, Piutang Anggota)
    LIABILITY = "LIABILITY"  # Kewajiban / Hutang (Simpanan Sukarela/Berjangka)
    EQUITY = "EQUITY"        # Ekuitas / Modal (Simpanan Pokok, Simpanan Wajib, Cadangan SHU)
    REVENUE = "REVENUE"      # Pendapatan (Pendapatan Jasa Pinjaman, Admin)
    EXPENSE = "EXPENSE"      # Beban (Biaya Operasional, Bunga Simpanan)


class NormalBalance(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class CashRegister(Base):
    __tablename__ = "cash_registers"

    id = Column(Integer, primary_key=True, index=True)
    cashier_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    shift_date = Column(Date, default=lambda: datetime.now(timezone.utc).date(), nullable=False, index=True)
    
    opening_balance = Column(Numeric(18, 2), default=0.0, nullable=False)   # Kas Awal Shift
    total_cash_in = Column(Numeric(18, 2), default=0.0, nullable=False)     # Total Masuk
    total_cash_out = Column(Numeric(18, 2), default=0.0, nullable=False)    # Total Keluar
    closing_balance = Column(Numeric(18, 2), default=0.0, nullable=False)   # Kas Akhir Shift (Sistem)
    physical_balance = Column(Numeric(18, 2), default=0.0, nullable=True)   # Kas Fisik Riil di laci kasir
    discrepancy = Column(Numeric(18, 2), default=0.0, nullable=True)        # Selisih = physical - closing_balance
    
    status = Column(String(20), default="OPEN", nullable=False, index=True) # OPEN, CLOSED
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    closed_at = Column(DateTime, nullable=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    notes = Column(Text, nullable=True)

    # Relationships
    cashier = relationship("User", foreign_keys=[cashier_user_id])
    closed_by = relationship("User", foreign_keys=[closed_by_user_id])
    transactions = relationship("CashTransaction", back_populates="cash_register")

    @property
    def system_balance(self):
        """Kalkulasi saldo kas sistem (Saldo Awal + Total Masuk - Total Keluar)."""
        op = float(self.opening_balance or 0)
        cin = float(self.total_cash_in or 0)
        cout = float(self.total_cash_out or 0)
        return op + cin - cout

    def __repr__(self):
        return f"<CashRegister ID={self.id} Cashier={self.cashier_user_id} Status={self.status}>"


class CashTransaction(Base):
    __tablename__ = "cash_transactions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_no = Column(String(50), unique=True, nullable=False, index=True) # E.g. TRX-CSH-20260828-0001
    cash_register_id = Column(Integer, ForeignKey("cash_registers.id", ondelete="SET NULL"), nullable=True, index=True)
    cashier_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    direction = Column(String(20), nullable=False, index=True)                   # CASH_IN / CASH_OUT
    category = Column(String(40), nullable=False, index=True)                    # SAVINGS_DEPOSIT, LOAN_PAYMENT, OTHER_INCOME, etc.
    amount = Column(Numeric(18, 2), nullable=False)
    
    member_id = Column(Integer, ForeignKey("members.id", ondelete="SET NULL"), nullable=True, index=True)
    reference_no = Column(String(60), nullable=True, index=True)                 # No Rekening Simpanan / No Pinjaman
    receipt_no = Column(String(60), unique=True, nullable=False, index=True)    # Nomor Struk Cetak
    
    payment_method = Column(String(30), default="CASH", nullable=False)          # CASH, BANK_TRANSFER, QRIS
    notes = Column(Text, nullable=True)
    
    # Pelacakan Financial Integrity & Reversal
    is_reversed = Column(Boolean, default=False, nullable=False, index=True)
    reversed_at = Column(DateTime, nullable=True)
    reversed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reversal_of_id = Column(Integer, ForeignKey("cash_transactions.id", ondelete="SET NULL"), nullable=True, index=True)
    reversal_reason = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    cash_register = relationship("CashRegister", back_populates="transactions")
    cashier = relationship("User", foreign_keys=[cashier_user_id])
    member = relationship("Member", back_populates="cash_transactions")
    reversed_by = relationship("User", foreign_keys=[reversed_by_user_id])
    reversal_of = relationship("CashTransaction", remote_side=[id], foreign_keys=[reversal_of_id], backref="reversed_by_trx")

    def __repr__(self):
        return f"<CashTransaction {self.transaction_no} ({self.direction}): {self.amount}>"


class ChartOfAccount(Base):
    __tablename__ = "chart_of_accounts"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, nullable=False, index=True)           # E.g. "1101" Kas, "1201" Piutang Pinjaman
    name = Column(String(100), nullable=False)
    account_type = Column(String(30), nullable=False, index=True)                # ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
    normal_balance = Column(String(10), default="DEBIT", nullable=False)         # DEBIT / CREDIT
    description = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    journal_lines = relationship("JournalLine", back_populates="account")

    def __repr__(self):
        return f"<COA {self.code} - {self.name} ({self.account_type})>"


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    entry_no = Column(String(50), unique=True, nullable=False, index=True)       # E.g. JRN-20260828-0001
    entry_date = Column(Date, default=lambda: datetime.now(timezone.utc).date(), nullable=False, index=True)
    reference_no = Column(String(60), nullable=True, index=True)                 # No Transaksi Kasir / No Mutasi
    description = Column(Text, nullable=False)
    
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    lines = relationship("JournalLine", back_populates="journal_entry", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<JournalEntry {self.entry_no} Date={self.entry_date}>"


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True, index=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    debit = Column(Numeric(18, 2), default=0.0, nullable=False)
    credit = Column(Numeric(18, 2), default=0.0, nullable=False)
    description = Column(String(255), nullable=True)

    # Relationships
    journal_entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("ChartOfAccount", back_populates="journal_lines")

    def __repr__(self):
        return f"<JournalLine Account={self.account_id} Debit={self.debit} Credit={self.credit}>"

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Text, Boolean, Index
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base


class SavingsProductType(str, enum.Enum):
    POKOK = "POKOK"          # Simpanan Pokok (Sekali saat pendaftaran anggota, tidak dapat ditarik)
    WAJIB = "WAJIB"          # Simpanan Wajib (Rutin per bulan via kasir/payroll, tidak dapat ditarik selama aktif)
    SUKARELA = "SUKARELA"    # Simpanan Sukarela (Bebas setor & tarik kapan saja)
    BERJANGKA = "BERJANGKA"  # Deposito Berjangka Koperasi (Tenor tertentu dengan bunga khusus)


class SavingsTransactionType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"            # Setor simpanan
    WITHDRAWAL = "WITHDRAWAL"      # Tarik simpanan
    SETOR = "SETOR"                # Alias SETOR (Setoran Simpanan)
    TARIK = "TARIK"                # Alias TARIK (Penarikan Simpanan)
    INTEREST_PAYOUT = "INTEREST"   # Bunga bagi hasil / jasa simpanan
    FEE = "FEE"                    # Biaya administrasi / penutupan rekening
    TRANSFER_IN = "TRANSFER_IN"    # Pindahan masuk
    TRANSFER_OUT = "TRANSFER_OUT"  # Pindahan keluar
    CORRECTION = "CORRECTION"      # Koreksi pembukuan


class SavingsTransactionStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"


class SavingsProduct(Base):
    __tablename__ = "savings_products"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, nullable=False, index=True)   # E.g. "PROD-POKOK", "PROD-WAJIB", "PROD-SUKARELA"
    name = Column(String(100), nullable=False)
    product_type = Column(String(30), nullable=False, index=True)        # POKOK, WAJIB, SUKARELA, BERJANGKA
    
    min_initial_deposit = Column(Numeric(18, 2), default=0.0, nullable=False)
    min_monthly_deposit = Column(Numeric(18, 2), default=0.0, nullable=False)
    annual_interest_rate = Column(Numeric(6, 3), default=0.0, nullable=False) # Persentase bunga tahunan (%)
    allow_withdrawal = Column(Boolean, default=True, nullable=False)
    
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    accounts = relationship("SavingsAccount", back_populates="product")

    def __repr__(self):
        return f"<SavingsProduct {self.code}: {self.name}>"


class SavingsAccount(Base):
    __tablename__ = "savings_accounts"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("savings_products.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    account_no = Column(String(40), unique=True, nullable=False, index=True)  # E.g. SAV-POK-2026-0001
    balance = Column(Numeric(18, 2), default=0.0, nullable=False)             # Saldo terkini
    status = Column(String(25), default="ACTIVE", nullable=False, index=True) # ACTIVE, DORMANT, BLOCKED, CLOSED
    
    opened_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    closed_date = Column(DateTime, nullable=True)
    closure_reason = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    member = relationship("Member", back_populates="savings_accounts")
    product = relationship("SavingsProduct", back_populates="accounts")
    transactions = relationship("SavingsTransaction", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<SavingsAccount {self.account_no} [Balance: {self.balance}]>"

    @property
    def reconstructed_balance(self):
        """Rekonstruksi saldo dari buku besar transaksi (ledger) secara deterministik."""
        from decimal import Decimal
        total = Decimal("0.00")
        for tx in self.transactions:
            if tx.status == "COMPLETED":
                if tx.transaction_type in ("SETOR", "DEPOSIT", "INTEREST", "TRANSFER_IN"):
                    total += Decimal(str(tx.amount))
                elif tx.transaction_type in ("TARIK", "WITHDRAWAL", "FEE", "TRANSFER_OUT"):
                    total -= Decimal(str(tx.amount))
        return total


class SavingsTransaction(Base):
    __tablename__ = "savings_transactions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("savings_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_no = Column(String(50), unique=True, nullable=False, index=True)  # E.g. TRX-SAV-20260828-00001
    
    transaction_type = Column(String(30), nullable=False, index=True)             # DEPOSIT, WITHDRAWAL, INTEREST, etc.
    amount = Column(Numeric(18, 2), nullable=False)                               # Nominal transaksi
    balance_before = Column(Numeric(18, 2), nullable=False)                        # Saldo sebelum transaksi
    balance_after = Column(Numeric(18, 2), nullable=False)                         # Saldo sesudah transaksi
    
    payment_channel = Column(String(30), default="CASHIER", nullable=False)       # CASHIER, HRD_PAYROLL, BANK_TRANSFER, SYSTEM
    reference_no = Column(String(60), nullable=True, index=True)                  # Referensi eksternal (No Struk Kasir / No Batch Payroll)
    status = Column(String(20), default=SavingsTransactionStatus.COMPLETED.value, nullable=False, index=True)
    
    description = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    account = relationship("SavingsAccount", back_populates="transactions")
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<SavingsTransaction {self.transaction_no} ({self.transaction_type}): {self.amount}>"

"""
Schemas: Modul Simpanan KSP AHNRFZI
====================================
Pydantic schemas untuk validasi transaksi simpanan, ledger, bukti transaksi, dan ringkasan saldo.
"""
from typing import Optional, List, Any
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel, Field, validator


# ============================================================================
# HELPER: TERBILANG RUPIAH
# ============================================================================

def terbilang_rupiah(angka: int) -> str:
    """Mengubah bilangan integer ke kalimat terbilang bahasa Indonesia."""
    satuan = ["", "Satu", "Dua", "Tiga", "Empat", "Lima", "Enam", "Tujuh", "Delapan", "Sembilan", "Sepuluh", "Sebelas"]
    n = int(angka)
    if n < 12:
        return satuan[n]
    elif n < 20:
        return terbilang_rupiah(n - 10) + " Belas"
    elif n < 100:
        return terbilang_rupiah(n // 10) + " Puluh " + satuan[n % 10]
    elif n < 200:
        return "Seratus " + terbilang_rupiah(n - 100)
    elif n < 1000:
        return terbilang_rupiah(n // 100) + " Ratus " + terbilang_rupiah(n % 100)
    elif n < 2000:
        return "Seribu " + terbilang_rupiah(n - 1000)
    elif n < 1000000:
        return terbilang_rupiah(n // 1000) + " Ribu " + terbilang_rupiah(n % 1000)
    elif n < 1000000000:
        return terbilang_rupiah(n // 1000000) + " Juta " + terbilang_rupiah(n % 1000000)
    elif n < 1000000000000:
        return terbilang_rupiah(n // 1000000000) + " Miliar " + terbilang_rupiah(n % 1000000000)
    else:
        return str(n)


# ============================================================================
# MASTER PRODUCTS
# ============================================================================

class SavingsProductOut(BaseModel):
    id: int
    code: str
    name: str
    product_type: str
    min_initial_deposit: Decimal
    min_monthly_deposit: Decimal
    annual_interest_rate: Decimal
    allow_withdrawal: bool
    description: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


# ============================================================================
# TRANSACTION REQUESTS
# ============================================================================

class SavingsDepositRequest(BaseModel):
    """Permohonan setor simpanan di loket kasir."""
    account_id: Optional[int] = Field(None, description="ID rekening simpanan spesifik")
    member_id: Optional[int] = Field(None, description="ID Anggota (jika account_id tidak diisi)")
    product_type: Optional[str] = Field("SUKARELA", description="POKOK, WAJIB, atau SUKARELA")
    amount: Decimal = Field(..., gt=0, description="Nominal setoran (harus > 0)")
    payment_channel: Optional[str] = Field("CASHIER", description="Kanal pembayaran: CASHIER, BANK_TRANSFER, HRD_PAYROLL")
    reference_no: Optional[str] = Field(None, max_length=60, description="No referensi / kuitansi kasir")
    description: Optional[str] = Field(None, max_length=255, description="Keterangan transaksi")

    @validator("amount")
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Nominal setoran harus lebih besar dari 0")
        return v

    @validator("product_type")
    def validate_product_type(cls, v):
        if v:
            v = v.upper()
            if v not in ("POKOK", "WAJIB", "SUKARELA", "BERJANGKA"):
                raise ValueError("Jenis simpanan harus POKOK, WAJIB, atau SUKARELA")
        return v


class SavingsWithdrawRequest(BaseModel):
    """Permohonan tarik simpanan di loket kasir sesuai kebijakan."""
    account_id: Optional[int] = Field(None, description="ID rekening simpanan spesifik")
    member_id: Optional[int] = Field(None, description="ID Anggota (jika account_id tidak diisi)")
    product_type: Optional[str] = Field("SUKARELA", description="Jenis simpanan yang ditarik: POKOK, WAJIB, SUKARELA")
    amount: Decimal = Field(..., gt=0, description="Nominal penarikan (harus > 0)")
    payment_channel: Optional[str] = Field("CASHIER", description="Kanal pembayaran: CASHIER, BANK_TRANSFER")
    reference_no: Optional[str] = Field(None, max_length=60, description="No referensi penarikan")
    description: Optional[str] = Field(None, max_length=255, description="Keterangan penarikan")

    @validator("amount")
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Nominal penarikan harus lebih besar dari 0")
        return v

    @validator("product_type")
    def validate_product_type(cls, v):
        if v:
            v = v.upper()
            if v not in ("POKOK", "WAJIB", "SUKARELA", "BERJANGKA"):
                raise ValueError("Jenis simpanan harus POKOK, WAJIB, atau SUKARELA")
        return v


# ============================================================================
# TRANSACTION RESPONSES
# ============================================================================

class SavingsTransactionOut(BaseModel):
    """Representasi entri buku besar (ledger) transaksi simpanan."""
    id: int
    transaction_no: str
    account_id: int
    member_id: Optional[int] = None
    member_no: Optional[str] = None
    member_name: Optional[str] = None
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    product_type: Optional[str] = None
    transaction_type: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    payment_channel: str
    reference_no: Optional[str] = None
    status: str
    description: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SavingsReceiptOut(BaseModel):
    """Bukti transaksi / struk resmi koperasi."""
    koperasi_name: str = "KSP AHNRFZI GRAHA"
    koperasi_address: str = "Komp. Perumahan AHNRFZI Graha No. 12, Jakarta"
    koperasi_phone: str = "(021) 8899-7766"
    
    transaction_no: str
    date: datetime
    cashier_name: str
    
    # Data Anggota
    member_id: int
    member_no: str
    member_name: str
    nik: str
    unit_divisi: Optional[str] = None
    jabatan: Optional[str] = None
    
    # Detail Transaksi
    account_no: str
    product_type: str
    product_name: str
    transaction_type: str
    amount: Decimal
    amount_terbilang: str
    balance_before: Decimal
    balance_after: Decimal
    
    payment_channel: str
    reference_no: Optional[str] = None
    description: Optional[str] = None
    status: str


class SavingsTransactionListResponse(BaseModel):
    """Respon riwayat transaksi berpaginasi."""
    items: List[SavingsTransactionOut]
    total: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_prev: bool


# ============================================================================
# ACCOUNT & SUMMARY SCHEMAS
# ============================================================================

class SavingsAccountOut(BaseModel):
    """Informasi rekening simpanan anggota dan verifikasi saldo ledger."""
    id: int
    member_id: int
    member_no: Optional[str] = None
    member_name: Optional[str] = None
    product_id: int
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    product_type: Optional[str] = None
    account_no: str
    balance: Decimal
    reconstructed_balance: Optional[Decimal] = None
    is_balance_valid: bool = True
    status: str
    allow_withdrawal: bool = True
    opened_date: datetime

    class Config:
        from_attributes = True


class SavingsAccountListResponse(BaseModel):
    """Daftar rekening simpanan berpaginasi."""
    items: List[SavingsAccountOut]
    total: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ProductBalanceItem(BaseModel):
    account_id: Optional[int] = None
    account_no: Optional[str] = None
    product_type: str
    product_name: str
    balance: Decimal = Decimal("0.00")
    allow_withdrawal: bool = False


class SavingsSummaryOut(BaseModel):
    """Ringkasan saldo anggota (Pokok, Wajib, Sukarela, Total Saldo)."""
    member_id: int
    member_no: str
    full_name: str
    nik: str
    status: str
    unit_divisi: Optional[str] = None
    jabatan: Optional[str] = None
    
    pokok: ProductBalanceItem
    wajib: ProductBalanceItem
    sukarela: ProductBalanceItem
    total_balance: Decimal

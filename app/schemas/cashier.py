from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal
from app.db.models.transaction import CashDirection, CashCategory


class CashTransactionCreate(BaseModel):
    direction: CashDirection = Field(..., description="Arah kas: CASH_IN (Masuk) atau CASH_OUT (Keluar)")
    category: CashCategory = Field(..., description="Kategori transaksi kas")
    amount: Decimal = Field(..., gt=0, description="Nominal transaksi wajib lebih besar dari 0")
    payment_method: str = Field("CASH", description="Metode pembayaran (CASH, BANK_TRANSFER, QRIS)")
    member_id: Optional[int] = Field(None, description="ID Anggota jika berkaitan dengan anggota")
    reference_no: Optional[str] = Field(None, description="Nomor referensi (No Rekening / No Pinjaman / Bukti Eksternal)")
    notes: Optional[str] = Field(None, description="Keterangan transaksi")


class CashReversalRequest(BaseModel):
    reason: str = Field(..., min_length=5, description="Alasan pembatalan/reversal transaksi kas")


class CashRegisterOpenRequest(BaseModel):
    opening_balance: Decimal = Field(Decimal("0.0"), ge=0, description="Modal kas awal shift")
    notes: Optional[str] = Field(None, description="Catatan pembukaan shift")


class CashRegisterCloseRequest(BaseModel):
    physical_balance: Decimal = Field(..., ge=0, description="Saldo fisik uang tunai di laci kasir")
    notes: Optional[str] = Field(None, description="Catatan penutupan shift / penjelasan selisih")


class CashTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_no: str
    receipt_no: str
    cash_register_id: Optional[int] = None
    cashier_user_id: int
    cashier_name: Optional[str] = None
    direction: str
    category: str
    category_label: Optional[str] = None
    amount: Decimal
    member_id: Optional[int] = None
    member_name: Optional[str] = None
    member_no: Optional[str] = None
    reference_no: Optional[str] = None
    payment_method: str
    notes: Optional[str] = None
    is_reversed: bool = False
    reversed_at: Optional[datetime] = None
    reversed_by_id: Optional[int] = None
    reversed_by_name: Optional[str] = None
    reversal_of_id: Optional[int] = None
    reversal_reason: Optional[str] = None
    created_at: datetime


class CashRegisterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cashier_user_id: int
    cashier_name: Optional[str] = None
    shift_date: date
    opening_balance: Decimal
    total_cash_in: Decimal
    total_cash_out: Decimal
    closing_balance: Decimal
    physical_balance: Optional[Decimal] = None
    discrepancy: Optional[Decimal] = None
    status: str
    opened_at: datetime
    closed_at: Optional[datetime] = None
    closed_by_name: Optional[str] = None
    notes: Optional[str] = None


class DailyRecapCategoryBreakdown(BaseModel):
    category: str
    category_name: str
    direction: str
    count: int
    total_amount: Decimal


class DailyRecapOut(BaseModel):
    date: date
    total_cash_in: Decimal
    total_cash_out: Decimal
    net_cash_flow: Decimal
    total_transactions: int
    categories: List[DailyRecapCategoryBreakdown]
    registers_open: int
    registers_closed: int


class CashReceiptOut(BaseModel):
    cooperative_name: str = "KOPERASI SIMPAN PINJAM AHNRFZI"
    legal_info: str = "AHU-0012948.AH.01.26.TAHUN 2026"
    receipt_no: str
    transaction_no: str
    transaction_date: str
    cashier_name: str
    member_name: Optional[str] = None
    member_no: Optional[str] = None
    direction: str
    category: str
    category_label: str
    amount: Decimal
    amount_formatted: str
    amount_terbilang: str
    payment_method: str
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    is_reversed: bool = False

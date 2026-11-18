from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field


class InstallmentPaymentRequest(BaseModel):
    installment_id: int = Field(..., description="ID Tagihan Angsuran yang akan dibayar")
    amount: Decimal = Field(..., gt=0, description="Nominal uang yang disetorkan/dibayar")
    payment_method: str = Field("CASHIER", description="Metode: CASHIER, BANK_TRANSFER, HRD_PAYROLL")
    notes: Optional[str] = Field(None, max_length=500, description="Catatan kasir / nomor referensi transfer")


class InstallmentItemOut(BaseModel):
    id: int
    installment_no: int
    loan_id: int
    loan_no: str
    member_id: int
    member_no: str
    member_name: str
    member_department: Optional[str] = None
    due_date: date
    principal_due: Decimal
    interest_due: Decimal
    penalty_due: Decimal
    total_due: Decimal
    principal_paid: Decimal
    interest_paid: Decimal
    penalty_paid: Decimal
    total_paid: Decimal
    remaining_due: Decimal
    status: str
    days_overdue: int
    paid_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LoanPaymentOut(BaseModel):
    id: int
    payment_no: str
    receipt_no: str
    loan_id: int
    loan_no: str
    installment_id: Optional[int] = None
    installment_no: Optional[int] = None
    member_id: int
    member_no: str
    member_name: str
    amount_paid: Decimal
    principal_portion: Decimal
    interest_portion: Decimal
    penalty_portion: Decimal
    payment_method: str
    received_by_user_id: Optional[int] = None
    received_by_name: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class InstallmentReceiptOut(BaseModel):
    receipt_no: str
    payment_no: str
    cash_transaction_no: Optional[str] = None
    cooperative_name: str = "KSP AHNRFZI"
    cooperative_address: str = "Gedung Pusat Koperasi Simpan Pinjam AHNRFZI"
    cooperative_phone: str = "(021) 7890-1234"
    payment_date: datetime
    
    loan_id: int
    loan_no: str
    product_name: str
    installment_id: int
    installment_no: int
    due_date: date
    
    member_id: int
    member_no: str
    member_name: str
    member_department: Optional[str] = None
    cashier_name: str
    
    amount_paid: Decimal
    amount_in_words: str
    principal_portion: Decimal
    interest_portion: Decimal
    penalty_portion: Decimal
    
    remaining_installment_due: Decimal
    remaining_loan_principal: Decimal
    installment_status_after: str
    loan_status_after: str
    payment_method: str
    notes: Optional[str] = None


class MemberInstallmentSummaryOut(BaseModel):
    total_active_loans: int
    total_outstanding_principal: Decimal
    total_outstanding_interest: Decimal
    total_due_this_month: Decimal
    total_overdue_amount: Decimal
    overdue_installments_count: int
    next_due_date: Optional[date] = None
    next_due_amount: Optional[Decimal] = None
    next_due_loan_no: Optional[str] = None

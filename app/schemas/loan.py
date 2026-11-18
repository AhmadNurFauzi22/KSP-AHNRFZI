from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field


class LoanProductOut(BaseModel):
    id: int
    code: str
    name: str
    min_amount: Decimal
    max_amount: Decimal
    min_tenor_months: int
    max_tenor_months: int
    annual_interest_rate: Decimal
    calculation_type: str
    admin_fee_percent: Decimal
    provision_fee_percent: Decimal
    penalty_rate_daily: Decimal
    require_collateral: bool
    description: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class LoanSimulationRequest(BaseModel):
    product_id: Optional[int] = None
    principal: Decimal = Field(..., gt=0, description="Nominal pinjaman yang disimulasikan")
    tenor_months: int = Field(..., ge=1, le=120, description="Durasi pinjaman dalam bulan")
    annual_interest_rate: Optional[Decimal] = Field(None, ge=0, le=100, description="Suku bunga tahunan (%)")
    calculation_type: Optional[str] = Field("FLAT", description="Metode bunga: FLAT, ANUITAS, SLIDING")
    admin_fee_percent: Optional[Decimal] = Field(None, ge=0, le=100, description="Biaya administrasi (%)")
    provision_fee_percent: Optional[Decimal] = Field(None, ge=0, le=100, description="Biaya provisi (%)")


class LoanSimulationInstallmentItem(BaseModel):
    installment_no: int
    due_month: int
    principal_portion: Decimal
    interest_portion: Decimal
    total_installment: Decimal
    remaining_principal: Decimal


class LoanSimulationResponse(BaseModel):
    principal: Decimal
    tenor_months: int
    annual_interest_rate: Decimal
    calculation_type: str
    monthly_principal: Decimal
    monthly_interest: Decimal
    monthly_installment_total: Decimal
    total_interest: Decimal
    total_payable: Decimal
    admin_fee: Decimal
    provision_fee: Decimal
    net_disbursement: Decimal
    schedule: List[LoanSimulationInstallmentItem]


class LoanCreateRequest(BaseModel):
    product_id: int = Field(..., description="ID Produk Pinjaman")
    requested_amount: Decimal = Field(..., gt=0, description="Nominal pengajuan pinjaman")
    tenor_months: int = Field(..., ge=1, le=120, description="Tenor pinjaman dalam bulan")
    purpose: str = Field(..., min_length=3, max_length=500, description="Tujuan pinjaman")
    collateral_info: Optional[str] = Field(None, max_length=500, description="Informasi jaminan/agunan jika ada")
    member_id: Optional[int] = Field(None, description="ID Anggota (khusus Admin/Manager yang menginputkan)")
    is_draft: bool = Field(False, description="True jika disimpan sebagai DRAFT, False langsung DIAJUKAN")


class LoanSubmitRequest(BaseModel):
    notes: Optional[str] = None


class LoanVerifyRequest(BaseModel):
    notes: Optional[str] = Field(None, description="Catatan hasil verifikasi berkas & kelayakan")


class LoanApproveRequest(BaseModel):
    approved_amount: Decimal = Field(..., gt=0, description="Plafon nominal pinjaman yang disetujui")
    notes: Optional[str] = Field(None, description="Catatan keputusan approval")


class LoanRejectRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500, description="Alasan penolakan pinjaman")


class LoanDisburseRequest(BaseModel):
    payment_method: str = Field("CASH", description="Metode pencairan: CASH, BANK_TRANSFER")
    notes: Optional[str] = Field(None, description="Catatan pencairan")


class LoanInstallmentOut(BaseModel):
    id: int
    installment_no: int
    due_date: date
    principal_due: Decimal
    interest_due: Decimal
    penalty_due: Decimal
    total_due: Decimal
    principal_paid: Decimal
    interest_paid: Decimal
    penalty_paid: Decimal
    total_paid: Decimal
    status: str
    paid_at: Optional[datetime] = None
    days_overdue: int

    class Config:
        from_attributes = True


class LoanApprovalOut(BaseModel):
    id: int
    stage: str
    decision: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    approved_amount: Optional[Decimal] = None
    notes: Optional[str] = None
    approver_user_id: int
    approver_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class LoanListItemOut(BaseModel):
    id: int
    loan_no: str
    member_id: int
    member_user_id: Optional[int] = None
    member_no: str
    member_name: str
    product_id: int
    product_code: str
    product_name: str
    requested_amount: Decimal
    approved_amount: Optional[Decimal] = None
    tenor_months: int
    interest_rate_percent: Decimal
    calculation_type: str
    monthly_installment_total: Decimal
    status: str
    created_at: datetime
    approved_at: Optional[datetime] = None
    approved_by_name: Optional[str] = None
    disbursed_at: Optional[datetime] = None


class LoanDetailOut(BaseModel):
    id: int
    loan_no: str
    member_id: int
    member_user_id: Optional[int] = None
    member_no: str
    member_name: str
    member_nik: Optional[str] = None
    member_phone: Optional[str] = None
    member_department: Optional[str] = None
    
    product_id: int
    product_code: str
    product_name: str
    
    requested_amount: Decimal
    approved_amount: Optional[Decimal] = None
    interest_rate_percent: Decimal
    tenor_months: int
    calculation_type: str
    
    admin_fee: Decimal
    provision_fee: Decimal
    net_disbursed_amount: Decimal
    
    monthly_principal: Decimal
    monthly_interest: Decimal
    monthly_installment_total: Decimal
    total_interest: Decimal
    total_payable: Decimal
    
    remaining_principal: Decimal
    remaining_interest: Decimal
    
    purpose: str
    collateral_info: Optional[str] = None
    status: str
    document_path: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    approved_by_user_id: Optional[int] = None
    approved_by_name: Optional[str] = None
    approved_at: Optional[datetime] = None
    
    disbursed_by_user_id: Optional[int] = None
    disbursed_by_name: Optional[str] = None
    disbursed_at: Optional[datetime] = None
    due_date: Optional[date] = None
    
    created_at: datetime
    updated_at: datetime
    
    approvals: List[LoanApprovalOut] = []
    installments: List[LoanInstallmentOut] = []

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class EmployeeCreate(BaseModel):
    nip: str = Field(..., min_length=3, max_length=50)
    full_name: str = Field(..., min_length=3, max_length=120)
    id_card_number: Optional[str] = Field(None, max_length=30)
    department: str = Field(..., min_length=2, max_length=100)
    position: str = Field(..., min_length=2, max_length=100)
    employment_status: str = Field("TETAP")
    base_salary: Decimal = Field(Decimal("0"), ge=0)
    allowances: Decimal = Field(Decimal("0"), ge=0)
    payroll_bank_name: Optional[str] = None
    payroll_bank_account: Optional[str] = None
    email_corporate: Optional[str] = None
    phone_number: Optional[str] = None
    hire_date: date = Field(...)
    user_id: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("employment_status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        allowed = {"TETAP", "KONTRAK", "PROBATION", "MAGANG", "RESIGNED"}
        up = (v or "").upper()
        if up not in allowed:
            raise ValueError(f"Status harus salah satu: {sorted(allowed)}")
        return up


class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=3, max_length=120)
    id_card_number: Optional[str] = Field(None, max_length=30)
    department: Optional[str] = Field(None, min_length=2, max_length=100)
    position: Optional[str] = Field(None, min_length=2, max_length=100)
    employment_status: Optional[str] = None
    base_salary: Optional[Decimal] = Field(None, ge=0)
    allowances: Optional[Decimal] = Field(None, ge=0)
    payroll_bank_name: Optional[str] = None
    payroll_bank_account: Optional[str] = None
    email_corporate: Optional[str] = None
    phone_number: Optional[str] = None
    hire_date: Optional[date] = None
    user_id: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("employment_status")
    @classmethod
    def _valid_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"TETAP", "KONTRAK", "PROBATION", "MAGANG", "RESIGNED"}
        up = v.upper()
        if up not in allowed:
            raise ValueError(f"Status harus salah satu: {sorted(allowed)}")
        return up


class EmployeeStatusChange(BaseModel):
    employment_status: Optional[str] = None
    resignation_date: Optional[date] = None
    notes: Optional[str] = None


class EmployeeOut(BaseModel):
    id: int
    nip: str
    full_name: str
    id_card_number: Optional[str] = None
    department: str
    position: str
    employment_status: str
    base_salary: Decimal
    allowances: Decimal
    total_income: Decimal
    payroll_bank_name: Optional[str] = None
    payroll_bank_account: Optional[str] = None
    email_corporate: Optional[str] = None
    phone_number: Optional[str] = None
    hire_date: date
    resignation_date: Optional[date] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    member_no: Optional[str] = None
    member_status: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EmployeeListResponse(BaseModel):
    metadata: dict
    summary: dict
    data: List[EmployeeOut]

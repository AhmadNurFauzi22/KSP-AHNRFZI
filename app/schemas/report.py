from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from decimal import Decimal


class ReportFilterParams(BaseModel):
    search: Optional[str] = None
    status: Optional[str] = None
    unit: Optional[str] = None
    product_id: Optional[int] = None
    direction: Optional[str] = None
    category: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    page: int = Field(1, ge=1)
    limit: int = Field(25, ge=1, le=500)
    export: Optional[str] = None  # "excel" or "pdf"


class ReportMetadata(BaseModel):
    report_name: str
    generated_at: str
    total_records: int
    current_page: int
    total_pages: int
    limit: int
    filter_applied: Dict[str, Any] = {}


class GenericReportResponse(BaseModel):
    metadata: ReportMetadata
    summary: Dict[str, Any] = {}
    data: List[Dict[str, Any]]

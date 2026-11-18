"""API Manajemen Kepegawaian (HRD) — KSP AHNRFZI (Prompt #10).

Memerlukan permission employee.view / employee.create / employee.update.
Semua operasi tercatat di audit log via employee_service.
"""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_permission
from app.db.models.user import User
from app.schemas.employee import (EmployeeCreate, EmployeeUpdate, EmployeeStatusChange,
                                  EmployeeOut, EmployeeListResponse)
from app.services import employee_service

router = APIRouter(prefix="/employees", tags=["Employees (HRD)"])


def _out(emp) -> dict:
    return employee_service._serialize(emp)


@router.get("", response_model=EmployeeListResponse)
def list_employees(search: Optional[str] = Query(None),
                   department: Optional[str] = Query(None),
                   position: Optional[str] = Query(None),
                   status_filter: Optional[str] = Query(None, alias="status"),
                   page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=200),
                   current_user: User = Depends(get_current_user),
                   authorized: bool = Depends(require_permission("employee.view")),
                   db: Session = Depends(get_db)):
    skip = (page - 1) * limit
    rows, total, summary = employee_service.list_employees(
        db, search=search, department=department, position=position,
        status_filter=status_filter, skip=skip, limit=limit)
    return {"metadata": {"total_records": total, "current_page": page,
                         "total_pages": (total + limit - 1) // limit if total else 1,
                         "limit": limit},
            "summary": summary, "data": rows}


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int,
                 current_user: User = Depends(get_current_user),
                 authorized: bool = Depends(require_permission("employee.view")),
                 db: Session = Depends(get_db)):
    return _out(employee_service.get_employee(db, employee_id))


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(payload: EmployeeCreate,
                    current_user: User = Depends(get_current_user),
                    authorized: bool = Depends(require_permission("employee.create")),
                    db: Session = Depends(get_db)):
    return _out(employee_service.create_employee(db, payload, current_user))


@router.put("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, payload: EmployeeUpdate,
                    current_user: User = Depends(get_current_user),
                    authorized: bool = Depends(require_permission("employee.update")),
                    db: Session = Depends(get_db)):
    return _out(employee_service.update_employee(db, employee_id, payload, current_user))


@router.patch("/{employee_id}/deactivate", response_model=EmployeeOut)
def deactivate_employee(employee_id: int, payload: EmployeeStatusChange,
                        current_user: User = Depends(get_current_user),
                        authorized: bool = Depends(require_permission("employee.update")),
                        db: Session = Depends(get_db)):
    return _out(employee_service.set_employee_active(
        db, employee_id, False, current_user,
        resignation_date=payload.resignation_date, notes=payload.notes))


@router.patch("/{employee_id}/activate", response_model=EmployeeOut)
def activate_employee(employee_id: int,
                       current_user: User = Depends(get_current_user),
                       authorized: bool = Depends(require_permission("employee.update")),
                       db: Session = Depends(get_db)):
    return _out(employee_service.set_employee_active(db, employee_id, True, current_user))

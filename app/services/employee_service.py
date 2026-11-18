"""Service manajemen kepegawaian (HRD) — KSP AHNRFZI (Prompt #10).

Memisahkan secara logis: User (login) vs Role (hak akses) vs
Employee (kepegawaian) vs Member (keanggotaan koperasi).
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple, List, Dict, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, desc

from app.db.models.employee import Employee, EmploymentStatus
from app.db.models.member import Member, MemberStatus
from app.db.models.user import User
from app.services.audit_service import AuditService

ACTIVE_EMPLOYMENT = {EmploymentStatus.TETAP.value, EmploymentStatus.KONTRAK.value,
                     EmploymentStatus.PROBATION.value, EmploymentStatus.MAGANG.value}


def _serialize(emp: Employee) -> Dict[str, Any]:
    return {
        "id": emp.id, "nip": emp.nip, "full_name": emp.full_name,
        "id_card_number": emp.id_card_number, "department": emp.department,
        "position": emp.position, "employment_status": emp.employment_status,
        "base_salary": emp.base_salary, "allowances": emp.allowances,
        "total_income": Decimal(str(emp.base_salary or 0)) + Decimal(str(emp.allowances or 0)),
        "payroll_bank_name": emp.payroll_bank_name,
        "payroll_bank_account": emp.payroll_bank_account,
        "email_corporate": emp.email_corporate, "phone_number": emp.phone_number,
        "hire_date": emp.hire_date, "resignation_date": emp.resignation_date,
        "user_id": emp.user_id,
        "username": emp.user.username if emp.user else None,
        "member_no": emp.member.member_no if emp.member else None,
        "member_status": emp.member.status if emp.member else None,
        "notes": emp.notes, "created_at": emp.created_at, "updated_at": emp.updated_at,
    }


def validate_employee_link(db: Session, employee_id: int) -> Employee:
    """Validasi keterkaitan pegawai -> anggota: pegawai harus ada & aktif.

    Dipakai oleh modul anggota agar pegawai nonaktif (RESIGNED) tidak dapat
    divalidasi/diproses sebagai anggota baru.
    """
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Data pegawai ID {employee_id} tidak ditemukan.")
    if emp.employment_status == EmploymentStatus.RESIGNED.value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Pegawai {emp.nip} berstatus nonaktif (RESIGNED) sehingga tidak dapat diproses sebagai anggota.")
    return emp


def list_employees(db: Session, search: Optional[str] = None,
                   department: Optional[str] = None, position: Optional[str] = None,
                   status_filter: Optional[str] = None,
                   skip: int = 0, limit: int = 25) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    q = db.query(Employee)
    if search:
        s = f"%{search}%"
        q = q.filter(or_(Employee.full_name.ilike(s), Employee.nip.ilike(s),
                         Employee.phone_number.ilike(s),
                         Employee.email_corporate.ilike(s)))
    if department:
        q = q.filter(Employee.department.ilike(f"%{department}%"))
    if position:
        q = q.filter(Employee.position.ilike(f"%{position}%"))
    if status_filter:
        q = q.filter(Employee.employment_status == status_filter.upper())
    total = q.count()
    rows = q.order_by(Employee.full_name.asc()).offset(skip).limit(limit).all()
    aktif = db.query(func.count(Employee.id)).filter(
        Employee.employment_status.in_(list(ACTIVE_EMPLOYMENT))).scalar() or 0
    return ([_serialize(e) for e in rows], total,
            {"total_pegawai": db.query(func.count(Employee.id)).scalar() or 0,
             "pegawai_aktif": aktif,
             "pegawai_nonaktif": (db.query(func.count(Employee.id)).scalar() or 0) - aktif})


def get_employee(db: Session, employee_id: int) -> Employee:
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Data pegawai ID {employee_id} tidak ditemukan.")
    return emp


def create_employee(db: Session, data, actor: User) -> Employee:
    if db.query(Employee).filter(Employee.nip == data.nip.strip()).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"NIP '{data.nip}' sudah terdaftar.")
    if data.id_card_number and db.query(Employee).filter(
            Employee.id_card_number == data.id_card_number.strip()).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="NIK KTP sudah terdaftar pada pegawai lain.")
    user = None
    if data.user_id:
        user = db.query(User).filter(User.id == data.user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Akun pengguna ID {data.user_id} tidak ditemukan.")
        if user.employee:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"Pengguna '{user.username}' sudah tertaut ke pegawai {user.employee.nip}.")
    emp = Employee(
        nip=data.nip.strip(), full_name=data.full_name.strip(),
        id_card_number=data.id_card_number.strip() if data.id_card_number else None,
        department=data.department.strip(), position=data.position.strip(),
        employment_status=(data.employment_status or "TETAP").upper(),
        base_salary=data.base_salary or Decimal("0"),
        allowances=data.allowances or Decimal("0"),
        payroll_bank_name=data.payroll_bank_name, payroll_bank_account=data.payroll_bank_account,
        email_corporate=data.email_corporate.lower().strip() if data.email_corporate else None,
        phone_number=data.phone_number, hire_date=data.hire_date,
        user_id=data.user_id, notes=data.notes,
    )
    db.add(emp)
    db.flush()
    AuditService.log_event(db, action="CREATE_EMPLOYEE", entity_name="Employee",
                           entity_id=str(emp.id), user_id=actor.id,
                           new_values={"nip": emp.nip, "nama": emp.full_name,
                                       "status": emp.employment_status},
                           notes=f"Pegawai {emp.nip} ({emp.full_name}) didaftarkan oleh {actor.username}")
    db.commit()
    db.refresh(emp)
    return emp


def update_employee(db: Session, employee_id: int, data, actor: User) -> Employee:
    emp = get_employee(db, employee_id)
    old = {"status": emp.employment_status, "department": emp.department,
           "position": emp.position}
    changes = data.dict(exclude_unset=True)
    # Prompt #11: whitelist anti mass-assignment. NIP immutable (tak ada di
    # schema); status kepegawaian hanya via endpoint activate/deactivate agar
    # resignation_date selalu tercatat.
    ALLOWED = {"full_name", "id_card_number", "department", "position",
               "base_salary", "allowances", "payroll_bank_name",
               "payroll_bank_account", "email_corporate", "phone_number",
               "hire_date", "user_id", "notes"}
    changes = {k: v for k, v in changes.items() if k in ALLOWED}
    if "id_card_number" in changes and changes["id_card_number"]:
        dup = db.query(Employee).filter(Employee.id_card_number == changes["id_card_number"].strip(),
                                         Employee.id != employee_id).first()
        if dup:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="NIK KTP sudah terdaftar pada pegawai lain.")
        changes["id_card_number"] = changes["id_card_number"].strip()
    if "user_id" in changes and changes["user_id"]:
        user = db.query(User).filter(User.id == changes["user_id"]).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"Akun pengguna ID {changes['user_id']} tidak ditemukan.")
        if user.employee and user.employee.id != employee_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"Pengguna '{user.username}' sudah tertaut ke pegawai lain.")
    if "email_corporate" in changes and changes["email_corporate"]:
        changes["email_corporate"] = changes["email_corporate"].lower().strip()
    for k, v in changes.items():
        if k == "employment_status" and v:
            v = v.upper()
        setattr(emp, k, v)
    emp.updated_at = datetime.now(timezone.utc)
    AuditService.log_event(db, action="UPDATE_EMPLOYEE", entity_name="Employee",
                           entity_id=str(emp.id), user_id=actor.id,
                           old_values=old,
                           new_values={k: str(getattr(emp, k)) for k in changes},
                           notes=f"Data pegawai {emp.nip} diubah oleh {actor.username}")
    db.commit()
    db.refresh(emp)
    return emp


def set_employee_active(db: Session, employee_id: int, active: bool, actor: User,
                        resignation_date: Optional[date] = None,
                        notes: Optional[str] = None) -> Employee:
    """Aktif/nonaktifkan pegawai. Nonaktif => status RESIGNED + tanggal resign."""
    emp = get_employee(db, employee_id)
    old_status = emp.employment_status
    if active:
        if emp.employment_status == EmploymentStatus.TETAP.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Pegawai {emp.nip} sudah berstatus aktif.")
        emp.employment_status = EmploymentStatus.TETAP.value
        emp.resignation_date = None
        action = "ACTIVATE_EMPLOYEE"
    else:
        if emp.employment_status == EmploymentStatus.RESIGNED.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Pegawai {emp.nip} sudah nonaktif.")
        emp.employment_status = EmploymentStatus.RESIGNED.value
        emp.resignation_date = resignation_date or date.today()
        if notes:
            emp.notes = ((emp.notes or "") + f"\n[Nonaktif] {notes}").strip()
        action = "DEACTIVATE_EMPLOYEE"
    emp.updated_at = datetime.now(timezone.utc)
    AuditService.log_event(db, action=action, entity_name="Employee",
                           entity_id=str(emp.id), user_id=actor.id,
                           old_values={"status": old_status},
                           new_values={"status": emp.employment_status},
                           notes=f"Pegawai {emp.nip} {old_status}->{emp.employment_status} oleh {actor.username}")
    # Prompt #13: nonaktif → beritahu HRD + akun tertaut (tanpa data sensitif)
    if not active:
        from app.services.notification_service import NotificationService as _HNS
        _HNS.notify_roles(db, ["HRD"],
                          title=f"Pegawai nonaktif: {emp.nip}",
                          message=f"Pegawai {emp.full_name} ({emp.nip}) dinonaktifkan oleh {actor.username}.",
                          ntype="WARNING", link_url="/employees",
                          entity_name="Employee", entity_id=str(emp.id),
                          event=f"EmployeeDeactivated:{emp.id}", actor_id=actor.id)
        if emp.user_id:
            _HNS.send(db, emp.user_id,
                      title="Status kepegawaian Anda berubah",
                      message=f"Status kepegawaian Anda ({emp.nip}) kini NONAKTIF.",
                      ntype="WARNING", link_url="/profile",
                      entity_name="Employee", entity_id=str(emp.id),
                      event=f"EmployeeDeactivatedSelf:{emp.id}", actor_id=actor.id)
    db.commit()
    db.refresh(emp)
    return emp

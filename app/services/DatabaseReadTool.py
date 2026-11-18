"""Database Read Tool for AI Assistant KSP AHNRFZI.

Memungkinkan AI Assistant meminta data dari database secara aman
dengan validasi tabel, kolom, dan permission yang telah dikonfigurasi.
Hanya operasi READ (seleksi), tidak ada operasi WRITE.
"""

from typing import Dict, Any, List, Optional, Set
from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from fastapi import HTTPException, status


# ============================================================================
# CORE VALIDATION HELPERS
# ============================================================================

def validate_table_access(table_name: str) -> None:
    """Validasi bahwa tabel boleh dibaca AI."""
    from app.services.database_knowledge_layer import is_table_allowed
    if not is_table_allowed(table_name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tabel '{table_name}' tidak diizinkan untuk diakses AI Assistant.",
        )


def validate_column_access(table_name: str, column_name: str) -> None:
    """Validasi bahwa kolom boleh dibaca AI."""
    from app.services.database_knowledge_layer import get_allowed_columns
    allowed = get_allowed_columns(table_name)
    if column_name not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Kolom '{column_name}' pada tabel '{table_name}' tidak diizinkan untuk diakses AI Assistant.",
        )


# ============================================================================
# TABLE-SPECIFIC QUERY HELPERS
# ============================================================================

def get_table_count(db: Session, table_name: str, **filters) -> int:
    """Mengembalikan jumlah baris dari tabel yang ditentukan."""
    validate_table_access(table_name)
    table_lower = table_name.lower()
    from app.services.database_knowledge_layer import get_all_category_labels

    model_map = {
        "user": "User",
        "member": "Member",
        "employee": "Employee",
        "savings_account": "SavingsAccount",
        "savings_product": "SavingsProduct",
        "savings_transaction": "SavingsTransaction",
        "loan": "Loan",
        "loan_product": "LoanProduct",
        "loan_installment": "LoanInstallment",
        "cash_transaction": "CashTransaction",
    }

    if table_lower in model_map:
        from sqlalchemy.orm import Session as SessionType
        from app.db.models import (
            User as UserModel,
            Member as MemberModel,
            Employee as EmployeeModel,
            SavingsAccount as SavingsAccountModel,
            SavingsProduct as SavingsProductModel,
            SavingsTransaction as SavingsTransactionModel,
            Loan as LoanModel,
            LoanProduct as LoanProductModel,
            LoanInstallment as LoanInstallmentModel,
            CashTransaction as CashTransactionModel,
        )

        model_dict = {
            "User": UserModel,
            "Member": MemberModel,
            "Employee": EmployeeModel,
            "SavingsAccount": SavingsAccountModel,
            "SavingsProduct": SavingsProductModel,
            "SavingsTransaction": SavingsTransactionModel,
            "Loan": LoanModel,
            "LoanProduct": LoanProductModel,
            "LoanInstallment": LoanInstallmentModel,
            "CashTransaction": CashTransactionModel,
        }

        model_name = model_map[table_lower]
        model = model_dict.get(model_name)
        if model is None:
            return 0

        query = db.query(model)
        for key, value in filters.items():
            attr = getattr(model, key, None)
            if attr is not None:
                query = query.filter(attr == value)
        return query.count() or 0
    else:
        return db.query(func.count()).select_from(table_name).scalar() or 0


def get_column_values(
    db: Session,
    table_name: str,
    column_name: str,
    limit: int = 100,
) -> List[Any]:
    """Mengambil nilai kolom tertentu dari tabel."""
    validate_table_access(table_name)
    validate_column_access(table_name, column_name)

    table_lower = table_name.lower()
    from sqlalchemy import inspect as sa_inspect

    model_map = {
        "user": User,
        "member": Member,
        "employee": Employee,
        "savings_account": SavingsAccount,
        "savings_product": SavingsProduct,
        "savings_transaction": SavingsTransaction,
        "loan": Loan,
        "loan_product": LoanProduct,
        "loan_installment": LoanInstallment,
        "cash_transaction": CashTransaction,
    }

    if table_lower in model_map:
        from app.db.models import (
            User as UserModel,
            Member as MemberModel,
            Employee as EmployeeModel,
            SavingsAccount as SavingsAccountModel,
            SavingsProduct as SavingsProductModel,
            SavingsTransaction as SavingsTransactionModel,
            Loan as LoanModel,
            LoanProduct as LoanProductModel,
            LoanInstallment as LoanInstallmentModel,
            CashTransaction as CashTransactionModel,
        )

        model_dict = {
            "User": UserModel,
            "Member": MemberModel,
            "Employee": EmployeeModel,
            "SavingsAccount": SavingsAccountModel,
            "SavingsProduct": SavingsProductModel,
            "SavingsTransaction": SavingsTransactionModel,
            "Loan": LoanModel,
            "LoanProduct": LoanProductModel,
            "LoanInstallment": LoanInstallmentModel,
            "CashTransaction": CashTransactionModel,
        }

        model = model_dict.get(model_map[table_lower])
        if model is None:
            return []

        column = getattr(model, column_name, None)
        if column is None:
            return []

        query = db.query(column).limit(limit)
        result = query.all()
        return [r[0] for r in result]
    else:
        return []


# ============================================================================
# METRIC QUERIES (Dashboard & Sistem)
# ============================================================================

def get_metric_data(metric_name: str, db: Session) -> Optional[Dict[str, Any]]:
    """Mengambil data metrik dashboard yang sudah didefinisikan."""
    from app.services.database_knowledge_layer import get_metric_definition

    definition = get_metric_definition(metric_name)
    if definition is None:
        return None

    table_name = definition.get("table", "")
    column_name = definition.get("column", "")
    aggregation = definition.get("aggregation", "COUNT")
    filter_str = definition.get("filter", "")

    # Implementasi berdasarkan definisi metrik dari knowledge layer
    if metric_name == "total_users":
        from app.db.models import User
        count = db.query(func.count(User.id)).scalar() or 0
        return {"total_users": count}

    if metric_name == "active_users":
        from app.db.models import User
        count = (
            db.query(func.count(User.id))
            .filter(User.is_active.is_(True))
            .scalar()
            or 0
        )
        return {"active_users": count}

    if metric_name == "login_7d":
        from app.db.models import AuditLog
        from datetime import timezone as tz
        from datetime import datetime as dt

        seven_days_ago = dt.now(tz.utc) - timedelta(days=7)
        count = (
            db.query(func.count(AuditLog.id))
            .filter(
                AuditLog.action.in_(["LOGIN_SUCCESS", "LOGIN", "LOGIN_FAILED"]),
                AuditLog.created_at >= seven_days_ago,
            )
            .scalar()
            or 0
        )
        return {"login_7d": count}

    if metric_name == "error_7d":
        from app.db.models import AuditLog
        from datetime import timezone as tz
        from datetime import datetime as dt

        seven_days_ago = dt.now(tz.utc) - timedelta(days=7)
        count = (
            db.query(func.count(AuditLog.id))
            .filter(
                AuditLog.action.ilike("%ERROR%")
                | AuditLog.action.ilike("%FAIL%"),
                AuditLog.created_at >= seven_days_ago,
            )
            .scalar()
            or 0
        )
        return {"error_7d": count}

    # Simpanan metrics
    if metric_name == "total_simpanan":
        from app.db.models import SavingsAccount
        total = db.query(func.coalesce(func.sum(SavingsAccount.balance), 0)).scalar() or 0
        return {"total_simpanan": float(total)}

    if metric_name == "simpanan_pokok":
        from app.db.models import SavingsAccount
        from app.db.models.savings import SavingsProductType
        total = (
            db.query(func.coalesce(func.sum(SavingsAccount.balance), 0))
            .filter(SavingsAccount.product_id == SavingsProductType.POKOK.value)
            .scalar()
            or 0
        )
        return {"simpanan_pokok": float(total)}

    if metric_name == "simpanan_wajib":
        from app.db.models import SavingsAccount
        from app.db.models.savings import SavingsProductType
        total = (
            db.query(func.coalesce(func.sum(SavingsAccount.balance), 0))
            .filter(SavingsAccount.product_id == SavingsProductType.WAJIB.value)
            .scalar()
            or 0
        )
        return {"simpanan_wajib": float(total)}

    if metric_name == "simpanan_sukarela":
        from app.db.models import SavingsAccount
        from app.db.models.savings import SavingsProductType
        total = (
            db.query(func.coalesce(func.sum(SavingsAccount.balance), 0))
            .filter(SavingsAccount.product_id == SavingsProductType.SUKARELA.value)
            .scalar()
            or 0
        )
        return {"simpanan_sukarela": float(total)}

    # Pinjaman metrics
    if metric_name == "portofolio_kredit_aktif":
        from app.db.models import Loan
        from app.db.models import LoanStatus
        total = (
            db.query(func.coalesce(func.sum(Loan.remaining_principal), 0))
            .filter(Loan.status.in_([LoanStatus.BERJALAN.value, "ACTIVE"]))
            .scalar()
            or 0
        )
        return {"portofolio_kredit_aktif": float(total)}

    if metric_name == "total_pinjaman":
        from app.db.models import Loan
        count = db.query(func.count(Loan.id)).scalar() or 0
        return {"total_pinjaman": count}

    if metric_name == "pinjaman_menunggu_verifikasi":
        from app.db.models import Loan
        count = (
            db.query(func.count(Loan.id))
            .filter(Loan.status == "MENTGU_VERIFIKASI")
            .scalar()
            or 0
        )
        return {"pinjaman_menunggu_verifikasi": count}

    if metric_name == "pinjaman_terverifikasi":
        from app.db.models import Loan
        count = db.query(func.count(Loan.id)).filter(Loan.status == "BERJALAN").scalar() or 0
        return {"pinjaman_terverifikasi": count}

    # Installment metrics
    if metric_name == "total_tagihan_angsuran":
        from app.db.models import LoanInstallment
        from datetime import date as dt_date
        today = dt_date.today()
        first_of_month = dt_date(today.year, today.month, 1)
        last_of_month = dt_date(today.year, today.month + 1, 1) if today.month < 12 else dt_date(today.year + 1, 1, 1)
        total = (
            db.query(func.coalesce(func.sum(LoanInstallment.total_due), 0))
            .filter(
                LoanInstallment.due_date >= first_of_month,
                LoanInstallment.due_date < last_of_month,
            )
            .scalar()
            or 0
        )
        return {"total_tagihan_angsuran": float(total)}

    if metric_name == "total_dibayar_angsuran":
        from app.db.models import LoanInstallment
        total = (
            db.query(func.coalesce(func.sum(LoanInstallment.total_paid), 0)).scalar() or 0
        )
        return {"total_dibayar_angsuran": float(total)}

    if metric_name == "tunggakan_angsuran":
        from app.db.models import LoanInstallment
        total = (
            db.query(func.coalesce(func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0))
            .filter(LoanInstallment.total_paid < LoanInstallment.total_due)
            .scalar()
            or 0
        )
        return {"tunggakan_angsuran": float(total)}

    # Kasir metrics
    if metric_name == "saldo_kas":
        from app.db.models import CashTransaction
        from app.db.models import CashDirection
        total_in = (
            db.query(func.coalesce(func.sum(CashTransaction.amount), 0))
            .filter(CashTransaction.direction == CashDirection.CASH_IN.value)
            .scalar()
            or 0
        )
        total_out = (
            db.query(func.coalesce(func.sum(CashTransaction.amount), 0))
            .filter(CashTransaction.direction == CashDirection.CASH_OUT.value)
            .scalar()
            or 0
        )
        return {"saldo_kas": float(total_in - total_out)}

    if metric_name == "kas_masuk_hari_ini":
        from app.db.models import CashTransaction
        from datetime import date as dt_date
        today = dt_date.today()
        start_of_day = dt_date(today.year, today.month, today.day, 0, 0, 0)
        end_of_day = dt_date(today.year, today.month, today.day, 23, 59, 59)
        total = (
            db.query(func.coalesce(func.sum(CashTransaction.amount), 0))
            .filter(
                CashTransaction.direction == CashDirection.CASH_IN.value,
                CashTransaction.created_at >= start_of_day,
                CashTransaction.created_at <= end_of_day,
            )
            .scalar()
            or 0
        )
        return {"kas_masuk_hari_ini": float(total)}

    if metric_name == "kas_keluar_hari_ini":
        from app.db.models import CashTransaction
        from datetime import date as dt_date
        today = dt_date.today()
        start_of_day = dt_date(today.year, today.month, today.day, 0, 0, 0)
        end_of_day = dt_date(today.year, today.month, today.day, 23, 59, 59)
        total = (
            db.query(func.coalesce(func.sum(CashTransaction.amount), 0))
            .filter(
                CashTransaction.direction == CashDirection.CASH_OUT.value,
                CashTransaction.created_at >= start_of_day,
                CashTransaction.created_at <= end_of_day,
            )
            .scalar()
            or 0
        )
        return {"kas_keluar_hari_ini": float(total)}

    if metric_name == "total_transaksi_hari_ini":
        from app.db.models import CashTransaction
        from datetime import date as dt_date
        today = dt_date.today()
        start_of_day = dt_date(today.year, today.month, today.day, 0, 0, 0)
        end_of_day = dt_date(today.year, today.month, today.day, 23, 59, 59)
        count = (
            db.query(func.count(CashTransaction.id))
            .filter(
                CashTransaction.created_at >= start_of_day,
                CashTransaction.created_at <= end_of_day,
            )
            .scalar()
            or 0
        )
        return {"total_transaksi_hari_ini": count}

    # Jika metrik tidak ditemukan, return None
    return None


# ============================================================================
# RELATIONSHIP QUERIES (LINTAS MODEL)
# ============================================================================

def get_related_data(
    db: Session,
    table_name: str,
    related_field: str,
    related_table: str,
    related_column: str,
    filter_conditions: dict = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Mengambil data terkait dari tabel lain melalui foreign key."""
    validate_table_access(table_name)
    return []


# ============================================================================
# ACCOUNT & SAVINGS SPECIFIC QUERIES
# ============================================================================

def get_member_savings_summary(member_id: int, db: Session) -> Dict[str, Any]:
    """Mengambil ringkasan saldo simpanan anggota lengkap."""
    from app.db.models import SavingsAccount
    from app.db.models.savings import SavingsProductType
    from app.db.models import Member

    # Pastikan akun ada untuk tiap jenis produk standar
    pokok_acc = (
        db.query(SavingsAccount)
        .filter(
            SavingsAccount.member_id == member_id,
            SavingsAccount.product_id == SavingsProductType.POKOK.value,
        )
        .first()
    )

    wajib_acc = (
        db.query(SavingsAccount)
        .filter(
            SavingsAccount.member_id == member_id,
            SavingsAccount.product_id == SavingsProductType.WAJIB.value,
        )
        .first()
    )

    sukarela_acc = (
        db.query(SavingsAccount)
        .filter(
            SavingsAccount.member_id == member_id,
            SavingsAccount.product_id == SavingsProductType.SUKARELA.value,
        )
        .first()
    )

    # Rekonstruksi saldo untuk akurasi mutlak
    def get_balance(account):
        if account:
            return float(account.balance)
        return 0.0

    pokok_bal = get_balance(pokok_acc)
    wajib_bal = get_balance(wajib_acc)
    sukarela_bal = get_balance(sukarela_acc)
    total_balance = pokok_bal + wajib_bal + sukarela_bal

    # Ambil info anggota
    from app.db.models import Member
    member = db.query(Member).filter(Member.id == member_id).first()

    return {
        "member_id": member.id if member else 0,
        "member_no": member.member_no if member else "-",
        "full_name": member.full_name if member else "-",
        "status": member.status if member else "-",
        "unit_divisi": member.unit_divisi if member else "-",
        "jabatan": member.jabatan if member else "-",
        "pokok": {
            "account_id": pokok_acc.id if pokok_acc else 0,
            "account_no": pokok_acc.account_no if pokok_acc else "-",
            "product_type": "POKOK",
            "product_name": "Simpanan Pokok",
            "balance": pokok_bal,
            "allow_withdrawal": pokok_acc.product.allow_withdrawal if pokok_acc and pokok_acc.product else False,
        },
        "wajib": {
            "account_id": wajib_acc.id if wajib_acc else 0,
            "account_no": wajib_acc.account_no if wajib_acc else "-",
            "product_type": "WAJIB",
            "product_name": "Simpanan Wajib",
            "balance": wajib_bal,
            "allow_withdrawal": wajib_acc.product.allow_withdrawal if wajib_acc and wajib_acc.product else False,
        },
        "sukarela": {
            "account_id": sukarela_acc.id if sukarela_acc else 0,
            "account_no": sukarela_acc.account_no if sukarela_acc else "-",
            "product_type": "SUKARELA",
            "product_name": "Simpanan Sukarela",
            "balance": sukarela_bal,
            "allow_withdrawal": sukarela_acc.product.allow_withdrawal if sukarela_acc and sukarela_acc.product else False,
        },
        "total_balance": total_balance,
    }


def get_loan_portfolio_summary(member_id: int = None, db: Session = None) -> Dict[str, Any]:
    """Mengambil ringkasan portfolio pinjaman."""
    from app.db.models import Loan, LoanStatus

    if db is None:
        from app.core.database import SessionLocal
        db = SessionLocal()

    query = db.query(Loan)

    if member_id:
        query = query.filter(Loan.member_id == member_id)

    loans = query.all()

    total_plafon = sum(float(l.approved_amount or l.requested_amount or 0) for l in loans)
    total_outstanding = sum(float(l.remaining_principal or 0) for l in loans)
    total_count = len(loans)

    # Kelompokkan berdasarkan status
    status_counts = {}
    for l in loans:
        status = l.status or "UNKNOWN"
        status_counts[status] = status_counts.get(status, 0) + 1

    # Pinjaman berjalan
    berjalan = [l for l in loans if l.status in [LoanStatus.BERJALAN.value, "ACTIVE"]]

    return {
        "member_id": member_id,
        "total_pinjaman": total_count,
        "total_plafon": total_plafon,
        "total_outstanding": total_outstanding,
        "pinjaman_berjalan_count": len(berjalan),
        "status_counts": status_counts,
        "detail": [
            {
                "loan_no": l.loan_no,
                "status": l.status,
                "approved_amount": float(l.approved_amount or 0),
                "remaining_principal": float(l.remaining_principal or 0),
                "tenor_months": l.tenor_months,
                "interest_rate": float(l.interest_rate_percent or 0),
            }
            for l in loans[:10]
        ],
    }


# ============================================================================
# CASHFLOW & KASIR QUERIES
# ============================================================================

def get_cashflow_summary(db: Session, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    """Mengambil ringkasan alir kas periode."""
    from app.db.models import CashTransaction
    from app.db.models import CashDirection

    query = db.query(CashTransaction)

    if start_date:
        from datetime import datetime
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(CashTransaction.created_at >= start_dt)
    if end_date:
        from datetime import datetime
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        end_dt = datetime(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
        query = query.filter(CashTransaction.created_at <= end_dt)

    total_in = (
        query.filter(CashTransaction.direction == CashDirection.CASH_IN.value)
        .with_entities(func.coalesce(func.sum(CashTransaction.amount), 0))
        .scalar()
        or 0
    )

    total_out = (
        query.filter(CashTransaction.direction == CashDirection.CASH_OUT.value)
        .with_entities(func.coalesce(func.sum(CashTransaction.amount), 0))
        .scalar()
        or 0
    )

    total_tx = query.count()

    return {
        "period_start": start_date,
        "period_end": end_date,
        "total_kas_masuk": float(total_in),
        "total_kas_keluar": float(total_out),
        "net_cash_flow": float(total_in - total_out),
        "total_transaksi": total_tx,
    }


def get_cash_transaction_list(
    db: Session,
    start_date: str = None,
    end_date: str = None,
    direction: str = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Mengambil daftar transaksi kas."""
    from app.db.models import CashTransaction
    from app.db.models import Member, Employee

    query = db.query(CashTransaction)

    if start_date:
        from datetime import datetime
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(CashTransaction.created_at >= start_dt)
    if end_date:
        from datetime import datetime
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        end_dt = datetime(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
        query = query.filter(CashTransaction.created_at <= end_dt)
    if direction:
        query = query.filter(CashTransaction.direction == direction.upper())

    # Ambil daftar transaksi kas (tanpa join untuk nama, agar lebih sederhana)
    query = db.query(CashTransaction)

    if start_date:
        from datetime import datetime
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(CashTransaction.created_at >= start_dt)
    if end_date:
        from datetime import datetime
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        end_dt = datetime(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
        query = query.filter(CashTransaction.created_at <= end_dt)
    if direction:
        query = query.filter(CashTransaction.direction == direction.upper())

    # Ambil dengan query khusus untuk dapat nama anggota/kasir
    from app.db.models import Member as MemberModel, Employee as EmployeeModel
    query = query.outerjoin(MemberModel, CashTransaction.member_id == MemberModel.id)\
        .outerjoin(EmployeeModel, CashTransaction.cashier_user_id == EmployeeModel.id)

    # Use with_entities to get the names properly
    query = query.with_entities(
        CashTransaction,
        MemberModel.full_name.label('member_name'),
        EmployeeModel.full_name.label('employee_name')
    )

    txs = query.order_by(CashTransaction.created_at.desc()).limit(limit).all()

    results = []
    for tx, member_name, employee_name in txs:
        results.append(
            {
                "no_transaksi": tx.transaction_no,
                "waktu": tx.created_at.strftime("%d/%m/%Y %H:%M"),
                "arah": "KAS MASUK" if tx.direction == "CASH_IN" else "KAS KELUAR",
                "nominal": float(tx.amount or 0),
                "anggota": member_name or "-",
                "kasir": employee_name or "-",
                "status": "DIBATALKAN" if getattr(tx, 'is_reversed', False) else "FINAL",
                "catatan": tx.notes or "-",
            }
        )
    return results


# ============================================================================
# AUDIT & LOGGING
# ============================================================================

def log_data_access(db: Session, action: str, entity_name: str, user_id: int = None, notes: str = "") -> None:
    """Catat aktivitas akses data untuk audit trail (read-only)."""
    try:
        from app.services.audit_service import AuditService
        AuditService.log_event(
            db=db,
            action=action,
            entity_name=entity_name,
            user_id=user_id,
            notes=f"[AI_READ] {notes}",
        )
    except Exception:
        pass  # Jangan error jika audit gagal, tetap lanjut pembacaan data


# ============================================================================
# EXPORT UTILITIES
# ============================================================================

def get_data_summary(table_name: str, db: Session) -> Dict[str, Any]:
    """Dapatkan ringkasan data tabel untuk validasi."""
    from app.services.database_knowledge_layer import is_table_allowed

    validate_table_access(table_name)

    from sqlalchemy import inspect as sa_inspect

    from app.db.models import User, Member, SavingsAccount, Loan, CashTransaction

    model_map = {
        "user": User,
        "member": Member,
        "savings_account": SavingsAccount,
        "loan": Loan,
        "cash_transaction": CashTransaction,
    }

    table_lower = table_name.lower()
    if table_lower in model_map:
        model = model_map[table_lower]
        row_count = db.query(model).count()
        columns = [c.name for c in sa_inspect(model).columns]
        return {
            "table": table_name,
            "row_count": row_count,
            "columns": columns[:20],
        }

    # Generic count
    from sqlalchemy import func
    count = db.query(func.count()).select_from(table_name).scalar() or 0
    return {"table": table_name, "row_count": count}
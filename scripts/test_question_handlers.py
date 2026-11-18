import sys, os
sys.path.insert(0, os.path.abspath("."))
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import func
from app.core.database import SessionLocal
from app.db.models.user import User
from app.db.models.member import Member
from app.db.models.employee import Employee
from app.db.models.loan import Loan, LoanInstallment, LoanPayment, LoanApproval
from app.db.models.savings import SavingsAccount, SavingsProduct, SavingsTransaction
from app.db.models.transaction import CashRegister, CashTransaction
from app.db.models.audit_log import AuditLog
from app.db.models.telegram import TelegramUserLink, TelegramDeliveryLog

db = SessionLocal()
now = datetime.now(timezone.utc)
today = now.date()
m_start = date(now.year, now.month, 1)

print("=== VERIFYING DATABASE QUERIES ===")
# B. Admin
print("Q11 all members:", db.query(Member).count())
print("Q12 active members:", db.query(Member).filter(Member.status.in_(['AKTIF', 'ACTIVE'])).count())
print("Q13 inactive members:", db.query(Member).filter(Member.status.in_(['NONAKTIF', 'INACTIVE', 'KELUAR', 'RESIGNED', 'SUSPENDED', 'CALON', 'PENDING'])).count())
print("Q14 new members this month:", db.query(Member).filter(Member.join_date >= m_start).count())
print("Q15 active loan members:", db.query(func.count(func.distinct(Loan.member_id))).filter(Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED', 'LANCAR', 'KURANG_LANCAR', 'DIRAGUKAN', 'MACET'])).scalar())
print("Q16 savings members:", db.query(func.count(func.distinct(SavingsAccount.member_id))).filter(SavingsAccount.balance > 0).scalar())
print("Q17 loan verification pending:", db.query(Loan).filter(Loan.status.in_(['DIAJUKAN', 'SUBMITTED', 'MENUNGGU_VERIFIKASI'])).count())
print("Q18 loan rejected this month:", db.query(Loan).filter(Loan.status.in_(['DITOLAK', 'REJECTED']), func.date(Loan.created_at) >= m_start).count())
print("Q19 total member savings:", db.query(func.coalesce(func.sum(SavingsAccount.balance), 0)).scalar())
print("Q20 incomplete member data:", db.query(Member).filter((Member.nik == None) | (Member.phone_number == None) | (Member.address == None)).count())
print("Q22 employees as members:", db.query(Employee).join(Member, (Employee.id == Member.employee_id) | (Employee.user_id == Member.user_id)).count())

# C. Ketua
print("Q24 outstanding loans:", db.query(func.coalesce(func.sum(Loan.remaining_principal), 0)).filter(Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED'])).scalar())
print("Q25 loans disbursed this month:", db.query(func.coalesce(func.sum(Loan.approved_amount), 0)).filter(Loan.status.in_(['DICAIRKAN', 'BERJALAN', 'ACTIVE', 'DISBURSED']), func.date(Loan.disbursed_at) >= m_start).scalar())
print("Q27 NPL loans count:", db.query(func.count(func.distinct(LoanInstallment.loan_id))).filter(LoanInstallment.status.in_(['BELUM_LUNAS', 'OVERDUE', 'TERLAMBAT']), LoanInstallment.due_date < today).scalar())
print("Q29 cash in this month:", db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(CashTransaction.direction == 'CASH_IN', CashTransaction.is_reversed == False, func.date(CashTransaction.created_at) >= m_start).scalar())
print("Q30 cash out this month:", db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(CashTransaction.direction == 'CASH_OUT', CashTransaction.is_reversed == False, func.date(CashTransaction.created_at) >= m_start).scalar())

# D. Manager
print("Q33 active loans:", db.query(Loan).filter(Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED'])).count())
print("Q34 loans pending approval:", db.query(Loan).filter(Loan.status.in_(['VERIFIKASI', 'VERIFIED_STAF', 'MENUNGGU_APPROVAL_MANAGER', 'MENUNGGU_APPROVAL_KETUA'])).count())
print("Q36 late installments:", db.query(LoanInstallment).filter(LoanInstallment.status.in_(['BELUM_LUNAS', 'OVERDUE', 'TERLAMBAT']), LoanInstallment.due_date < today).count())
print("Q40 delinquent members:", db.query(func.count(func.distinct(Loan.member_id))).join(LoanInstallment, Loan.id == LoanInstallment.loan_id).filter(LoanInstallment.due_date < today, LoanInstallment.status.in_(['BELUM_LUNAS', 'OVERDUE', 'TERLAMBAT'])).scalar())

# E. HRD
print("Q43 total employees:", db.query(Employee).count())
print("Q44 active employees:", db.query(Employee).filter(Employee.employment_status != 'RESIGNED').count())
print("Q45 inactive employees:", db.query(Employee).filter(Employee.employment_status == 'RESIGNED').count())
print("Q47 new employees this month:", db.query(Employee).filter(Employee.hire_date >= m_start).count())
print("Q50 incomplete employee data:", db.query(Employee).filter((Employee.id_card_number == None) | (Employee.payroll_bank_account == None)).count())

# F. Pengawas
print("Q55 trx today:", db.query(CashTransaction).filter(func.date(CashTransaction.created_at) == today).count())
print("Q56 reversals:", db.query(CashTransaction).filter((CashTransaction.is_reversed == True) | (CashTransaction.reversal_of_id.isnot(None)) | (CashTransaction.category == 'REVERSAL')).count())
print("Q57 loans through approval:", db.query(func.count(func.distinct(LoanApproval.loan_id))).scalar())
print("Q61 sensitive changes:", db.query(AuditLog).filter(AuditLog.action.in_(['UPDATE', 'DELETE', 'ROLE_CHANGE', 'PASSWORD_CHANGE'])).count())

# H. IT
print("Q77 telegram links:", db.query(TelegramUserLink).filter(TelegramUserLink.is_active == True).count())
print("Q78 telegram delivery failures:", db.query(TelegramDeliveryLog).filter(TelegramDeliveryLog.status == 'FAILED').count())

db.close()
print("=== ALL QUERIES EXECUTED SUCCESSFULLY ===")

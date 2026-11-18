import sys
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from app.core.database import engine, Base, SessionLocal
from app.core.security import get_password_hash
from app.core.permissions import SystemRole
from app.db.models import (
    User, Role, Permission,
    Employee, EmploymentStatus,
    Member, MemberStatus,
    SavingsProduct, SavingsProductType,
    SavingsAccount, SavingsTransaction, SavingsTransactionType, SavingsTransactionStatus,
    LoanProduct, LoanCalculationType,
    Loan, LoanStatus, LoanApproval, LoanInstallment, LoanPayment,
    CashRegister, CashTransaction, CashDirection, CashCategory,
    ChartOfAccount, AccountType, NormalBalance,
    JournalEntry, JournalLine,
    AuditLog, Notification
)

def seed_database():
    """Create all tables and seed comprehensive domain model data for KSP AHNRFZI."""
    print("[*] Rebuilding database schema & tables...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # =========================================================================
        # 1. PERMISSIONS (GRANULAR DOT-NOTATION)
        # =========================================================================
        print("[*] Seeding Granular Permissions...")
        permissions_data = [
            # Member Domain
            {"code": "member.view", "name": "Melihat Data Anggota", "module": "MEMBER", "desc": "Melihat detail profil anggota"},
            {"code": "member.create", "name": "Pendaftaran Anggota", "module": "MEMBER", "desc": "Mendaftarkan anggota baru"},
            {"code": "member.update", "name": "Ubah Data Anggota", "module": "MEMBER", "desc": "Mengubah biodata dan KYC anggota"},
            {"code": "member.view_all", "name": "Melihat Seluruh Anggota", "module": "MEMBER", "desc": "Akses data seluruh anggota (Non-IDOR)"},

            # Employee / HRD Domain (Prompt #10)
            {"code": "employee.view", "name": "Melihat Data Pegawai", "module": "HRD", "desc": "Melihat daftar dan detail pegawai"},
            {"code": "employee.create", "name": "Pendaftaran Pegawai", "module": "HRD", "desc": "Mendaftarkan pegawai baru"},
            {"code": "employee.update", "name": "Ubah Data Pegawai", "module": "HRD", "desc": "Mengubah, mengaktifkan/menonaktifkan pegawai"},
            
            # Savings Domain
            {"code": "saving.view", "name": "Melihat Simpanan", "module": "SAVING", "desc": "Melihat rekening dan saldo simpanan"},
            {"code": "saving.create", "name": "Buka Rekening Simpanan", "module": "SAVING", "desc": "Membuka produk simpanan baru"},
            {"code": "saving.transaction", "name": "Transaksi Simpanan", "module": "SAVING", "desc": "Setor/Tarik tabungan di kasir"},
            
            # Loan Domain
            {"code": "loan.view", "name": "Melihat Pinjaman", "module": "LOAN", "desc": "Melihat pengajuan dan portofolio pinjaman"},
            {"code": "loan.create", "name": "Pengajuan Pinjaman", "module": "LOAN", "desc": "Mengajukan permohonan pinjaman baru"},
            {"code": "loan.verify", "name": "Verifikasi Pinjaman", "module": "LOAN", "desc": "Verifikasi berkas & kelayakan oleh staf"},
            {"code": "loan.approve", "name": "Persetujuan Pinjaman", "module": "LOAN", "desc": "Persetujuan pinjaman oleh Manager/Ketua"},
            {"code": "loan.disburse", "name": "Pencairan Pinjaman", "module": "LOAN", "desc": "Pencairan dana kredit kepada anggota"},
            
            # Installment Domain
            {"code": "installment.view", "name": "Melihat Jadwal Angsuran", "module": "INSTALLMENT", "desc": "Melihat jadwal dan status cicilan"},
            {"code": "installment.payment", "name": "Pembayaran Angsuran", "module": "INSTALLMENT", "desc": "Input pembayaran cicilan pinjaman"},
            
            # Cashier Domain
            {"code": "cashier.view", "name": "Melihat Kasir", "module": "CASHIER", "desc": "Melihat status loket kasir"},
            {"code": "cashier.transaction", "name": "Transaksi Kasir", "module": "CASHIER", "desc": "Eksekusi transaksi kas loket"},
            {"code": "cashier.close", "name": "Tutup Buku Kasir", "module": "CASHIER", "desc": "Tutup shift dan rekonsiliasi kas"},
            
            # Report & Audit Domain
            {"code": "report.view", "name": "Melihat Laporan", "module": "REPORT", "desc": "Melihat laporan keuangan, neraca, SHU"},
            {"code": "audit.view", "name": "Melihat Audit Log", "module": "AUDIT", "desc": "Melihat riwayat aktivitas dan audit trail"},
            
            # User & System Domain
            {"code": "user.manage", "name": "Kelola Pengguna", "module": "SYSTEM", "desc": "Manajemen akun pengguna dan password"},
            {"code": "role.manage", "name": "Kelola Peran & Izin", "module": "SYSTEM", "desc": "Manajemen role dan mapping permission"},
            {"code": "system.manage", "name": "Konfigurasi Sistem", "module": "SYSTEM", "desc": "Pengaturan parameter sistem KSP"},
            
            # Profile & AI
            {"code": "profile.view", "name": "Melihat Profil", "module": "PROFILE", "desc": "Melihat profil akun sendiri"},
            {"code": "profile.update", "name": "Ubah Profil & Password", "module": "PROFILE", "desc": "Mengubah password dan profil mandiri"},
            {"code": "ai.assistant", "name": "Akses Asisten AI", "module": "AI", "desc": "Menggunakan asisten AI & credit scoring"},
        ]

        permission_map = {}
        for p_data in permissions_data:
            perm = db.query(Permission).filter(Permission.code == p_data["code"]).first()
            if not perm:
                perm = Permission(
                    code=p_data["code"],
                    name=p_data["name"],
                    module=p_data["module"],
                    description=p_data["desc"]
                )
                db.add(perm)
                db.flush()
            else:
                perm.name = p_data["name"]
                perm.module = p_data["module"]
                perm.description = p_data["desc"]
            permission_map[p_data["code"]] = perm

        # =========================================================================
        # 2. ROLES & ROLE-PERMISSIONS (9 ROLES)
        # =========================================================================
        print("[*] Seeding 9 System Roles & Mapping Permissions...")
        roles_data = [
            {
                "code": "ADMIN_KOPERASI",
                "name": "Admin Koperasi",
                "desc": "Administrator penuh sistem, RBAC, dan konfigurasi master data",
                "perms": list(permission_map.keys())
            },
            {
                "code": "KETUA_UMUM",
                "name": "Ketua Umum",
                "desc": "Pimpinan eksekutif koperasi, persetujuan pinjaman & pengesahan laporan SHU",
                "perms": [
                    "member.view", "member.view_all", "saving.view", "loan.view", "loan.approve", 
                    "installment.view", "report.view", "audit.view", "profile.view", "profile.update", "ai.assistant"
                ]
            },
            {
                "code": "MANAGER",
                "name": "Manager Koperasi",
                "desc": "Pengawas operasional harian, persetujuan kredit, dan rekap kas",
                "perms": [
                    "member.view", "member.create", "member.update", "member.view_all",
                    "employee.view",
                    "saving.view", "saving.create", "loan.view", "loan.verify", "loan.approve",
                    "installment.view", "cashier.view", "cashier.close", "report.view", "audit.view",
                    "profile.view", "profile.update", "ai.assistant"
                ]
            },
            {
                "code": "HRD",
                "name": "HRD Perusahaan",
                "desc": "Pengelola data kepegawaian AHNRFZI dan pemotongan gaji (payroll deduction)",
                "perms": [
                    "member.view", "member.create", "member.update", "member.view_all",
                    "employee.view", "employee.create", "employee.update",
                    "installment.view", "report.view", "profile.view", "profile.update", "ai.assistant"
                ]
            },
            {
                "code": "PENGAWAS_PEMBINA",
                "name": "Pengawas / Pembina",
                "desc": "Audit independen, verifikasi kepatuhan, review neraca keuangan dan SHU",
                "perms": [
                    "member.view", "member.view_all", "saving.view", "loan.view", "installment.view", 
                    "report.view", "audit.view", "profile.view", "profile.update", "ai.assistant"
                ]
            },
            {
                "code": "STAF",
                "name": "Staf Operasional",
                "desc": "Pelayanan pendaftaran anggota dan verifikasi berkas pinjaman",
                "perms": [
                    "member.view", "member.create", "member.update", "member.view_all",
                    "employee.view",
                    "saving.view", "loan.view", "loan.verify", "installment.view",
                    "profile.view", "profile.update", "ai.assistant"
                ]
            },
            {
                "code": "IT_PUSAT",
                "name": "IT Pusat",
                "desc": "Manajemen teknis sistem, keamanan, hak akses RBAC, dan audit trail",
                "perms": [
                    "user.manage", "role.manage", "system.manage", "audit.view", 
                    "profile.view", "profile.update", "ai.assistant"
                ]
            },
            {
                "code": "KASIR",
                "name": "Kasir Loket",
                "desc": "Petugas loket kas setor/tarik tunai, pencairan pinjaman, dan angsuran",
                "perms": [
                    "saving.view", "saving.transaction", "loan.view", "loan.disburse", 
                    "installment.view", "installment.payment", "cashier.view", "cashier.transaction", 
                    "cashier.close", "profile.view", "profile.update", "ai.assistant"
                ]
            },
            {
                "code": "ANGGOTA",
                "name": "Anggota Koperasi",
                "desc": "Portal mandiri anggota untuk cek saldo simpanan, pengajuan pinjaman, jadwal angsuran",
                "perms": [
                    "member.view", "saving.view", "loan.view", "loan.create", "installment.view", 
                    "profile.view", "profile.update", "ai.assistant"
                ]
            }
        ]

        role_map = {}
        for r_info in roles_data:
            role = db.query(Role).filter((Role.code == r_info["code"]) | (Role.name == r_info["name"])).first()
            if not role:
                role = Role(code=r_info["code"], name=r_info["name"], description=r_info["desc"], is_system_role=True)
                db.add(role)
                db.flush()
            else:
                role.code = r_info["code"]
                role.name = r_info["name"]
                role.description = r_info["desc"]
                db.flush()
            
            # Sync permissions
            role.permissions = [permission_map[p_code] for p_code in r_info["perms"] if p_code in permission_map]
            role_map[r_info["code"]] = role
            print(f"  + Role: {role.name} ({len(role.permissions)} permissions assigned)")

        # =========================================================================
        # 3. MASTER PRODUCTS (SAVINGS & LOANS)
        # =========================================================================
        print("[*] Seeding Savings & Loan Products...")
        sav_prods = [
            {"code": "PROD-POKOK", "name": "Simpanan Pokok", "type": SavingsProductType.POKOK.value, "min_init": 500000, "min_month": 0, "rate": 0.0, "allow_wd": False, "desc": "Simpanan awal pendaftaran anggota (sekali bayar)."},
            {"code": "PROD-WAJIB", "name": "Simpanan Wajib", "type": SavingsProductType.WAJIB.value, "min_init": 100000, "min_month": 100000, "rate": 0.0, "allow_wd": False, "desc": "Simpanan rutin bulanan anggota koperasi."},
            {"code": "PROD-SUKARELA", "name": "Simpanan Sukarela", "type": SavingsProductType.SUKARELA.value, "min_init": 50000, "min_month": 0, "rate": 3.5, "allow_wd": True, "desc": "Tabungan harian fleksibel dapat disetor dan ditarik sewaktu-waktu."},
            {"code": "PROD-BERJANGKA", "name": "Simpanan Berjangka (Deposito)", "type": SavingsProductType.BERJANGKA.value, "min_init": 5000000, "min_month": 0, "rate": 6.0, "allow_wd": False, "desc": "Deposito berjangka 12 bulan dengan imbal hasil optimal."}
        ]

        sav_prod_map = {}
        for sp in sav_prods:
            p = db.query(SavingsProduct).filter(SavingsProduct.code == sp["code"]).first()
            if not p:
                p = SavingsProduct(
                    code=sp["code"],
                    name=sp["name"],
                    product_type=sp["type"],
                    min_initial_deposit=Decimal(sp["min_init"]),
                    min_monthly_deposit=Decimal(sp["min_month"]),
                    annual_interest_rate=Decimal(sp["rate"]),
                    allow_withdrawal=sp["allow_wd"],
                    description=sp["desc"],
                    is_active=True
                )
                db.add(p)
                db.flush()
            sav_prod_map[sp["code"]] = p

        loan_prods = [
            {"code": "PINJ-REGULER", "name": "Pinjaman Reguler Anggota", "min_a": 1000000, "max_a": 50000000, "min_t": 6, "max_t": 36, "rate": 12.0, "calc": LoanCalculationType.FLAT.value, "admin": 1.0, "prov": 0.5},
            {"code": "PINJ-DARURAT", "name": "Pinjaman Kilat / Dana Darurat", "min_a": 500000, "max_a": 10000000, "min_t": 1, "max_t": 6, "rate": 6.0, "calc": LoanCalculationType.FLAT.value, "admin": 0.5, "prov": 0.0},
            {"code": "PINJ-KENDARAAN", "name": "Pinjaman Pengadaan Kendaraan", "min_a": 10000000, "max_a": 150000000, "min_t": 12, "max_t": 48, "rate": 10.0, "calc": LoanCalculationType.ANUITAS.value, "admin": 1.5, "prov": 1.0}
        ]

        loan_prod_map = {}
        for lp in loan_prods:
            p = db.query(LoanProduct).filter(LoanProduct.code == lp["code"]).first()
            if not p:
                p = LoanProduct(
                    code=lp["code"],
                    name=lp["name"],
                    min_amount=Decimal(lp["min_a"]),
                    max_amount=Decimal(lp["max_a"]),
                    min_tenor_months=lp["min_t"],
                    max_tenor_months=lp["max_t"],
                    annual_interest_rate=Decimal(lp["rate"]),
                    calculation_type=lp["calc"],
                    admin_fee_percent=Decimal(lp["admin"]),
                    provision_fee_percent=Decimal(lp["prov"]),
                    penalty_rate_daily=Decimal("0.1"),
                    is_active=True
                )
                db.add(p)
                db.flush()
            loan_prod_map[lp["code"]] = p

        # =========================================================================
        # 4. CHART OF ACCOUNTS (COA)
        # =========================================================================
        print("[*] Seeding Chart of Accounts (COA)...")
        coa_list = [
            {"code": "1101", "name": "Kas Loket Kasir", "type": AccountType.ASSET.value, "norm": NormalBalance.DEBIT.value},
            {"code": "1102", "name": "Bank Operasional Koperasi", "type": AccountType.ASSET.value, "norm": NormalBalance.DEBIT.value},
            {"code": "1201", "name": "Piutang Pinjaman Reguler", "type": AccountType.ASSET.value, "norm": NormalBalance.DEBIT.value},
            {"code": "1202", "name": "Piutang Pinjaman Darurat", "type": AccountType.ASSET.value, "norm": NormalBalance.DEBIT.value},
            {"code": "2101", "name": "Simpanan Sukarela Anggota", "type": AccountType.LIABILITY.value, "norm": NormalBalance.CREDIT.value},
            {"code": "2102", "name": "Simpanan Berjangka (Deposito)", "type": AccountType.LIABILITY.value, "norm": NormalBalance.CREDIT.value},
            {"code": "3101", "name": "Simpanan Pokok Anggota", "type": AccountType.EQUITY.value, "norm": NormalBalance.CREDIT.value},
            {"code": "3102", "name": "Simpanan Wajib Anggota", "type": AccountType.EQUITY.value, "norm": NormalBalance.CREDIT.value},
            {"code": "3201", "name": "Cadangan Modal & SHU Belum Dibagi", "type": AccountType.EQUITY.value, "norm": NormalBalance.CREDIT.value},
            {"code": "4101", "name": "Pendapatan Jasa Bunga Pinjaman", "type": AccountType.REVENUE.value, "norm": NormalBalance.CREDIT.value},
            {"code": "4102", "name": "Pendapatan Biaya Admin & Provisi", "type": AccountType.REVENUE.value, "norm": NormalBalance.CREDIT.value},
            {"code": "5101", "name": "Beban Operasional & Kantor", "type": AccountType.EXPENSE.value, "norm": NormalBalance.DEBIT.value},
            {"code": "5102", "name": "Beban Bunga Simpanan Sukarela/Deposito", "type": AccountType.EXPENSE.value, "norm": NormalBalance.DEBIT.value},
        ]

        coa_map = {}
        for coa in coa_list:
            acc = db.query(ChartOfAccount).filter(ChartOfAccount.code == coa["code"]).first()
            if not acc:
                acc = ChartOfAccount(
                    code=coa["code"],
                    name=coa["name"],
                    account_type=coa["type"],
                    normal_balance=coa["norm"],
                    is_active=True
                )
                db.add(acc)
                db.flush()
            coa_map[coa["code"]] = acc

        # =========================================================================
        # 5. EMPLOYEES, USERS, ROLES, AND MEMBERS (SEPARATE IDENTITY INTEGRATION)
        # =========================================================================
        print("[*] Seeding Employees, Users, Roles, and Cooperative Members...")
        default_pwd = get_password_hash("Password123!")

        personnel_data = [
            {
                "username": "admin",
                "email": "admin@ahnrfzi.co.id",
                "full_name": "Administrator Utama AHNRFZI",
                "phone": "081234567890",
                "roles": ["ADMIN_KOPERASI", "IT_PUSAT", "ANGGOTA"],
                "emp": {"nip": "EMP-001", "dept": "Direksi & TI", "pos": "Head of IT Systems", "salary": 18000000, "allowance": 4000000, "bank": "BCA", "acc": "1234567890"},
                "mem": {"no": "KSP-2026-0001", "nik": "3171010101900001", "sukarela": 5000000}
            },
            {
                "username": "ketua",
                "email": "ketua@ahnrfzi.co.id",
                "full_name": "H. Ahmad Fauzi",
                "phone": "081234567891",
                "roles": ["KETUA_UMUM", "ANGGOTA"],
                "emp": {"nip": "EMP-002", "dept": "Pengurus Koperasi", "pos": "Ketua KSP", "salary": 25000000, "allowance": 5000000, "bank": "Mandiri", "acc": "1234567891"},
                "mem": {"no": "KSP-2026-0002", "nik": "3171010101850002", "sukarela": 15000000}
            },
            {
                "username": "manager",
                "email": "manager@ahnrfzi.co.id",
                "full_name": "Budi Santoso, S.E.",
                "phone": "081234567892",
                "roles": ["MANAGER", "ANGGOTA"],
                "emp": {"nip": "EMP-003", "dept": "Operasional KSP", "pos": "General Manager", "salary": 15000000, "allowance": 3000000, "bank": "BNI", "acc": "1234567892"},
                "mem": {"no": "KSP-2026-0003", "nik": "3171010101880003", "sukarela": 8000000}
            },
            {
                "username": "hrd",
                "email": "hrd@ahnrfzi.co.id",
                "full_name": "Siti Rahmawati, S.Psi.",
                "phone": "081234567893",
                "roles": ["HRD", "ANGGOTA"],
                "emp": {"nip": "EMP-004", "dept": "Human Resources", "pos": "HR Specialist", "salary": 12000000, "allowance": 2500000, "bank": "BCA", "acc": "1234567893"},
                "mem": {"no": "KSP-2026-0004", "nik": "3171010101920004", "sukarela": 4500000}
            },
            {
                "username": "pengawas",
                "email": "pengawas@ahnrfzi.co.id",
                "full_name": "Drs. Hendra Wijaya, Ak.",
                "phone": "081234567894",
                "roles": ["PENGAWAS_PEMBINA", "ANGGOTA"],
                "emp": {"nip": "EMP-005", "dept": "Badan Pengawas", "pos": "Ketua Pengawas", "salary": 20000000, "allowance": 4000000, "bank": "Mandiri", "acc": "1234567894"},
                "mem": {"no": "KSP-2026-0005", "nik": "3171010101800005", "sukarela": 12000000}
            },
            {
                "username": "staf",
                "email": "staf@ahnrfzi.co.id",
                "full_name": "Rian Pratama",
                "phone": "081234567895",
                "roles": ["STAF", "ANGGOTA"],
                "emp": {"nip": "EMP-006", "dept": "Customer Service", "pos": "Front Office Officer", "salary": 7500000, "allowance": 1500000, "bank": "BRI", "acc": "1234567895"},
                "mem": {"no": "KSP-2026-0006", "nik": "3171010101950006", "sukarela": 2500000}
            },
            {
                "username": "itpusat",
                "email": "itpusat@ahnrfzi.co.id",
                "full_name": "Andi Kurniawan",
                "phone": "081234567896",
                "roles": ["IT_PUSAT", "ANGGOTA"],
                "emp": {"nip": "EMP-007", "dept": "Information Technology", "pos": "Infrastructure Specialist", "salary": 11000000, "allowance": 2000000, "bank": "BCA", "acc": "1234567896"},
                "mem": {"no": "KSP-2026-0007", "nik": "3171010101960007", "sukarela": 3000000}
            },
            {
                "username": "kasir",
                "email": "kasir@ahnrfzi.co.id",
                "full_name": "Dewi Lestari",
                "phone": "081234567897",
                "roles": ["KASIR", "ANGGOTA"],
                "emp": {"nip": "EMP-008", "dept": "Kasir & Perbendaharaan", "pos": "Head Teller", "salary": 6500000, "allowance": 1200000, "bank": "BCA", "acc": "1234567897"},
                "mem": {"no": "KSP-2026-0008", "nik": "3171010101970008", "sukarela": 2000000}
            },
            {
                "username": "anggota",
                "email": "anggota@ahnrfzi.co.id",
                "full_name": "Eko Prasetyo",
                "phone": "081234567898",
                "roles": ["ANGGOTA"],
                "emp": {"nip": "EMP-009", "dept": "Operasional Lapangan", "pos": "Field Specialist", "salary": 8000000, "allowance": 1800000, "bank": "BRI", "acc": "1234567898"},
                "mem": {"no": "KSP-2026-0009", "nik": "3171010101980009", "sukarela": 6500000}
            }
        ]

        created_users = {}
        created_members = {}

        for p_info in personnel_data:
            # A. Create or Update User Account
            user = db.query(User).filter(User.username == p_info["username"]).first()
            if not user:
                user = User(
                    username=p_info["username"],
                    email=p_info["email"],
                    hashed_password=default_pwd,
                    full_name=p_info["full_name"],
                    phone_number=p_info["phone"],
                    is_active=True,
                    is_verified=True
                )
                db.add(user)
                db.flush()
            else:
                user.email = p_info["email"]
                user.full_name = p_info["full_name"]
                user.phone_number = p_info["phone"]
                user.is_active = True
                user.hashed_password = default_pwd
            
            # Sync user roles
            user.roles = [role_map[r_code] for r_code in p_info["roles"] if r_code in role_map]
            db.flush()
            created_users[p_info["username"]] = user

            # B. Create Employee Record (HR)
            emp_info = p_info["emp"]
            employee = db.query(Employee).filter(Employee.nip == emp_info["nip"]).first()
            if not employee:
                employee = Employee(
                    user_id=user.id,
                    nip=emp_info["nip"],
                    full_name=user.full_name,
                    department=emp_info["dept"],
                    position=emp_info["pos"],
                    employment_status=EmploymentStatus.TETAP.value,
                    base_salary=Decimal(emp_info["salary"]),
                    allowances=Decimal(emp_info["allowance"]),
                    payroll_bank_name=emp_info["bank"],
                    payroll_bank_account=emp_info["acc"],
                    email_corporate=user.email,
                    phone_number=user.phone_number,
                    hire_date=date(2023, 1, 15)
                )
                db.add(employee)
                db.flush()
            else:
                employee.user_id = user.id

            # C. Create Cooperative Member Record (Member)
            mem_info = p_info["mem"]
            member = db.query(Member).filter(Member.member_no == mem_info["no"]).first()
            if not member:
                member = Member(
                    user_id=user.id,
                    employee_id=employee.id,
                    member_no=mem_info["no"],
                    nik=mem_info["nik"],
                    full_name=user.full_name,
                    gender="L" if "Siti" not in user.full_name and "Dewi" not in user.full_name else "P",
                    birth_place="Jakarta",
                    birth_date=date(1990, 5, 20),
                    address="Komp. Perumahan AHNRFZI Graha No. 12, Jakarta",
                    phone_number=user.phone_number,
                    email=user.email,
                    unit_divisi=emp_info["dept"],
                    jabatan=emp_info["pos"],
                    status="AKTIF",
                    join_date=date(2023, 2, 1)
                )
                db.add(member)
                db.flush()
            else:
                member.user_id = user.id
                member.employee_id = employee.id

            created_members[p_info["username"]] = member

            # D. Create Initial Savings Accounts for Member
            pokok_acc = db.query(SavingsAccount).filter(SavingsAccount.member_id == member.id, SavingsAccount.product_id == sav_prod_map["PROD-POKOK"].id).first()
            if not pokok_acc:
                pokok_acc = SavingsAccount(
                    member_id=member.id,
                    product_id=sav_prod_map["PROD-POKOK"].id,
                    account_no=f"SA-PKK-{member.member_no}",
                    balance=Decimal("500000.00"),
                    status="ACTIVE",
                    opened_date=datetime(2023, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
                )
                db.add(pokok_acc)
                db.flush()
                # Simpanan Pokok Transaction
                db.add(SavingsTransaction(
                    account_id=pokok_acc.id,
                    transaction_no=f"TRX-PKK-{member.member_no}",
                    transaction_type=SavingsTransactionType.DEPOSIT.value,
                    amount=Decimal("500000.00"),
                    balance_before=Decimal("0.00"),
                    balance_after=Decimal("500000.00"),
                    payment_channel="BANK_TRANSFER",
                    status=SavingsTransactionStatus.COMPLETED.value,
                    description="Setoran Simpanan Pokok Awal Keanggotaan"
                ))

            wajib_acc = db.query(SavingsAccount).filter(SavingsAccount.member_id == member.id, SavingsAccount.product_id == sav_prod_map["PROD-WAJIB"].id).first()
            if not wajib_acc:
                wajib_acc = SavingsAccount(
                    member_id=member.id,
                    product_id=sav_prod_map["PROD-WAJIB"].id,
                    account_no=f"SA-WJB-{member.member_no}",
                    balance=Decimal("1200000.00"), # 12 months x 100k
                    status="ACTIVE",
                    opened_date=datetime(2023, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
                )
                db.add(wajib_acc)
                db.flush()
                # Simpanan Wajib Transaction
                db.add(SavingsTransaction(
                    account_id=wajib_acc.id,
                    transaction_no=f"TRX-WJB-{member.member_no}",
                    transaction_type=SavingsTransactionType.DEPOSIT.value,
                    amount=Decimal("1200000.00"),
                    balance_before=Decimal("0.00"),
                    balance_after=Decimal("1200000.00"),
                    payment_channel="PAYROLL_DEDUCTION",
                    status=SavingsTransactionStatus.COMPLETED.value,
                    description="Akumulasi Simpanan Wajib Bulanan Payroll"
                ))

            sukarela_acc = db.query(SavingsAccount).filter(SavingsAccount.member_id == member.id, SavingsAccount.product_id == sav_prod_map["PROD-SUKARELA"].id).first()
            if not sukarela_acc:
                sukarela_balance = Decimal(str(mem_info["sukarela"]))
                sukarela_acc = SavingsAccount(
                    member_id=member.id,
                    product_id=sav_prod_map["PROD-SUKARELA"].id,
                    account_no=f"SA-SKR-{member.member_no}",
                    balance=sukarela_balance,
                    status="ACTIVE",
                    opened_date=datetime(2023, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
                )
                db.add(sukarela_acc)
                db.flush()
                db.add(SavingsTransaction(
                    account_id=sukarela_acc.id,
                    transaction_no=f"TRX-SKR-{member.member_no}",
                    transaction_type=SavingsTransactionType.DEPOSIT.value,
                    amount=sukarela_balance,
                    balance_before=Decimal("0.00"),
                    balance_after=sukarela_balance,
                    payment_channel="CASHIER_DESK",
                    status=SavingsTransactionStatus.COMPLETED.value,
                    description="Saldo Simpanan Sukarela Anggota"
                ))

        # =========================================================================
        # 6. SAMPLE ACTIVE LOAN & AMORTIZATION (EKO PRASETYO)
        # =========================================================================
        print("[*] Seeding Sample Loan, Approvals, and Installment Schedules...")
        eko_member = created_members["anggota"]
        sample_loan = db.query(Loan).filter(Loan.member_id == eko_member.id).first()
        if not sample_loan:
            principal = Decimal("24000000.00")
            rate = Decimal("12.0")
            tenor = 12
            monthly_prin = Decimal("2000000.00")
            monthly_int = Decimal("240000.00")
            monthly_inst = monthly_prin + monthly_int
            total_interest = monthly_int * Decimal(tenor)
            total_payable = principal + total_interest

            sample_loan = Loan(
                loan_no="LOAN-2026-0001",
                member_id=eko_member.id,
                product_id=loan_prod_map["PINJ-REGULER"].id,
                requested_amount=principal,
                approved_amount=principal,
                interest_rate_percent=rate,
                tenor_months=tenor,
                calculation_type=LoanCalculationType.FLAT.value,
                admin_fee=Decimal("240000.00"),
                provision_fee=Decimal("120000.00"),
                net_disbursed_amount=Decimal("23640000.00"),
                monthly_principal=monthly_prin,
                monthly_interest=monthly_int,
                monthly_installment_total=monthly_inst,
                total_interest=total_interest,
                total_payable=total_payable,
                remaining_principal=principal - (monthly_prin * Decimal("2")),
                remaining_interest=total_interest - (monthly_int * Decimal("2")),
                purpose="Renovasi Tempat Tinggal & Pendidikan",
                status=LoanStatus.ACTIVE.value,
                disbursed_at=datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
                disbursed_by_user_id=created_users["kasir"].id
            )
            db.add(sample_loan)
            db.flush()

            # Multi-tier Approvals Audit Trail
            db.add_all([
                LoanApproval(loan_id=sample_loan.id, approver_user_id=created_users["staf"].id, stage="STAF", decision="APPROVED", approved_amount=principal, notes="Berkas NIK, Slip Gaji, dan Rekomendasi HRD lengkap"),
                LoanApproval(loan_id=sample_loan.id, approver_user_id=created_users["manager"].id, stage="MANAGER", decision="APPROVED", approved_amount=principal, notes="Kapasitas DSR 28% aman, disetujui untuk diteruskan ke Ketua"),
                LoanApproval(loan_id=sample_loan.id, approver_user_id=created_users["ketua"].id, stage="KETUA_UMUM", decision="APPROVED", approved_amount=principal, notes="Disetujui pencairan dana pinjaman reguler")
            ])

            # Generate 12 Installment Schedules
            start_date = date(2026, 2, 10)
            for i in range(1, tenor + 1):
                due_d = start_date + timedelta(days=30 * (i - 1))
                is_paid = i <= 2 # First 2 installments already paid
                inst = LoanInstallment(
                    loan_id=sample_loan.id,
                    installment_no=i,
                    due_date=due_d,
                    principal_due=monthly_prin,
                    interest_due=monthly_int,
                    penalty_due=Decimal("0.0"),
                    total_due=monthly_inst,
                    principal_paid=monthly_prin if is_paid else Decimal("0.0"),
                    interest_paid=monthly_int if is_paid else Decimal("0.0"),
                    total_paid=monthly_inst if is_paid else Decimal("0.0"),
                    status="PAID" if is_paid else "UNPAID",
                    paid_at=datetime.combine(due_d, datetime.min.time(), tzinfo=timezone.utc) if is_paid else None
                )
                db.add(inst)
                db.flush()

                if is_paid:
                    db.add(LoanPayment(
                        payment_no=f"PAY-LOAN-2026{i:02d}-0001",
                        loan_id=sample_loan.id,
                        installment_id=inst.id,
                        member_id=eko_member.id,
                        amount_paid=monthly_inst,
                        principal_portion=monthly_prin,
                        interest_portion=monthly_int,
                        payment_method="HRD_PAYROLL",
                        receipt_no=f"RCP-PAY-2026{i:02d}-0001",
                        received_by_user_id=created_users["kasir"].id,
                        notes=f"Angsuran ke-{i} via Pemotongan Payroll HRD"
                    ))

        # =========================================================================
        # 7. CASH REGISTER & CASHIER DESK
        # =========================================================================
        print("[*] Seeding Cashier Shift & Cash Transactions...")
        kasir_user = created_users["kasir"]
        today = date.today()
        c_reg = db.query(CashRegister).filter(CashRegister.cashier_user_id == kasir_user.id, CashRegister.shift_date == today).first()
        if not c_reg:
            c_reg = CashRegister(
                cashier_user_id=kasir_user.id,
                shift_date=today,
                opening_balance=Decimal("10000000.00"),
                total_cash_in=Decimal("5500000.00"),
                total_cash_out=Decimal("1200000.00"),
                closing_balance=Decimal("14300000.00"),
                status="OPEN",
                notes="Shift Pagi Loket 1 KSP AHNRFZI"
            )
            db.add(c_reg)
            db.flush()

            # Cash Transaction Entry
            db.add(CashTransaction(
                transaction_no="TRX-CSH-20260828-0001",
                cash_register_id=c_reg.id,
                cashier_user_id=kasir_user.id,
                direction=CashDirection.CASH_IN.value,
                category=CashCategory.SAVINGS_DEPOSIT.value,
                amount=Decimal("500000.00"),
                member_id=eko_member.id,
                receipt_no="STRUK-20260828-0001",
                payment_method="CASH",
                notes="Setor Tunai Tabungan Sukarela via Loket"
            ))

        # =========================================================================
        # 8. ACCOUNTING DOUBLE-ENTRY JOURNAL DEMO
        # =========================================================================
        print("[*] Seeding Accounting Journal Entry...")
        j_entry = db.query(JournalEntry).filter(JournalEntry.entry_no == "JRN-20260828-0001").first()
        if not j_entry:
            j_entry = JournalEntry(
                entry_no="JRN-20260828-0001",
                entry_date=today,
                reference_no="TRX-CSH-20260828-0001",
                description="Penerimaan Setoran Kas Simpanan Sukarela Anggota",
                created_by_user_id=created_users["kasir"].id
            )
            db.add(j_entry)
            db.flush()

            # Debit: Kas Loket (1101) Rp 500.000
            db.add(JournalLine(
                journal_entry_id=j_entry.id,
                account_id=coa_map["1101"].id,
                debit=Decimal("500000.00"),
                credit=Decimal("0.00"),
                description="Kas Bertambah (Debit)"
            ))
            # Credit: Simpanan Sukarela (2101) Rp 500.000
            db.add(JournalLine(
                journal_entry_id=j_entry.id,
                account_id=coa_map["2101"].id,
                debit=Decimal("0.00"),
                credit=Decimal("500000.00"),
                description="Kewajiban Simpanan Bertambah (Credit)"
            ))

        # =========================================================================
        # 9. AUDIT LOG & NOTIFICATIONS
        # =========================================================================
        print("[*] Seeding Initial Audit Trail...")
        db.add(AuditLog(
            action="SCHEMA_SEED_COMPLETED",
            entity_name="Database",
            entity_id="DOMAIN_V2_FULL",
            notes="Domain models (Users, Roles, Permissions, Employees, Members, Savings, Loans, CoA, Cashier) seeded successfully",
            ip_address="127.0.0.1",
            user_agent="System Database CLI Seeder"
        ))

        db.add(Notification(
            user_id=created_users["admin"].id,
            title="Database Koperasi Siap",
            message="Seluruh entitas database dan modul finansial KSP AHNRFZI telah berhasil diinisialisasi.",
            type="SUCCESS",
            is_read=False
        ))

        db.commit()
        print("[+] Domain Model & Database Seeding Completed Successfully!")
    except Exception as e:
        db.rollback()
        print(f"[!] Error seeding database: {e}", file=sys.stderr)
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()

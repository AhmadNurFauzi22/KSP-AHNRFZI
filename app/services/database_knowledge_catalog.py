"""Database Knowledge Catalog KSP AHNRFZI.

Katalog otoritatif dan komprehensif seluruh skema database existing (22 tabel):
- Metadata tabel, kolom, tipe data, PK, FK, indeks
- Relasi antarentitas (1-to-N, N-to-1, M-to-M)
- Model ORM & status/enum
- Aturan bisnis & batasan operasional koperasi
- Rumus perhitungan finansial (Flat, Anuitas, Sliding, Biaya, Denda, DSR, Kas, SHU)
- Hubungan transaksi antar-modul (Pinjaman, Angsuran, Kasir, Simpanan, Jurnal Akuntansi)
- Pemetaan modul fungsional pemakai setiap tabel
"""

from typing import Dict, Any, List, Optional
import re


TABLE_CATALOG: Dict[str, Dict[str, Any]] = {
    "users": {
        "table_name": "users",
        "orm_model": "User",
        "title": "Pengguna Sistem & Otentikasi",
        "module": "SYSTEM",
        "description": "Menyimpan kredensial otentikasi login pengguna, hash password (bcrypt), profil akun, status aktif, status verifikasi email, dan metadata login terakhir.",
        "primary_key": ["id"],
        "foreign_keys": [],
        "relationships": [
            {"target": "roles", "type": "many-to-many", "via": "user_roles", "desc": "Peran yang dimiliki pengguna"},
            {"target": "employees", "type": "one-to-one", "fk": "employees.user_id", "desc": "Profil pegawai jika pengguna adalah karyawan AHNRFZI"},
            {"target": "members", "type": "one-to-one", "fk": "members.user_id", "desc": "Profil anggota jika pengguna adalah anggota koperasi"},
            {"target": "audit_logs", "type": "one-to-many", "fk": "audit_logs.user_id", "desc": "Aktivitas audit trail pengguna"},
            {"target": "notifications", "type": "one-to-many", "fk": "notifications.user_id", "desc": "Notifikasi yang diterima pengguna"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID unik pengguna (Auto-increment)"},
            {"name": "username", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Username unik untuk autentikasi login"},
            {"name": "email", "type": "VARCHAR(120)", "pk": False, "nullable": False, "desc": "Alamat email resmi pengguna"},
            {"name": "hashed_password", "type": "VARCHAR(255)", "pk": False, "nullable": False, "desc": "Hash password aman (bcrypt/passlib)"},
            {"name": "full_name", "type": "VARCHAR(120)", "pk": False, "nullable": False, "desc": "Nama lengkap pengguna sesuai identitas"},
            {"name": "phone_number", "type": "VARCHAR(25)", "pk": False, "nullable": True, "desc": "Nomor telepon/WhatsApp aktif"},
            {"name": "is_active", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Status aktif akun (True=aktif, False=terkunci)"},
            {"name": "is_verified", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Status verifikasi identitas akun"},
            {"name": "avatar_url", "type": "VARCHAR(255)", "pk": False, "nullable": True, "desc": "URL foto avatar profil"},
            {"name": "notif_email_enabled", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Preferensi notifikasi email"},
            {"name": "last_login_at", "type": "DATETIME", "pk": False, "nullable": True, "desc": "Timestamp login terakhir"},
            {"name": "last_login_ip", "type": "VARCHAR(45)", "pk": False, "nullable": True, "desc": "Alamat IP saat login terakhir"}
        ],
        "business_rules": [
            "Username dan email wajib unik di seluruh sistem.",
            "Pengguna non-aktif (is_active=False) dilarang login ke sistem.",
            "Superadmin memiliki akses penuh tanpa pembatasan role.",
            "Sesi pengguna diamankan dengan JWT (HS256) berekspirasi 480 menit."
        ]
    },
    "roles": {
        "table_name": "roles",
        "orm_model": "Role",
        "title": "Peran Pengguna (RBAC)",
        "module": "SYSTEM",
        "description": "Menyimpan 9 peran sistem KSP AHNRFZI yang membatasi hak akses pengguna secara bertingkat.",
        "primary_key": ["id"],
        "foreign_keys": [],
        "relationships": [
            {"target": "users", "type": "many-to-many", "via": "user_roles", "desc": "Pengguna dengan peran ini"},
            {"target": "permissions", "type": "many-to-many", "via": "role_permissions", "desc": "Izin granular yang dimiliki peran ini"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID peran"},
            {"name": "code", "type": "VARCHAR(40)", "pk": False, "nullable": False, "desc": "Kode unik peran (ADMIN_KOPERASI, KETUA_UMUM, MANAGER, HRD, PENGAWAS_PEMBINA, STAF, IT_PUSAT, KASIR, ANGGOTA)"},
            {"name": "name", "type": "VARCHAR(80)", "pk": False, "nullable": False, "desc": "Nama peran dalam Bahasa Indonesia"},
            {"name": "description", "type": "VARCHAR(255)", "pk": False, "nullable": True, "desc": "Deskripsi tanggung jawab peran"},
            {"name": "is_system_role", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Flag apakah peran baku bawaan sistem"}
        ],
        "business_rules": [
            "Peran sistem (is_system_role=True) tidak boleh dihapus sembarangan.",
            "Setiap peran dipetakan ke himpunan granular permissions melalui role_permissions.",
            "Seorang pengguna dapat memiliki lebih dari satu peran (dual-role context)."
        ]
    },
    "permissions": {
        "table_name": "permissions",
        "orm_model": "Permission",
        "title": "Izin Granular (Dot-Notation)",
        "module": "SYSTEM",
        "description": "Koleksi 28 izin spesifik berbasis domain modul (e.g. member.view, saving.transaction, loan.approve).",
        "primary_key": ["id"],
        "foreign_keys": [],
        "relationships": [
            {"target": "roles", "type": "many-to-many", "via": "role_permissions", "desc": "Peran yang memiliki izin ini"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID izin"},
            {"name": "code", "type": "VARCHAR(80)", "pk": False, "nullable": False, "desc": "Kode izin unik dengan format domain.aksi (mis. loan.disburse)"},
            {"name": "name", "type": "VARCHAR(100)", "pk": False, "nullable": False, "desc": "Nama izin deskriptif"},
            {"name": "module", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Domain modul (MEMBER, HRD, SAVING, LOAN, INSTALLMENT, CASHIER, REPORT, AUDIT, SYSTEM, AI)"},
            {"name": "description", "type": "VARCHAR(255)", "pk": False, "nullable": True, "desc": "Keterangan fungsi izin"}
        ],
        "business_rules": [
            "Pengecekan otoritas di API dilakukan dengan dependensi require_permission('kode.izin').",
            "ADMIN_KOPERASI memiliki bypass otomatis untuk seluruh izin."
        ]
    },
    "user_roles": {
        "table_name": "user_roles",
        "orm_model": "user_roles (Association Table)",
        "title": "Pemetaan Pengguna - Peran",
        "module": "SYSTEM",
        "description": "Tabel pivot many-to-many menghubungkan akun pengguna dengan peran yang diembannya.",
        "primary_key": ["user_id", "role_id"],
        "foreign_keys": [
            {"column": "user_id", "references": "users.id"},
            {"column": "role_id", "references": "roles.id"}
        ],
        "relationships": [],
        "columns": [
            {"name": "user_id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID pengguna"},
            {"name": "role_id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID peran"},
            {"name": "assigned_at", "type": "DATETIME", "pk": False, "nullable": False, "desc": "Waktu pemberian peran"}
        ],
        "business_rules": [
            "Kombinasi user_id dan role_id unik (composite primary key)."
        ]
    },
    "role_permissions": {
        "table_name": "role_permissions",
        "orm_model": "role_permissions (Association Table)",
        "title": "Pemetaan Peran - Izin",
        "module": "SYSTEM",
        "description": "Tabel pivot many-to-many menghubungkan peran dengan izin granular yang diberikan.",
        "primary_key": ["role_id", "permission_id"],
        "foreign_keys": [
            {"column": "role_id", "references": "roles.id"},
            {"column": "permission_id", "references": "permissions.id"}
        ],
        "relationships": [],
        "columns": [
            {"name": "role_id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID peran"},
            {"name": "permission_id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID izin"},
            {"name": "granted_at", "type": "DATETIME", "pk": False, "nullable": False, "desc": "Waktu pemberian izin"}
        ],
        "business_rules": [
            "Kombinasi role_id dan permission_id unik."
        ]
    },
    "employees": {
        "table_name": "employees",
        "orm_model": "Employee",
        "title": "Data Kepegawaian AHNRFZI",
        "module": "HRD",
        "description": "Menyimpan data master pegawai PT/KSP AHNRFZI, unit kerja/divisi, gaji pokok, tunjangan, dan nomor rekening payroll.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "users", "type": "one-to-one", "fk": "employees.user_id", "desc": "Akun login pegawai"},
            {"target": "members", "type": "one-to-one", "fk": "members.employee_id", "desc": "Profil anggota koperasi terkait"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID pegawai"},
            {"name": "user_id", "type": "INTEGER", "pk": False, "nullable": True, "desc": "ID akun login pengguna terkait"},
            {"name": "nip", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Nomor Induk Pegawai unik (mis. EMP-001)"},
            {"name": "full_name", "type": "VARCHAR(120)", "pk": False, "nullable": False, "desc": "Nama lengkap pegawai"},
            {"name": "id_card_number", "type": "VARCHAR(30)", "pk": False, "nullable": True, "desc": "Nomor NIK KTP"},
            {"name": "department", "type": "VARCHAR(100)", "pk": False, "nullable": False, "desc": "Divisi/Unit kerja (Direksi & TI, Pengurus, HRD, dll)"},
            {"name": "position", "type": "VARCHAR(100)", "pk": False, "nullable": False, "desc": "Jabatan struktural/fungsional"},
            {"name": "employment_status", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Status kerja: TETAP, KONTRAK, PROBATION, MAGANG, RESIGNED"},
            {"name": "base_salary", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Gaji pokok bulanan untuk dasar DSR pinjaman"},
            {"name": "allowances", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Tunjangan tetap bulanan"},
            {"name": "payroll_bank_name", "type": "VARCHAR(50)", "pk": False, "nullable": True, "desc": "Nama bank transfer gaji (BCA, Mandiri, BNI, dll)"},
            {"name": "payroll_bank_account", "type": "VARCHAR(50)", "pk": False, "nullable": True, "desc": "Nomor rekening bank transfer gaji"},
            {"name": "hire_date", "type": "DATE", "pk": False, "nullable": False, "desc": "Tanggal mulai bekerja"},
            {"name": "resignation_date", "type": "DATE", "pk": False, "nullable": True, "desc": "Tanggal berhenti kerja jika RESIGNED"}
        ],
        "business_rules": [
            "Pegawai berstatus RESIGNED tidak dapat diajukan pinjaman baru.",
            "Total pendapatan (base_salary + allowances) menjadi batas plafon simulasi DSR kredit (maksimal cicilan 30-40% gaji).",
            "Pemotongan angsuran dan simpanan wajib dapat dilakukan via payroll deduction HRD."
        ]
    },
    "members": {
        "table_name": "members",
        "orm_model": "Member",
        "title": "Master Anggota Koperasi",
        "module": "MEMBER",
        "description": "Menyimpan data induk keanggotaan KSP AHNRFZI, NIK KTP, kontak darurat, unit kerja, jabatan, dan status keanggotaan.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "user_id", "references": "users.id"},
            {"column": "employee_id", "references": "employees.id"}
        ],
        "relationships": [
            {"target": "users", "type": "one-to-one", "fk": "members.user_id", "desc": "Akun login anggota"},
            {"target": "employees", "type": "one-to-one", "fk": "members.employee_id", "desc": "Data pegawai AHNRFZI"},
            {"target": "savings_accounts", "type": "one-to-many", "fk": "savings_accounts.member_id", "desc": "Buku rekening simpanan milik anggota"},
            {"target": "loans", "type": "one-to-many", "fk": "loans.member_id", "desc": "Daftar pinjaman milik anggota"},
            {"target": "cash_transactions", "type": "one-to-many", "fk": "cash_transactions.member_id", "desc": "Transaksi kas anggota di loket"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID anggota"},
            {"name": "user_id", "type": "INTEGER", "pk": False, "nullable": True, "desc": "ID akun login pengguna terkait"},
            {"name": "employee_id", "type": "INTEGER", "pk": False, "nullable": True, "desc": "ID pegawai terkait"},
            {"name": "member_no", "type": "VARCHAR(40)", "pk": False, "nullable": False, "desc": "Nomor register anggota unik (KSP-2026-XXXX)"},
            {"name": "nik", "type": "VARCHAR(25)", "pk": False, "nullable": False, "desc": "Nomor Induk Kependudukan (16 digit unik)"},
            {"name": "full_name", "type": "VARCHAR(120)", "pk": False, "nullable": False, "desc": "Nama lengkap sesuai KTP"},
            {"name": "gender", "type": "VARCHAR(10)", "pk": False, "nullable": True, "desc": "Jenis kelamin: L / P"},
            {"name": "birth_date", "type": "DATE", "pk": False, "nullable": True, "desc": "Tanggal lahir"},
            {"name": "address", "type": "TEXT", "pk": False, "nullable": True, "desc": "Alamat domisili"},
            {"name": "phone_number", "type": "VARCHAR(25)", "pk": False, "nullable": False, "desc": "Nomor telepon aktif"},
            {"name": "unit_divisi", "type": "VARCHAR(100)", "pk": False, "nullable": True, "desc": "Unit/divisi penempatan kerja"},
            {"name": "jabatan", "type": "VARCHAR(100)", "pk": False, "nullable": True, "desc": "Jabatan di organisasi"},
            {"name": "status", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Status keanggotaan: CALON, AKTIF, NONAKTIF, KELUAR"},
            {"name": "join_date", "type": "DATE", "pk": False, "nullable": False, "desc": "Tanggal resmi menjadi anggota"}
        ],
        "business_rules": [
            "Hanya anggota berstatus AKTIF yang berhak mengajukan pinjaman dan membuka rekening simpanan.",
            "Setiap anggota baru diwajibkan menyetor Simpanan Pokok (Rp 500.000) saat pendaftaran.",
            "Anggota berhak atas bagian SHU pada RAT berdasarkan partisipasi modal dan transaksi.",
            "Data anggota diproteksi oleh kebijakan data isolation: Anggota biasa hanya dapat melihat profil miliknya sendiri."
        ]
    },
    "savings_products": {
        "table_name": "savings_products",
        "orm_model": "SavingsProduct",
        "title": "Master Produk Simpanan",
        "module": "SAVING",
        "description": "Menyimpan konfigurasi 4 produk simpanan: Pokok, Wajib, Sukarela, dan Berjangka (Deposito).",
        "primary_key": ["id"],
        "foreign_keys": [],
        "relationships": [
            {"target": "savings_accounts", "type": "one-to-many", "fk": "savings_accounts.product_id", "desc": "Rekening yang menggunakan produk ini"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID produk simpanan"},
            {"name": "code", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Kode produk (PROD-POKOK, PROD-WAJIB, PROD-SUKARELA, PROD-BERJANGKA)"},
            {"name": "name", "type": "VARCHAR(100)", "pk": False, "nullable": False, "desc": "Nama produk simpanan"},
            {"name": "product_type", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Jenis simpanan: POKOK, WAJIB, SUKARELA, BERJANGKA"},
            {"name": "min_initial_deposit", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Setoran awal minimal"},
            {"name": "min_monthly_deposit", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Setoran rutin bulanan minimal (mis. Wajib Rp 100.000)"},
            {"name": "annual_interest_rate", "type": "NUMERIC(6, 3)", "pk": False, "nullable": False, "desc": "Suku bunga/imbal hasil per tahun (%)"},
            {"name": "allow_withdrawal", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Apakah boleh ditarik sewaktu-waktu (True hanya untuk Sukarela)"},
            {"name": "is_active", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Status aktif produk"}
        ],
        "business_rules": [
            "Simpanan Pokok (Rp 500.000) dan Wajib (Rp 100.000/bln) tidak dapat ditarik selama anggota masih aktif.",
            "Simpanan Sukarela bebas disetor dan ditarik kapan saja melalui loket kasir dengan saldo cukup.",
            "Simpanan Berjangka memiliki tenor tertentu dan hanya dapat dicairkan saat jatuh tempo."
        ]
    },
    "savings_accounts": {
        "table_name": "savings_accounts",
        "orm_model": "SavingsAccount",
        "title": "Buku Rekening Simpanan Anggota",
        "module": "SAVING",
        "description": "Menyimpan rekening tabungan per anggota per jenis produk, saldo terkini, dan status rekening.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "member_id", "references": "members.id"},
            {"column": "product_id", "references": "savings_products.id"}
        ],
        "relationships": [
            {"target": "members", "type": "many-to-one", "fk": "savings_accounts.member_id", "desc": "Anggota pemilik rekening"},
            {"target": "savings_products", "type": "many-to-one", "fk": "savings_accounts.product_id", "desc": "Produk simpanan terkait"},
            {"target": "savings_transactions", "type": "one-to-many", "fk": "savings_transactions.account_id", "desc": "Riwayat mutasi pembukuan rekening"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID rekening"},
            {"name": "member_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID anggota pemilik"},
            {"name": "product_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID produk simpanan"},
            {"name": "account_no", "type": "VARCHAR(40)", "pk": False, "nullable": False, "desc": "Nomor rekening unik (SAV-POK-*, SAV-WAJ-*, SAV-SUK-*)"},
            {"name": "balance", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Saldo terkini rekening"},
            {"name": "status", "type": "VARCHAR(25)", "pk": False, "nullable": False, "desc": "Status rekening: ACTIVE, DORMANT, BLOCKED, CLOSED"},
            {"name": "opened_date", "type": "DATETIME", "pk": False, "nullable": False, "desc": "Waktu pembukaan rekening"}
        ],
        "business_rules": [
            "Saldo rekening tidak boleh negatif.",
            "Saldo selalu dapat direkonstruksi dari seluruh transaksi berstatus COMPLETED.",
            "Penarikan hanya diizinkan bila saldo mencukupi dan produk mengizinkan (allow_withdrawal=True)."
        ]
    },
    "savings_transactions": {
        "table_name": "savings_transactions",
        "orm_model": "SavingsTransaction",
        "title": "Buku Besar Transaksi Simpanan",
        "module": "SAVING",
        "description": "Mencatat setiap mutasi setoran, penarikan, bunga simpanan, dan biaya administrasi rekening.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "account_id", "references": "savings_accounts.id"},
            {"column": "created_by_user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "savings_accounts", "type": "many-to-one", "fk": "savings_transactions.account_id", "desc": "Rekening yang dimutasi"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID mutasi"},
            {"name": "account_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID rekening simpanan"},
            {"name": "transaction_no", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Nomor transaksi unik"},
            {"name": "transaction_type", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Jenis mutasi: SETOR, TARIK, DEPOSIT, WITHDRAWAL, INTEREST, FEE, TRANSFER_IN, TRANSFER_OUT"},
            {"name": "amount", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Nominal mutasi"},
            {"name": "balance_before", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Saldo sebelum mutasi"},
            {"name": "balance_after", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Saldo setelah mutasi"},
            {"name": "payment_channel", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Kanal pembayaran (CASH, BANK, PAYROLL)"},
            {"name": "status", "type": "VARCHAR(20)", "pk": False, "nullable": False, "desc": "Status mutasi: COMPLETED, PENDING, REVERSED"},
            {"name": "created_at", "type": "DATETIME", "pk": False, "nullable": False, "desc": "Waktu eksekusi mutasi"}
        ],
        "business_rules": [
            "Setiap mutasi simpanan tunai di loket kasir wajib berpasangan dengan catatan di cash_transactions.",
            "Balance before dan balance after wajib konsisten matematis: balance_after = balance_before + amount (untuk kredit) atau balance_before - amount (untuk debit)."
        ]
    },
    "loan_products": {
        "table_name": "loan_products",
        "orm_model": "LoanProduct",
        "title": "Master Produk Pinjaman Koperasi",
        "module": "LOAN",
        "description": "Menyimpan konfigurasi 3 produk pinjaman: Reguler, Darurat/Kilat, dan Kendaraan.",
        "primary_key": ["id"],
        "foreign_keys": [],
        "relationships": [
            {"target": "loans", "type": "one-to-many", "fk": "loans.product_id", "desc": "Pinjaman yang menggunakan produk ini"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID produk pinjaman"},
            {"name": "code", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Kode produk: PINJ-REGULER, PINJ-DARURAT, PINJ-KENDARAAN"},
            {"name": "name", "type": "VARCHAR(100)", "pk": False, "nullable": False, "desc": "Nama produk kredit"},
            {"name": "min_amount", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Plafon minimal pinjaman"},
            {"name": "max_amount", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Plafon maksimal pinjaman"},
            {"name": "min_tenor_months", "type": "INTEGER", "pk": False, "nullable": False, "desc": "Tenor minimal (bulan)"},
            {"name": "max_tenor_months", "type": "INTEGER", "pk": False, "nullable": False, "desc": "Tenor maksimal (bulan)"},
            {"name": "annual_interest_rate", "type": "NUMERIC(6, 3)", "pk": False, "nullable": False, "desc": "Suku bunga per tahun (%)"},
            {"name": "calculation_type", "type": "VARCHAR(20)", "pk": False, "nullable": False, "desc": "Metode bunga: FLAT, ANUITAS, SLIDING"},
            {"name": "admin_fee_percent", "type": "NUMERIC(5, 2)", "pk": False, "nullable": False, "desc": "Biaya administrasi (%) dipotong saat pencairan"},
            {"name": "provision_fee_percent", "type": "NUMERIC(5, 2)", "pk": False, "nullable": False, "desc": "Biaya provisi (%) dipotong saat pencairan"},
            {"name": "penalty_rate_daily", "type": "NUMERIC(5, 3)", "pk": False, "nullable": False, "desc": "Denda keterlambatan harian (%)"},
            {"name": "require_collateral", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Apakah membutuhkan agunan (mis. Kendaraan)"},
            {"name": "is_active", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Status aktif produk"}
        ],
        "business_rules": [
            "Pinjaman Reguler: Plafon Rp 1jt - 50jt, tenor 6-36 bulan, bunga 12% Flat.",
            "Pinjaman Darurat: Plafon Rp 500rb - 10jt, tenor 1-6 bulan, bunga 6% Flat.",
            "Pinjaman Kendaraan: Plafon Rp 10jt - 150jt, tenor 12-48 bulan, bunga 10% Anuitas, wajib agunan BPKB."
        ]
    },
    "loans": {
        "table_name": "loans",
        "orm_model": "Loan",
        "title": "Transaksi Pinjaman Kredit Anggota",
        "module": "LOAN",
        "description": "Menyimpan permohonan pinjaman, status alur persetujuan, nominal pencairan, perhitungan angsuran, dan saldo pokok/bunga terutang.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "member_id", "references": "members.id"},
            {"column": "product_id", "references": "loan_products.id"},
            {"column": "approved_by_user_id", "references": "users.id"},
            {"column": "disbursed_by_user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "members", "type": "many-to-one", "fk": "loans.member_id", "desc": "Anggota peminjam"},
            {"target": "loan_products", "type": "many-to-one", "fk": "loans.product_id", "desc": "Produk pinjaman yang digunakan"},
            {"target": "loan_approvals", "type": "one-to-many", "fk": "loan_approvals.loan_id", "desc": "Riwayat tahapan persetujuan kredit"},
            {"target": "loan_installments", "type": "one-to-many", "fk": "loan_installments.loan_id", "desc": "Jadwal dan rincian angsuran kredit"},
            {"target": "loan_payments", "type": "one-to-many", "fk": "loan_payments.loan_id", "desc": "Riwayat kuitansi pembayaran angsuran"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID pinjaman"},
            {"name": "loan_no", "type": "VARCHAR(40)", "pk": False, "nullable": False, "desc": "Nomor kontrak pinjaman unik (LOAN-2026-XXXX)"},
            {"name": "member_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID anggota peminjam"},
            {"name": "product_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID produk pinjaman"},
            {"name": "requested_amount", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Plafon yang diajukan peminjam"},
            {"name": "approved_amount", "type": "NUMERIC(18, 2)", "pk": False, "nullable": True, "desc": "Plafon yang disetujui komite pembiayaan"},
            {"name": "interest_rate_percent", "type": "NUMERIC(6, 3)", "pk": False, "nullable": False, "desc": "Suku bunga yang disepakati (%/thn)"},
            {"name": "tenor_months", "type": "INTEGER", "pk": False, "nullable": False, "desc": "Jangka waktu angsuran dalam bulan"},
            {"name": "calculation_type", "type": "VARCHAR(20)", "pk": False, "nullable": False, "desc": "Metode bunga: FLAT, ANUITAS, SLIDING"},
            {"name": "admin_fee", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Biaya administrasi (dipotong saat pencairan)"},
            {"name": "provision_fee", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Biaya provisi (dipotong saat pencairan)"},
            {"name": "net_disbursed_amount", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Dana bersih yang diterima peminjam: approved_amount - admin_fee - provision_fee"},
            {"name": "monthly_principal", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Angsuran pokok bulanan"},
            {"name": "monthly_interest", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Angsuran jasa bunga bulanan"},
            {"name": "monthly_installment_total", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Total cicilan per bulan (pokok + bunga)"},
            {"name": "total_interest", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Total bunga keseluruhan tenor"},
            {"name": "total_payable", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Total kewajiban pengembalian (pokok disetujui + total bunga)"},
            {"name": "remaining_principal", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Sisa pokok utang yang belum dibayar"},
            {"name": "remaining_interest", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Sisa bunga yang belum dibayar"},
            {"name": "status", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Status alur: DRAFT, DIAJUKAN, VERIFIKASI, DISETUJUI, DITOLAK, DICAIRKAN, BERJALAN, LUNAS"},
            {"name": "purpose", "type": "TEXT", "pk": False, "nullable": False, "desc": "Tujuan pemanfaatan pinjaman"},
            {"name": "collateral_info", "type": "TEXT", "pk": False, "nullable": True, "desc": "Informasi agunan jaminan"},
            {"name": "rejection_reason", "type": "TEXT", "pk": False, "nullable": True, "desc": "Alasan penolakan jika tidak disetujui"}
        ],
        "business_rules": [
            "Alur resmi pinjaman: DRAFT -> DIAJUKAN -> VERIFIKASI (Staf) -> DISETUJUI/DITOLAK (Manager/Ketua) -> DICAIRKAN (Kasir) -> BERJALAN -> LUNAS.",
            "Pengaju pinjaman dilarang memverifikasi, menyetujui, atau mencairkan pinjamannya sendiri (segregation of duties).",
            "Pencairan oleh kasir secara otomatis membentuk jadwal di loan_installments dan transaksi kas keluar di cash_transactions.",
            "Penolakan pinjaman wajib mencatat alasan penolakan pada rejection_reason."
        ]
    },
    "loan_approvals": {
        "table_name": "loan_approvals",
        "orm_model": "LoanApproval",
        "title": "Jejak Persetujuan & Komite Pinjaman",
        "module": "LOAN",
        "description": "Menyimpan audit trail verifikasi bertingkat: STAF (verifikasi berkas), MANAGER (rekomendasi kredit), KETUA_UMUM (persetujuan final plafon besar).",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "loan_id", "references": "loans.id"},
            {"column": "approver_user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "loans", "type": "many-to-one", "fk": "loan_approvals.loan_id", "desc": "Pinjaman yang diproses"},
            {"target": "users", "type": "many-to-one", "fk": "loan_approvals.approver_user_id", "desc": "Pejabat yang memverifikasi/menyetujui"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID log approval"},
            {"name": "loan_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID pinjaman terkait"},
            {"name": "approver_user_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID pengguna yang mengambil keputusan"},
            {"name": "stage", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Tahapan level: STAF, MANAGER, KETUA_UMUM, PENGAWAS"},
            {"name": "decision", "type": "VARCHAR(25)", "pk": False, "nullable": False, "desc": "Keputusan: SUBMITTED, VERIFIED, APPROVED, REJECTED, DISBURSED, REVISION"},
            {"name": "from_status", "type": "VARCHAR(30)", "pk": False, "nullable": True, "desc": "Status pinjaman sebelum aksi"},
            {"name": "to_status", "type": "VARCHAR(30)", "pk": False, "nullable": True, "desc": "Status pinjaman setelah aksi"},
            {"name": "approved_amount", "type": "NUMERIC(18, 2)", "pk": False, "nullable": True, "desc": "Nominal plafon yang disetujui pada tahapan ini"},
            {"name": "notes", "type": "TEXT", "pk": False, "nullable": True, "desc": "Catatan rekomendasi / alasan penolakan"},
            {"name": "created_at", "type": "DATETIME", "pk": False, "nullable": False, "desc": "Waktu keputusan diambil"}
        ],
        "business_rules": [
            "Setiap perubahan status pinjaman wajib mencatat riwayat lengkap di loan_approvals.",
            "Keputusan REJECTED menghentikan proses pengajuan pinjaman."
        ]
    },
    "loan_installments": {
        "table_name": "loan_installments",
        "orm_model": "LoanInstallment",
        "title": "Jadwal Angsuran & Tagihan Kredit",
        "module": "INSTALLMENT",
        "description": "Menyimpan jadwal cicilan per periode (1..N tenor) dengan tanggal jatuh tempo, rincian pokok, bunga, denda, dan total tagihan.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "loan_id", "references": "loans.id"}
        ],
        "relationships": [
            {"target": "loans", "type": "many-to-one", "fk": "loan_installments.loan_id", "desc": "Pinjaman induk"},
            {"target": "loan_payments", "type": "one-to-many", "fk": "loan_payments.installment_id", "desc": "Pembayaran untuk angsuran ini"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID angsuran"},
            {"name": "loan_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID pinjaman terkait"},
            {"name": "installment_no", "type": "INTEGER", "pk": False, "nullable": False, "desc": "Nomor urut angsuran ke-N (1, 2, dst)"},
            {"name": "due_date", "type": "DATE", "pk": False, "nullable": False, "desc": "Tanggal jatuh tempo tagihan (tiap 30 hari)"},
            {"name": "principal_due", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Kewajiban pokok pada periode ini"},
            {"name": "interest_due", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Kewajiban bunga pada periode ini"},
            {"name": "penalty_due", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Denda keterlambatan jika lewat jatuh tempo"},
            {"name": "total_due", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Total tagihan periode ini (pokok + bunga + denda)"},
            {"name": "principal_paid", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Pokok yang sudah terbayar"},
            {"name": "interest_paid", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Bunga yang sudah terbayar"},
            {"name": "penalty_paid", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Denda yang sudah terbayar"},
            {"name": "total_paid", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Total akumulasi pembayaran pada periode ini"},
            {"name": "status", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Status angsuran: BELUM_JATUH_TEMPO, JATUH_TEMPO, TERLAMBAT, DIBAYAR, LUNAS"},
            {"name": "paid_at", "type": "DATETIME", "pk": False, "nullable": True, "desc": "Waktu pelunasan penuh"},
            {"name": "days_overdue", "type": "INTEGER", "pk": False, "nullable": False, "desc": "Jumlah hari keterlambatan"}
        ],
        "business_rules": [
            "Status LUNAS dicapai saat total_paid >= total_due.",
            "Jika pembayaran hanya sebagian, status menjadi DIBAYAR.",
            "Jika tanggal saat ini > due_date dan belum lunas, status menjadi TERLAMBAT dan dikenakan denda harian (penalty_rate_daily).",
            "Sisa tagihan dihitung dari max(0, total_due - total_paid)."
        ]
    },
    "loan_payments": {
        "table_name": "loan_payments",
        "orm_model": "LoanPayment",
        "title": "Kuitansi Pembayaran Angsuran",
        "module": "INSTALLMENT",
        "description": "Menyimpan transaksi pembayaran angsuran, alokasi porsi pokok/bunga/denda, metode pembayaran, dan nomor kuitansi resmi.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "loan_id", "references": "loans.id"},
            {"column": "installment_id", "references": "loan_installments.id"},
            {"column": "member_id", "references": "members.id"},
            {"column": "received_by_user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "loans", "type": "many-to-one", "fk": "loan_payments.loan_id", "desc": "Pinjaman yang diangsur"},
            {"target": "loan_installments", "type": "many-to-one", "fk": "loan_payments.installment_id", "desc": "Tagihan angsuran terkait"},
            {"target": "members", "type": "many-to-one", "fk": "loan_payments.member_id", "desc": "Anggota pembayar"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID pembayaran"},
            {"name": "payment_no", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Nomor pembayaran unik (PAY-LOAN-XXXX)"},
            {"name": "loan_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID pinjaman terkait"},
            {"name": "installment_id", "type": "INTEGER", "pk": False, "nullable": True, "desc": "ID baris angsuran terkait"},
            {"name": "member_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID anggota yang membayar"},
            {"name": "amount_paid", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Total uang yang disetorkan pembayar"},
            {"name": "principal_portion", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Alokasi untuk pelunasan pokok"},
            {"name": "interest_portion", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Alokasi untuk pelunasan bunga"},
            {"name": "penalty_portion", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Alokasi untuk pelunasan denda"},
            {"name": "payment_method", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Metode pembayaran: CASHIER, HRD_PAYROLL, BANK_TRANSFER"},
            {"name": "receipt_no", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Nomor kuitansi tanda terima kasir"}
        ],
        "business_rules": [
            "Uang yang disetorkan dialokasikan dengan urutan: Denda -> Bunga -> Pokok.",
            "Setiap pembayaran tunai otomatis dicatat di kasir sebagai cash_transactions arah CASH_IN.",
            "Pelunasan pokok mengurangi remaining_principal pada pinjaman induk."
        ]
    },
    "cash_registers": {
        "table_name": "cash_registers",
        "orm_model": "CashRegister",
        "title": "Buku Kasir & Rekonsiliasi Shift",
        "module": "CASHIER",
        "description": "Menyimpan buku kas per shift kerja kasir, saldo kas awal, akumulasi kas masuk/keluar, saldo akhir sistem, uang fisik riil, dan selisih (discrepancy).",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "cashier_user_id", "references": "users.id"},
            {"column": "closed_by_user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "cash_transactions", "type": "one-to-many", "fk": "cash_transactions.cash_register_id", "desc": "Daftar transaksi kas pada shift ini"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID shift kasir"},
            {"name": "cashier_user_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID petugas kasir pemegang shift"},
            {"name": "shift_date", "type": "DATE", "pk": False, "nullable": False, "desc": "Tanggal operasional shift"},
            {"name": "opening_balance", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Uang modal kas awal di laci"},
            {"name": "total_cash_in", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Total penerimaan uang tunai selama shift"},
            {"name": "total_cash_out", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Total pengeluaran uang tunai selama shift"},
            {"name": "closing_balance", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Saldo sistem saat penutupan = opening + total_in - total_out"},
            {"name": "physical_balance", "type": "NUMERIC(18, 2)", "pk": False, "nullable": True, "desc": "Hasil perhitungan fisik uang tunai aktual di laci"},
            {"name": "discrepancy", "type": "NUMERIC(18, 2)", "pk": False, "nullable": True, "desc": "Selisih kas = physical_balance - closing_balance"},
            {"name": "status", "type": "VARCHAR(20)", "pk": False, "nullable": False, "desc": "Status shift: OPEN (berlangsung), CLOSED (sudah tutup buku)"}
        ],
        "business_rules": [
            "Kasir hanya boleh memiliki 1 shift berstatus OPEN pada saat yang sama.",
            "Tutup shift menghitung selisih kas fisik vs sistem (discrepancy). Bila selisih != 0 wajib dicatat alasannya.",
            "Penutupan kasir hanya dapat dilakukan oleh kasir pemegang shift, Manager, atau Admin."
        ]
    },
    "cash_transactions": {
        "table_name": "cash_transactions",
        "orm_model": "CashTransaction",
        "title": "Transaksi Kas Loket & Rekonsiliasi",
        "module": "CASHIER",
        "description": "Menyimpan seluruh transaksi tunai/loket (setoran tabungan, penarikan tabungan, pencairan kredit, pembayaran angsuran, biaya operasional).",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "cash_register_id", "references": "cash_registers.id"},
            {"column": "cashier_user_id", "references": "users.id"},
            {"column": "member_id", "references": "members.id"},
            {"column": "reversed_by_user_id", "references": "users.id"},
            {"column": "reversal_of_id", "references": "cash_transactions.id"}
        ],
        "relationships": [
            {"target": "cash_registers", "type": "many-to-one", "fk": "cash_transactions.cash_register_id", "desc": "Shift kasir tempat transaksi diproses"},
            {"target": "members", "type": "many-to-one", "fk": "cash_transactions.member_id", "desc": "Anggota yang bertransaksi"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID transaksi kas"},
            {"name": "transaction_no", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Nomor transaksi kas unik (TRX-CSH-XXXX)"},
            {"name": "cash_register_id", "type": "INTEGER", "pk": False, "nullable": True, "desc": "ID shift kasir aktif"},
            {"name": "cashier_user_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID petugas kasir pelaksana"},
            {"name": "direction", "type": "VARCHAR(20)", "pk": False, "nullable": False, "desc": "Arah aliran kas: CASH_IN (masuk) atau CASH_OUT (keluar)"},
            {"name": "category", "type": "VARCHAR(40)", "pk": False, "nullable": False, "desc": "Kategori: SAVINGS_DEPOSIT, SAVINGS_WITHDRAWAL, LOAN_DISBURSEMENT, LOAN_PAYMENT, OPERATIONAL_EXPENSE, dll"},
            {"name": "amount", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Nominal uang transaksi"},
            {"name": "receipt_no", "type": "VARCHAR(60)", "pk": False, "nullable": False, "desc": "Nomor struk bukti transaksi"},
            {"name": "is_reversed", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Flag apakah transaksi telah dibatalkan/dibalik (reversal)"},
            {"name": "reversal_reason", "type": "TEXT", "pk": False, "nullable": True, "desc": "Alasan pembatalan transaksi"}
        ],
        "business_rules": [
            "Transaksi kas berarah CASH_IN menambah saldo kas, CASH_OUT mengurangi saldo kas.",
            "Transaksi yang dibatalkan (reversal) tidak dihapus dari database, melainkan dibuatkan transaksi pembalik dengan is_reversed=True dan catatan alasan pembatalan (audit-safe immutable ledger)."
        ]
    },
    "chart_of_accounts": {
        "table_name": "chart_of_accounts",
        "orm_model": "ChartOfAccount",
        "title": "Bagan Akun Standar (COA) Koperasi",
        "module": "ACCOUNTING",
        "description": "Bagan akun buku besar akuntansi standar koperasi (Harta, Kewajiban, Ekuitas/Modal, Pendapatan, Beban).",
        "primary_key": ["id"],
        "foreign_keys": [],
        "relationships": [
            {"target": "journal_lines", "type": "one-to-many", "fk": "journal_lines.account_id", "desc": "Baris jurnal yang mencatat mutasi pada akun ini"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID akun"},
            {"name": "code", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Kode akun unik (1101 Kas, 1102 Bank, 1201 Piutang Pinjaman, 2101 Simpanan Sukarela, 3101 Simpanan Pokok, 3102 Simpanan Wajib, 4101 Pendapatan Jasa, 5101 Beban Operasional)"},
            {"name": "name", "type": "VARCHAR(100)", "pk": False, "nullable": False, "desc": "Nama akun buku besar"},
            {"name": "account_type", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Tipe: ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE"},
            {"name": "normal_balance", "type": "VARCHAR(10)", "pk": False, "nullable": False, "desc": "Saldo normal: DEBIT atau CREDIT"},
            {"name": "is_active", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Status aktif akun"}
        ],
        "business_rules": [
            "Akun Harta (ASSET) dan Beban (EXPENSE) bertambah di DEBIT, berkurang di CREDIT.",
            "Akun Kewajiban (LIABILITY), Ekuitas (EQUITY), dan Pendapatan (REVENUE) bertambah di CREDIT, berkurang di DEBIT.",
            "Setiap pencairan kredit, setoran simpanan, atau angsuran memicu entri jurnal berimbang ke COA."
        ]
    },
    "journal_entries": {
        "table_name": "journal_entries",
        "orm_model": "JournalEntry",
        "title": "Header Jurnal Umum Akuntansi",
        "module": "ACCOUNTING",
        "description": "Menyimpan header bukti pencatatan transaksi keuangan ganda (double-entry bookkeeping) berkala.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "created_by_user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "journal_lines", "type": "one-to-many", "fk": "journal_lines.journal_entry_id", "desc": "Rincian baris debit dan kredit jurnal"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID jurnal"},
            {"name": "entry_no", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Nomor jurnal unik (JRN-YYYYMMDD-XXXX)"},
            {"name": "entry_date", "type": "DATE", "pk": False, "nullable": False, "desc": "Tanggal pembukuan entri jurnal"},
            {"name": "reference_no", "type": "VARCHAR(60)", "pk": False, "nullable": True, "desc": "Nomor referensi bukti transaksi asal"},
            {"name": "description", "type": "TEXT", "pk": False, "nullable": False, "desc": "Keterangan transaksi pembukuan"}
        ],
        "business_rules": [
            "Total debit dan total kredit seluruh baris pada sebuah jurnal wajib berimbang (balance: sum(debit) == sum(credit))."
        ]
    },
    "journal_lines": {
        "table_name": "journal_lines",
        "orm_model": "JournalLine",
        "title": "Baris Detail Debit / Kredit Jurnal",
        "module": "ACCOUNTING",
        "description": "Menyimpan setiap rincian pembebanan pos akun debit dan pos akun kredit pada entri jurnal.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "journal_entry_id", "references": "journal_entries.id"},
            {"column": "account_id", "references": "chart_of_accounts.id"}
        ],
        "relationships": [
            {"target": "journal_entries", "type": "many-to-one", "fk": "journal_lines.journal_entry_id", "desc": "Header entri jurnal induk"},
            {"target": "chart_of_accounts", "type": "many-to-one", "fk": "journal_lines.account_id", "desc": "Akun COA yang dipengaruhi"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID baris jurnal"},
            {"name": "journal_entry_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID header jurnal terkait"},
            {"name": "account_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID akun COA"},
            {"name": "debit", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Nominal sisi debit"},
            {"name": "credit", "type": "NUMERIC(18, 2)", "pk": False, "nullable": False, "desc": "Nominal sisi kredit"},
            {"name": "description", "type": "VARCHAR(255)", "pk": False, "nullable": True, "desc": "Catatan baris spesifik"}
        ],
        "business_rules": [
            "Sebuah baris minimal memiliki salah satu nilai debit > 0 atau credit > 0 (tidak boleh keduanya nol)."
        ]
    },
    "audit_logs": {
        "table_name": "audit_logs",
        "orm_model": "AuditLog",
        "title": "Audit Trail & Rekam Jejak Sistem",
        "module": "AUDIT",
        "description": "Mencatat setiap aksi penting pengguna: login, perubahan data, approval pinjaman, transaksi kasir, perubahan peran, dan query AI.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "users", "type": "many-to-one", "fk": "audit_logs.user_id", "desc": "Pengguna pelaksana aksi"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID log audit"},
            {"name": "user_id", "type": "INTEGER", "pk": False, "nullable": True, "desc": "ID pengguna pelaksana"},
            {"name": "action", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Kode aksi (LOGIN, LOGOUT, CREATE_LOAN, APPROVE_LOAN, CASH_IN, AI_ASK, dll)"},
            {"name": "entity_name", "type": "VARCHAR(50)", "pk": False, "nullable": False, "desc": "Nama entitas yang dipengaruhi (User, Loan, Savings, Cash, AI)"},
            {"name": "entity_id", "type": "VARCHAR(50)", "pk": False, "nullable": True, "desc": "ID atau kunci rekaman entitas"},
            {"name": "old_values", "type": "JSON", "pk": False, "nullable": True, "desc": "Snapshot nilai sebelum perubahan (JSON)"},
            {"name": "new_values", "type": "JSON", "pk": False, "nullable": True, "desc": "Snapshot nilai setelah perubahan (JSON)"},
            {"name": "ip_address", "type": "VARCHAR(45)", "pk": False, "nullable": True, "desc": "Alamat IP pengguna"},
            {"name": "user_agent", "type": "VARCHAR(255)", "pk": False, "nullable": True, "desc": "Browser/klien pengeksekusi"},
            {"name": "notes", "type": "TEXT", "pk": False, "nullable": True, "desc": "Catatan rinci aksi"},
            {"name": "created_at", "type": "DATETIME", "pk": False, "nullable": False, "desc": "Waktu peristiwa tercatat"}
        ],
        "business_rules": [
            "Log audit bersifat WORM (Write Once, Read Many) — dilarang menghapus atau mengubah catatan audit trail.",
            "Setiap pertanyaan ke AI dicatat di audit log tanpa menyimpan pertanyaan privat anggota jika bersifat rahasia."
        ]
    },
    "notifications": {
        "table_name": "notifications",
        "orm_model": "Notification",
        "title": "Notifikasi Pengguna In-App",
        "module": "SYSTEM",
        "description": "Menyimpan notifikasi lonceng in-app untuk anggota dan staf perihal status pinjaman, jadwal tagihan, atau aksi sistem.",
        "primary_key": ["id"],
        "foreign_keys": [
            {"column": "user_id", "references": "users.id"}
        ],
        "relationships": [
            {"target": "users", "type": "many-to-one", "fk": "notifications.user_id", "desc": "Penerima notifikasi"}
        ],
        "columns": [
            {"name": "id", "type": "INTEGER", "pk": True, "nullable": False, "desc": "ID notifikasi"},
            {"name": "user_id", "type": "INTEGER", "pk": False, "nullable": False, "desc": "ID pengguna tujuan"},
            {"name": "title", "type": "VARCHAR(100)", "pk": False, "nullable": False, "desc": "Judul notifikasi"},
            {"name": "message", "type": "TEXT", "pk": False, "nullable": False, "desc": "Isi pesan lengkap"},
            {"name": "type", "type": "VARCHAR(30)", "pk": False, "nullable": False, "desc": "Tipe: INFO, SUCCESS, WARNING, DANGER"},
            {"name": "is_read", "type": "BOOLEAN", "pk": False, "nullable": False, "desc": "Status apakah sudah dibaca"},
            {"name": "read_at", "type": "DATETIME", "pk": False, "nullable": True, "desc": "Waktu dibaca"},
            {"name": "link_url", "type": "VARCHAR(255)", "pk": False, "nullable": True, "desc": "URL tautan terkait notifikasi"}
        ],
        "business_rules": [
            "Notifikasi diterbitkan saat terjadi perubahan status penting (misal pinjaman disetujui, pinjaman dicairkan, tagihan jatuh tempo)."
        ]
    }
}


FINANCIAL_FORMULAS: Dict[str, Dict[str, Any]] = {
    "bunga_flat": {
        "id": "bunga_flat",
        "nama": "Perhitungan Bunga Flat",
        "deskripsi": "Bunga dihitung rata dari plafon pokok pinjaman awal sepanjang tenor. Pokok dan bunga bulanan bernilai tetap.",
        "rumus": "total_bunga = plafon * (suku_bunga_tahunan / 100) * (tenor_bulan / 12)\nangsuran_pokok_bulanan = plafon / tenor_bulan\nangsuran_bunga_bulanan = total_bunga / tenor_bulan\ntotal_angsuran_bulanan = angsuran_pokok_bulanan + angsuran_bunga_bulanan",
        "contoh": "Plafon Rp 12.000.000, Tenor 12 bulan, Bunga 12% Flat:\n- Total Bunga = 12.000.000 * 12% * 1 = Rp 1.440.000\n- Pokok/bulan = 12.000.000 / 12 = Rp 1.000.000\n- Bunga/bulan = 1.440.000 / 12 = Rp 120.000\n- Total Angsuran/bulan = Rp 1.120.000"
    },
    "bunga_anuitas": {
        "id": "bunga_anuitas",
        "nama": "Perhitungan Bunga Anuitas",
        "deskripsi": "Total angsuran bulanan tetap, namun proporsi pokok membesar dan proporsi bunga mengecil seiring berjalannya waktu.",
        "rumus": "r = (suku_bunga_tahunan / 100) / 12\ntotal_angsuran_bulanan = plafon * [r * (1 + r)^n] / [((1 + r)^n) - 1]\nbunga_bulan_1 = plafon * r\npokok_bulan_1 = total_angsuran_bulanan - bunga_bulan_1",
        "contoh": "Plafon Rp 50.000.000, Tenor 24 bulan, Bunga 10% Anuitas:\n- r = 10% / 12 = 0.008333\n- Angsuran bulanan tetap = Rp 2.307.246\n- Pada bulan pertama: bunga Rp 416.667, pokok Rp 1.890.579"
    },
    "bunga_sliding": {
        "id": "bunga_sliding",
        "nama": "Perhitungan Bunga Menurun (Sliding Rate)",
        "deskripsi": "Angsuran pokok bulanan tetap, sedangkan bunga dihitung dari sisa pokok pinjaman yang semakin mengecil setiap bulannya.",
        "rumus": "angsuran_pokok_bulanan = plafon / tenor_bulan\nbunga_bulan_i = sisa_pokok_terutang_i * ((suku_bunga_tahunan / 100) / 12)\ntotal_angsuran_bulan_i = angsuran_pokok_bulanan + bunga_bulan_i",
        "contoh": "Plafon Rp 12.000.000, Tenor 12 bulan, Bunga 12% Sliding:\n- Pokok tetap: Rp 1.000.000/bln\n- Bulan 1: bunga = 12jt * 1% = Rp 120.000 (Total Rp 1.120.000)\n- Bulan 2: bunga = 11jt * 1% = Rp 110.000 (Total Rp 1.110.000)"
    },
    "biaya_pencairan": {
        "id": "biaya_pencairan",
        "nama": "Perhitungan Biaya Pencairan & Dana Bersih",
        "deskripsi": "Biaya administrasi dan provisi dipotong langsung saat pencairan kredit di loket kasir.",
        "rumus": "biaya_admin = plafon_disetujui * (admin_fee_percent / 100)\nbiaya_provisi = plafon_disetujui * (provision_fee_percent / 100)\ndana_cair_bersih = plafon_disetujui - biaya_admin - biaya_provisi",
        "contoh": "Plafon Disetujui Rp 10.000.000, Admin 1.0%, Provisi 0.5%:\n- Biaya Admin = Rp 100.000\n- Biaya Provisi = Rp 50.000\n- Dana Cair Bersih = 10.000.000 - 100.000 - 50.000 = Rp 9.850.000"
    },
    "denda_keterlambatan": {
        "id": "denda_keterlambatan",
        "nama": "Perhitungan Denda Keterlambatan Angsuran",
        "deskripsi": "Denda dihitung per hari keterlambatan sejak lewat tanggal jatuh tempo.",
        "rumus": "denda = hari_terlambat * (penalty_rate_daily / 100) * total_tagihan_angsuran",
        "contoh": "Tagihan Rp 1.000.000, Terlambat 5 hari, Denda 0.1%/hari:\n- Denda = 5 * 0.1% * 1.000.000 = Rp 5.000"
    },
    "credit_score_dsr": {
        "id": "credit_score_dsr",
        "nama": "Debt Service Ratio (DSR) & Credit Score",
        "deskripsi": "Rasio kemampuan bayar angsuran terhadap penghasilan bulanan pegawai/anggota.",
        "rumus": "DSR = (estimasi_angsuran_bulanan / gaji_bulanan) * 100%\nBatas aman:\n- DSR <= 30%: Risiko RENDAH (+10 poin)\n- DSR 30% - 40%: Risiko SEDANG (-15 poin)\n- DSR > 40%: Risiko TINGGI (-30 poin)\nSkor Dasar 85 poin, dipengaruhi saldo simpanan dan riwayat kredit macet.",
        "contoh": "Gaji Rp 10.000.000, Angsuran Rp 2.500.000 -> DSR = 25% (Aman / Sehat)"
    },
    "rekonsiliasi_kasir": {
        "id": "rekonsiliasi_kasir",
        "nama": "Rekonsiliasi Saldo Kasir Shift",
        "deskripsi": "Kalkulasi keseimbangan saldo kas fisik di laci kasir vs catatan sistem.",
        "rumus": "saldo_sistem = kas_awal + total_kas_masuk - total_kas_keluar\nselisih_kas = kas_fisik_riil - saldo_sistem",
        "contoh": "Kas awal Rp 1.000.000, Masuk Rp 5.000.000, Keluar Rp 2.000.000:\n- Saldo sistem = Rp 4.000.000\n- Jika fisik Rp 4.000.000 -> Selisih Rp 0 (Cocok / Seimbang)"
    },
    "rekonstruksi_simpanan": {
        "id": "rekonstruksi_simpanan",
        "nama": "Rekonstruksi Saldo Simpanan (Audit Ledger)",
        "deskripsi": "Verifikasi saldo rekening simpanan langsung dari riwayat transaksi yang berstatus COMPLETED.",
        "rumus": "saldo_rekonstruksi = sum(SETOR + DEPOSIT + INTEREST + TRANSFER_IN) - sum(TARIK + WITHDRAWAL + FEE + TRANSFER_OUT)",
        "contoh": "Total setoran Rp 5.500.000, Bunga Rp 50.000, Tarik Rp 1.000.000 -> Saldo riil = Rp 4.550.000"
    }
}


TRANSACTION_FLOWS: List[Dict[str, Any]] = [
    {
        "flow_name": "Siklus Pinjaman Lengkap (Loan Lifecycle)",
        "steps": [
            "1. Pengajuan (DRAFT -> DIAJUKAN): Anggota memilih produk, nominal, dan tenor di menu Pinjaman.",
            "2. Verifikasi Berkas (VERIFIKASI): Staf memeriksa berkas & kelayakan, mencatat di loan_approvals.",
            "3. Keputusan Komite (DISETUJUI / DITOLAK): Manager atau Ketua Umum memutuskan persetujuan kredit.",
            "4. Pencairan di Loket Kasir (DICAIRKAN -> BERJALAN): Kasir mencairkan dana bersih (plafon - admin - provisi), mencatat transaksi kas keluar di cash_transactions, membentuk jadwal angsuran di loan_installments, dan membukukan jurnal akuntansi.",
            "5. Pembayaran Angsuran: Dilakukan di kasir atau potong gaji HRD, mencatat loan_payments, mengurangi remaining_principal & remaining_interest pada loans.",
            "6. Pelunasan Penuh (LUNAS): Setelah seluruh pokok dan bunga terbayar 100%."
        ]
    },
    {
        "flow_name": "Siklus Kasir & Loket (Cashier Shift Lifecycle)",
        "steps": [
            "1. Buka Kasir: Kasir membuka shift baru dengan memasukkan saldo modal kas awal di cash_registers.",
            "2. Layanan Transaksi: Kasir memproses setoran simpanan (CASH_IN), penarikan simpanan (CASH_OUT), angsuran (CASH_IN), pencairan pinjaman (CASH_OUT), dan mencetak struk kuitansi resmi.",
            "3. Tutup Shift & Rekonsiliasi: Kasir menghitung uang fisik di laci kasir (physical_balance), sistem membandingkan dengan closing_balance. Bila terdapat selisih, dicatat pada discrepancy."
        ]
    },
    {
        "flow_name": "Siklus Simpanan (Savings Lifecycle)",
        "steps": [
            "1. Pendaftaran: Anggota menyetor Simpanan Pokok (Rp 500.000) sekali saat mendaftar.",
            "2. Rutin Bulanan: Anggota menyetor Simpanan Wajib (Rp 100.000/bln) via loket kasir atau potong gaji HRD.",
            "3. Fleksibel: Anggota dapat menyetor atau menarik Simpanan Sukarela kapan saja di loket kasir dengan saldo cukup.",
            "4. Pembukuan Otomatis: Setiap transaksi simpanan menghasilkan baris di savings_transactions dan cash_transactions."
        ]
    }
]


class DatabaseKnowledgeCatalog:
    """Service penyedia katalog pengetahuan database otoritatif untuk AI dan Pengguna."""

    @classmethod
    def get_all_tables(cls) -> List[str]:
        """Mendapatkan daftar 22 tabel terdaftar."""
        return sorted(list(TABLE_CATALOG.keys()))

    @classmethod
    def get_table_metadata(cls, table_name: str) -> Optional[Dict[str, Any]]:
        """Mendapatkan metadata mendalam satu tabel."""
        return TABLE_CATALOG.get(table_name.lower().strip())

    @classmethod
    def get_tables_by_module(cls, module_name: str) -> List[Dict[str, Any]]:
        """Mendapatkan seluruh tabel dalam modul tertentu (e.g. LOAN, SAVING, CASHIER)."""
        mod = module_name.upper().strip()
        results = []
        for t, data in TABLE_CATALOG.items():
            if data.get("module") == mod:
                results.append(data)
        return results

    @classmethod
    def get_financial_formula(cls, formula_id: str) -> Optional[Dict[str, Any]]:
        """Mendapatkan rumus perhitungan finansial tertentu."""
        return FINANCIAL_FORMULAS.get(formula_id.lower().strip())

    @classmethod
    def get_all_financial_formulas(cls) -> Dict[str, Dict[str, Any]]:
        """Mendapatkan seluruh rumus finansial standar koperasi."""
        return FINANCIAL_FORMULAS

    @classmethod
    def get_transaction_flows(cls) -> List[Dict[str, Any]]:
        """Mendapatkan alur hubungan transaksi antarmodul."""
        return TRANSACTION_FLOWS

    @classmethod
    def search(cls, query: str) -> Dict[str, Any]:
        """Pencarian cerdas dalam katalog: tabel, kolom, rumus, status, dan alur transaksi."""
        q = (query or "").lower().strip()
        if not q:
            return {"tables": [], "formulas": [], "flows": []}

        tokens = [w for w in re.split(r"[^a-z0-9_]+", q) if len(w) >= 3]

        matched_tables = []
        for t_name, data in TABLE_CATALOG.items():
            score = 0
            # Cek kecocokan nama tabel atau judul
            if t_name in q or q in t_name:
                score += 5
            for w in tokens:
                if w in t_name:
                    score += 3
                if w in data["title"].lower():
                    score += 3
                if w in data["description"].lower():
                    score += 1
                for c in data["columns"]:
                    if w == c["name"].lower():
                        score += 3
            if score > 0:
                matched_tables.append((score, data))

        matched_tables.sort(key=lambda x: -x[0])

        matched_formulas = []
        for f_id, data in FINANCIAL_FORMULAS.items():
            score = 0
            if f_id in q or q in f_id:
                score += 5
            for w in tokens:
                if w in data["nama"].lower() or w in data["deskripsi"].lower() or w in f_id:
                    score += 2
            if score > 0:
                matched_formulas.append((score, data))

        matched_formulas.sort(key=lambda x: -x[0])

        return {
            "query": query,
            "matched_tables": [item[1] for item in matched_tables[:4]],
            "matched_formulas": [item[1] for item in matched_formulas[:3]]
        }

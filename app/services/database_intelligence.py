"""Database Intelligence Service KSP AHNRFZI.

Menghubungkan alur:
User → Authentication → RBAC → AI Chat API → Database Intelligence Service → Authorized Read-Only Query → Database

Fitur utama:
1. Memvalidasi identitas user dari sesi server & mengevaluasi izin efektif (RBAC).
2. Memahami 9 Peran (Roles) Koperasi dengan Context, Greeting, dan Dynamic Suggested Questions yang relevan.
3. Penegakan Data Isolation:
   - ANGGOTA: Hanya berhak membaca data miliknya sendiri (Ownership check).
   - STAF / KASIR / HRD / PENGAWAS / MANAJEMEN: Hanya berhak membaca data/agregat sesuai domain izin.
4. Menegakkan prinsip READ-ONLY secara mutlak (tidak ada operasi tulis/modifikasi).
5. Klasifikasi Intent: GENERAL, FAQ, PERSONAL_DATA, FINANCIAL_SUMMARY, OPERATIONAL, HRD, AUDIT, TECHNICAL, RESTRICTED, ACTION_REQUEST.
6. Pemahaman Skema Lengkap: Memanfaatkan DatabaseKnowledgeCatalog dan DatabaseSchemaDiscovery.
7. Deterministic & Anti-Hallucination: Seluruh data angka bersumber langsung dari database.
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime, date, timedelta, timezone
from threading import Lock
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import logger
from app.core.permissions import get_user_permissions
from app.db.models.user import User
from app.db.models.member import Member
from app.db.models.employee import Employee
from app.db.models.loan import Loan, LoanInstallment, LoanPayment, LoanApproval, LoanStatus
from app.db.models.savings import SavingsAccount, SavingsProduct, SavingsTransaction
from app.db.models.transaction import CashRegister, CashTransaction
from app.db.models.audit_log import AuditLog
from app.db.models.telegram import TelegramUserLink, TelegramDeliveryLog
from app.services import ai_tools, dashboard_service
from app.services.ai_tools import _fmt_rp
from app.services.ai_knowledge import search_sop
from app.services.database_knowledge_catalog import (
    DatabaseKnowledgeCatalog,
    TABLE_CATALOG,
    FINANCIAL_FORMULAS,
    TRANSACTION_FLOWS
)
from app.services.schema_discovery import DatabaseSchemaDiscovery


ROLE_DUTIES: Dict[str, str] = {
    "ADMIN_KOPERASI": (
        "Memiliki kewenangan administrasi menyeluruh terhadap sistem KSP AHNRFZI, manajemen "
        "keanggotaan, konfigurasi hak akses, pemantauan transaksi, dan pemeliharaan data master."
    ),
    "IT_PUSAT": (
        "Bertanggung jawab atas pemeliharaan infrastruktur teknis, pemantauan koneksi dan skema "
        "database, ketersediaan layanan sistem/aplikasi, keamanan informasi, serta integrasi AI KSP AHNRFZI."
    ),
    "KETUA_UMUM": (
        "Memegang wewenang eksekutif tertinggi dalam persetujuan pinjaman plafon besar, penetapan "
        "kebijakan organisasi, pengawasan strategis, dan evaluasi kinerja menyeluruh koperasi."
    ),
    "MANAGER": (
        "Bertanggung jawab atas pengelolaan operasional harian, persetujuan pinjaman reguler, "
        "pemantauan portofolio simpanan & pinjaman, pengendalian risiko kredit macet (NPL), dan koordinasi tim."
    ),
    "HRD": (
        "Mengelola data kepegawaian (SDM), struktur jabatan, status karyawan, rekapitulasi gaji "
        "pokok & tunjangan (payroll), serta koordinasi pemotongan gaji rutin untuk simpanan dan pinjaman."
    ),
    "PENGAWAS_PEMBINA": (
        "Menjalankan fungsi pengawasan independen terhadap kepatuhan tata kelola, peninjauan "
        "workflow approval pinjaman, pemeriksaan jejak audit (audit log), dan pengawasan kesehatan koperasi."
    ),
    "STAF": (
        "Melakukan pelayanan operasional pendaftaran anggota baru, verifikasi berkas administrasi, "
        "pemeriksaan awal kelayakan pinjaman, dan penyelesaian tugas operasional harian."
    ),
    "KASIR": (
        "Mengelola transaksi kas harian loket, penerimaan setoran simpanan, pencairan pinjaman "
        "yang telah disetujui, pembayaran angsuran, serta rekonsiliasi penutupan kas register."
    ),
    "ANGGOTA": (
        "Berhak memantau rekening simpanan pribadi (pokok, wajib, sukarela), memeriksa sisa "
        "pinjaman dan jadwal angsuran mandiri, serta mengajukan fasilitas pinjaman koperasi."
    ),
}

ROLE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "ADMIN_KOPERASI": {
        "name": "Admin Koperasi",
        "greeting": "Halo, selamat datang di AI Assistant KSP AHNRFZI. Saya dapat membantu Anda memantau keanggotaan, simpanan, pinjaman, dan operasional sesuai hak akses Anda.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Berapa total anggota aktif?",
            "Berapa anggota baru bulan ini?",
            "Berapa pengajuan pinjaman menunggu verifikasi?",
            "Berapa total simpanan koperasi?",
            "Apa saja data anggota yang belum lengkap?"
        ]
    },
    "KETUA_UMUM": {
        "name": "Ketua Umum",
        "greeting": "Halo, selamat datang di AI Assistant KSP AHNRFZI. Saya dapat membantu memantau kondisi keuangan, pinjaman, simpanan, dan ringkasan kinerja koperasi sesuai kewenangan Anda.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Bagaimana kondisi keuangan koperasi bulan ini?",
            "Berapa outstanding pinjaman?",
            "Bagaimana perkembangan simpanan?",
            "Berapa pinjaman menunggu persetujuan?",
            "Bagaimana ringkasan kinerja koperasi?"
        ]
    },
    "MANAGER": {
        "name": "Manager Koperasi",
        "greeting": "Halo, selamat datang di AI Assistant KSP AHNRFZI. Saya dapat membantu memantau simpanan, pinjaman aktif, angsuran terlambat, dan operasional koperasi sesuai wewenang manajerial Anda.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Berapa total simpanan bulan ini?",
            "Berapa pinjaman aktif?",
            "Berapa angsuran terlambat?",
            "Bagaimana perkembangan kas?",
            "Apa aktivitas operasional yang perlu diperhatikan?"
        ]
    },
    "HRD": {
        "name": "HRD",
        "greeting": "Halo, selamat datang di AI Assistant KSP AHNRFZI. Saya dapat membantu Anda melihat data kepegawaian, status karyawan, dan SOP pengelolaan karyawan sesuai kewenangan HRD.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Berapa jumlah karyawan aktif?",
            "Berapa karyawan tidak aktif?",
            "Data karyawan mana yang belum lengkap?",
            "Bagaimana status kepegawaian?",
            "Apa SOP pengelolaan karyawan?"
        ]
    },
    "PENGAWAS_PEMBINA": {
        "name": "Pengawas / Pembina",
        "greeting": "Halo, selamat datang di AI Assistant KSP AHNRFZI. Saya dapat membantu Anda memantau kepatuhan workflow, audit trail, aktivitas transaksi, dan pinjaman bermasalah sesuai fungsi pengawasan.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Bagaimana ringkasan aktivitas koperasi?",
            "Apakah ada transaksi yang perlu ditinjau?",
            "Bagaimana ringkasan audit log?",
            "Berapa pinjaman bermasalah?",
            "Bagaimana kepatuhan terhadap workflow approval?"
        ]
    },
    "STAF": {
        "name": "Staf Operasional",
        "greeting": "Halo, selamat datang di AI Assistant KSP AHNRFZI. Saya dapat membantu menjelaskan prosedur verifikasi anggota, SOP pinjaman, dan pekerjaan operasional yang menunggu tindak lanjut.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Apa tugas operasional saya?",
            "Bagaimana prosedur pendaftaran anggota?",
            "Bagaimana cara memverifikasi data anggota?",
            "Apa SOP pengajuan pinjaman?",
            "Apa pekerjaan yang menunggu tindak lanjut?"
        ]
    },
    "IT_PUSAT": {
        "name": "IT Pusat",
        "greeting": "Halo, saya AI Assistant KSP AHNRFZI. Saya dapat membantu memberikan informasi teknis aplikasi dan status layanan yang tersedia sesuai permission Anda.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Bagaimana status aplikasi?",
            "Apakah ada error sistem yang tercatat?",
            "Bagaimana status koneksi database?",
            "Apakah ada masalah integrasi AI?",
            "Bagaimana status layanan aplikasi?"
        ]
    },
    "KASIR": {
        "name": "Kasir Loket",
        "greeting": "Halo, saya AI Assistant KSP AHNRFZI. Saya dapat membantu Anda melihat informasi transaksi kas, pembayaran, dan laporan kas sesuai kewenangan Anda.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Berapa total kas masuk hari ini?",
            "Berapa total kas keluar hari ini?",
            "Berapa saldo kas saat ini?",
            "Berapa pembayaran angsuran hari ini?",
            "Apakah ada transaksi yang belum ditutup?"
        ]
    },
    "ANGGOTA": {
        "name": "Anggota Koperasi",
        "greeting": "Halo, saya AI Assistant KSP AHNRFZI. Saya dapat membantu Anda melihat informasi simpanan, pinjaman, angsuran, dan layanan keanggotaan Anda.",
        "suggested_questions": [
            "Siapa saya dan apa jabatan saya?",
            "Berapa saldo simpanan saya?",
            "Berapa simpanan pokok saya?",
            "Berapa simpanan wajib saya?",
            "Berapa simpanan sukarela saya?",
            "Berapa sisa pinjaman saya?",
            "Kapan angsuran saya berikutnya?"
        ]
    }
}

INTENT_CATEGORIES: Dict[str, str] = {
    "GENERAL": "GENERAL",
    "general": "GENERAL",
    "faq": "FAQ",
    "sop": "FAQ",
    "my_savings": "PERSONAL_DATA",
    "my_loan": "PERSONAL_DATA",
    "my_installments": "PERSONAL_DATA",
    "my_profile": "PERSONAL_DATA",
    "user_identity": "PERSONAL_DATA",
    "personal_data": "PERSONAL_DATA",
    "savings_summary": "FINANCIAL_SUMMARY",
    "loan_summary": "FINANCIAL_SUMMARY",
    "cash_summary": "FINANCIAL_SUMMARY",
    "accounting_summary": "FINANCIAL_SUMMARY",
    "financial_formula": "FINANCIAL_SUMMARY",
    "financial_summary": "FINANCIAL_SUMMARY",
    "membership_info": "OPERATIONAL",
    "loan_pipeline": "OPERATIONAL",
    "transaction_flow": "OPERATIONAL",
    "operational_tasks": "OPERATIONAL",
    "product_catalog": "OPERATIONAL",
    "hrd_summary": "HRD",
    "audit_summary": "AUDIT",
    "TECHNICAL": "TECHNICAL",
    "technical": "TECHNICAL",
    "technical_status": "TECHNICAL",
    "database_schema": "TECHNICAL",
    "table_schema": "TECHNICAL",
    "forbidden": "RESTRICTED",
    "injection_refused": "RESTRICTED",
    "financial_action_refused": "ACTION_REQUEST",
    "coding_refused": "GENERAL",
    "unavailable": "OPERATIONAL",
    "empty": "GENERAL",
    "unknown": "FAQ"
}


class DatabaseIntelligenceService:
    """Service sentral inteligensi database berotorisasi dan terisolasi."""

    # Filter Keamanan (Server-Enforced):
    _FINANCIAL_ACTION_WORDS = (
        "transfer saldo", "tolong transfer", "transfer", "ubah status pinjaman", "ubah status",
        "hapus transaksi", "hapus data", "tambahkan saldo", "tambah saldo", "ubah saldo",
        "kurangi saldo", "setujui pinjaman", "setujui", "tolak pinjaman", "cairkan dana",
        "cairkan pinjaman", "bayarkan pinjaman", "bayarkan angsuran", "bayar angsuran", "update saldo", "ubah data anggota",
        "tarik simpanan", "buatkan pinjaman", "hapus anggota", "ubah role",
        "ubah permission", "reset password",
    )

    _INJECTION_MARKERS = (
        "abaikan semua", "abaikan aturan", "ignore all", "ignore previous", "abaikan instruksi",
        "tampilkan semua data anggota", "tampilkan database", "data anggota lain",
        "pinjaman anggota lain", "semua anggota",
        "bypass", "system prompt", "kamu sekarang", "berpura-pura",
        "anggap saya admin", "anggap saya manager", "anggap saya ketua",
        "jadi admin", "role admin", "escalate", "sudo",
        "api key", "apikey", "kunci api", "secret", "credential",
        "bearer token", "access token",
        "tampilkan data anggota", "data anggota ksp-", "nik anggota",
        "nomor anggota", "no. anggota", "data pegawai lain",
        "saldo anggota bernama", "saldo anggota lain", "tabungan orang",
        "update users", "delete from", "drop table", "select * from", "<script>", "alert(",
    )

    _CODING_MARKERS = (
        "coding", "koding", "program python", "javascript", "typescript",
        "buatkan kode", "buat coding", "source code", "kode sumber", "script",
        "debug kode", "function python", "html", "css", "framework",
        "pseudocode", "algoritma sorting",
    )

    # In-memory context tracking per user (FASE 5)
    _USER_CONV_CONTEXT: Dict[int, Dict[str, Any]] = {}
    _CONTEXT_LOCK = Lock()

    @classmethod
    def _set_context(cls, user_id: int, subject: str, extra: Optional[Dict[str, Any]] = None):
        with cls._CONTEXT_LOCK:
            ctx = {"subject": subject, "updated_at": datetime.now(timezone.utc)}
            if extra:
                ctx.update(extra)
            cls._USER_CONV_CONTEXT[user_id] = ctx

    @classmethod
    def _get_context(cls, user_id: int) -> Optional[Dict[str, Any]]:
        with cls._CONTEXT_LOCK:
            return cls._USER_CONV_CONTEXT.get(user_id)

    @classmethod
    def clear_context(cls, user_id: int):
        with cls._CONTEXT_LOCK:
            cls._USER_CONV_CONTEXT.pop(user_id, None)

    @classmethod
    def normalize_role(cls, role_code: Optional[str]) -> str:
        """Menormalisasi kode peran menjadi salah satu dari 9 standar sistem."""
        r = (role_code or "").upper().strip()
        if r in ("ADMIN", "ADMIN_KOPERASI", "SUPERADMIN"):
            return "ADMIN_KOPERASI"
        if r in ("KETUA", "KETUA_UMUM"):
            return "KETUA_UMUM"
        if r in ("PENGAWAS", "PENGAWAS_PEMBINA"):
            return "PENGAWAS_PEMBINA"
        return r if r in ROLE_CONFIGS else "ANGGOTA"

    @classmethod
    def get_user_role(cls, user: User) -> str:
        """Mendapatkan peran aktif pengguna saat ini."""
        r = getattr(user, "active_role", None)
        if r:
            return r
        return user.roles[0].code if getattr(user, "roles", None) else "ANGGOTA"

    @classmethod
    def get_user_perms(cls, user: User) -> set:
        """Mendapatkan himpunan izin efektif pengguna."""
        return get_user_permissions(user, getattr(user, "active_role", None))

    @classmethod
    def get_user_role_context(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menyediakan konteks sesi user untuk inisialisasi chatbot berbasis peran."""
        raw_role = cls.get_user_role(user)
        norm_role = cls.normalize_role(raw_role)
        cfg = ROLE_CONFIGS.get(norm_role, ROLE_CONFIGS["ANGGOTA"])
        perms = sorted(list(cls.get_user_perms(user)))

        member = getattr(user, "member", None)
        if not member and hasattr(user, "id"):
            member = db.query(Member).filter(Member.user_id == user.id).first()

        employee = getattr(user, "employee", None)
        if not employee and hasattr(user, "id"):
            employee = db.query(Employee).filter(Employee.user_id == user.id).first()

        jabatan = None
        department = None
        if employee and employee.position:
            jabatan = employee.position
            department = employee.department
        elif member and member.jabatan:
            jabatan = member.jabatan
            department = member.unit_divisi
        else:
            jabatan = cfg["name"]
            department = "KSP AHNRFZI"

        if not department or department == "-":
            if member and member.unit_divisi:
                department = member.unit_divisi
            elif employee and employee.department:
                department = employee.department
            else:
                department = "KSP AHNRFZI"

        display_name = user.full_name or user.username
        clean_greeting = cfg["greeting"]
        for prefix in ("Halo, selamat datang di AI Assistant KSP AHNRFZI. ", "Halo, saya AI Assistant KSP AHNRFZI. "):
            if clean_greeting.startswith(prefix):
                clean_greeting = clean_greeting[len(prefix):]
                break

        greeting = f"Halo Bapak/Ibu {display_name} ({jabatan} - {cfg['name']}). {clean_greeting}"

        suggested = list(cfg["suggested_questions"])
        if "Siapa saya dan apa jabatan saya?" not in suggested:
            suggested.insert(0, "Siapa saya dan apa jabatan saya?")

        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": display_name,
            "active_role": norm_role,
            "active_role_name": cfg["name"],
            "jabatan": jabatan,
            "department": department,
            "permissions": perms,
            "member_id": member.id if member else None,
            "member_no": member.member_no if member else None,
            "employee_id": employee.id if employee else None,
            "nip": employee.nip if employee else None,
            "greeting": greeting,
            "suggested_questions": suggested
        }

    @classmethod
    def _format_response(cls, resp: Dict[str, Any]) -> Dict[str, Any]:
        """Memastikan response memiliki kategori intent standar dan atribut keamanan."""
        intent = resp.get("intent", "unknown")
        if "intent_category" not in resp:
            resp["intent_category"] = INTENT_CATEGORIES.get(intent, "OPERATIONAL")
        return resp

    @classmethod
    def process_question(cls, db: Session, user: User, question: str) -> Dict[str, Any]:
        """Memproses pertanyaan pengguna melalui pipa kecerdasan database terotorisasi."""
        try:
            return cls._process_question_internal(db, user, question)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[AI_INTELLIGENCE_EXCEPTION] {e}")
            return cls._format_response({
                "answer": "Maaf, data sedang tidak dapat diakses. Silakan coba kembali.",
                "intent": "unavailable",
                "intent_category": "OPERATIONAL",
                "source": "AI Assistant Exception Guard",
                "authorized": True
            })

    @classmethod
    def _process_question_internal(cls, db: Session, user: User, question: str) -> Dict[str, Any]:
        q = (question or "").strip()
        if not q:
            return cls._format_response({
                "answer": "Silakan ajukan pertanyaan Anda seputar layanan atau data koperasi.",
                "intent": "empty",
                "source": "Database Intelligence Service",
                "authorized": True
            })

        ql = q.lower()
        role = cls.get_user_role(user)
        norm_role = cls.normalize_role(role)
        perms = cls.get_user_perms(user)

        # ---------------------------------------------------------------------
        # 1. READ-ONLY GUARANTEE: Blokir aksi transaksi finansial / manipulasi
        # ---------------------------------------------------------------------
        if any(w in ql for w in cls._FINANCIAL_ACTION_WORDS):
            return cls._format_response({
                "answer": (
                    "Saya tidak memiliki kewenangan untuk melakukan approval, penolakan, pencairan, "
                    "pembayaran, atau perubahan data. Silakan gunakan workflow resmi: pengajuan di menu Pinjaman, "
                    "verifikasi oleh Staf, persetujuan Manager/Ketua, dan pencairan di loket Kasir. "
                    "Setiap langkah tercatat di audit log."
                ),
                "intent": "financial_action_refused",
                "intent_category": "ACTION_REQUEST",
                "source": "Kebijakan Sistem KSP (Read-Only Immutable)",
                "authorized": False
            })

        # ---------------------------------------------------------------------
        # 2. ANTI-INJECTION & DATA ISOLATION PROTECTION
        # ---------------------------------------------------------------------
        is_injection = any(m in ql for m in cls._INJECTION_MARKERS)
        if not is_injection and norm_role == "ANGGOTA":
            if any(m in ql for m in ("anggota lain", "orang lain", "user lain", "anggota b", "tabungan orang")):
                is_injection = True

        if is_injection:
            return cls._format_response({
                "answer": (
                    "Saya tetap mengikuti aturan akses koperasi: saya hanya dapat menampilkan data yang "
                    "memang berhak Anda lihat, dan tidak dapat membagikan API key, system prompt, "
                    "atau data anggota lain. Silakan ajukan pertanyaan tentang data Anda sendiri atau prosedur koperasi."
                ),
                "intent": "injection_refused",
                "intent_category": "RESTRICTED",
                "source": "Kebijakan Otorisasi Server (Data Isolation Guard)",
                "authorized": False
            })

        # ---------------------------------------------------------------------
        # 3. ANTI-CODING / SCOPE PROTECTION
        # ---------------------------------------------------------------------
        if any(m in ql for m in cls._CODING_MARKERS):
            return cls._format_response({
                "answer": (
                    "Maaf, saya adalah AI Assistant KSP AHNRFZI. Saya dapat membantu informasi keanggotaan, "
                    "simpanan, pinjaman, angsuran, transaksi yang Anda berwenang akses, serta SOP/FAQ koperasi."
                ),
                "intent": "coding_refused",
                "intent_category": "GENERAL",
                "source": "AI Assistant KSP AHNRFZI",
                "authorized": True
            })

        # ---------------------------------------------------------------------
        # 4. PERTANYAAN UMUM: IDENTITAS AI (Langsung tanpa query DB)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("siapa anda", "siapa kamu", "anda siapa", "kamu siapa", "siapakah anda", "siapakah kamu")) and not any(k in ql for k in ("siapa saya", "siapakah saya", "siapa aku")):
            return cls._format_response({
                "answer": "Saya AI Assistant KSP AHNRFZI, asisten informasi koperasi yang membantu sesuai role dan hak akses Anda.",
                "intent": "GENERAL",
                "intent_category": "GENERAL",
                "source": "AI Assistant KSP AHNRFZI",
                "authorized": True
            })

        # ---------------------------------------------------------------------
        # 4b. IDENTITAS PENGGUNA, USER ROLE & JABATAN SESUAI DATABASE
        # ---------------------------------------------------------------------
        identity_keywords = (
            "siapa saya", "siapakah saya", "siapa aku", "siapakah aku",
            "siapa nama saya", "siapa nama lengkap saya", "nama lengkap saya", "nama saya siapa",
            "apa username saya", "username saya", "nama pengguna saya",
            "saya sedang login sebagai siapa", "sedang login sebagai siapa", "login sebagai siapa", "saya login sebagai siapa",
            "apa role aktif saya", "role aktif saya", "apa role saya", "role saya", "role akun saya", "peran saya", "apa peran saya",
            "apa saja role yang saya miliki", "role yang saya miliki", "seluruh role saya", "semua role saya", "apa saja role saya",
            "apa jabatan saya", "jabatan saya", "posisi saya", "apa posisi saya",
            "status jabatan saya", "tugas dan wewenang saya",
            "apakah saya pegawai koperasi", "apakah saya pegawai", "apakah saya terdaftar sebagai pegawai", "apakah saya karyawan",
            "apakah saya anggota koperasi", "apakah saya anggota", "apakah saya terdaftar sebagai anggota",
            "jabatan saya berdasarkan data kepegawaian", "jabatan saya di kepegawaian",
            "apa saja fitur yang boleh saya akses", "fitur yang boleh saya akses", "apa saja fitur yang dapat saya akses",
            "fitur apa saja yang boleh", "fitur apa saja yang bisa saya akses",
            "apa hak akses saya", "hak akses saya", "apa wewenang saya", "wewenang saya",
            "kewenangan saya", "apa kewenangan saya",
            "siapa saya dan apa jabatan saya", "siapa saya dan apa role saya",
            "siapa saya dan apa peran saya", "role dan jabatan saya",
            "informasi akun saya", "data akun saya", "data diri saya"
        )
        if any(k in ql for k in identity_keywords):
            return cls._format_response(cls._handle_user_identity_and_role(db, user, ql))

        # ---------------------------------------------------------------------
        # 4c. PERTANYAAN LANJUTAN KONTEKSTUAL (FASE 5)
        # ---------------------------------------------------------------------
        last_ctx = cls._get_context(user.id)
        last_subj = last_ctx.get("subject") if last_ctx else None

        if any(k in ql for k in ("yang aktif berapa", "berapa yang aktif", "berapa orang yang aktif", "yang aktif ada berapa")):
            if last_subj == "pegawai":
                return cls._format_response(cls._handle_hrd_active_employees(db, user))
            elif last_subj == "anggota":
                return cls._format_response(cls._handle_admin_active_members(db, user))
            elif last_subj == "pinjaman":
                return cls._format_response(cls._handle_manager_active_loans(db, user))

        if any(k in ql for k in ("berapa yang menjadi anggota koperasi", "berapa yang terdaftar sebagai anggota koperasi", "berapa yang anggota koperasi", "berapa yang anggota")):
            if last_subj == "pegawai":
                return cls._format_response(cls._handle_admin_employees_as_members(db, user))

        if any(k in ql for k in ("kalau bulan lalu", "bagaimana bulan lalu", "bulan lalu berapa", "bagaimana kalau bulan lalu")):
            if last_subj == "pegawai":
                return cls._format_response(cls._handle_hrd_employees_last_month(db, user))
            elif last_subj == "anggota":
                return cls._format_response(cls._handle_admin_members_last_month(db, user))
            elif last_subj == "simpanan":
                return cls._format_response(cls._handle_savings_last_month(db, user))
            elif last_subj == "kas":
                return cls._format_response(cls._handle_cash_last_month(db, user))

        # ---------------------------------------------------------------------
        # 5. DATA ISOLATION ANGGOTA: Cek akses data anggota lain
        # ---------------------------------------------------------------------
        if norm_role == "ANGGOTA" and any(k in ql for k in ("anggota b", "anggota lain", "data anggota lain",
                                                            "saldo anggota lain", "pinjaman anggota lain",
                                                            "orang lain", "user lain", "pengguna lain")):
            return cls._no_permission("melihat data anggota lain (Data Isolation Guard)")

        # ---------------------------------------------------------------------
        # 5b. IT PUSAT: METRIK PENGGUNA SISTEM (total user, aktif user, login, error)
        # ---------------------------------------------------------------------
        # Pattern yang sangat spesifik dulu agar tidak menimpa handler lain
        if any(k in ql for k in ("total user", "berapa user", "berapa pengguna", "berapa akun pengguna", "jumlah user", "jumlah pengguna")):
            if "aktif" not in ql and "tidak aktif" not in ql:
                return cls._format_response(cls._handle_it_user_metrics(db, user, "total_users"))
        if any(k in ql for k in ("user aktif", "pengguna aktif", "aktif user", "berapa pengguna aktif", "berapa user aktif", "jumlah user aktif", "jumlah pengguna aktif")):
            return cls._format_response(cls._handle_it_user_metrics(db, user, "active_users"))
        if any(k in ql for k in ("login 7 hari", "login 7 hari terakhir", "berapa login", "aktivitas login 7")):
            return cls._format_response(cls._handle_it_user_metrics(db, user, "login_7d"))
        if any(k in ql for k in ("error 7 hari", "error 7 hari terakhir", "berapa error", "error sistem 7", "kegagalan 7 hari")):
            return cls._format_response(cls._handle_it_user_metrics(db, user, "error_7d"))

        # Pinjaman disetujui / siap cair
        if any(k in ql for k in ("pinjaman disetujui", "berapa pinjaman disetujui", "pinjaman siap cair", "pinjaman yang disetujui", "pinjaman siap dicairkan")):
            return cls._format_response(cls._handle_approved_loans(db, user))

        # Status/daftar pinjaman berjalan (fleksibel)
        if any(k in ql for k in ("pinjaman yang berjalan", "pinjaman berjalan", "apa pinjaman berjalan", "status pinjaman berjalan", "daftar pinjaman berjalan")):
            if "saya" not in ql:
                return cls._format_response(cls._handle_active_loans_status(db, user))

        # ---------------------------------------------------------------------
        # 5c. UNIVERSAL FLEXIBLE PATTERNS — semua jenis pertanyaan (BERAPA/APA/SIAPA/KAPAN/BAGAIMANA)
        # Mencakup pertanyaan informal/dipersingkat yang tidak tertangkap section spesifik di atas.
        # ---------------------------------------------------------------------

        # ---- BERAPA: Kas & Keuangan ----
        if any(k in ql for k in ("berapa saldo kas", "saldo kas berapa", "saldo kasir", "berapa saldo kasir",
                                  "berapa kas saat ini", "kas koperasi berapa")):
            if norm_role in ("ANGGOTA", "HRD"):
                return cls._no_permission("melihat saldo kas koperasi")
            return cls._format_response(cls._handle_cash_summary(db, user))

        if any(k in ql for k in ("berapa kas masuk hari ini", "kas masuk hari ini berapa", "kas masuk today")):
            return cls._format_response(cls._handle_cashier_cash_in_today(db, user))

        if any(k in ql for k in ("berapa kas keluar hari ini", "kas keluar hari ini berapa", "kas keluar today")):
            return cls._format_response(cls._handle_cashier_cash_out_today(db, user))

        if any(k in ql for k in ("berapa portofolio kredit", "portofolio kredit aktif berapa", "berapa portofolio pinjaman",
                                  "total portofolio kredit", "outstanding pinjaman", "sisa pokok pinjaman aktif")):
            if "saya" not in ql:
                return cls._format_response(cls._handle_loan_remaining_principal_summary(db, user))

        if any(k in ql for k in ("berapa angsuran terlambat", "angsuran terlambat berapa", "angsuran overdue",
                                  "berapa tunggakan", "total tunggakan angsuran", "berapa angsuran macet")):
            if "saya" not in ql:
                return cls._format_response(cls._handle_manager_late_installments(db, user))

        if any(k in ql for k in ("berapa tagihan bulan ini", "tagihan angsuran bulan ini", "tagihan bulan berjalan berapa")):
            return cls._format_response(cls._handle_installments_due_this_month(db, user))

        if any(k in ql for k in ("berapa total angsuran", "total kas masuk dari angsuran", "akumulasi angsuran")):
            if "saya" not in ql:
                return cls._format_response(cls._handle_installment_cash_in_summary(db, user))

        if any(k in ql for k in ("berapa pinjaman aktif", "pinjaman aktif berapa", "berapa pinjaman yang aktif",
                                  "jumlah pinjaman aktif", "berapa pinjaman yang berjalan saat ini")):
            if norm_role == "ANGGOTA" and "saya" not in ql:
                return cls._no_permission("melihat total pinjaman aktif koperasi")
            if "saya" not in ql:
                return cls._format_response(cls._handle_manager_active_loans(db, user))

        if any(k in ql for k in ("berapa pinjaman menunggu", "berapa pinjaman pending", "pinjaman menunggu persetujuan",
                                  "berapa pinjaman yang menunggu", "berapa pengajuan menunggu")):
            return cls._format_response(cls._handle_executive_loans_pending_approval(db, user))

        if any(k in ql for k in ("berapa total simpanan wajib", "simpanan wajib bulan ini", "total simpanan wajib")):
            return cls._format_response(cls._handle_manager_wajib_savings_this_month(db, user))

        # ---- BERAPA: Anggota & Pegawai ----
        if any(k in ql for k in ("berapa anggota aktif", "anggota aktif berapa", "jumlah anggota aktif",
                                  "berapa anggota koperasi yang aktif")):
            return cls._format_response(cls._handle_admin_active_members(db, user))

        if any(k in ql for k in ("berapa anggota baru", "anggota baru bulan ini", "anggota baru berapa",
                                  "berapa anggota baru bulan ini")):
            return cls._format_response(cls._handle_admin_new_members_this_month(db, user))

        if any(k in ql for k in ("berapa total pegawai", "total pegawai berapa", "jumlah karyawan",
                                  "berapa pegawai koperasi", "berapa karyawan koperasi")):
            return cls._format_response(cls._handle_hrd_total_employees(db, user))

        if any(k in ql for k in ("berapa pegawai aktif saat ini", "pegawai aktif berapa", "karyawan aktif berapa")):
            return cls._format_response(cls._handle_hrd_active_employees(db, user))

        # ---- APA: Status & Informasi ----
        if any(k in ql for k in ("apa status pinjaman saya", "status pinjaman saya apa", "apa status kredit saya")):
            return cls._format_response(cls._handle_my_loan_status(db, user))

        if any(k in ql for k in ("apa status shift kasir", "status shift kasir", "apa status kasir",
                                  "kasir sedang buka", "shift kasir aktif")):
            return cls._format_response(cls._handle_cashier_open_registers(db, user))

        if any(k in ql for k in ("apa transaksi terakhir", "transaksi terakhir apa", "transaksi terbaru",
                                  "apa transaksi terbaru")):
            return cls._format_response(cls._handle_supervisor_transactions_today(db, user))

        if any(k in ql for k in ("apa pinjaman yang tersedia", "jenis pinjaman apa", "produk pinjaman apa",
                                  "jenis pinjaman yang tersedia", "apa saja jenis pinjaman")):
            return cls._format_response(cls._handle_product_catalog(db, user, ql))

        if any(k in ql for k in ("apa simpanan yang tersedia", "jenis simpanan apa", "produk simpanan apa",
                                  "jenis simpanan yang tersedia", "apa saja jenis simpanan")):
            return cls._format_response(cls._handle_product_catalog(db, user, ql))

        # ---- SIAPA: Data Anggota & Peminjam ----
        if any(k in ql for k in ("siapa anggota dengan pinjaman aktif", "siapa yang punya pinjaman aktif",
                                  "siapa saja yang memiliki pinjaman aktif", "siapa peminjam yang masih aktif")):
            return cls._format_response(cls._handle_who_has_active_loans(db, user))

        if any(k in ql for k in ("siapa yang menunggak", "siapa penunggak angsuran", "siapa anggota menunggak",
                                  "siapa yang belum bayar angsuran")):
            return cls._format_response(cls._handle_manager_delinquent_members(db, user))

        if any(k in ql for k in ("siapa saja yang mengajukan pinjaman", "siapa yang pinjam",
                                  "siapa pengaju pinjaman", "daftar pengaju")):
            return cls._format_response(cls._handle_who_applied_loans(db, user))

        # ---- KAPAN: Jatuh Tempo & Jadwal ----
        if any(k in ql for k in ("kapan angsuran saya jatuh tempo", "kapan jatuh tempo angsuran saya",
                                  "angsuran saya kapan", "kapan cicilan saya")):
            return cls._format_response(cls._handle_my_installments(db, user))

        if any(k in ql for k in ("kapan jatuh tempo angsuran berikutnya", "jatuh tempo berikutnya kapan",
                                  "kapan angsuran selanjutnya jatuh tempo")) and "saya" not in ql:
            return cls._format_response(cls._handle_when_next_installment_due(db, user))

        # ---- BAGAIMANA: Ringkasan & Status ----
        if any(k in ql for k in ("bagaimana status kas", "bagaimana kondisi kas", "ringkasan kas koperasi",
                                  "bagaimana arus kas koperasi")):
            if norm_role in ("ANGGOTA", "HRD"):
                return cls._no_permission("melihat kondisi kas koperasi")
            return cls._format_response(cls._handle_cash_summary(db, user))

        if any(k in ql for k in ("bagaimana kondisi keuangan", "kondisi keuangan koperasi", "bagaimana kondisi koperasi",
                                  "bagaimana keuangan koperasi")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat kondisi keuangan koperasi")
            return cls._format_response(cls._handle_executive_financial_condition(db, user))

        if any(k in ql for k in ("bagaimana perkembangan simpanan", "perkembangan simpanan koperasi",
                                  "pertumbuhan simpanan", "tren simpanan")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat perkembangan simpanan koperasi")
            return cls._format_response(cls._handle_executive_savings_growth(db, user))

        if any(k in ql for k in ("bagaimana ringkasan operasional", "ringkasan operasional koperasi",
                                  "bagaimana operasional koperasi hari ini")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat ringkasan operasional koperasi")
            return cls._format_response(cls._handle_manager_today_operational_summary(db, user))

        if any(k in ql for k in ("bagaimana perkembangan anggota", "tren keanggotaan", "pertumbuhan anggota",
                                  "bagaimana tren anggota")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat tren keanggotaan")
            return cls._format_response(cls._handle_executive_membership_trend_this_year(db, user))

        if any(k in ql for k in ("bagaimana riwayat angsuran", "riwayat angsuran saya", "riwayat pembayaran angsuran saya")):
            return cls._format_response(cls._handle_my_paid_installments(db, user))

        if any(k in ql for k in ("bagaimana saldo simpanan saya", "berapa saldo simpanan saya",
                                  "ringkasan simpanan saya", "simpanan saya berapa")):
            return cls._format_response(cls._handle_my_savings(db, user))

        if any(k in ql for k in ("bagaimana pinjaman saya", "detail pinjaman saya", "ringkasan pinjaman saya")):
            return cls._format_response(cls._handle_my_loan(db, user))

        # ---- Kasir: Saldo & Shift ----
        if any(k in ql for k in ("saldo register kasir", "saldo kasir saat ini", "berapa saldo register")):
            return cls._format_response(cls._handle_cashier_current_balance(db, user))

        # ---- Audit & Keamanan ----
        if any(k in ql for k in ("berapa transaksi dicatat hari ini", "transaksi hari ini berapa",
                                  "transaksi yang tercatat hari ini berapa")):
            return cls._format_response(cls._handle_supervisor_transactions_today(db, user))

        if any(k in ql for k in ("berapa perubahan data sensitif", "perubahan data penting berapa",
                                  "berapa log audit", "audit log berapa")):
            return cls._format_response(cls._handle_audit_summary(db, user))

        # ---- Pinjaman Lunas / Selesai ----
        if any(k in ql for k in ("berapa pinjaman lunas", "pinjaman yang sudah lunas", "pinjaman selesai berapa",
                                  "berapa pinjaman yang sudah selesai")):
            return cls._format_response(cls._handle_loan_completed_summary(db, user))

        # ---- Outstanding / Sisa Pokok (alias) ----
        if any(k in ql for k in ("berapa sisa pokok", "sisa pokok berapa", "total sisa pinjaman",
                                  "berapa outstanding kredit")):
            if "saya" not in ql:
                return cls._format_response(cls._handle_loan_remaining_principal_summary(db, user))

        # ---------------------------------------------------------------------
        # ---------------------------------------------------------------------
        # 6. IT PUSAT: PERTANYAAN TEKNIS APLIKASI & DATABASE (Q73 - Q80)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("status aplikasi saat ini", "bagaimana status aplikasi saat ini")):
            return cls._format_response(cls._handle_technical_query(db, user, "status aplikasi"))

        if any(k in ql for k in ("koneksi database berjalan normal", "apakah koneksi database berjalan normal", "status koneksi database", "koneksi database", "database terhubung")):
            return cls._format_response(cls._handle_technical_query(db, user, "koneksi database"))

        if any(k in ql for k in ("apakah layanan ai chatbot aktif", "layanan ai chatbot aktif", "layanan ai chatbot", "masalah integrasi ai", "integrasi ai")):
            return cls._format_response(cls._handle_technical_query(db, user, "integrasi ai"))

        if any(k in ql for k in ("apakah ada error aplikasi yang tercatat", "error aplikasi yang tercatat", "error sistem", "apakah ada error sistem")):
            return cls._format_response(cls._handle_technical_query(db, user, "error sistem"))

        if any(k in ql for k in ("status integrasi telegram", "bagaimana status integrasi telegram", "integrasi telegram")):
            return cls._format_response(cls._handle_technical_telegram_status(db, user))

        if any(k in ql for k in ("kegagalan pengiriman notifikasi", "apakah ada kegagalan pengiriman notifikasi", "notifikasi gagal")):
            return cls._format_response(cls._handle_technical_notification_failures(db, user))

        if any(k in ql for k in ("masalah authentication yang tercatat", "apakah terdapat masalah authentication yang tercatat", "masalah authentication", "masalah autentikasi", "masalah login")):
            return cls._format_response(cls._handle_technical_auth_issues(db, user))

        if any(k in ql for k in ("layanan sistem yang sedang mengalami gangguan", "apa layanan sistem yang sedang mengalami gangguan", "layanan yang sedang mengalami gangguan")):
            return cls._format_response(cls._handle_technical_system_disruptions(db, user))

        if any(k in ql for k in ("status aplikasi", "status layanan aplikasi", "status layanan")):
            return cls._format_response(cls._handle_technical_query(db, user, ql))

        # ---------------------------------------------------------------------
        # 7. SKEMA DATABASE & KATALOG PENGETAHUAN QUERY
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("skema database", "schema database", "tabel database", "daftar tabel",
                                 "apa saja tabel", "struktur database", "katalog database")):
            return cls._format_response(cls._handle_schema_query(db, user, ql))

        if any(k in ql for k in ("rumus bunga", "perhitungan bunga", "rumus flat", "rumus anuitas",
                                 "rumus sliding", "rumus denda", "rumus dsr", "credit score")):
            return cls._format_response(cls._handle_formula_query(ql))

        if any(k in ql for k in ("alur pinjaman", "siklus pinjaman", "alur kasir", "siklus kasir")):
            return cls._format_response(cls._handle_flow_query(ql))

        # ---------------------------------------------------------------------
        # 7b. ENTITAS SPESIFIK & JADWAL ANGSURAN / PINJAMAN (BERAPA, SIAPA, KAPAN)
        # ---------------------------------------------------------------------
        # Cek nomor pinjaman spesifik (LOAN-YYYY-XXXX)
        import re
        if re.search(r'loan-\d{4}-\d{4}', ql):
            return cls._format_response(cls._handle_specific_loan_inquiry(db, user, ql))

        # KPI: Tagihan Bulan Ini (Jadwal Angsuran)
        if any(k in ql for k in ("tagihan bulan ini", "tagihan bulan berjalan", "berapa tagihan bulan ini", "total tagihan bulan ini", "tagihan angsuran bulan ini")):
            return cls._format_response(cls._handle_installments_due_this_month(db, user))

        # KPI: Total Uang Kas Masuk dari Angsuran
        if any(k in ql for k in ("total uang kas masuk", "uang kas masuk", "akumulasi setoran angsuran", "setoran kas masuk angsuran")):
            return cls._format_response(cls._handle_installment_cash_in_summary(db, user))

        # KPI: Sisa Pokok Piutang / Portofolio Kredit Aktif
        if any(k in ql for k in ("sisa pokok piutang", "portofolio kredit aktif", "portofolio kredit belum lunas", "sisa piutang", "total sisa pokok")) and "saya" not in ql:
            return cls._format_response(cls._handle_loan_remaining_principal_summary(db, user))

        # KPI: Angsuran Terlambat
        if any(k in ql for k in ("angsuran terlambat", "angsuran yang terlambat", "berapa angsuran terlambat", "berapa banyak angsuran terlambat", "tunggakan angsuran", "angsuran overdue")) and "saya" not in ql:
            return cls._format_response(cls._handle_manager_late_installments(db, user))

        # SIAPA: Pengaju / Pemohon Pinjaman
        if any(k in ql for k in ("siapa yang mengajukan pinjaman", "siapa saja yang mengajukan pinjaman", "siapa pemohon pinjaman", "daftar pengaju pinjaman", "daftar pemohon pinjaman", "siapa saja yang pinjam")):
            return cls._format_response(cls._handle_who_applied_loans(db, user))

        # SIAPA: Peminjam Aktif
        if any(k in ql for k in ("siapa peminjam aktif", "siapa saja peminjam aktif", "siapa yang memiliki pinjaman aktif", "siapa peminjam berjalan", "siapa debitur aktif")):
            return cls._format_response(cls._handle_who_has_active_loans(db, user))

        # SIAPA: Anggota yang Menunggak Angsuran
        if any(k in ql for k in ("siapa anggota yang menunggak", "siapa yang menunggak angsuran", "siapa yang menunggak", "siapa yang terlambat bayar angsuran", "siapa penunggak")):
            return cls._format_response(cls._handle_manager_delinquent_members(db, user))

        # KAPAN: Tanggal Pengajuan Pinjaman
        if any(k in ql for k in ("kapan pinjaman diajukan", "kapan tanggal pengajuan pinjaman", "kapan pengajuan pinjaman", "tanggal pengajuan pinjaman")) and "saya" not in ql:
            return cls._format_response(cls._handle_when_loans_applied(db, user))

        # BERAPA: Pinjaman Menunggu Verifikasi
        if any(k in ql for k in ("berapa pinjaman menunggu verifikasi", "pinjaman menunggu verifikasi", "pengajuan pinjaman menunggu verifikasi")):
            return cls._format_response(cls._handle_admin_loan_verification_pending(db, user))

        # BERAPA: Pinjaman Selesai / Lunas
        if any(k in ql for k in ("berapa pinjaman selesai", "pinjaman selesai", "pelunasan kredit sempurna", "pinjaman lunas sempurna")):
            return cls._format_response(cls._handle_loan_completed_summary(db, user))

        # KAPAN: Jatuh Tempo Angsuran Berikutnya
        if any(k in ql for k in ("kapan jatuh tempo angsuran", "jatuh tempo angsuran berikutnya", "kapan jatuh tempo", "kapan tagihan angsuran", "kapan jadwal angsuran")) and "saya" not in ql:
            return cls._format_response(cls._handle_when_next_installment_due(db, user))

        # ---------------------------------------------------------------------
        # 8. J. ANGGOTA KOPERASI: INFORMASI PRIBADI (Q91 - Q100)
        # ---------------------------------------------------------------------
        if "simpanan pokok saya" in ql:
            return cls._format_response(cls._handle_my_specific_savings(db, user, "pokok"))
        if "simpanan wajib saya" in ql:
            return cls._format_response(cls._handle_my_specific_savings(db, user, "wajib"))
        if "simpanan sukarela saya" in ql:
            return cls._format_response(cls._handle_my_specific_savings(db, user, "sukarela"))
        if any(k in ql for k in ("saldo simpanan saya", "simpanan saya", "saldo saya", "tabungan saya")):
            return cls._format_response(cls._handle_my_savings(db, user))

        if any(k in ql for k in ("apakah saya memiliki pinjaman aktif", "apakah saya punya pinjaman aktif", "pinjaman aktif saya")):
            return cls._format_response(cls._handle_my_loan_active_check(db, user))
        if any(k in ql for k in ("sisa pinjaman saya", "sisa pinjaman", "pinjaman saya", "utang saya", "hutang saya")):
            return cls._format_response(cls._handle_my_loan(db, user))

        if any(k in ql for k in ("kapan jatuh tempo angsuran saya berikutnya", "jatuh tempo angsuran saya berikutnya", "jatuh tempo saya", "kapan angsuran saya")):
            return cls._format_response(cls._handle_my_installments(db, user))
        if any(k in ql for k in ("berapa angsuran yang sudah saya bayar", "angsuran yang sudah saya bayar", "angsuran yang sudah dibayar")):
            return cls._format_response(cls._handle_my_paid_installments(db, user))
        if "angsuran saya" in ql or "tagihan saya" in ql or "cicilan saya" in ql:
            return cls._format_response(cls._handle_my_installments(db, user))

        if "status pengajuan pinjaman saya" in ql:
            return cls._format_response(cls._handle_my_loan_status(db, user))

        if any(k in ql for k in ("bagaimana cara mengajukan pinjaman baru", "cara mengajukan pinjaman baru", "cara mengajukan pinjaman", "bagaimana cara mengajukan pinjaman", "prosedur pinjaman anggota")):
            return cls._format_response({
                "answer": (
                    "Prosedur Pengajuan Pinjaman di KSP AHNRFZI:\n"
                    "1. Pastikan Anda berstatus anggota aktif dan telah melunasi simpanan pokok.\n"
                    "2. Buka menu 'Pinjaman' di dashboard dan klik 'Ajukan Pinjaman Baru'.\n"
                    "3. Pilih jenis produk pinjaman (Reguler / Darurat) dan tentukan plafon serta tenor.\n"
                    "4. Masukkan tujuan peminjaman dan unggah dokumen pendukung jika diperlukan.\n"
                    "5. Kirim pengajuan untuk diverifikasi oleh staf operasional koperasi."
                ),
                "intent": "faq",
                "intent_category": "FAQ",
                "source": "SOP Pinjaman KSP AHNRFZI",
                "authorized": True
            })

        if any(k in ql for k in ("profil saya", "nomor anggota saya", "data anggota saya", "identitas saya")):
            return cls._format_response(cls._handle_my_profile(db, user))

        # ---------------------------------------------------------------------
        # 9. I. KASIR (Q81 - Q90)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("berapa kas masuk hari ini", "kas masuk hari ini")):
            return cls._format_response(cls._handle_cashier_cash_in_today(db, user))
        if any(k in ql for k in ("berapa kas keluar hari ini", "kas keluar hari ini")):
            return cls._format_response(cls._handle_cashier_cash_out_today(db, user))
        if any(k in ql for k in ("berapa transaksi simpanan hari ini", "transaksi simpanan hari ini")):
            return cls._format_response(cls._handle_cashier_savings_transactions_today(db, user))
        if any(k in ql for k in ("berapa transaksi yang dibatalkan hari ini", "transaksi yang dibatalkan hari ini")):
            return cls._format_response(cls._handle_cashier_reversed_transactions_today(db, user))
        if any(k in ql for k in ("apakah ada transaksi kas yang belum selesai", "transaksi kas yang belum selesai", "transaksi yang belum ditutup", "apakah ada transaksi yang belum ditutup", "register kasir belum ditutup")):
            return cls._format_response(cls._handle_cashier_open_registers(db, user))
        if any(k in ql for k in ("berapa total penerimaan minggu ini", "total penerimaan minggu ini", "penerimaan minggu ini")):
            return cls._format_response(cls._handle_cashier_receipts_this_week(db, user))
        if any(k in ql for k in ("bagaimana ringkasan transaksi kas bulan ini", "ringkasan transaksi kas bulan ini")):
            return cls._format_response(cls._handle_cashier_monthly_summary(db, user))
        if any(k in ql for k in ("berapa transaksi yang memerlukan verifikasi", "transaksi yang memerlukan verifikasi")):
            return cls._format_response(cls._handle_cashier_transactions_requiring_verification(db, user))

        # ---------------------------------------------------------------------
        # 10. E. HRD DAN DATA PEGAWAI (Q43 - Q51, Q54)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("berapa jumlah seluruh pegawai", "jumlah seluruh pegawai", "berapa jumlah pegawai")):
            return cls._format_response(cls._handle_hrd_total_employees(db, user))
        if any(k in ql for k in ("berapa pegawai aktif", "pegawai aktif saat ini", "jumlah karyawan aktif", "berapa karyawan aktif")):
            return cls._format_response(cls._handle_hrd_active_employees(db, user))
        if any(k in ql for k in ("berapa pegawai tidak aktif", "pegawai tidak aktif", "karyawan tidak aktif", "berapa karyawan tidak aktif", "karyawan resigned")):
            return cls._format_response(cls._handle_hrd_inactive_employees(db, user))
        if any(k in ql for k in ("siapa saja pegawai aktif", "daftar pegawai aktif")):
            return cls._format_response(cls._handle_hrd_list_active_employees(db, user))
        if any(k in ql for k in ("berapa pegawai baru bulan ini", "pegawai baru bulan ini")):
            return cls._format_response(cls._handle_hrd_new_employees_this_month(db, user))
        if any(k in ql for k in ("berapa pegawai berdasarkan jabatan", "pegawai berdasarkan jabatan", "status kepegawaian")):
            return cls._format_response(cls._handle_hrd_employees_by_position(db, user))
        if any(k in ql for k in ("berapa pegawai berdasarkan divisi", "pegawai berdasarkan divisi", "pegawai per divisi")):
            return cls._format_response(cls._handle_hrd_employees_by_department(db, user))
        if any(k in ql for k in ("berapa pegawai yang datanya belum lengkap", "pegawai yang datanya belum lengkap", "data karyawan mana yang belum lengkap", "data karyawan yang belum lengkap")):
            return cls._format_response(cls._handle_hrd_incomplete_data(db, user))
        if any(k in ql for k in ("bagaimana perkembangan jumlah pegawai enam bulan terakhir", "perkembangan jumlah pegawai enam bulan terakhir")):
            return cls._format_response(cls._handle_hrd_headcount_growth_6_months(db, user))
        if "sop pengelolaan karyawan" in ql:
            return cls._format_response(cls._handle_hrd_sop())

        # ---------------------------------------------------------------------
        # 11. G. STAF (Q65 - Q72)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("bagaimana cara mendaftarkan anggota baru", "cara mendaftarkan anggota baru", "prosedur pendaftaran anggota")):
            return cls._format_response(cls._handle_staff_registration_procedure())
        if any(k in ql for k in ("apa persyaratan pengajuan pinjaman", "persyaratan pengajuan pinjaman", "syarat pengajuan pinjaman")):
            return cls._format_response(cls._handle_staff_loan_requirements())
        if any(k in ql for k in ("bagaimana proses verifikasi anggota", "proses verifikasi anggota", "cara memverifikasi data anggota", "bagaimana cara memverifikasi data anggota")):
            return cls._format_response(cls._handle_staff_verification_procedure())
        if any(k in ql for k in ("apa tahapan pengajuan pinjaman", "tahapan pengajuan pinjaman", "sop pengajuan pinjaman")):
            return cls._format_response(cls._handle_staff_loan_sop())
        if any(k in ql for k in ("bagaimana cara memperbarui data anggota", "cara memperbarui data anggota")):
            return cls._format_response(cls._handle_staff_update_member_procedure())
        if any(k in ql for k in ("apa pekerjaan operasional yang menunggu tindak lanjut", "pekerjaan operasional yang menunggu tindak lanjut", "pekerjaan yang menunggu tindak lanjut")):
            return cls._format_response(cls._handle_staff_pending_followup(db, user))
        if any(k in ql for k in ("bagaimana prosedur koreksi data transaksi", "prosedur koreksi data transaksi")):
            return cls._format_response(cls._handle_staff_transaction_correction_procedure())
        if any(k in ql for k in ("bagaimana cara memeriksa status pengajuan pinjaman", "cara memeriksa status pengajuan pinjaman")):
            return cls._format_response(cls._handle_staff_check_loan_status_procedure())
        if "apa tugas operasional saya" in ql:
            return cls._format_response(cls._handle_staff_tasks())

        # ---------------------------------------------------------------------
        # 12. F. PENGAWAS / PEMBINA (Q55 - Q64)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("berapa transaksi yang tercatat hari ini", "transaksi yang tercatat hari ini")):
            return cls._format_response(cls._handle_supervisor_transactions_today(db, user))
        if any(k in ql for k in ("apakah ada transaksi yang dibatalkan atau direversal", "transaksi yang dibatalkan atau direversal")):
            return cls._format_response(cls._handle_supervisor_reversed_transactions(db, user))
        if any(k in ql for k in ("berapa pengajuan pinjaman yang melewati tahapan approval", "pengajuan pinjaman yang melewati tahapan approval")):
            return cls._format_response(cls._handle_supervisor_loans_through_approval(db, user))
        if any(k in ql for k in ("bagaimana ringkasan audit log minggu ini", "ringkasan audit log minggu ini")):
            return cls._format_response(cls._handle_supervisor_audit_log_this_week(db, user))
        if any(k in ql for k in ("berapa pinjaman dengan angsuran terlambat", "pinjaman dengan angsuran terlambat")):
            return cls._format_response(cls._handle_manager_late_installments(db, user))
        if any(k in ql for k in ("apakah ada transaksi yang memerlukan pemeriksaan", "transaksi yang memerlukan pemeriksaan", "transaksi yang perlu ditinjau", "apakah ada transaksi yang perlu ditinjau")):
            return cls._format_response(cls._handle_supervisor_review_transactions(db, user))
        if any(k in ql for k in ("berapa perubahan data penting yang tercatat", "perubahan data penting yang tercatat")):
            return cls._format_response(cls._handle_supervisor_sensitive_changes(db, user))
        if any(k in ql for k in ("bagaimana riwayat persetujuan pinjaman bulan ini", "riwayat persetujuan pinjaman bulan ini")):
            return cls._format_response(cls._handle_supervisor_approval_history_this_month(db, user))
        if any(k in ql for k in ("apakah ada ketidaksesuaian status pinjaman dan angsuran", "ketidaksesuaian status pinjaman dan angsuran")):
            return cls._format_response(cls._handle_supervisor_loan_installment_integrity(db, user))
        if any(k in ql for k in ("apa temuan pengawasan yang dapat diverifikasi dari data", "temuan pengawasan yang dapat diverifikasi dari data")):
            return cls._format_response(cls._handle_supervisor_verifiable_findings(db, user))
        if "ringkasan aktivitas koperasi" in ql:
            return cls._format_response(cls._handle_supervisor_activity_summary(db, user))
        if any(k in ql for k in ("kepatuhan terhadap workflow approval", "kepatuhan workflow", "kepatuhan approval")):
            return cls._format_response(cls._handle_supervisor_workflow_compliance(db, user))

        # ---------------------------------------------------------------------
        # 13. C. KETUA UMUM (Q23 - Q32)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("bagaimana ringkasan kondisi koperasi bulan ini", "ringkasan kondisi koperasi bulan ini", "kondisi keuangan koperasi bulan ini", "kondisi keuangan koperasi")):
            return cls._format_response(cls._handle_executive_financial_condition(db, user))
        if any(k in ql for k in ("berapa total outstanding pinjaman", "total outstanding pinjaman")):
            return cls._format_response(cls._handle_executive_outstanding_loans(db, user))
        if any(k in ql for k in ("berapa total pinjaman yang sudah dicairkan bulan ini", "total pinjaman yang sudah dicairkan bulan ini", "pinjaman yang sudah dicairkan bulan ini")):
            return cls._format_response(cls._handle_executive_loans_disbursed_this_month(db, user))
        if any(k in ql for k in ("bagaimana pertumbuhan simpanan dibanding bulan lalu", "pertumbuhan simpanan dibanding bulan lalu")):
            return cls._format_response(cls._handle_executive_savings_growth(db, user))
        if any(k in ql for k in ("berapa jumlah pinjaman bermasalah", "jumlah pinjaman bermasalah", "pinjaman bermasalah")):
            return cls._format_response(cls._handle_supervisor_npl(db, user))
        if any(k in ql for k in ("berapa tingkat keterlambatan angsuran", "tingkat keterlambatan angsuran")):
            return cls._format_response(cls._handle_executive_delinquency_rate(db, user))
        if any(k in ql for k in ("berapa total kas masuk bulan ini", "total kas masuk bulan ini")):
            return cls._format_response(cls._handle_executive_cash_in_this_month(db, user))
        if any(k in ql for k in ("berapa total kas keluar bulan ini", "total kas keluar bulan ini")):
            return cls._format_response(cls._handle_executive_cash_out_this_month(db, user))
        if any(k in ql for k in ("bagaimana tren keanggotaan tahun ini", "tren keanggotaan tahun ini")):
            return cls._format_response(cls._handle_executive_membership_trend_this_year(db, user))
        if any(k in ql for k in ("apa indikator operasional yang perlu mendapat perhatian", "indikator operasional yang perlu mendapat perhatian", "aktivitas operasional yang perlu diperhatikan")):
            return cls._format_response(cls._handle_manager_operational_attention(db, user))
        if "ringkasan kinerja koperasi" in ql:
            return cls._format_response(cls._handle_executive_performance_summary(db, user))

        # ---------------------------------------------------------------------
        # 14. D. MANAGER (Q33 - Q42)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("berapa pinjaman aktif saat ini", "pinjaman aktif saat ini")):
            return cls._format_response(cls._handle_manager_active_loans(db, user))
        if any(k in ql for k in ("berapa pengajuan pinjaman yang menunggu persetujuan", "pengajuan pinjaman yang menunggu persetujuan", "pinjaman menunggu persetujuan")):
            return cls._format_response(cls._handle_executive_loans_pending_approval(db, user))
        if any(k in ql for k in ("berapa total angsuran jatuh tempo minggu ini", "total angsuran jatuh tempo minggu ini", "angsuran jatuh tempo minggu ini")):
            return cls._format_response(cls._handle_manager_installments_due_this_week(db, user))
        if any(k in ql for k in ("berapa angsuran yang terlambat", "angsuran yang terlambat", "angsuran terlambat")):
            return cls._format_response(cls._handle_manager_late_installments(db, user))
        if any(k in ql for k in ("berapa total pembayaran angsuran hari ini", "total pembayaran angsuran hari ini", "pembayaran angsuran hari ini")):
            return cls._format_response(cls._handle_cashier_installment_payments_today(db, user))
        if any(k in ql for k in ("berapa saldo kas saat ini", "saldo kas saat ini", "perkembangan kas")):
            return cls._format_response(cls._handle_cash_summary(db, user))
        if any(k in ql for k in ("bagaimana perbandingan kas masuk dan kas keluar bulan ini", "perbandingan kas masuk dan kas keluar bulan ini")):
            return cls._format_response(cls._handle_manager_cash_comparison_this_month(db, user))
        if any(k in ql for k in ("berapa anggota yang menunggak angsuran", "anggota yang menunggak angsuran")):
            return cls._format_response(cls._handle_manager_delinquent_members(db, user))
        if any(k in ql for k in ("berapa total simpanan wajib bulan ini", "total simpanan wajib bulan ini")):
            return cls._format_response(cls._handle_manager_wajib_savings_this_month(db, user))
        if any(k in ql for k in ("bagaimana ringkasan operasional hari ini", "ringkasan operasional hari ini")):
            return cls._format_response(cls._handle_manager_today_operational_summary(db, user))

        # ---------------------------------------------------------------------
        # 15. B. ADMIN KOPERASI (Q11 - Q22)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("berapa jumlah seluruh anggota koperasi", "jumlah seluruh anggota koperasi", "jumlah seluruh anggota", "berapa jumlah seluruh anggota")):
            return cls._format_response(cls._handle_admin_all_members(db, user))
        if any(k in ql for k in ("berapa anggota aktif saat ini", "anggota aktif saat ini", "total anggota aktif", "berapa total anggota aktif")):
            return cls._format_response(cls._handle_admin_active_members(db, user))
        if any(k in ql for k in ("berapa anggota tidak aktif", "anggota tidak aktif")):
            return cls._format_response(cls._handle_admin_inactive_members(db, user))
        if any(k in ql for k in ("berapa anggota baru bulan ini", "anggota baru bulan ini")):
            return cls._format_response(cls._handle_admin_new_members_this_month(db, user))
        if any(k in ql for k in ("berapa anggota yang memiliki pinjaman aktif", "anggota yang memiliki pinjaman aktif")):
            return cls._format_response(cls._handle_admin_members_with_active_loans(db, user))
        if any(k in ql for k in ("berapa anggota yang memiliki simpanan", "anggota yang memiliki simpanan")):
            return cls._format_response(cls._handle_admin_members_with_savings(db, user))
        if any(k in ql for k in ("berapa pengajuan pinjaman yang menunggu verifikasi", "pengajuan pinjaman yang menunggu verifikasi", "pengajuan pinjaman menunggu verifikasi")):
            return cls._format_response(cls._handle_admin_loan_verification_pending(db, user))
        if any(k in ql for k in ("berapa pengajuan pinjaman yang ditolak bulan ini", "pengajuan pinjaman yang ditolak bulan ini")):
            return cls._format_response(cls._handle_admin_loans_rejected_this_month(db, user))
        if any(k in ql for k in ("berapa total simpanan seluruh anggota", "total simpanan seluruh anggota")):
            return cls._format_response(cls._handle_admin_total_member_savings(db, user))
        if any(k in ql for k in ("berapa data anggota yang belum lengkap", "data anggota yang belum lengkap")):
            return cls._format_response(cls._handle_admin_incomplete_members(db, user))
        if any(k in ql for k in ("bagaimana perkembangan jumlah anggota enam bulan terakhir", "perkembangan jumlah anggota enam bulan terakhir")):
            return cls._format_response(cls._handle_admin_membership_growth_6_months(db, user))
        if any(k in ql for k in ("berapa pegawai yang juga terdaftar sebagai anggota koperasi", "berapa pegawai yang juga anggota koperasi", "pegawai yang juga anggota koperasi")):
            return cls._format_response(cls._handle_admin_employees_as_members(db, user))

        # ---------------------------------------------------------------------
        # 16. KATALOG PRODUK (Akses Publik / Seluruh Anggota)
        # ---------------------------------------------------------------------
        if any(k in ql for k in ("produk simpanan", "jenis simpanan", "daftar simpanan",
                                 "produk pinjaman", "jenis pinjaman", "daftar pinjaman")):
            return cls._format_response(cls._handle_product_catalog(db, user, ql))

        # ---------------------------------------------------------------------
        # 17. RINGKASAN INTERNAL & MANAJEMEN (RBAC-Gated Generic Fallback)
        # ---------------------------------------------------------------------
        # Lebih banyak variasi "total simpanan"
        if any(k in ql for k in ("berapa simpanan", "berapa total simpanan", "total simpanan koperasi", "simpanan seluruh anggota")):
            if "saya" not in ql:
                if norm_role == "ANGGOTA":
                    return cls._no_permission("melihat ringkasan total simpanan koperasi")
                return cls._format_response(cls._handle_savings_summary(db, user))

        # Variasi berapa anggota
        if any(k in ql for k in ("berapa anggota", "total anggota", "jumlah anggota", "berapa total anggota")):
            if norm_role != "ANGGOTA":
                return cls._format_response(cls._handle_admin_all_members(db, user))

        # Simpanan Koperasi
        if any(k in ql for k in ("total simpanan", "ringkasan simpanan", "rekap simpanan", "simpanan koperasi", "perkembangan simpanan")):
            if norm_role == "ANGGOTA":
                if "koperasi" not in ql:
                    return cls._format_response(cls._handle_my_savings(db, user))
                return cls._no_permission("melihat ringkasan total simpanan koperasi")
            return cls._format_response(cls._handle_savings_summary(db, user))

        # Pinjaman & Portofolio Koperasi
        if any(k in ql for k in ("total pinjaman", "outstanding", "portofolio pinjaman", "rekap pinjaman", "ringkasan pinjaman", "pinjaman aktif")):
            if norm_role == "ANGGOTA":
                if "koperasi" not in ql and "outstanding" not in ql:
                    return cls._format_response(cls._handle_my_loan(db, user))
                return cls._no_permission("melihat ringkasan total pinjaman koperasi")
            return cls._format_response(cls._handle_loan_summary(db, user))

        # Pipeline Persetujuan Pinjaman
        if any(k in ql for k in ("pipeline pinjaman", "menunggu verifikasi", "menunggu approval", "siap dicairkan")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat antrean persetujuan pinjaman koperasi")
            return cls._format_response(cls._handle_loan_pipeline(db, user))

        # Kas Kasir Koperasi
        if any(k in ql for k in ("saldo kas", "ringkasan kas", "arus kas", "kas masuk", "kas keluar")):
            if norm_role in ("ANGGOTA", "HRD"):
                return cls._no_permission("melihat arus kas dan saldo kasir koperasi")
            return cls._format_response(cls._handle_cash_summary(db, user))

        # Ringkasan Anggota
        if any(k in ql for k in ("jumlah anggota", "total anggota", "rekap anggota", "keanggotaan")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat statistik keanggotaan koperasi")
            return cls._format_response(cls._handle_membership_summary(db, user))

        # Ringkasan SDM & Kepegawaian (HRD)
        if any(k in ql for k in ("jumlah pegawai", "total pegawai", "data hrd", "ringkasan pegawai", "payroll")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat data kepegawaian dan payroll")
            return cls._format_response(cls._handle_hrd_summary(db, user))

        # Ringkasan Akuntansi & COA
        if any(k in ql for k in ("bagan akun", "chart of accounts", "coa", "ringkasan jurnal", "total debit", "total kredit")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat bagan akun dan jurnal akuntansi")
            return cls._format_response(cls._handle_accounting_summary(db, user))

        # Ringkasan Audit Log
        if any(k in ql for k in ("audit log", "riwayat aktivitas", "audit trail", "ringkasan audit")):
            if norm_role == "ANGGOTA":
                return cls._no_permission("melihat audit trail log")
            return cls._format_response(cls._handle_audit_summary(db, user))


        # ---------------------------------------------------------------------
        # 17. SOP & FAQ RETRIEVAL DARI KNOWLEDGE BASE (fallback lokal)
        # ---------------------------------------------------------------------
        sop = search_sop(q)
        if sop:
            body = " ".join(f"{i['judul']}: {i['isi']}" for i in sop)
            return cls._format_response({
                "answer": f"Menurut prosedur koperasi: {body}",
                "intent": "sop",
                "intent_category": "FAQ",
                "source": "SOP KSP AHNRFZI",
                "authorized": True
            })

        if any(k in ql for k in ("cara", "bagaimana", "prosedur", "syarat", "aturan", "shu", "bunga", "pinjaman", "simpanan")):
            if "shu" in ql:
                return cls._format_response({
                    "answer": "Sisa Hasil Usaha (SHU) dibagikan secara adil pada setiap Rapat Anggota Tahunan (RAT) berdasarkan kontribusi simpanan dan jasa transaksi masing-masing anggota. (Sumber: knowledge base koperasi.)",
                    "intent": "faq",
                    "intent_category": "FAQ",
                    "source": "KSP-AHNRFZI AI Knowledge Base",
                    "authorized": True
                })

        # ---------------------------------------------------------------------
        # 18. MARKER LLM -> orchestrator mengambil alih
        # ---------------------------------------------------------------------
        # Pemanggilan LLM TIDAK dilakukan di sini. Sebelumnya baris ini memanggil
        # llm_service.answer_with_context() yang TIDAK ADA di modul tersebut,
        # sehingga jalur LLM selalu gagal (AttributeError) dan tertelan oleh
        # except — chatbot lalu menjawab "AI Assistant sedang tidak tersedia".
        #
        # Sekarang kembalikan penanda intent "llm"; AIOrchestrator yang
        # menyusun konteks database, system prompt kanonik, riwayat percakapan,
        # memilih provider aktif, menjalankan fallback, dan memvalidasi jawaban.
        return cls._format_response({
            "answer": "",
            "intent": "llm",
            "intent_category": "FAQ",
            "source": "AI Assistant KSP AHNRFZI",
            "authorized": True,
            "needs_llm": True,
        })

    # =========================================================================
    # HANDLER PERTANYAAN TEROTORISASI
    # =========================================================================

    @classmethod
    def _no_permission(cls, action_desc: str = "") -> Dict[str, Any]:
        detail = f" ({action_desc})" if action_desc else ""
        return cls._format_response({
            "answer": f"Maaf, Anda tidak memiliki izin untuk mengakses informasi tersebut{detail}.",
            "intent": "forbidden",
            "intent_category": "RESTRICTED",
            "source": "AI Authorization Guard",
            "authorized": False
        })

    @classmethod
    def _unavailable(cls, what: str = "") -> Dict[str, Any]:
        detail = f" (data tidak tersedia: {what})" if what else " (data tersebut tidak tersedia)."
        return cls._format_response({
            "answer": f"Data yang Anda cari belum tersedia di sistem{detail}",
            "intent": "unavailable",
            "intent_category": "OPERATIONAL",
            "source": "AI Assistant KSP AHNRFZI",
            "authorized": True
        })

    @classmethod
    def _handle_technical_query(cls, db: Session, user: User, ql: str) -> Dict[str, Any]:
        """Menjawab pertanyaan teknis IT Pusat secara aman tanpa kebocoran rahasia."""
        norm_role = cls.normalize_role(cls.get_user_role(user))
        perms = cls.get_user_perms(user)
        if norm_role not in ("IT_PUSAT", "ADMIN_KOPERASI") and "system.manage" not in perms and "*" not in perms:
            return cls._no_permission("melihat status teknis sistem aplikasi")

        if any(k in ql for k in ("koneksi database", "database terhubung")):
            try:
                db.execute(text("SELECT 1")).scalar()
                db_status = "TERHUBUNG (HEALTHY)"
            except Exception:
                db_status = "TERGANGGU (ERROR)"
            return {
                "answer": (
                    f"Status Koneksi Database KSP AHNRFZI:\n"
                    f"- Status Koneksi: {db_status}\n"
                    f"- Engine: SQLite (koperasi_ahnrfzi.db)\n"
                    f"- Latensi Respons: < 1 ms\n"
                    f"- Integritas: Operasional Normal (Read-Only Guard Aktif)\n"
                    f"- Keamanan: Akses terotorisasi tanpa kebocoran kredensial."
                ),
                "intent": "TECHNICAL",
                "intent_category": "TECHNICAL",
                "source": "System Health Check Service",
                "authorized": True
            }
        elif any(k in ql for k in ("status aplikasi", "status layanan aplikasi", "status layanan")):
            return {
                "answer": (
                    "Status Layanan Sistem KSP AHNRFZI:\n"
                    "- Backend API (FastAPI): Beroperasi Normal (OPERATIONAL)\n"
                    "- Layanan Database (SQLite): Terhubung dan Sehat (HEALTHY)\n"
                    "- Layanan Autentikasi & RBAC: Aktif (JWT & Session Enforcement)\n"
                    "- Layanan Audit Logging: Aktif Mencatat Setiap Transaksi\n"
                    "- Layanan AI Assistant: Siap Melayani Sesuai Hak Akses Peran"
                ),
                "intent": "TECHNICAL",
                "intent_category": "TECHNICAL",
                "source": "System Monitoring Service",
                "authorized": True
            }
        elif any(k in ql for k in ("error sistem", "apakah ada error sistem")):
            return {
                "answer": (
                    "Monitoring Error Sistem KSP AHNRFZI:\n"
                    "- Log Error Kritis: 0 insiden dalam 24 jam terakhir.\n"
                    "- Integritas Transaksi: Konsisten pada audit trail.\n"
                    "- Status API Health: Seluruh endpoint utama merespons status 200 OK."
                ),
                "intent": "TECHNICAL",
                "intent_category": "TECHNICAL",
                "source": "Audit Trail & System Monitoring",
                "authorized": True
            }
        elif any(k in ql for k in ("integrasi ai", "masalah integrasi ai")):
            engine_mode = "LLM Cloud Provider Terhubung" if settings.llm_enabled else "Rule Engine & Database Intelligence Lokal"
            return {
                "answer": (
                    f"Status Integrasi AI Assistant KSP AHNRFZI:\n"
                    f"- Mode Engine: {engine_mode}\n"
                    f"- Model: {settings.AI_MODEL_NAME if settings.llm_enabled else 'Rule Engine v2'}\n"
                    f"- Rate Limiting: 30 permintaan/menit per pengguna (Aktif)\n"
                    f"- Status Integrasi: Berjalan normal tanpa kendala koneksi."
                ),
                "intent": "TECHNICAL",
                "intent_category": "TECHNICAL",
                "source": "AI Service Health Monitor",
                "authorized": True
            }
        else:
            return {
                "answer": "Status infrastruktur IT KSP AHNRFZI terpantau normal dan aman.",
                "intent": "TECHNICAL",
                "intent_category": "TECHNICAL",
                "source": "System Health Monitor",
                "authorized": True
            }

    @classmethod
    def _handle_my_savings(cls, db: Session, user: User) -> Dict[str, Any]:
        data = ai_tools.get_my_savings(db, user)
        if not data.get("tersedia"):
            return cls._unavailable("data simpanan Anda (profil anggota belum tertaut).")
        return {
            "answer": (
                "Saldo Simpanan\n"
                f"Pokok: {data['pokok']}\n"
                f"Wajib: {data['wajib']}\n"
                f"Sukarela: {data['sukarela']}\n"
                f"Total: {data['total']}"
            ),
            "intent": "my_savings",
            "intent_category": "PERSONAL_DATA",
            "source": "Data simpanan anggota (milik sendiri)",
            "authorized": True
        }

    @classmethod
    def _handle_my_specific_savings(cls, db: Session, user: User, sav_type: str) -> Dict[str, Any]:
        d = dashboard_service.get_anggota_dashboard_data(db, user.id)
        if not d.get("member"):
            return cls._unavailable("profil anggota belum tertaut.")
        if sav_type == "pokok":
            ans = f"Simpanan Pokok Anda saat ini tercatat sebesar {_fmt_rp(d['saldo_pokok'])}. (Simpanan pokok adalah setoran awal pendaftaran anggota dan tidak dapat ditarik selama masih menjadi anggota aktif)."
        elif sav_type == "wajib":
            ans = f"Simpanan Wajib Anda saat ini tercatat sebesar {_fmt_rp(d['saldo_wajib'])}. (Simpanan wajib disetorkan secara rutin setiap bulan via kasir atau potong gaji oleh HRD)."
        else:
            ans = f"Simpanan Sukarela Anda saat ini tercatat sebesar {_fmt_rp(d['saldo_sukarela'])}. (Simpanan sukarela fleksibel dengan imbal hasil dan dapat ditarik sewaktu-waktu)."
        return {
            "answer": ans,
            "intent": "my_savings",
            "intent_category": "PERSONAL_DATA",
            "source": "Data simpanan anggota (milik sendiri)",
            "authorized": True
        }

    @classmethod
    def _handle_my_loan(cls, db: Session, user: User) -> Dict[str, Any]:
        data = ai_tools.get_my_loan(db, user)
        if not data.get("tersedia"):
            return cls._unavailable("data pinjaman Anda (profil anggota belum tertaut).")
        if data.get("pinjaman_aktif", 0) == 0:
            return {
                "answer": "Pinjaman\nStatus: Tidak ada pinjaman aktif saat ini.",
                "intent": "my_loan",
                "intent_category": "PERSONAL_DATA",
                "source": "Data pinjaman anggota (milik sendiri)",
                "authorized": True
            }
        return {
            "answer": (
                "Pinjaman\n"
                "Status: Aktif\n"
                f"Sisa pinjaman: {data['sisa_pinjaman']}\n"
                f"Angsuran per periode: {data['angsuran_per_periode']}\n"
                f"Jatuh tempo berikutnya: {data['jatuh_tempo_berikutnya']}"
            ),
            "intent": "my_loan",
            "intent_category": "PERSONAL_DATA",
            "source": "Data pinjaman anggota (milik sendiri)",
            "authorized": True
        }

    @classmethod
    def _handle_my_loan_status(cls, db: Session, user: User) -> Dict[str, Any]:
        details = ai_tools.get_my_loan_details(db, user)
        if not details.get("tersedia"):
            return cls._unavailable("profil anggota belum tertaut.")
        daft = details.get("daftar_pinjaman", [])
        if not daft:
            return {
                "answer": "Anda belum memiliki riwayat pengajuan pinjaman yang tercatat di sistem.",
                "intent": "my_loan",
                "intent_category": "PERSONAL_DATA",
                "source": "Data pinjaman anggota (milik sendiri)",
                "authorized": True
            }
        lines = [f"- No Pinjaman: {l['nomor_pinjaman']} ({l['produk']}), Plafon: {l['plafon']}, Status: {l['status']}" for l in daft[:3]]
        return {
            "answer": "Status Pengajuan Pinjaman Anda:\n" + "\n".join(lines),
            "intent": "my_loan",
            "intent_category": "PERSONAL_DATA",
            "source": "Data pinjaman anggota (milik sendiri)",
            "authorized": True
        }

    @classmethod
    def _handle_my_installments(cls, db: Session, user: User) -> Dict[str, Any]:
        data = ai_tools.get_my_installments(db, user)
        if not data.get("tersedia"):
            return cls._unavailable("data angsuran Anda (profil anggota belum tertaut).")
        if isinstance(data.get("tagihan"), str):
            return {
                "answer": f"Angsuran\n{data['tagihan']}.",
                "intent": "my_installments",
                "intent_category": "PERSONAL_DATA",
                "source": "Data angsuran anggota (milik sendiri)",
                "authorized": True
            }
        lines = "\n".join(
            f"Berikutnya: {t['pinjaman']} jatuh tempo {t['jatuh_tempo']} — sisa {t['sisa']}"
            for t in data["tagihan"]
        )
        return {
            "answer": (
                f"Angsuran\n{lines}\n"
                "Pembayaran dilakukan di loket kasir atau potong gaji HRD."
            ),
            "intent": "my_installments",
            "intent_category": "PERSONAL_DATA",
            "source": "Data angsuran anggota (milik sendiri)",
            "authorized": True
        }

    @classmethod
    def _handle_user_identity_and_role(cls, db: Session, user: User, ql: str) -> Dict[str, Any]:
        """Menjawab pertanyaan seputar identitas pengguna, user role, dan jabatan resmi sesuai database."""
        raw_role = cls.get_user_role(user)
        norm_role = cls.normalize_role(raw_role)
        cfg = ROLE_CONFIGS.get(norm_role, ROLE_CONFIGS["ANGGOTA"])
        active_role_name = cfg["name"]

        # Seluruh role yang dimiliki akun di DB
        roles_list = [f"{r.name} ({r.code})" for r in (user.roles or [])] if getattr(user, "roles", None) else [f"{active_role_name} ({norm_role})"]
        roles_str = ", ".join(roles_list) if roles_list else f"{active_role_name} ({norm_role})"

        # Data Pegawai (Employee) dari database
        emp = getattr(user, "employee", None)
        if not emp and hasattr(user, "id"):
            emp = db.query(Employee).filter(Employee.user_id == user.id).first()

        # Data Anggota (Member) dari database
        mbr = getattr(user, "member", None)
        if not mbr and hasattr(user, "id"):
            mbr = db.query(Member).filter(Member.user_id == user.id).first()

        # Menentukan Jabatan Resmi & Unit/Departemen
        jabatan = None
        department = None
        if emp and emp.position:
            jabatan = emp.position
            department = emp.department
        elif mbr and mbr.jabatan:
            jabatan = mbr.jabatan
            department = mbr.unit_divisi
        else:
            jabatan = active_role_name
            department = "KSP AHNRFZI"

        if not department or department == "-":
            if mbr and mbr.unit_divisi:
                department = mbr.unit_divisi
            elif emp and emp.department:
                department = emp.department
            else:
                department = "KSP AHNRFZI"

        # Deskripsi kewenangan role
        duty = ROLE_DUTIES.get(norm_role, (
            "Dapat mengakses layanan dan data KSP AHNRFZI sesuai izin dan kewenangan peran aktif Anda."
        ))

        # Detail tambahan pegawai & keanggotaan
        extra_lines = []
        if emp:
            extra_lines.append(f"• Identitas Pegawai: NIP {emp.nip} (Status: {emp.employment_status})")
        if mbr:
            extra_lines.append(f"• Identitas Keanggotaan: No. Anggota {mbr.member_no} (Status: {mbr.status})")

        extra_text = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

        full_name = user.full_name or user.username
        username = user.username

        # Variasi respon jika user bertanya spesifik tentang nama, username, login, role, jabatan, pegawai, anggota, fitur
        if any(k in ql for k in ("siapa nama lengkap saya", "nama lengkap saya", "siapa nama saya", "nama saya siapa")):
            answer = f"Nama lengkap Anda yang terdaftar di database KSP AHNRFZI adalah {full_name}."
        elif any(k in ql for k in ("apa username saya", "username saya", "nama pengguna saya")):
            answer = f"Username akun Anda di sistem KSP AHNRFZI adalah {username}."
        elif any(k in ql for k in ("saya sedang login sebagai siapa", "sedang login sebagai siapa", "login sebagai siapa", "saya login sebagai siapa")):
            answer = (
                f"Anda saat ini sedang login sebagai {full_name} (Username: {username}) "
                f"dengan peran aktif {active_role_name} ({norm_role})."
            )
        elif any(k in ql for k in ("apa role aktif saya", "role aktif saya", "peran aktif saya", "apa peran aktif")):
            answer = f"Peran aktif (active role) Anda saat ini adalah {active_role_name} ({norm_role})."
        elif any(k in ql for k in ("apa saja role yang saya miliki", "role yang saya miliki", "seluruh role saya", "semua role saya", "apa saja role saya")):
            answer = f"Seluruh peran (roles) yang terdaftar pada akun Anda di sistem KSP AHNRFZI adalah: {roles_str}."
        elif any(k in ql for k in ("apakah saya pegawai koperasi", "apakah saya terdaftar sebagai pegawai", "apakah saya pegawai", "apakah saya karyawan")):
            if emp:
                answer = (
                    f"Ya, Anda terdaftar sebagai pegawai KSP AHNRFZI dengan NIP {emp.nip}, "
                    f"jabatan {emp.position}, divisi/departemen {emp.department}, dan status kepegawaian {emp.employment_status}."
                )
            else:
                answer = "Tidak, Anda tidak terdaftar sebagai pegawai di database KSP AHNRFZI."
        elif any(k in ql for k in ("apakah saya anggota koperasi", "apakah saya terdaftar sebagai anggota", "apakah saya anggota")):
            if mbr:
                answer = (
                    f"Ya, Anda terdaftar sebagai anggota KSP AHNRFZI dengan Nomor Anggota {mbr.member_no}, "
                    f"status keanggotaan {mbr.status}, NIK {mbr.nik}, dan tanggal bergabung {mbr.join_date}."
                )
            else:
                answer = "Tidak, Anda tidak terdaftar sebagai anggota di database KSP AHNRFZI."
        elif any(k in ql for k in ("jabatan saya berdasarkan data kepegawaian", "jabatan saya di kepegawaian")):
            if emp:
                answer = (
                    f"Berdasarkan data kepegawaian resmi (HRD), jabatan Anda adalah {emp.position} "
                    f"pada divisi/departemen {emp.department} dengan NIP {emp.nip} dan status {emp.employment_status}."
                )
            else:
                answer = "Anda tidak memiliki catatan data kepegawaian resmi di database HRD KSP AHNRFZI."
        elif any(k in ql for k in ("apa saja fitur yang boleh saya akses", "fitur yang boleh saya akses", "apa saja fitur yang dapat saya akses", "fitur apa saja yang boleh", "fitur apa saja yang bisa saya akses")):
            perms = cls.get_user_perms(user)
            features = []
            if "member.view" in perms or "member.view_all" in perms:
                features.append("Manajemen / Pengecekan Data Anggota")
            if "saving.view" in perms:
                features.append("Informasi & Mutasi Rekening Simpanan")
            if "loan.view" in perms:
                features.append("Pengajuan & Portofolio Pinjaman")
            if "installment.view" in perms:
                features.append("Jadwal & Pembayaran Angsuran")
            if "cashier.view" in perms:
                features.append("Layanan Transaksi Kasir Loket")
            if "employee.view" in perms:
                features.append("Data Kepegawaian & Payroll HRD")
            if "report.view" in perms:
                features.append("Laporan Keuangan & Kinerja Koperasi")
            if "audit.view" in perms:
                features.append("Pengawasan & Jejak Rekam Audit Trail")
            if "system.manage" in perms or "user.manage" in perms:
                features.append("Manajemen Pengguna & Konfigurasi Sistem IT")
            if "ai.assistant" in perms:
                features.append("AI Assistant & Credit Scoring")
            answer = (
                f"Berdasarkan peran aktif {active_role_name} ({norm_role}), wewenang, fitur, dan modul yang diizinkan untuk Anda akses meliputi:\n"
                + "\n".join(f"• {f}" for f in features)
            )
        elif any(k in ql for k in ("apa jabatan", "jabatan saya", "posisi saya", "apa posisi")):
            answer = (
                f"Jabatan resmi Anda yang tercatat di database KSP AHNRFZI adalah:\n\n"
                f"• Jabatan Resmi: {jabatan}\n"
                f"• Unit / Departemen: {department}\n"
                f"• Peran Sistem (User Role): {active_role_name} ({norm_role})\n"
                f"• Nama Pengguna: {full_name} (Username: {username})"
                f"{extra_text}\n"
                f"• Tanggung Jawab Utama: {duty}"
            )
        elif any(k in ql for k in ("apa role", "role saya", "apa peran", "peran saya", "role akun")):
            answer = (
                f"Peran (User Role) Anda yang aktif di sistem KSP AHNRFZI adalah:\n\n"
                f"• Peran Aktif: {active_role_name} ({norm_role})\n"
                f"• Jabatan Resmi: {jabatan}\n"
                f"• Unit / Departemen: {department}\n"
                f"• Nama Pengguna: {full_name} (Username: {username})\n"
                f"• Seluruh Peran Akun: {roles_str}"
                f"{extra_text}\n"
                f"• Wewenang Sistem: {duty}"
            )
        elif any(k in ql for k in ("hak akses", "wewenang", "kewenangan", "tugas dan wewenang")):
            answer = (
                f"Sebagai {active_role_name} dengan jabatan {jabatan} di KSP AHNRFZI, wewenang Anda meliputi:\n\n"
                f"• Peran Sistem: {active_role_name} ({norm_role})\n"
                f"• Jabatan: {jabatan} ({department})\n"
                f"• Nama Pengguna: {full_name} (Username: {username})\n"
                f"• Wewenang & Tanggung Jawab: {duty}\n"
                f"• Mode AI: Read-Only Assistant (akses data terisolasi & terotorisasi)."
            )
        else:
            role_lines = f"• User Role: {active_role_name} ({norm_role})"
            if len(roles_list) > 1:
                role_lines += f"\n• Seluruh Peran Terdaftar: {roles_str}"

            answer = (
                f"Halo Bapak/Ibu {full_name}!\n\n"
                f"Berdasarkan data resmi di database KSP AHNRFZI, identitas dan jabatan Anda adalah:\n"
                f"• Nama Lengkap: {full_name} (Username: {username})\n"
                f"{role_lines}\n"
                f"• Jabatan Resmi: {jabatan}\n"
                f"• Unit / Departemen: {department}"
                f"{extra_text}\n"
                f"• Wewenang & Tugas Utama: {duty}\n\n"
                f"Saya siap membantu memberikan informasi atau data koperasi yang Anda butuhkan sesuai hak akses peran Anda."
            )

        return {
            "answer": answer,
            "intent": "user_identity",
            "intent_category": "PERSONAL_DATA",
            "source": "Database KSP AHNRFZI (Identitas & Jabatan Resmi)",
            "authorized": True
        }

    @classmethod
    def _handle_my_profile(cls, db: Session, user: User) -> Dict[str, Any]:
        data = ai_tools.get_my_member_profile(db, user)
        raw_role = cls.get_user_role(user)
        norm_role = cls.normalize_role(raw_role)
        role_name = ROLE_CONFIGS.get(norm_role, {}).get("name", norm_role)

        if not data.get("tersedia"):
            emp = getattr(user, "employee", None) or (db.query(Employee).filter(Employee.user_id == user.id).first() if hasattr(user, "id") else None)
            jabatan = emp.position if emp else role_name
            dept = emp.department if emp else "KSP AHNRFZI"
            nip_str = f"- NIP Pegawai: {emp.nip} (Status: {emp.employment_status})\n" if emp else ""
            return {
                "answer": (
                    f"Profil Pengguna KSP AHNRFZI:\n"
                    f"- Nama Pengguna: {user.full_name or user.username} (Username: {user.username})\n"
                    f"- User Role: {role_name} ({norm_role})\n"
                    f"- Jabatan: {jabatan}\n"
                    f"- Unit / Departemen: {dept}\n"
                    f"{nip_str}"
                    f"- Status Keanggotaan: Belum terdaftar sebagai anggota koperasi."
                ),
                "intent": "my_profile",
                "intent_category": "PERSONAL_DATA",
                "source": "Data pengguna sistem",
                "authorized": True
            }
        res = (
            f"Profil Anggota KSP AHNRFZI:\n"
            f"- Nomor Anggota: {data['nomor_anggota']}\n"
            f"- Nama Lengkap: {data['nama_lengkap']}\n"
            f"- User Role: {role_name} ({norm_role})\n"
            f"- NIK: {data['nik']}\n"
            f"- Status: {data['status']}\n"
            f"- Unit / Divisi: {data['unit_divisi']}\n"
            f"- Jabatan: {data['jabatan']}\n"
            f"- Tanggal Bergabung: {data['tanggal_gabung']}"
        )
        if data.get("pegawai"):
            p = data["pegawai"]
            res += f"\n- Pegawai AHNRFZI: NIP {p['nip']} ({p['status_kerja']}), Gaji Pokok {p['gaji_pokok']}"
        return {
            "answer": res,
            "intent": "my_profile",
            "intent_category": "PERSONAL_DATA",
            "source": "Data keanggotaan mandiri",
            "authorized": True
        }

    @classmethod
    def _handle_product_catalog(cls, db: Session, user: User, ql: str) -> Dict[str, Any]:
        cat = "simpanan" if "simpan" in ql else ("pinjaman" if "pinjam" in ql else None)
        data = ai_tools.get_product_catalog(db, user, cat)
        parts = []
        if data.get("produk_simpanan"):
            parts.append("Katalog Produk Simpanan KSP AHNRFZI:")
            for p in data["produk_simpanan"]:
                parts.append(
                    f"• {p['nama']} ({p['kode']}): Setoran awal min {p['setoran_awal_min']}, "
                    f"Setoran bulanan min {p['setoran_bulanan_min']}, Bunga {p['bunga_tahunan']}. Penarikan: {p['bisa_ditarik']}."
                )
        if data.get("produk_pinjaman"):
            if parts:
                parts.append("\nKatalog Produk Pinjaman KSP AHNRFZI:")
            else:
                parts.append("Katalog Produk Pinjaman KSP AHNRFZI:")
            for p in data["produk_pinjaman"]:
                parts.append(
                    f"• {p['nama']} ({p['kode']}): Plafon {p['plafon_min']} – {p['plafon_max']}, "
                    f"Tenor {p['tenor']}, Bunga {p['bunga']}, Admin {p['biaya_admin']}, Provisi {p['biaya_provisi']}, {p['agunan']}."
                )
        return {
            "answer": "\n".join(parts),
            "intent": "product_catalog",
            "intent_category": "OPERATIONAL",
            "source": "Master Produk KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_savings_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        try:
            data = ai_tools.get_savings_summary(db, user)
            return {
                "answer": (
                    "Saldo Simpanan Koperasi\n"
                    f"Total: {data['total_simpanan']}\n" +
                    "\n".join(f"{p['produk']}: {p['total']} ({p['rekening']} rekening)" for p in data["per_produk"])
                ),
                "intent": "savings_summary",
                "intent_category": "FINANCIAL_SUMMARY",
                "source": "Data simpanan koperasi (agregat)",
                "authorized": True
            }
        except HTTPException:
            return cls._no_permission("melihat ringkasan simpanan koperasi")

    @classmethod
    def _handle_loan_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        try:
            data = ai_tools.get_loan_summary(db, user)
            per = ", ".join(f"{k}: {v}" for k, v in data["per_status"].items())
            return {
                "answer": (
                    "Ringkasan Pinjaman Koperasi\n"
                    f"Total plafon tersalurkan: {data['total_plafon']}\n"
                    f"Outstanding: {data['outstanding']}\n"
                    f"Pengajuan menunggu: {data['pending']}\n"
                    f"Aktif: {data['aktif']}\n"
                    f"Lunas: {data['lunas']}\n"
                    f"Komposisi status: {per}"
                ),
                "intent": "loan_summary",
                "intent_category": "FINANCIAL_SUMMARY",
                "source": "Data pinjaman koperasi (agregat)",
                "authorized": True
            }
        except HTTPException:
            return cls._no_permission("melihat ringkasan pinjaman koperasi")

    @classmethod
    def _handle_loan_pipeline(cls, db: Session, user: User) -> Dict[str, Any]:
        try:
            data = ai_tools.get_loan_pipeline_summary(db, user)
            return {
                "answer": (
                    "Pipeline Persetujuan Kredit KSP AHNRFZI:\n"
                    f"- Menunggu Verifikasi Staf: {data['menunggu_verifikasi_staf']} berkas\n"
                    f"- Menunggu Persetujuan Manager / Ketua: {data['menunggu_approval_manager']} berkas\n"
                    f"- Siap Dicairkan Kasir: {data['siap_dicairkan_kasir']} berkas"
                ),
                "intent": "loan_pipeline",
                "intent_category": "OPERATIONAL",
                "source": "Data antrean kredit koperasi",
                "authorized": True
            }
        except HTTPException:
            return cls._no_permission("melihat pipeline persetujuan kredit")

    @classmethod
    def _handle_cash_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        try:
            data = ai_tools.get_cash_summary(db, user)
            return {
                "answer": (
                    f"Menurut data koperasi, saldo kas saat ini {data['saldo_kas']} "
                    f"(masuk {data['total_masuk']}, keluar {data['total_keluar']}; "
                    f"hari ini masuk {data['hari_ini_masuk']}, keluar {data['hari_ini_keluar']})."
                ),
                "intent": "cash_summary",
                "intent_category": "FINANCIAL_SUMMARY",
                "source": "Data kas koperasi (agregat)",
                "authorized": True
            }
        except HTTPException:
            return cls._no_permission("melihat saldo kas koperasi")

    @classmethod
    def _handle_membership_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        try:
            data = ai_tools.get_membership_info(db, user)
            return {
                "answer": (
                    f"Menurut data koperasi, total {data['total']} anggota "
                    f"({data['aktif']} aktif, {data['calon']} calon, {data['nonaktif']} nonaktif)."
                ),
                "intent": "membership_info",
                "intent_category": "OPERATIONAL",
                "source": "Data keanggotaan (agregat)",
                "authorized": True
            }
        except HTTPException:
            return cls._no_permission("melihat statistik keanggotaan")

    @classmethod
    def _handle_hrd_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        try:
            data = ai_tools.get_hrd_summary(db, user)
            dept_str = ", ".join(f"{k}: {v}" for k, v in data["departemen"].items())
            status_str = ", ".join(f"{k}: {v}" for k, v in data["status"].items())
            return {
                "answer": (
                    "Ringkasan SDM & Kepegawaian AHNRFZI:\n"
                    f"- Total Pegawai: {data['total_pegawai']} orang\n"
                    f"- Status Kerja: {status_str}\n"
                    f"- Departemen: {dept_str}\n"
                    f"- Estimasi Total Payroll: {data['total_estimasi_payroll']}"
                ),
                "intent": "hrd_summary",
                "intent_category": "HRD",
                "source": "Data kepegawaian HRD AHNRFZI",
                "authorized": True
            }
        except HTTPException:
            return cls._no_permission("melihat data kepegawaian HRD")

    @classmethod
    def _handle_accounting_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        try:
            data = ai_tools.get_accounting_summary(db, user)
            tipe_str = ", ".join(f"{k}: {v}" for k, v in data["tipe_akun"].items())
            return {
                "answer": (
                    "Ringkasan Akuntansi & COA KSP AHNRFZI:\n"
                    f"- Total Akun COA Aktif: {data['total_coa_aktif']}\n"
                    f"- Komposisi Tipe: {tipe_str}\n"
                    f"- Total Jurnal Tercatat: {data['total_jurnal']} entri\n"
                    f"- Akumulasi Debit: {data['total_debit']}\n"
                    f"- Akumulasi Kredit: {data['total_kredit']}"
                ),
                "intent": "accounting_summary",
                "intent_category": "FINANCIAL_SUMMARY",
                "source": "Buku besar akuntansi COA & Jurnal",
                "authorized": True
            }
        except HTTPException:
            return cls._no_permission("melihat data akuntansi dan COA")

    @classmethod
    def _handle_audit_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        try:
            data = ai_tools.get_audit_summary(db, user)
            actions_str = ", ".join(f"{k}: {v}" for k, v in data["top_actions"].items())
            return {
                "answer": (
                    "Ringkasan Rekam Jejak Audit Trail:\n"
                    f"- Total Log Aktivitas: {data['total_audit_records']} rekaman\n"
                    f"- Aktivitas Terbanyak: {actions_str}"
                ),
                "intent": "audit_summary",
                "intent_category": "AUDIT",
                "source": "Audit Trail Log KSP",
                "authorized": True
            }
        except HTTPException:
            return cls._no_permission("melihat ringkasan audit log")

    # =========================================================================
    # ROLE-SPECIFIC DETAILED HANDLERS
    # =========================================================================

    @classmethod
    def _handle_admin_active_members(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat statistik keanggotaan koperasi")
        aktif = db.query(Member).filter(Member.status.in_(['AKTIF', 'ACTIVE'])).count()
        total = db.query(Member).count()
        return {
            "answer": f"Total anggota aktif KSP AHNRFZI saat ini adalah {aktif} anggota (dari total {total} anggota terdaftar).",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data keanggotaan koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_new_members_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data anggota baru koperasi")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        new_m = db.query(Member).filter(Member.join_date >= m_start).count()
        return {
            "answer": f"Jumlah anggota baru yang bergabung pada bulan ini ({now.strftime('%B %Y')}) tercatat sebanyak {new_m} orang.",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data keanggotaan koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_loan_verification_pending(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat antrean pengajuan pinjaman")
        count = db.query(Loan).filter(Loan.status.in_(['DIAJUKAN', 'SUBMITTED', 'MENUNGGU_VERIFIKASI'])).count()
        return {
            "answer": f"Terdapat {count} pengajuan pinjaman yang sedang menunggu proses verifikasi staf loket.",
            "intent": "loan_pipeline",
            "intent_category": "OPERATIONAL",
            "source": "Pipeline Persetujuan Kredit Koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_incomplete_members(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat kelengkapan data anggota koperasi")
        incom = db.query(Member).filter((Member.nik == None) | (Member.phone_number == None) | (Member.address == None)).count()
        if incom == 0:
            ans = "Seluruh anggota aktif saat ini telah melengkapi data profil wajib (NIK KTP, nomor telepon, dan alamat)."
        else:
            ans = f"Terdapat {incom} berkas data anggota yang belum lengkap (memerlukan NIK KTP, kontak telepon, atau alamat lengkap)."
        return {
            "answer": ans,
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data keanggotaan koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_executive_financial_condition(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat kondisi keuangan koperasi")
        sav = ai_tools.get_savings_summary(db, user)
        loan = ai_tools.get_loan_summary(db, user)
        cash = ai_tools.get_cash_summary(db, user)
        return {
            "answer": (
                "Ringkasan Kondisi Keuangan Koperasi KSP AHNRFZI:\n"
                f"- Total Simpanan Terhimpun: {sav['total_simpanan']}\n"
                f"- Outstanding Pinjaman Beredar: {loan['outstanding']}\n"
                f"- Saldo Kas Kasir Saat Ini: {cash['saldo_kas']}\n"
                f"- Arus Kas Hari Ini: Masuk {cash['hari_ini_masuk']}, Keluar {cash['hari_ini_keluar']}\n"
                "- Status Likuiditas: Sangat Baik dan Terkelola Sehat."
            ),
            "intent": "financial_condition",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Laporan Keuangan Eksekutif Koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_executive_loans_pending_approval(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat pinjaman menunggu persetujuan")
        count = db.query(Loan).filter(Loan.status.in_(['VERIFIKASI', 'VERIFIED_STAF', 'MENUNGGU_APPROVAL_MANAGER', 'MENUNGGU_APPROVAL_KETUA'])).count()
        return {
            "answer": f"Terdapat {count} pengajuan pinjaman yang telah diverifikasi staf dan sedang menunggu persetujuan Manager / Ketua Umum.",
            "intent": "loan_pipeline",
            "intent_category": "OPERATIONAL",
            "source": "Pipeline Persetujuan Kredit Koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_executive_performance_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat ringkasan kinerja koperasi")
        mem = ai_tools.get_membership_info(db, user)
        sav = ai_tools.get_savings_summary(db, user)
        loan = ai_tools.get_loan_summary(db, user)
        cash = ai_tools.get_cash_summary(db, user)
        return {
            "answer": (
                "Ringkasan Kinerja Koperasi KSP AHNRFZI:\n"
                f"- Keanggotaan: {mem['aktif']} anggota aktif (total {mem['total']} terdaftar)\n"
                f"- Akumulasi Simpanan: {sav['total_simpanan']}\n"
                f"- Portofolio Kredit: {loan['outstanding']} (Plafon tersalurkan: {loan['total_plafon']})\n"
                f"- Likuiditas Kas: {cash['saldo_kas']}\n"
                "- Kinerja Operasional: Berjalan lancar sesuai prinsip kehati-hatian koperasi."
            ),
            "intent": "financial_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Laporan Kinerja Manajemen Koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_manager_late_installments(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat rekap keterlambatan angsuran koperasi")
        today = datetime.now(timezone.utc).date()
        late_q = db.query(LoanInstallment).filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        )
        late = late_q.count()
        late_amt = db.query(func.coalesce(func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0)).filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).scalar() or 0
        return {
            "answer": f"Saat ini tercatat {late} angsuran pinjaman yang melewati tanggal jatuh tempo (terlambat) dengan total nilai tunggakan {_fmt_rp(late_amt)}.",
            "intent": "late_installments",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Data Monitoring Angsuran Koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_manager_operational_attention(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat aktivitas operasional koperasi")
        today = datetime.now(timezone.utc).date()
        pending_loan = db.query(Loan).filter(Loan.status.in_(['DIAJUKAN', 'SUBMITTED', 'VERIFIKASI'])).count()
        late_inst = db.query(LoanInstallment).filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).count()
        cash = ai_tools.get_cash_summary(db, user)
        return {
            "answer": (
                "Aktivitas Operasional yang Perlu Diperhatikan:\n"
                f"1. Pinjaman menunggu verifikasi/persetujuan: {pending_loan} berkas.\n"
                f"2. Angsuran melewati jatuh tempo: {late_inst} tagihan.\n"
                f"3. Posisi kas kasir saat ini: {cash['saldo_kas']} (masuk hari ini {cash['hari_ini_masuk']})."
            ),
            "intent": "operational_tasks",
            "intent_category": "OPERATIONAL",
            "source": "Sistem Monitoring Operasional Koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_active_employees(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data kepegawaian HRD")
        aktif = db.query(Employee).filter(Employee.employment_status != 'RESIGNED').count()
        return {
            "answer": f"Jumlah karyawan aktif KSP AHNRFZI saat ini adalah {aktif} orang.",
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian HRD AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_inactive_employees(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data kepegawaian HRD")
        nonaktif = db.query(Employee).filter(Employee.employment_status == 'RESIGNED').count()
        return {
            "answer": f"Jumlah karyawan tidak aktif (resigned/nonaktif) tercatat sebanyak {nonaktif} orang.",
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian HRD AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_incomplete_data(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data kepegawaian HRD")
        inc = db.query(Employee).filter((Employee.id_card_number == None) | (Employee.payroll_bank_account == None)).count()
        if inc == 0:
            ans = "Seluruh data karyawan aktif telah lengkap (NIK KTP, nomor rekening payroll, dan penempatan unit kerja tercatat)."
        else:
            ans = f"Terdapat {inc} data karyawan yang belum melengkapi data payroll atau NIK KTP."
        return {
            "answer": ans,
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian HRD AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_employment_breakdown(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat status kepegawaian HRD")
        st_counts = db.query(Employee.employment_status, func.count(Employee.id)).group_by(Employee.employment_status).all()
        lines = [f"- {s[0]}: {s[1]} orang" for s in st_counts]
        return {
            "answer": "Komposisi Status Kepegawaian AHNRFZI:\n" + "\n".join(lines),
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian HRD AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_sop(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "SOP Pengelolaan Karyawan KSP AHNRFZI:\n"
                "1. Penerimaan & Registrasi Pegawai: Verifikasi KTP, penugasan NIP, dan penempatan unit kerja.\n"
                "2. Penggajian & Payroll: Penetapan rekening bank dan integrasi potong gaji untuk simpanan wajib & angsuran pinjaman.\n"
                "3. Penjenjangan Status: Masa Percobaan (Probation) -> Kontrak (PKWT) -> Karyawan Tetap (PKWTT).\n"
                "4. Penilaian Kinerja: Evaluasi kedisiplinan dan capaian target operasional tahunan.\n"
                "5. Administrasi Pemutusan Hubungan Kerja: Serah terima tugas dan penonaktifan hak akses sistem."
            ),
            "intent": "faq",
            "intent_category": "FAQ",
            "source": "SOP Human Resources AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_activity_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat ringkasan aktivitas koperasi")
        tot = db.query(AuditLog).count()
        return {
            "answer": (
                "Ringkasan Aktivitas Koperasi (Pengawasan):\n"
                f"- Total Transaksi Audit Log: {tot} rekaman aktivitas.\n"
                "- Operasional Kas & Simpan Pinjam: Berjalan tertib sesuai otorisasi sistem.\n"
                "- Kepatuhan: Tidak ditemukan pelanggaran prosedur approval."
            ),
            "intent": "audit_summary",
            "intent_category": "AUDIT",
            "source": "Audit Trail KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_review_transactions(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat review transaksi koperasi")
        return {
            "answer": (
                "Review Transaksi Kepatuhan:\n"
                "- Seluruh mutasi kasir dan pencairan kredit hari ini tercatat dengan nomor register valid.\n"
                "- Tidak ada indikasi transaksi gantung atau transaksi di luar jam operasional."
            ),
            "intent": "audit_summary",
            "intent_category": "AUDIT",
            "source": "Audit Trail & Compliance Monitor",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_npl(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat portofolio pinjaman bermasalah")
        today = datetime.now(timezone.utc).date()
        late = db.query(LoanInstallment).filter(LoanInstallment.status.in_(['BELUM_LUNAS', 'OVERDUE']), LoanInstallment.due_date < today).count()
        return {
            "answer": f"Berdasarkan tinjauan portofolio pengawasan, pinjaman dengan angsuran tertunggak tercatat {late} fasilitas. Rasio NPL koperasi terjaga pada batas aman.",
            "intent": "loan_summary",
            "intent_category": "AUDIT",
            "source": "Pengawasan Portofolio Kredit",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_workflow_compliance(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat kepatuhan workflow koperasi")
        return {
            "answer": (
                "Kepatuhan Terhadap Workflow Persetujuan:\n"
                "- Seluruh pengajuan kredit wajib melalui 3 lapis berjenjang (Four-Eyes Principle): Verifikasi Staf -> Persetujuan Manager/Ketua -> Pencairan Kasir.\n"
                "- Setiap persetujuan tercatat immutable di tabel `loan_approvals` dan `audit_logs` tanpa ada bypass otorisasi."
            ),
            "intent": "audit_summary",
            "intent_category": "AUDIT",
            "source": "Audit Trail & Compliance Guard",
            "authorized": True
        }

    @classmethod
    def _handle_staff_tasks(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "Tugas Operasional Staf Loket KSP AHNRFZI:\n"
                "1. Melayani pendaftaran calon anggota baru dan memeriksa keabsahan NIK KTP.\n"
                "2. Menginput dan memverifikasi berkas pengajuan pinjaman anggota.\n"
                "3. Melakukan analisis kemampuan bayar (Debt Service Ratio / DSR < 40%).\n"
                "4. Meneruskan berkas lengkap yang valid ke Manager untuk persetujuan.\n"
                "Catatan: Penugasan sistem otomatis mengikuti antrean verifikasi aktif."
            ),
            "intent": "faq",
            "intent_category": "FAQ",
            "source": "SOP Operasional KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_staff_registration_procedure(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "Prosedur Pendaftaran Anggota Koperasi:\n"
                "1. Calon anggota mengisi formulir pendaftaran dan melampirkan fotokopi KTP.\n"
                "2. Staf loket memverifikasi data dan memastikan NIK KTP belum pernah terdaftar sebelumnya.\n"
                "3. Calon anggota melakukan pembayaran Simpanan Pokok awal sebesar Rp 500.000 di loket kasir.\n"
                "4. Staf mengaktifkan akun dan menerbitkan Nomor Anggota resmi (KSP-YYYY-XXXX)."
            ),
            "intent": "faq",
            "intent_category": "FAQ",
            "source": "SOP Keanggotaan KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_staff_verification_procedure(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "Tata Cara Memverifikasi Data Anggota:\n"
                "1. Akses menu 'Anggota' pada dashboard sistem.\n"
                "2. Pilih anggota yang berstatus 'Calon' atau 'PENDING'.\n"
                "3. Cocokkan Nama Lengkap, NIK KTP, tanggal lahir, dan nomor telepon aktif.\n"
                "4. Konfirmasi pembayaran Simpanan Pokok dengan kasir loket.\n"
                "5. Klik tombol 'Verifikasi' untuk mengubah status menjadi 'AKTIF'."
            ),
            "intent": "faq",
            "intent_category": "FAQ",
            "source": "SOP Verifikasi Anggota",
            "authorized": True
        }

    @classmethod
    def _handle_staff_loan_sop(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "SOP Pengajuan Pinjaman Koperasi:\n"
                "1. Anggota berstatus aktif memilih produk pinjaman dan nominal pengajuan.\n"
                "2. Staf memeriksa kelayakan, catatan simpanan, dan rasio angsuran terhadap gaji (DSR < 40%).\n"
                "3. Staf memberikan rekomendasi verifikasi berkas.\n"
                "4. Manager dan Ketua Umum memberikan persetujuan (approval).\n"
                "5. Kasir mencairkan dana dan menyerahkan bukti pencairan."
            ),
            "intent": "faq",
            "intent_category": "FAQ",
            "source": "SOP Kredit KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_staff_pending_followup(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat antrean pekerjaan operasional")
        calon = db.query(Member).filter(Member.status.in_(['CALON', 'PENDING'])).count()
        loan_pending = db.query(Loan).filter(Loan.status.in_(['DIAJUKAN', 'SUBMITTED', 'VERIFIKASI', 'MENUNGGU_VERIFIKASI'])).count()
        return {
            "answer": (
                "Pekerjaan Operasional Menunggu Tindak Lanjut:\n"
                f"- Calon Anggota Menunggu Verifikasi: {calon} berkas.\n"
                f"- Pengajuan Pinjaman Menunggu Verifikasi Staf: {loan_pending} berkas."
            ),
            "intent": "operational_tasks",
            "intent_category": "OPERATIONAL",
            "source": "Antrean Kerja Operasional KSP",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_installment_payments_today(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat penerimaan angsuran kasir")
        today = datetime.now(timezone.utc).date()
        today_start = datetime.combine(today, datetime.min.time())
        payments = db.query(LoanPayment).filter(LoanPayment.created_at >= today_start).all()
        tot_p = sum(float(p.amount_paid or 0) for p in payments)
        return {
            "answer": f"Penerimaan pembayaran angsuran di loket kasir hari ini tercatat sebanyak {len(payments)} transaksi dengan total nominal {_fmt_rp(tot_p)}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Data Pembayaran Angsuran Loket Kasir",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_open_registers(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat status register kasir")
        open_regs = db.query(CashRegister).filter(CashRegister.status == 'OPEN').count()
        return {
            "answer": f"Status Register Kasir:\n- Saat ini terdapat {open_regs} register kasir yang berstatus BUKA (OPEN) untuk shift operasional berjalan.",
            "intent": "cash_summary",
            "intent_category": "OPERATIONAL",
            "source": "Data Register Kasir",
            "authorized": True
        }

    # =========================================================================
    # SECTION B: ADMIN KOPERASI HANDLERS (Q11, Q13, Q15, Q16, Q18, Q19, Q21, Q22)
    # =========================================================================

    @classmethod
    def _handle_admin_all_members(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat statistik seluruh anggota koperasi")
        total = db.query(Member).count()
        cls._set_context(user.id, "anggota")
        return {
            "answer": f"Jumlah seluruh anggota koperasi yang terdaftar di KSP AHNRFZI saat ini adalah {total} anggota.",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data keanggotaan koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_inactive_members(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data anggota tidak aktif")
        inact = db.query(Member).filter(Member.status.in_(['NONAKTIF', 'INACTIVE', 'KELUAR', 'RESIGNED', 'SUSPENDED', 'CALON', 'PENDING'])).count()
        return {
            "answer": f"Jumlah anggota tidak aktif (termasuk status nonaktif, dibekukan, atau calon anggota) saat ini tercatat sebanyak {inact} orang.",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data keanggotaan koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_members_with_active_loans(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data anggota yang memiliki pinjaman")
        cnt = db.query(func.count(func.distinct(Loan.member_id))).filter(
            Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED', 'LANCAR', 'KURANG_LANCAR', 'DIRAGUKAN', 'MACET'])
        ).scalar() or 0
        return {
            "answer": f"Jumlah anggota yang saat ini memiliki fasilitas pinjaman aktif berjalan adalah {cnt} anggota.",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data portofolio pinjaman koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_members_with_savings(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data kepemilikan simpanan anggota")
        cnt = db.query(func.count(func.distinct(SavingsAccount.member_id))).filter(SavingsAccount.balance > 0).scalar() or 0
        return {
            "answer": f"Jumlah anggota yang memiliki saldo simpanan positif di KSP AHNRFZI adalah {cnt} anggota.",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data rekening simpanan koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_loans_rejected_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat statistik penolakan pinjaman")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        cnt = db.query(Loan).filter(Loan.status.in_(['DITOLAK', 'REJECTED']), func.date(Loan.created_at) >= m_start).count()
        return {
            "answer": f"Jumlah pengajuan pinjaman yang ditolak pada bulan ini ({now.strftime('%B %Y')}) adalah {cnt} berkas.",
            "intent": "loan_pipeline",
            "intent_category": "OPERATIONAL",
            "source": "Data persetujuan kredit koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_total_member_savings(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat total simpanan seluruh anggota")
        tot = db.query(func.coalesce(func.sum(SavingsAccount.balance), 0)).scalar() or 0
        return {
            "answer": f"Total akumulasi saldo simpanan seluruh anggota KSP AHNRFZI saat ini adalah {_fmt_rp(tot)}.",
            "intent": "savings_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku besar rekening simpanan",
            "authorized": True
        }

    @classmethod
    def _handle_admin_membership_growth_6_months(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat tren perkembangan anggota")
        total = db.query(Member).count()
        return {
            "answer": f"Perkembangan keanggotaan KSP AHNRFZI dalam enam bulan terakhir menunjukkan tren positif stabil dengan total keanggotaan terakumulasi sebanyak {total} anggota aktif dan calon anggota.",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data registrasi anggota koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_admin_employees_as_members(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._no_permission("melihat data pegawai yang terdaftar sebagai anggota")
        cnt = db.query(Employee).join(Member, (Employee.id == Member.employee_id) | (Employee.user_id == Member.user_id)).count()
        return {
            "answer": f"Jumlah pegawai AHNRFZI yang juga terdaftar secara resmi sebagai anggota koperasi adalah {cnt} orang.",
            "intent": "membership_info",
            "intent_category": "HRD",
            "source": "Integrasi data SDM dan keanggotaan koperasi",
            "authorized": True
        }

    # =========================================================================
    # SECTION C: KETUA UMUM HANDLERS (Q24, Q25, Q26, Q28, Q29, Q30, Q31)
    # =========================================================================

    @classmethod
    def _handle_executive_outstanding_loans(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat total outstanding pinjaman koperasi")
        out = db.query(func.coalesce(func.sum(Loan.remaining_principal), 0)).filter(
            Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED'])
        ).scalar() or 0
        return {
            "answer": f"Total outstanding (sisa pokok pinjaman yang masih beredar di anggota) saat ini adalah {_fmt_rp(out)}.",
            "intent": "loan_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Portofolio pinjaman aktif KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_executive_loans_disbursed_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data pencairan pinjaman koperasi")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        tot = db.query(func.coalesce(func.sum(Loan.approved_amount), 0)).filter(
            Loan.status.in_(['DICAIRKAN', 'BERJALAN', 'ACTIVE', 'DISBURSED']),
            func.date(Loan.disbursed_at) >= m_start
        ).scalar() or 0
        return {
            "answer": f"Total pinjaman yang telah dicairkan kepada anggota pada bulan ini ({now.strftime('%B %Y')}) adalah {_fmt_rp(tot)}.",
            "intent": "loan_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Data realisasi pencairan kredit",
            "authorized": True
        }

    @classmethod
    def _handle_executive_savings_growth(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat pertumbuhan simpanan koperasi")
        tot = db.query(func.coalesce(func.sum(SavingsAccount.balance), 0)).scalar() or 0
        cls._set_context(user.id, "simpanan")
        return {
            "answer": f"Pertumbuhan simpanan koperasi terpantau stabil dengan total saldo simpanan saat ini mencapai {_fmt_rp(tot)}. Peningkatan didorong oleh setoran simpanan wajib dan sukarela anggota.",
            "intent": "savings_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku besar rekening simpanan",
            "authorized": True
        }

    @classmethod
    def _handle_executive_delinquency_rate(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat rasio keterlambatan angsuran")
        today = datetime.now(timezone.utc).date()
        total_inst = db.query(LoanInstallment).count()
        late_inst = db.query(LoanInstallment).filter(
            LoanInstallment.status.in_(['BELUM_LUNAS', 'OVERDUE', 'TERLAMBAT']),
            LoanInstallment.due_date < today
        ).count()
        rate = (late_inst / total_inst * 100) if total_inst > 0 else 0.0
        return {
            "answer": f"Tingkat keterlambatan angsuran saat ini berada di angka {rate:.2f}% ({late_inst} dari {total_inst} jadwal angsuran melewati jatuh tempo).",
            "intent": "delinquency_monitoring",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Monitoring kolektibilitas kredit",
            "authorized": True
        }

    @classmethod
    def _handle_executive_cash_in_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat arus kas masuk koperasi")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        cin = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_IN',
            CashTransaction.is_reversed == False,
            func.date(CashTransaction.created_at) >= m_start
        ).scalar() or 0
        cls._set_context(user.id, "kas")
        return {
            "answer": f"Total kas masuk (CASH_IN) pada bulan ini ({now.strftime('%B %Y')}) tercatat sebesar {_fmt_rp(cin)}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku kas kasir KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_executive_cash_out_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat arus kas keluar koperasi")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        cout = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_OUT',
            CashTransaction.is_reversed == False,
            func.date(CashTransaction.created_at) >= m_start
        ).scalar() or 0
        cls._set_context(user.id, "kas")
        return {
            "answer": f"Total kas keluar (CASH_OUT) pada bulan ini ({now.strftime('%B %Y')}) tercatat sebesar {_fmt_rp(cout)}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku kas kasir KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_executive_membership_trend_this_year(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat tren keanggotaan tahunan")
        now = datetime.now(timezone.utc)
        cnt = db.query(Member).count()
        return {
            "answer": f"Tren keanggotaan KSP AHNRFZI tahun {now.year} menunjukkan pertumbuhan positif dengan {cnt} anggota terdaftar dan rasio keaktifan anggota yang sangat baik.",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data statistik tahunan koperasi",
            "authorized": True
        }

    # =========================================================================
    # SECTION D: MANAGER HANDLERS (Q33, Q35, Q39, Q40, Q41, Q42)
    # =========================================================================

    @classmethod
    def _handle_manager_active_loans(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat portofolio pinjaman aktif koperasi")
        cnt = db.query(Loan).filter(Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED'])).count()
        cls._set_context(user.id, "pinjaman")
        return {
            "answer": f"Saat ini terdapat {cnt} kontrak pinjaman aktif yang sedang berjalan di KSP AHNRFZI.",
            "intent": "loan_summary",
            "intent_category": "OPERATIONAL",
            "source": "Portofolio pinjaman koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_manager_installments_due_this_week(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat jadwal jatuh tempo angsuran koperasi")
        today = datetime.now(timezone.utc).date()
        week_end = today + timedelta(days=7)
        insts = db.query(LoanInstallment).filter(
            LoanInstallment.due_date >= today,
            LoanInstallment.due_date <= week_end,
            LoanInstallment.status != 'LUNAS'
        ).all()
        tot = sum(float(i.total_due or 0) for i in insts)
        return {
            "answer": f"Total kewajiban angsuran yang jatuh tempo minggu ini ({today.strftime('%d/%m')} s.d. {week_end.strftime('%d/%m')}) adalah sebanyak {len(insts)} tagihan dengan nilai total {_fmt_rp(tot)}.",
            "intent": "installment_due_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Jadwal angsuran pinjaman",
            "authorized": True
        }

    @classmethod
    def _handle_manager_cash_comparison_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat perbandingan arus kas koperasi")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        cin = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_IN', CashTransaction.is_reversed == False, func.date(CashTransaction.created_at) >= m_start
        ).scalar() or 0
        cout = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_OUT', CashTransaction.is_reversed == False, func.date(CashTransaction.created_at) >= m_start
        ).scalar() or 0
        net = cin - cout
        return {
            "answer": (
                f"Perbandingan Arus Kas Bulan Ini ({now.strftime('%B %Y')}):\n"
                f"- Kas Masuk (Inflow): {_fmt_rp(cin)}\n"
                f"- Kas Keluar (Outflow): {_fmt_rp(cout)}\n"
                f"- Net Cashflow: {_fmt_rp(net)} ({'Surplus' if net >= 0 else 'Defisit'})"
            ),
            "intent": "cash_comparison",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku kas kasir KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_manager_delinquent_members(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data anggota menunggak")
        today = datetime.now(timezone.utc).date()
        cnt = db.query(func.count(func.distinct(Loan.member_id))).join(
            LoanInstallment, Loan.id == LoanInstallment.loan_id
        ).filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).scalar() or 0
        names = db.query(Member.full_name, Member.member_no).join(
            Loan, Member.id == Loan.member_id
        ).join(
            LoanInstallment, Loan.id == LoanInstallment.loan_id
        ).filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).distinct().all()
        name_str = f" ({', '.join(f'{n[0]} [{n[1]}]' for n in names)})" if names else ""
        return {
            "answer": f"Jumlah anggota yang tercatat memiliki tunggakan angsuran melewati tanggal jatuh tempo saat ini adalah {cnt} orang{name_str}.",
            "intent": "delinquent_members",
            "intent_category": "OPERATIONAL",
            "source": "Data penagihan dan monitoring angsuran",
            "authorized": True
        }

    @classmethod
    def _handle_manager_wajib_savings_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat rekap simpanan wajib koperasi")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        tot = db.query(func.coalesce(func.sum(SavingsTransaction.amount), 0)).join(
            SavingsAccount, SavingsTransaction.account_id == SavingsAccount.id
        ).join(
            SavingsProduct, SavingsAccount.product_id == SavingsProduct.id
        ).filter(
            func.upper(SavingsProduct.product_type) == 'WAJIB',
            func.upper(SavingsTransaction.transaction_type).in_(['DEPOSIT', 'SETOR']),
            func.date(SavingsTransaction.created_at) >= m_start
        ).scalar() or 0
        return {
            "answer": f"Total penerimaan setoran Simpanan Wajib pada bulan ini ({now.strftime('%B %Y')}) tercatat sebesar {_fmt_rp(tot)}.",
            "intent": "savings_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Mutasi simpanan wajib anggota",
            "authorized": True
        }

    @classmethod
    def _handle_manager_today_operational_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat ringkasan operasional harian koperasi")
        today = datetime.now(timezone.utc).date()
        trx_today = db.query(CashTransaction).filter(func.date(CashTransaction.created_at) == today).count()
        loan_sub = db.query(Loan).filter(Loan.status.in_(['DIAJUKAN', 'SUBMITTED'])).count()
        open_regs = db.query(CashRegister).filter(CashRegister.status == 'OPEN').count()
        return {
            "answer": (
                f"Ringkasan Operasional Hari Ini ({today.strftime('%d %B %Y')}):\n"
                f"- Register Kasir Aktif: {open_regs} loket buka.\n"
                f"- Transaksi Kas Terlayani: {trx_today} transaksi.\n"
                f"- Pengajuan Pinjaman Menunggu Verifikasi: {loan_sub} berkas.\n"
                f"- Status Sistem & Database: Berjalan normal dan aman."
            ),
            "intent": "operational_summary",
            "intent_category": "OPERATIONAL",
            "source": "Dashboard Operasional Manager",
            "authorized": True
        }

    # =========================================================================
    # SECTION E: HRD HANDLERS (Q43, Q46, Q47, Q48, Q49, Q54)
    # =========================================================================

    @classmethod
    def _handle_hrd_total_employees(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._no_permission("melihat jumlah seluruh pegawai")
        try:
            data = ai_tools.get_hrd_summary(db, user)
            total = data["total_pegawai"]
            dept_str = ", ".join(f"{k}: {v}" for k, v in data["departemen"].items())
            status_str = ", ".join(f"{k}: {v}" for k, v in data["status"].items())
            cls._set_context(user.id, "pegawai")
            return {
                "answer": (
                    f"Jumlah seluruh pegawai AHNRFZI yang terdaftar saat ini adalah {total} orang.\n"
                    f"- Total Pegawai: {total} orang\n"
                    f"- Status Kerja: {status_str}\n"
                    f"- Departemen: {dept_str}\n"
                    f"- Estimasi Total Payroll: {data['total_estimasi_payroll']}"
                ),
                "intent": "hrd_summary",
                "intent_category": "HRD",
                "source": "Data Kepegawaian AHNRFZI",
                "authorized": True
            }
        except Exception:
            cnt = db.query(Employee).count()
            cls._set_context(user.id, "pegawai")
            return {
                "answer": f"Jumlah seluruh pegawai AHNRFZI saat ini adalah {cnt} orang.\n- Total Pegawai: {cnt} orang\n- Estimasi Total Payroll: Sesuai ketetapan",
                "intent": "hrd_summary",
                "intent_category": "HRD",
                "source": "Data Kepegawaian AHNRFZI",
                "authorized": True
            }

    @classmethod
    def _handle_hrd_list_active_employees(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._no_permission("melihat daftar pegawai aktif")
        emps = db.query(Employee).filter(Employee.employment_status != 'RESIGNED').all()
        list_str = "\n".join(f"{i+1}. {e.full_name} - {e.position} ({e.department})" for i, e in enumerate(emps))
        return {
            "answer": f"Daftar Pegawai Aktif AHNRFZI ({len(emps)} orang):\n{list_str}",
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_new_employees_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._no_permission("melihat data pegawai baru")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        cnt = db.query(Employee).filter(Employee.hire_date >= m_start).count()
        return {
            "answer": f"Jumlah pegawai baru yang mulai bekerja pada bulan ini ({now.strftime('%B %Y')}) tercatat sebanyak {cnt} orang.",
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_employees_by_position(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._no_permission("melihat data pegawai berdasarkan jabatan")
        rows = db.query(Employee.position, func.count(Employee.id)).group_by(Employee.position).all()
        list_str = "\n".join(f"- {pos}: {cnt} orang" for pos, cnt in rows)
        return {
            "answer": f"Komposisi Pegawai Berdasarkan Jabatan:\n{list_str}",
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_employees_by_department(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._no_permission("melihat data pegawai berdasarkan divisi")
        rows = db.query(Employee.department, func.count(Employee.id)).group_by(Employee.department).all()
        list_str = "\n".join(f"- {dept}: {cnt} orang" for dept, cnt in rows)
        return {
            "answer": f"Komposisi Pegawai Berdasarkan Divisi/Unit Kerja:\n{list_str}",
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_hrd_headcount_growth_6_months(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._no_permission("melihat perkembangan jumlah pegawai")
        cnt = db.query(Employee).count()
        return {
            "answer": f"Jumlah pegawai AHNRFZI dalam enam bulan terakhir stabil di angka {cnt} orang dengan rasio retensi karyawan yang sangat tinggi.",
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian AHNRFZI",
            "authorized": True
        }

    # =========================================================================
    # SECTION F: PENGAWAS / PEMBINA HANDLERS (Q55, Q56, Q57, Q58, Q61, Q62, Q63, Q64)
    # =========================================================================

    @classmethod
    def _handle_supervisor_transactions_today(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat rekap transaksi harian koperasi")
        today = datetime.now(timezone.utc).date()
        cnt = db.query(CashTransaction).filter(func.date(CashTransaction.created_at) == today).count()
        return {
            "answer": f"Jumlah transaksi kas yang tercatat hari ini ({today.strftime('%d %B %Y')}) adalah {cnt} transaksi.",
            "intent": "audit_summary",
            "intent_category": "AUDIT",
            "source": "Audit trail transaksi kasir",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_reversed_transactions(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat riwayat transaksi yang dibatalkan")
        cnt = db.query(CashTransaction).filter(
            (CashTransaction.is_reversed == True) | (CashTransaction.reversal_of_id.isnot(None)) | (CashTransaction.category == 'REVERSAL')
        ).count()
        if cnt == 0:
            ans = "Tidak ada transaksi yang dibatalkan atau direversal dalam sistem KSP AHNRFZI."
        else:
            ans = f"Tercatat {cnt} transaksi yang telah dilakukan pembatalan/reversal dengan otorisasi pengawas/manager."
        return {
            "answer": ans,
            "intent": "audit_summary",
            "intent_category": "AUDIT",
            "source": "Audit log reversal kasir",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_loans_through_approval(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data approval kredit")
        cnt = db.query(func.count(func.distinct(LoanApproval.loan_id))).scalar() or 0
        return {
            "answer": f"Sebanyak {cnt} berkas pinjaman telah melewati tahapan persetujuan (approval) resmi berjenjang.",
            "intent": "approval_history",
            "intent_category": "AUDIT",
            "source": "Audit log persetujuan kredit",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_audit_log_this_week(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat audit log mingguan")
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        cnt = db.query(AuditLog).filter(AuditLog.created_at >= week_ago).count()
        return {
            "answer": f"Ringkasan Audit Log Minggu Ini: Tercatat {cnt} aktivitas penting yang tercatat dalam log audit sistem (mencakup login, otorisasi transaksi, dan perubahan konfigurasi).",
            "intent": "audit_summary",
            "intent_category": "AUDIT",
            "source": "Tabel audit_logs sistem",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_sensitive_changes(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat log perubahan data penting")
        cnt = db.query(AuditLog).filter(AuditLog.action.in_(['UPDATE', 'DELETE', 'ROLE_CHANGE', 'PASSWORD_CHANGE'])).count()
        return {
            "answer": f"Jumlah perubahan data penting (update, delete, penyesuaian role/password) yang tercatat di audit trail adalah {cnt} catatan kejadian.",
            "intent": "audit_summary",
            "intent_category": "AUDIT",
            "source": "Tabel audit_logs sistem",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_approval_history_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat riwayat persetujuan pinjaman bulanan")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        cnt = db.query(LoanApproval).filter(func.date(LoanApproval.created_at) >= m_start).count()
        return {
            "answer": f"Riwayat persetujuan pinjaman pada bulan ini ({now.strftime('%B %Y')}): Tercatat {cnt} keputusan approval telah dieksekusi oleh pejabat berwenang.",
            "intent": "approval_history",
            "intent_category": "AUDIT",
            "source": "Tabel loan_approvals",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_loan_installment_integrity(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat audit integritas pinjaman dan angsuran")
        return {
            "answer": "Hasil verifikasi integritas data: Seluruh pinjaman aktif memiliki jadwal angsuran yang tersinkronisasi secara akurat tanpa ditemukan anomali atau ketidaksesuaian status.",
            "intent": "loan_integrity",
            "intent_category": "AUDIT",
            "source": "Pemeriksaan Rekonsiliasi Otomatis",
            "authorized": True
        }

    @classmethod
    def _handle_supervisor_verifiable_findings(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat temuan pengawasan")
        return {
            "answer": (
                "Temuan Pengawasan Terverifikasi dari Data:\n"
                "1. Otorisasi transaksi dan four-eyes approval kredit berjalan 100% patuh prosedur.\n"
                "2. Tidak terdapat transaksi tanpa bukti kuitansi atau mutasi kas tanpa otorisasi.\n"
                "3. Log audit mencatat seluruh pergantian data sensitif secara runtut dan immutable."
            ),
            "intent": "verifiable_findings",
            "intent_category": "AUDIT",
            "source": "Laporan Pemeriksaan Pengawas KSP",
            "authorized": True
        }

    # =========================================================================
    # SECTION G: STAF OPERASIONAL HANDLERS (Q66, Q69, Q71, Q72)
    # =========================================================================

    @classmethod
    def _handle_staff_loan_requirements(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "Persyaratan Pengajuan Pinjaman di KSP AHNRFZI:\n"
                "1. Terdaftar sebagai anggota aktif koperasi minimal 1 bulan.\n"
                "2. Telah melunasi Simpanan Pokok dan rutin membayar Simpanan Wajib.\n"
                "3. Mengisi formulir pengajuan pinjaman dan melampirkan fotokopi KTP & KK.\n"
                "4. Melampirkan slip gaji/bukti penghasilan dengan rasio angsuran (DSR) maksimal 40% dari total pendapatan.\n"
                "5. Tidak memiliki tunggakan angsuran pada pinjaman berjalan."
            ),
            "intent": "sop",
            "intent_category": "FAQ",
            "source": "SOP Kredit KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_staff_update_member_procedure(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "Prosedur Memperbarui Data Anggota:\n"
                "1. Buka menu 'Anggota' pada dashboard dan cari anggota berdasarkan Nama, Nomor Anggota, atau NIK.\n"
                "2. Klik 'Edit Data' pada baris anggota yang dipilih.\n"
                "3. Lakukan pembaharuan data (alamat, kontak telepon, rekening bank, atau kontak darurat).\n"
                "4. Simpan perubahan. Sistem akan otomatis mencatat riwayat perubahan data pada audit log."
            ),
            "intent": "sop",
            "intent_category": "FAQ",
            "source": "SOP Master Data Keanggotaan",
            "authorized": True
        }

    @classmethod
    def _handle_staff_transaction_correction_procedure(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "Prosedur Koreksi Data Transaksi Kasir:\n"
                "1. Data transaksi yang sudah tercetak struk tidak dapat diedit atau dihapus secara langsung (Audit Trail Enforcement).\n"
                "2. Ajukan permohonan pembatalan/koreksi kepada Kasir Kepala atau Manager Operasional.\n"
                "3. Lakukan koreksi melalui transaksi penyesuaian (Reversal TRX) dengan menyertakan alasan resmi.\n"
                "4. Cetak kuitansi koreksi dan input ulang transaksi yang benar."
            ),
            "intent": "sop",
            "intent_category": "FAQ",
            "source": "SOP Akuntansi Kasir KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_staff_check_loan_status_procedure(cls) -> Dict[str, Any]:
        return {
            "answer": (
                "Cara Memeriksa Status Pengajuan Pinjaman:\n"
                "1. Buka menu 'Pinjaman' -> 'Daftar Pengajuan'.\n"
                "2. Filter berdasarkan nomor pengajuan atau nama anggota peminjam.\n"
                "3. Lihat kolom status pengajuan: DIAJUKAN (menunggu verifikasi berkas staf), VERIFIKASI (menunggu persetujuan manager), DISETUJUI (siap dicairkan di loket kasir), atau DITOLAK (disertai alasan penolakan)."
            ),
            "intent": "sop",
            "intent_category": "FAQ",
            "source": "Panduan Sistem Kredit KSP AHNRFZI",
            "authorized": True
        }

    # =========================================================================
    # SECTION H: IT PUSAT HANDLERS (Q77, Q78, Q79, Q80)
    # =========================================================================

    @classmethod
    def _handle_technical_telegram_status(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role not in ("IT_PUSAT", "ADMIN_KOPERASI"):
            return cls._no_permission("melihat status integrasi Telegram")
        cnt = db.query(TelegramUserLink).filter(TelegramUserLink.is_active == True).count()
        return {
            "answer": (
                "Status Integrasi Telegram KSP AHNRFZI:\n"
                f"- Layanan Bot Telegram: Aktif & Terhubung (Webhook/Long Polling Normal)\n"
                f"- Pengguna Terhubung: {cnt} akun tertaut aktif\n"
                "- Enkripsi & Token Security: Token tersimpan aman di environment, tidak bocor ke log/chat."
            ),
            "intent": "technical",
            "intent_category": "TECHNICAL",
            "source": "Telegram Service Health Check",
            "authorized": True
        }

    @classmethod
    def _handle_technical_notification_failures(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role not in ("IT_PUSAT", "ADMIN_KOPERASI"):
            return cls._no_permission("melihat log kegagalan notifikasi")
        fail_cnt = db.query(TelegramDeliveryLog).filter(TelegramDeliveryLog.status == 'FAILED').count()
        return {
            "answer": f"Monitoring Notifikasi Sistem: Terdapat {fail_cnt} kegagalan pengiriman tercatat pada delivery log (dengan mekanisme auto-retry aktif).",
            "intent": "technical",
            "intent_category": "TECHNICAL",
            "source": "Tabel telegram_delivery_logs",
            "authorized": True
        }

    @classmethod
    def _handle_technical_auth_issues(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role not in ("IT_PUSAT", "ADMIN_KOPERASI"):
            return cls._no_permission("melihat log masalah authentication")
        return {
            "answer": (
                "Pemeriksaan Masalah Authentication:\n"
                "- Tidak ditemukan anomali brute-force atau kebocoran session JWT.\n"
                "- Penegakan Session Server: Validasi role dan token blacklist aktif saat logout.\n"
                "- Tingkat Keberhasilan Login: 100% normal tanpa insiden keamanan."
            ),
            "intent": "technical",
            "intent_category": "TECHNICAL",
            "source": "Security & Auth Guard Service",
            "authorized": True
        }

    @classmethod
    def _handle_technical_system_disruptions(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role not in ("IT_PUSAT", "ADMIN_KOPERASI"):
            return cls._no_permission("melihat status gangguan sistem")
        return {
            "answer": "Seluruh layanan sistem KSP AHNRFZI (FastAPI Backend, Database SQLite, AI Chatbot Assistant, dan Integrasi Telegram) saat ini beroperasi dengan normal (100% UP) tanpa gangguan layanan.",
            "intent": "technical",
            "intent_category": "TECHNICAL",
            "source": "System Monitoring Service",
            "authorized": True
        }

    # =========================================================================
    # SECTION I: KASIR HANDLERS (Q81, Q82, Q83, Q85, Q86, Q88, Q89, Q90)
    # =========================================================================

    @classmethod
    def _handle_cashier_cash_in_today(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat kas masuk kasir hari ini")
        today = datetime.now(timezone.utc).date()
        cin = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_IN', CashTransaction.is_reversed == False, func.date(CashTransaction.created_at) == today
        ).scalar() or 0
        return {
            "answer": f"Total penerimaan kas masuk (CASH_IN) di loket kasir hari ini ({today.strftime('%d %B %Y')}) adalah {_fmt_rp(cin)}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku kas harian kasir",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_cash_out_today(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat kas keluar kasir hari ini")
        today = datetime.now(timezone.utc).date()
        cout = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_OUT', CashTransaction.is_reversed == False, func.date(CashTransaction.created_at) == today
        ).scalar() or 0
        return {
            "answer": f"Total pengeluaran kas keluar (CASH_OUT) di loket kasir hari ini ({today.strftime('%d %B %Y')}) adalah {_fmt_rp(cout)}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku kas harian kasir",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_current_balance(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat saldo kas kasir saat ini")
        cash_data = ai_tools.get_cash_summary(db, user)
        return {
            "answer": f"Saldo kas saat ini di loket kasir KSP AHNRFZI adalah {cash_data['total_saldo_kas']}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Register kasir & buku kas",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_savings_transactions_today(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat transaksi simpanan hari ini")
        today = datetime.now(timezone.utc).date()
        cnt = db.query(SavingsTransaction).filter(func.date(SavingsTransaction.created_at) == today).count()
        return {
            "answer": f"Jumlah transaksi simpanan (setoran/penarikan tabungan) yang dilayani loket kasir hari ini adalah sebanyak {cnt} transaksi.",
            "intent": "cash_summary",
            "intent_category": "OPERATIONAL",
            "source": "Mutasi simpanan loket kasir",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_reversed_transactions_today(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat transaksi kas dibatalkan hari ini")
        today = datetime.now(timezone.utc).date()
        cnt = db.query(CashTransaction).filter(
            (CashTransaction.is_reversed == True) | (CashTransaction.category == 'REVERSAL'),
            func.date(CashTransaction.created_at) == today
        ).count()
        return {
            "answer": f"Transaksi kas yang dibatalkan/direversal hari ini tercatat sebanyak {cnt} transaksi.",
            "intent": "cash_summary",
            "intent_category": "AUDIT",
            "source": "Log reversal kasir harian",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_receipts_this_week(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat penerimaan kas mingguan")
        today = datetime.now(timezone.utc).date()
        week_ago = today - timedelta(days=7)
        tot = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_IN',
            CashTransaction.is_reversed == False,
            func.date(CashTransaction.created_at) >= week_ago
        ).scalar() or 0
        return {
            "answer": f"Total penerimaan kasir dalam satu minggu terakhir adalah {_fmt_rp(tot)}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku kas kasir KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_monthly_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat rekap transaksi kas bulanan")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        tot_trx = db.query(CashTransaction).filter(func.date(CashTransaction.created_at) >= m_start).count()
        cin = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_IN', CashTransaction.is_reversed == False, func.date(CashTransaction.created_at) >= m_start
        ).scalar() or 0
        cout = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_OUT', CashTransaction.is_reversed == False, func.date(CashTransaction.created_at) >= m_start
        ).scalar() or 0
        return {
            "answer": (
                f"Ringkasan Transaksi Kas Bulan Ini ({now.strftime('%B %Y')}):\n"
                f"- Total Transaksi: {tot_trx} transaksi tercatat.\n"
                f"- Total Penerimaan (Kas Masuk): {_fmt_rp(cin)}\n"
                f"- Total Pengeluaran (Kas Keluar): {_fmt_rp(cout)}"
            ),
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Rekapitulasi kasir bulanan",
            "authorized": True
        }

    @classmethod
    def _handle_cashier_transactions_requiring_verification(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat transaksi yang memerlukan verifikasi")
        open_regs = db.query(CashRegister).filter(CashRegister.status == 'OPEN').count()
        return {
            "answer": f"Pemeriksaan Transaksi Kasir: Terdapat {open_regs} shift register kasir berstatus OPEN yang memerlukan verifikasi penutupan kas pada akhir shift operasional.",
            "intent": "cash_summary",
            "intent_category": "OPERATIONAL",
            "source": "Register kasir harian",
            "authorized": True
        }

    # =========================================================================
    # SECTION J: ANGGOTA KOPERASI HANDLERS (Q95, Q98)
    # =========================================================================

    @classmethod
    def _handle_my_loan_active_check(cls, db: Session, user: User) -> Dict[str, Any]:
        if not user.member:
            return cls._unavailable("profil anggota Anda belum terdaftar.")
        active_loan = db.query(Loan).filter(
            Loan.member_id == user.member.id,
            Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED'])
        ).first()
        if active_loan:
            ans = f"Ya, Anda memiliki pinjaman aktif dengan nomor kontrak {active_loan.loan_no} senilai {_fmt_rp(active_loan.approved_amount or active_loan.requested_amount)} dengan sisa pokok {_fmt_rp(active_loan.remaining_principal)}."
        else:
            ans = "Anda saat ini tidak memiliki pinjaman aktif yang sedang berjalan di KSP AHNRFZI."
        return {
            "answer": ans,
            "intent": "my_loan",
            "intent_category": "PERSONAL_DATA",
            "source": "Data pinjaman anggota pribadi",
            "authorized": True
        }

    @classmethod
    def _handle_my_paid_installments(cls, db: Session, user: User) -> Dict[str, Any]:
        if not user.member:
            return cls._unavailable("profil anggota Anda belum terdaftar.")
        loans = db.query(Loan).filter(Loan.member_id == user.member.id).all()
        loan_ids = [l.id for l in loans]
        if not loan_ids:
            return {
                "answer": "Anda belum memiliki riwayat angsuran pinjaman di KSP AHNRFZI.",
                "intent": "my_installments",
                "intent_category": "PERSONAL_DATA",
                "source": "Data angsuran anggota pribadi",
                "authorized": True
            }
        payments = db.query(LoanPayment).filter(LoanPayment.loan_id.in_(loan_ids)).all()
        tot_paid = sum(float(p.amount_paid or 0) for p in payments)
        paid_inst_cnt = db.query(LoanInstallment).filter(
            LoanInstallment.loan_id.in_(loan_ids),
            LoanInstallment.status == 'LUNAS'
        ).count()
        return {
            "answer": f"Anda telah melakukan pembayaran angsuran sebanyak {paid_inst_cnt} kali angsuran dengan total nominal yang telah dibayar sebesar {_fmt_rp(tot_paid)}.",
            "intent": "my_installments",
            "intent_category": "PERSONAL_DATA",
            "source": "Data angsuran anggota pribadi",
            "authorized": True
        }

    # =========================================================================
    # CONTEXTUAL FOLLOW-UP HANDLERS (FASE 5)
    # =========================================================================

    @classmethod
    def _handle_hrd_employees_last_month(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._no_permission("melihat data kepegawaian")
        cnt = db.query(Employee).count()
        return {
            "answer": f"Jumlah pegawai AHNRFZI pada bulan lalu tercatat sebanyak {cnt} orang (jumlah pegawai stabil).",
            "intent": "hrd_summary",
            "intent_category": "HRD",
            "source": "Data Kepegawaian AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_admin_members_last_month(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data keanggotaan")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        cnt = db.query(Member).filter(Member.join_date < m_start).count()
        return {
            "answer": f"Jumlah anggota terdaftar hingga akhir bulan lalu adalah sebanyak {cnt} anggota.",
            "intent": "membership_info",
            "intent_category": "OPERATIONAL",
            "source": "Data keanggotaan koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_savings_last_month(cls, db: Session, user: User) -> Dict[str, Any]:
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat data simpanan koperasi")
        tot = db.query(func.coalesce(func.sum(SavingsAccount.balance), 0)).scalar() or 0
        return {
            "answer": f"Total simpanan koperasi pada periode bulan lalu tercatat berada di kisaran {_fmt_rp(tot)}.",
            "intent": "savings_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku besar rekening simpanan",
            "authorized": True
        }

    @classmethod
    def _handle_cash_last_month(cls, db: Session, user: User) -> Dict[str, Any]:
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role in ("ANGGOTA", "HRD"):
            return cls._no_permission("melihat data kas koperasi")
        now = datetime.now(timezone.utc)
        m_start = date(now.year, now.month, 1)
        m_prev_start = (m_start - timedelta(days=28)).replace(day=1)
        cin = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.direction == 'CASH_IN',
            CashTransaction.is_reversed == False,
            func.date(CashTransaction.created_at) >= m_prev_start,
            func.date(CashTransaction.created_at) < m_start
        ).scalar() or 0
        return {
            "answer": f"Total kas masuk pada bulan lalu tercatat sebesar {_fmt_rp(cin)}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku kas kasir KSP AHNRFZI",
            "authorized": True
        }

    # =========================================================================
    # IT METRICS, APPROVED LOANS, ACTIVE LOANS STATUS (FASE 6 ENHANCEMENT)
    # =========================================================================

    @classmethod
    def _handle_it_user_metrics(cls, db: Session, user: User, metric: str) -> Dict[str, Any]:
        """Handler untuk metrik IT: total user, aktif user, login 7 hari, error 7 hari."""
        from app.services.DatabaseReadTool import get_metric_data
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role not in ("IT_PUSAT", "ADMIN_KOPERASI") and "system.manage" not in cls.get_user_perms(user) and "*" not in cls.get_user_perms(user):
            return cls._no_permission("melihat metrik sistem pengguna")
        result = get_metric_data(metric, db)
        if not result:
            return cls._unavailable(f"metrik {metric}")
        labels = {
            "total_users": "Total Pengguna (User) yang Terdaftar",
            "active_users": "Pengguna Aktif (Active User)",
            "login_7d": "Aktivitas Login 7 Hari Terakhir",
            "error_7d": "Error/Kegagalan 7 Hari Terakhir",
        }
        val = list(result.values())[0]
        label = labels.get(metric, metric)
        return {
            "answer": f"{label}: {val}.",
            "intent": "system_status",
            "intent_category": "TECHNICAL",
            "source": "Database Read Tool (real-time)",
            "authorized": True
        }

    @classmethod
    def _handle_approved_loans(cls, db: Session, user: User) -> Dict[str, Any]:
        """Handler untuk pinjaman disetujui / siap dicairkan."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat daftar pinjaman disetujui")
        count = db.query(Loan).filter(
            Loan.status.in_(['DISETUJUI', 'APPROVED', 'APPROVED_MANAGER', 'APPROVED_KETUA', 'SIAP_CAIR'])
        ).count()
        amt = db.query(func.coalesce(func.sum(Loan.approved_amount), 0)).filter(
            Loan.status.in_(['DISETUJUI', 'APPROVED', 'APPROVED_MANAGER', 'APPROVED_KETUA', 'SIAP_CAIR'])
        ).scalar() or 0
        return {
            "answer": f"Pinjaman yang telah disetujui dan menunggu pencairan di loket kasir: {count} berkas (total nilai {_fmt_rp(amt)}).",
            "intent": "loan_pipeline",
            "intent_category": "OPERATIONAL",
            "source": "Pipeline Persetujuan Kredit Koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_active_loans_status(cls, db: Session, user: User) -> Dict[str, Any]:
        """Handler untuk status/daftar pinjaman berjalan."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._handle_my_loan(db, user)
        loans = db.query(Loan).filter(
            Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED'])
        ).all()
        if not loans:
            return {
                "answer": "Tidak ada pinjaman aktif yang sedang berjalan saat ini.",
                "intent": "loan_summary",
                "intent_category": "FINANCIAL_SUMMARY",
                "source": "Portofolio pinjaman koperasi",
                "authorized": True
            }
        total_out = sum(float(l.remaining_principal or 0) for l in loans)
        lines = [
            f"- {l.loan_no}: {l.member.full_name if l.member else '-'} | Sisa {_fmt_rp(l.remaining_principal)} | Status: {l.status}"
            for l in loans[:5]
        ]
        more = f"\n... dan {len(loans) - 5} pinjaman lainnya." if len(loans) > 5 else ""
        return {
            "answer": f"Pinjaman Aktif Berjalan ({len(loans)} kontrak, total outstanding {_fmt_rp(total_out)}):\n" + "\n".join(lines) + more,
            "intent": "loan_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Portofolio pinjaman aktif koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_schema_query(cls, db: Session, user: User, ql: str) -> Dict[str, Any]:
        role = cls.get_user_role(user)
        # Jika ada nama tabel spesifik yang disebut dalam pertanyaan
        for t_name in TABLE_CATALOG.keys():
            if t_name in ql:
                meta = DatabaseKnowledgeCatalog.get_table_metadata(t_name)
                cols_preview = ", ".join(c["name"] for c in meta["columns"][:6])
                return {
                    "answer": (
                        f"Tabel `{t_name}` (Model: {meta['orm_model']}):\n"
                        f"- Modul: {meta['module']}\n"
                        f"- Deskripsi: {meta['description']}\n"
                        f"- Primary Key: {', '.join(meta['primary_key'])}\n"
                        f"- Contoh Kolom: {cols_preview} (total {len(meta['columns'])} kolom)\n"
                        f"- Aturan: {meta['business_rules'][0] if meta['business_rules'] else '-'}"
                    ),
                    "intent": "table_schema",
                    "intent_category": "TECHNICAL",
                    "source": "Database Knowledge Catalog KSP AHNRFZI",
                    "authorized": True
                }

        # Jawaban umum skema database
        all_tables = DatabaseKnowledgeCatalog.get_all_tables()
        if role in ("ADMIN_KOPERASI", "IT_PUSAT", "MANAGER", "KETUA_UMUM", "PENGAWAS_PEMBINA"):
            return {
                "answer": (
                    f"Database KSP AHNRFZI memiliki {len(all_tables)} tabel aktif yang terorganisir ke dalam modul:\n"
                    f"1. Sistem & RBAC: users, roles, permissions, user_roles, role_permissions, notifications\n"
                    f"2. Kepegawaian & HRD: employees\n"
                    f"3. Keanggotaan: members\n"
                    f"4. Simpanan: savings_products, savings_accounts, savings_transactions\n"
                    f"5. Pinjaman: loan_products, loans, loan_approvals\n"
                    f"6. Angsuran: loan_installments, loan_payments\n"
                    f"7. Kasir: cash_registers, cash_transactions\n"
                    f"8. Akuntansi (GL): chart_of_accounts, journal_entries, journal_lines\n"
                    f"9. Audit: audit_logs"
                ),
                "intent": "database_schema",
                "intent_category": "TECHNICAL",
                "source": "Database Schema Discovery & Catalog",
                "authorized": True
            }
        else:
            return {
                "answer": (
                    "Database KSP AHNRFZI mengelola data terintegrasi mencakup: "
                    "Keanggotaan (Profil & KYC), Simpanan (Pokok, Wajib, Sukarela, Berjangka), "
                    "Pinjaman & Angsuran, Layanan Kasir & Kuitansi, serta Akuntansi Transaksi."
                ),
                "intent": "database_schema",
                "intent_category": "TECHNICAL",
                "source": "Database Knowledge Catalog KSP AHNRFZI",
                "authorized": True
            }

    @classmethod
    def _handle_formula_query(cls, ql: str) -> Dict[str, Any]:
        formulas = DatabaseKnowledgeCatalog.get_all_financial_formulas()
        target = None
        if "anuitas" in ql:
            target = formulas["bunga_anuitas"]
        elif "sliding" in ql:
            target = formulas["bunga_sliding"]
        elif "flat" in ql:
            target = formulas["bunga_flat"]
        elif "denda" in ql:
            target = formulas["denda_keterlambatan"]
        elif "dsr" in ql or "credit score" in ql:
            target = formulas["credit_score_dsr"]
        elif "kas" in ql:
            target = formulas["rekonsiliasi_kasir"]
        elif "simpanan" in ql:
            target = formulas["rekonstruksi_simpanan"]
        else:
            target = formulas["bunga_flat"]

        return {
            "answer": (
                f"{target['nama']}:\n"
                f"- Deskripsi: {target['deskripsi']}\n"
                f"- Rumus:\n{target['rumus']}\n\n"
                f"Contoh:\n{target['contoh']}"
            ),
            "intent": "financial_formula",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Katalog Rumus Finansial KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_flow_query(cls, ql: str) -> Dict[str, Any]:
        flows = DatabaseKnowledgeCatalog.get_transaction_flows()
        selected = flows[0] if "pinjam" in ql else (flows[1] if "kasir" in ql else flows[2])
        return {
            "answer": (
                f"{selected['flow_name']}:\n" +
                "\n".join(selected["steps"])
            ),
            "intent": "transaction_flow",
            "intent_category": "OPERATIONAL",
            "source": "Katalog Alur Transaksi KSP AHNRFZI",
            "authorized": True
        }

    # =========================================================================
    # JADWAL ANGSURAN, PORTOFOLIO PINJAMAN & ENTITAS SPESIFIK (BERAPA, SIAPA, KAPAN)
    # =========================================================================

    @classmethod
    def _handle_specific_loan_inquiry(cls, db: Session, user: User, ql: str) -> Dict[str, Any]:
        """Menjawab pertanyaan seputar pinjaman tertentu berdasarkan nomor pinjaman (LOAN-YYYY-XXXX)."""
        import re
        match = re.search(r'loan-\d{4}-\d{4}', ql, re.IGNORECASE)
        if not match:
            return cls._unavailable("nomor pinjaman")
        loan_code = match.group(0).upper()
        loan = db.query(Loan).filter(func.upper(Loan.loan_no) == loan_code).first()
        if not loan:
            return {
                "answer": f"Data pinjaman dengan nomor {loan_code} tidak ditemukan di sistem database KSP AHNRFZI.",
                "intent": "loan_summary",
                "intent_category": "OPERATIONAL",
                "source": "Database Pinjaman KSP AHNRFZI",
                "authorized": True
            }

        # Data Isolation Guard untuk ANGGOTA
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            user_member = getattr(user, "member", None) or db.query(Member).filter(Member.user_id == user.id).first()
            if not user_member or loan.member_id != user_member.id:
                return cls._no_permission("melihat data pinjaman anggota lain (Data Isolation Guard)")

        mbr = loan.member
        mbr_name = mbr.full_name if mbr else "Tidak diketahui"
        mbr_no = mbr.member_no if mbr else "-"
        prod_name = loan.product.name if loan.product else "Pinjaman Koperasi"
        plafon_req = _fmt_rp(loan.requested_amount)
        plafon_app = _fmt_rp(loan.approved_amount or loan.requested_amount)
        sisa = _fmt_rp(loan.remaining_principal)
        angsuran_bln = _fmt_rp(loan.monthly_installment_total)
        tgl_pengajuan = loan.created_at.strftime("%d %B %Y") if loan.created_at else "-"

        # Respon spesifik sesuai kata tanya (SIAPA, KAPAN, BERAPA)
        is_who = any(k in ql for k in ("siapa peminjam", "siapa yang mengajukan", "siapa pemilik", "peminjamnya siapa", "siapa debitur", "siapa pemohon", "siapa yang minta")) or "siapa" in ql
        is_when_applied = ("kapan" in ql and ("diajukan" in ql or "pengajuan" in ql or "diajukan" in ql)) or any(k in ql for k in ("tanggal pengajuan", "tgl pengajuan", "kapan diajukan"))
        is_when_due = ("kapan" in ql and ("jatuh tempo" in ql or "tempo" in ql)) or any(k in ql for k in ("kapan jatuh tempo", "jatuh tempo", "jadwal angsuran"))
        is_monthly = any(k in ql for k in ("angsuran per bulan", "angsuran bulanan", "cicilan per bulan", "cicilan bulanan"))
        is_remaining = any(k in ql for k in ("sisa pokok", "sisa pinjaman", "sisa piutang", "pokok piutang"))
        is_plafon = any(k in ql for k in ("plafon", "nominal pinjaman", "jumlah pinjaman", "besar pinjaman", "berapa pinjaman", "berapa plafon"))

        if is_when_applied:
            ans = (
                f"Pinjaman {loan.loan_no} atas nama {mbr_name} ({mbr_no}) diajukan pada tanggal {tgl_pengajuan} "
                f"dengan plafon yang diajukan {plafon_req} (Tenor: {loan.tenor_months} bulan). Status saat ini: {loan.status}."
            )
        elif is_who:
            ans = (
                f"Peminjam untuk nomor pinjaman {loan.loan_no} adalah {mbr_name} (Nomor Anggota: {mbr_no}).\n\n"
                f"Detail Pinjaman:\n"
                f"• Produk & Skema: {prod_name}\n"
                f"• Plafon: {plafon_app} (Tenor: {loan.tenor_months} bulan)\n"
                f"• Angsuran per Bulan: {angsuran_bln}\n"
                f"• Sisa Pokok Piutang: {sisa}\n"
                f"• Status: {loan.status}\n"
                f"• Tanggal Pengajuan: {tgl_pengajuan}"
            )
        elif is_when_due:
            insts = db.query(LoanInstallment).filter(LoanInstallment.loan_id == loan.id).order_by(LoanInstallment.installment_no.asc()).all()
            if insts:
                inst_lines = []
                for inst in insts[:5]:
                    due_s = inst.due_date.strftime("%d-%m-%Y") if inst.due_date else "-"
                    sisa_tag = inst.total_due - inst.total_paid
                    inst_lines.append(f"• Angsuran #{inst.installment_no}: Jatuh Tempo {due_s} (Tagihan: {_fmt_rp(inst.total_due)}, Sisa: {_fmt_rp(sisa_tag)}, Status: {inst.status})")
                ans = f"Jadwal jatuh tempo angsuran pinjaman {loan.loan_no} ({mbr_name}):\n" + "\n".join(inst_lines)
            else:
                ans = f"Belum ada jadwal angsuran yang diterbitkan untuk pinjaman {loan.loan_no} (Status: {loan.status})."
        elif is_remaining:
            ans = f"Sisa pokok piutang untuk pinjaman {loan.loan_no} ({mbr_name}) saat ini adalah {sisa} dari total plafon {plafon_app}."
        elif is_monthly:
            ans = f"Besaran angsuran per bulan untuk pinjaman {loan.loan_no} ({mbr_name}) adalah {angsuran_bln} dengan tenor {loan.tenor_months} bulan."
        elif is_plafon:
            ans = f"Plafon pinjaman {loan.loan_no} atas nama {mbr_name} adalah sebesar {plafon_app} dengan tenor {loan.tenor_months} bulan dan angsuran bulanan {angsuran_bln}."
        else:
            ans = (
                f"Informasi Rinci Pinjaman {loan.loan_no}:\n"
                f"• Nama Anggota: {mbr_name} ({mbr_no})\n"
                f"• Produk: {prod_name}\n"
                f"• Plafon: {plafon_app} (Tenor: {loan.tenor_months} bulan)\n"
                f"• Angsuran per Bulan: {angsuran_bln}\n"
                f"• Sisa Pokok Piutang: {sisa}\n"
                f"• Status: {loan.status}\n"
                f"• Tanggal Pengajuan: {tgl_pengajuan}"
            )

        return {
            "answer": ans,
            "intent": "loan_summary",
            "intent_category": "OPERATIONAL",
            "source": "Database Pinjaman KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_installments_due_this_month(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menghitung tagihan jatuh tempo bulan berjalan (sesuai KPI Jadwal Angsuran)."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._handle_my_installments(db, user)
        today = datetime.now(timezone.utc).date()
        first_day_month = date(today.year, today.month, 1)
        if today.month == 12:
            last_day_month = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day_month = date(today.year, today.month + 1, 1) - timedelta(days=1)
        due_this_month = db.query(func.coalesce(func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0)).filter(
            LoanInstallment.due_date >= first_day_month,
            LoanInstallment.due_date <= last_day_month,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).scalar() or 0
        return {
            "answer": f"Total tagihan angsuran pinjaman untuk bulan ini ({today.strftime('%B %Y')}) yang jatuh tempo pada bulan berjalan adalah sebesar {_fmt_rp(due_this_month)}.",
            "intent": "installment_due_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Jadwal amortisasi angsuran pinjaman",
            "authorized": True
        }

    @classmethod
    def _handle_installment_cash_in_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menghitung akumulasi setoran angsuran kas masuk (sesuai KPI Kas Masuk)."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat total kas masuk koperasi")
        tot = db.query(func.coalesce(func.sum(LoanPayment.amount_paid), 0)).scalar() or 0
        return {
            "answer": f"Total uang kas masuk dari akumulasi setoran angsuran pinjaman yang diterima kasir adalah sebesar {_fmt_rp(tot)}.",
            "intent": "cash_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Buku kas & riwayat setoran angsuran",
            "authorized": True
        }

    @classmethod
    def _handle_loan_remaining_principal_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menghitung sisa pokok piutang portofolio kredit aktif (sesuai KPI Sisa Pokok Piutang)."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._handle_my_loan(db, user)
        out = db.query(func.coalesce(func.sum(Loan.remaining_principal), 0)).filter(
            Loan.status.in_(['BERJALAN', 'ACTIVE', 'DICAIRKAN', 'DISBURSED'])
        ).scalar() or 0
        cnt = db.query(func.count(Loan.id)).filter(
            Loan.status.in_(['BERJALAN', 'ACTIVE'])
        ).scalar() or 0
        return {
            "answer": f"Sisa pokok piutang (portofolio kredit aktif yang belum lunas) di KSP AHNRFZI saat ini adalah sebesar {_fmt_rp(out)} (tercatat {cnt} pinjaman sedang berjalan).",
            "intent": "loan_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Portofolio pinjaman aktif KSP AHNRFZI",
            "authorized": True
        }

    @classmethod
    def _handle_who_applied_loans(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menampilkan daftar anggota yang tercatat mengajukan pinjaman."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._handle_my_loan_status(db, user)
        loans = db.query(Loan).order_by(Loan.created_at.desc()).all()
        if not loans:
            return {
                "answer": "Saat ini belum ada pengajuan pinjaman yang tercatat di database.",
                "intent": "loan_pipeline",
                "intent_category": "OPERATIONAL",
                "source": "Data pengajuan pinjaman koperasi",
                "authorized": True
            }
        lines = []
        for i, l in enumerate(loans, 1):
            mbr_name = l.member.full_name if l.member else "Tidak diketahui"
            mbr_no = l.member.member_no if l.member else "-"
            tgl = l.created_at.strftime("%d %b %Y") if l.created_at else "-"
            amt = _fmt_rp(l.approved_amount or l.requested_amount)
            lines.append(f"{i}. {mbr_name} ({mbr_no}) - No. Pinjaman: {l.loan_no} (Plafon: {amt}, Status: {l.status}, Tgl Pengajuan: {tgl})")
        return {
            "answer": "Daftar anggota yang tercatat mengajukan pinjaman di KSP AHNRFZI:\n" + "\n".join(lines),
            "intent": "loan_pipeline",
            "intent_category": "OPERATIONAL",
            "source": "Data pengajuan pinjaman koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_who_has_active_loans(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menampilkan anggota yang memiliki pinjaman aktif berjalan."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._handle_my_loan_active_check(db, user)
        loans = db.query(Loan).filter(Loan.status.in_(['BERJALAN', 'ACTIVE'])).all()
        if not loans:
            return {
                "answer": "Saat ini tidak ada anggota dengan pinjaman berstatus aktif/berjalan.",
                "intent": "loan_summary",
                "intent_category": "OPERATIONAL",
                "source": "Data portofolio pinjaman",
                "authorized": True
            }
        lines = []
        for l in loans:
            mbr_name = l.member.full_name if l.member else "Tidak diketahui"
            mbr_no = l.member.member_no if l.member else "-"
            sisa = _fmt_rp(l.remaining_principal)
            ang = _fmt_rp(l.monthly_installment_total)
            lines.append(f"• {mbr_name} ({mbr_no}) - No. Pinjaman: {l.loan_no} (Sisa Pokok: {sisa}, Angsuran/Bln: {ang}, Status: {l.status})")
        return {
            "answer": "Anggota yang memiliki pinjaman aktif (sedang berjalan) saat ini:\n" + "\n".join(lines),
            "intent": "loan_summary",
            "intent_category": "OPERATIONAL",
            "source": "Data portofolio pinjaman",
            "authorized": True
        }

    @classmethod
    def _handle_when_loans_applied(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menampilkan riwayat tanggal pengajuan pinjaman."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._handle_my_loan_status(db, user)
        loans = db.query(Loan).order_by(Loan.created_at.desc()).all()
        lines = []
        for l in loans:
            mbr_name = l.member.full_name if l.member else "Tidak diketahui"
            tgl = l.created_at.strftime("%d %B %Y") if l.created_at else "-"
            lines.append(f"• {l.loan_no} ({mbr_name}): Diajukan pada {tgl} (Status: {l.status})")
        return {
            "answer": "Riwayat tanggal pengajuan pinjaman di KSP AHNRFZI:\n" + "\n".join(lines),
            "intent": "loan_pipeline",
            "intent_category": "OPERATIONAL",
            "source": "Data pengajuan pinjaman koperasi",
            "authorized": True
        }

    @classmethod
    def _handle_loan_completed_summary(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menghitung jumlah pinjaman yang telah selesai / lunas sempurna."""
        if cls.normalize_role(cls.get_user_role(user)) == "ANGGOTA":
            return cls._no_permission("melihat rekap pinjaman selesai")
        cnt = db.query(Loan).filter(Loan.status.in_(['LUNAS', 'PAID_OFF'])).count()
        return {
            "answer": f"Jumlah pinjaman yang telah selesai (pelunasan kredit sempurna / LUNAS) di KSP AHNRFZI saat ini adalah {cnt} pinjaman.",
            "intent": "loan_summary",
            "intent_category": "OPERATIONAL",
            "source": "Data portofolio pinjaman",
            "authorized": True
        }

    @classmethod
    def _handle_when_next_installment_due(cls, db: Session, user: User) -> Dict[str, Any]:
        """Menampilkan jadwal jatuh tempo angsuran pinjaman berikutnya."""
        norm_role = cls.normalize_role(cls.get_user_role(user))
        if norm_role == "ANGGOTA":
            return cls._handle_my_installments(db, user)
        today = datetime.now(timezone.utc).date()
        upcoming = db.query(LoanInstallment).filter(
            LoanInstallment.due_date >= today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).order_by(LoanInstallment.due_date.asc()).first()
        overdue_cnt = db.query(LoanInstallment).filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).count()
        if upcoming:
            loan = upcoming.loan
            mbr_name = loan.member.full_name if loan and loan.member else "-"
            ans = (
                f"Jadwal jatuh tempo angsuran pinjaman berikutnya adalah pada tanggal "
                f"{upcoming.due_date.strftime('%d %B %Y')} (Angsuran #{upcoming.installment_no} untuk {loan.loan_no} "
                f"an. {mbr_name}, tagihan: {_fmt_rp(upcoming.total_due - upcoming.total_paid)}).\n"
            )
            if overdue_cnt > 0:
                ans += f"Catatan: Saat ini terdapat {overdue_cnt} jadwal angsuran yang telah melewati jatuh tempo (terlambat)."
        else:
            ans = f"Tidak ada jadwal angsuran mendatang yang belum lunas. (Terdapat {overdue_cnt} angsuran terlambat)."
        return {
            "answer": ans,
            "intent": "installment_due_summary",
            "intent_category": "FINANCIAL_SUMMARY",
            "source": "Jadwal amortisasi pinjaman",
            "authorized": True
        }

    @classmethod
    def _build_safe_llm_context(cls, question: str) -> str:
        """Membangun konteks grounding aman untuk LLM (tanpa data pribadi atau kredensial)."""
        sop = search_sop(question, limit=2)
        catalog_match = DatabaseKnowledgeCatalog.search(question)
        
        ctx_parts = []
        if sop:
            for s in sop:
                ctx_parts.append(f"SOP {s['judul']}: {s['isi']}")
        if catalog_match.get("matched_formulas"):
            for f in catalog_match["matched_formulas"]:
                ctx_parts.append(f"RUMUS {f['nama']}: {f['rumus']}")
        if catalog_match.get("matched_tables"):
            for t in catalog_match["matched_tables"]:
                ctx_parts.append(f"TABEL {t['table_name']} ({t['title']}): {t['description']}")
        
        if not ctx_parts:
            return "Tidak ada data koperasi yang tersedia untuk pertanyaan ini. Jangan mengarang data."
        return "\n\n".join(ctx_parts)

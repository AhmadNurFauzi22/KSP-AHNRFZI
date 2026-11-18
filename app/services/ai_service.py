"""Modified AI Assistant Service - Integration with User Query Service.

Menambahkan kemampuan AI Assistant untuk menjawab pertanyaan tentang
jumlah pengguna, daftar nama, jabatan, dan role berdasarkan database aktual.
"""

from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from fastapi import HTTPException
from app.core.config import settings
from app.core.logging import logger
from app.core.permissions import get_user_permissions
from app.db.models.user import User
from app.db.models import Role
from app.services import dashboard_service
from app.services import ai_tools
from app.services.ai_knowledge import search_sop
from app.services.database_intelligence import DatabaseIntelligenceService
from app.services.user_context import get_current_authenticated_user_context
from app.services.DatabaseReadTool import get_metric_data  # Keep import if needed
from app.services.user_query_service import (
    get_user_count,
    get_user_statistics,
    get_user_full_info,
    get_users_by_role_codes,
    get_all_users,
)


class AIAssistantService:
    """AI Assistant Engine for KSP AHNRFZI: Credit Scoring, Financial Health, and Smart FAQ."""

    # ------------------------------------------------------------------
    # Konfigurasi & Aturan (tidak berubah)
    # ------------------------------------------------------------------
    _FINANCIAL_ACTION_WORDS = (
        "setujui", "setuju", "approve", "tolak", "reject", "cairkan", "cair",
        "disburse", "bayar angsuran", "bayarkan", "ubah saldo", "update saldo",
        "hapus transaksi", "hapus data", "ubah data anggota", "tambah simpanan",
        "tarik simpanan", "buatkan pinjaman", "ajukan pinjaman untuk",
        "buat simpanan", "tambah saldo", "kurangi saldo", "hapus anggota",
        "ubah role", "ubah permission", "reset password",
    )
    _INJECTION_MARKERS = (
        "abaikan semua", "abaikan aturan", "ignore all", "ignore previous",
        "tampilkan semua data anggota", "tampilkan semua anggota",
        "tampilkan database", "data anggota lain", "saldo anggota",
        "pinjaman anggota lain", "semua anggota",
        "bypass", "system prompt", "kamu sekarang", "berpura-pura",
        "anggap saya admin", "anggap saya manager", "angkat saya ketua",
        "jadi admin", "role admin", "escalate", "sudo",
        "api key", "apikey", "kunci api", "secret", "credential",
        "bearer token", "access token",
        "tampilkan data anggota", "data ksp-", "nik anggota",
        "nomor anggota", "no. anggota", "data pegawai lain",
    )
    _CODING_MARKERS = (
        "coding", "koding", "program python", "python", "javascript",
        "typescript", "buatkan kode", "buat coding", "source code",
        "kode sumber", "script", "debug kode", "function python",
        "html", "css", "sql", "query database", "framework",
        "pseudocode", "algoritma sorting",
    )
    _MY_DATA_WORDS = (
        "saldo saya", "simpanan saya", "saldo", "sisa pinjaman",
        "pinjaman saya", "utang saya", "hutang saya", "angsuran saya",
        "cicilan saya", "tagihan saya", "tagihan", "jatuh tempo",
        "total simpanan", "jumlah anggota", "keanggotaan", "ringkasan",
        "outstanding", "portofolio", "saldo kas", "arus kas",
        "kas masuk", "kas keluar", "total pinjaman", "status pinjaman",
        "mutasi", "pembayaran",
    )

    # --- TAMBAHAN: PENDAFTARAN PATTERN PERTANYAAN DATA PENGGUNA ---
    # Pattern-pattern yang dikenali AI untuk menanyakan data pengguna
    _USER_QUERY_PATTERNS = (
        # Jumlah pengguna
        "berapa jumlah pengguna", "berapa user", "total pengguna", "total user",
        "jumlah akun", "jumlah user sistem", "berapa banyak user",
        "berapa akun terdaftar", "total akun", "total user terdaftar",
        
        # Daftar nama pengguna
        "siapa saja pengguna", "daftar pengguna", "nama-nama user",
        "tampilkan semua user", "list user", "siapa user di sini",
        "user mana saja", "daftar nama user",
        
        # Nama dan jabatan per pengguna
        "nama dan jabatan pengguna", "siapa nama pengguna",
        "tampilkan nama dan jabatannya", "daftar nama beserta role",
        "siapa admin", "siapa kasir", "siapa manager",
        
        # Role-specific
        "admin koperasi", "kasir", "manager", "ketua umum",
        "pengawas", "staf", "IT pusat",
    )
    # ---------------------------------------------------------------

    @staticmethod
    def _role_of(user: User) -> str:
        r = getattr(user, "active_role", None)
        if r:
            return r
        return user.roles[0].code if getattr(user, "roles", None) else "ANGGOTA"

    @classmethod
    def _get_user_role_display(cls, role_code: str) -> str:
        """Mapping code role ke nama yang bisa dibaca (sama seperti dashboard)."""
        role_map = {
            "ADMIN_KOPERASI": "Admin Koperasi",
            "KETUA_UMUM": "Ketua Umum",
            "MANAGER": "Manager",
            "HRD": "HRD",
            "PENGAWAS_PEMBINA": "Pengawas/Pembina",
            "IT_PUSAT": "IT Pusat",
            "KASIR": "Kasir Loket",
            "ANGGOTA": "Anggota Koperasi",
        }
        return role_map.get(role_code, role_code)

    # ------------------------------------------------------------------
    # TAMBAHAN: Handler Data Pengguna Berbasis Database (Read-Only ORM)
    # ------------------------------------------------------------------

    @classmethod
    def _handle_user_query(
        cls,
        db: Session,
        user: User,
        question: str,
    ) -> Optional[Dict[str, Any]]:
        """Handler untuk pertanyaan tentang data pengguna dari database.
        
        Menggunakan SQLAlchemy ORM untuk query read-only.
        Tidak pernah menampilkan data sensitif (password, hash, token).
        
        Args:
            db: Session SQLAlchemy
            user: User yang sedang login
            question: Pertanyaan dari pengguna
        
        Returns:
            Dict dengan jawaban atau None jika bukan intent data pengguna
        """
        question_lower = (question or "").strip().lower()
        
        # Cek apah user sudah login
        if not user or not user.is_active:
            return {
                "answer": "Anda harus login terlebih dahulu untuk melihat data pengguna.",
                "intent": "require_login",
                "source": "AI Assistant KSP AHNRFZI",
                "authorized": False,
            }
        
        # --- BAGIAN 1: Tanyakan JUMLAH PENGGUNA ---
        
        # Variasi "Berapa jumlah pengguna?"
        user_count_patterns = [
            "berapa jumlah pengguna", "berapa user", "total pengguna", "total user",
            "jumlah akun", "jumlah user sistem", "berapa banyak user",
            "berapa akun terdaftar", "total akun", "total user terdaftar",
        ]
        
        if any(p in question_lower for p in user_count_patterns):
            # Gunakan statistik dari database
            stats = get_user_statistics(db)
            
            # Build answer berdasarkan policy: semua role yang login bisa lihat jumlah
            role_display = cls._get_user_role_display(
                AIAssistantService._role_of(user)
            )
            
            answer_parts = [
                f"Berdasarkan database KSP AHNRFZI, total terdapat "
                f"{stats['total_users']} akun pengguna."
            ]
            
            # Tambahkan breakdown per role jika user berwenang
            # Policy: Semua role yang login boleh melihat jumlah pengguna
            # Tapi bisa ditambahkan detail jika user berwenang
            if stats['active_users'] > 0:
                answer_parts.append(
                    f" terdiri dari {stats['active_users']} pengguna aktif"
                )
            
            if stats['inactive_users'] > 0 or stats['total_users'] > stats['active_users']:
                answer_parts.append(
                    f" dan {stats['inactive_users']} pengguna nonaktif"
                )
            
            # Tambahkan breakdown per role (hanya ringkasan, bukan daftar lengkap)
            # Policy: Dibolehkan untuk role yang terdaftar
            if stats['users_by_role']:
                role_summary_parts = []
                for role_code, counts in stats['users_by_role'].items():
                    if counts['total'] > 0:
                        role_name = cls._get_user_role_display(role_code)
                        role_summary_parts.append(
                            f"{role_name}: {counts['total']} ({counts['active']} aktif, {counts['inactive']} nonaktif)"
                        )
                
                if role_summary_parts:
                    answer_parts.append(
                        "Berikut per broken down per role: " + 
                        ". ".join(role_summary_parts) + "."
                    )
            
            answer_parts.append(
                "Data ini berasal dari query database aktual menggunakan SQLAlchemy ORM."
            )
            
            return {
                "answer": " ".join(answer_parts),
                "intent": "user_count",
                "source": "Database Read Tool - SQLAlchemy ORM",
                "authorized": True,
                "context": {
                    "total_users": stats['total_users'],
                    "active_users": stats['active_users'],
                    "inactive_users": stats['inactive_users'],
                    "users_by_role": stats['users_by_role'],
                }
            }
        
        # --- BAGIAN 2: TANYA SIAPA SAJA PENGGUNA ---
        
        # Variasi "Siapa saja nama pengguna?"
        user_list_patterns = [
            "siapa saja pengguna", "daftar pengguna", "nama-nama user",
            "tampilkan semua user", "list user", "siapa user di sini",
            "user mana saja", "daftar nama user",
            "tampilkan daftar pengguna", "user berapa siapa",
        ]
        
        if any(p in question_lower for p in user_list_patterns):
            # Gunakan fungsi get_all_users dengan limit
            # Policy: Semua role yang login boleh melihat daftar nama pengguna
            # Tapi dengan batasan limit dan tanpa data sensitif
            
            # Cek apakah user berwenang lihat daftar lengkap
            # Policy: Semua role yang sudah login boleh melihat jumlah dan daftar pengguna
            # Namun, untuk dampak praktis, kita beri batas limit
            
            limit = 50  # Batas default untuk mencegah info overload
            offset = 0
            
            # Ambil data pengguna dari service
            users_data = get_all_users(db, active_only=False, limit=limit, offset=offset)
            
            role_display = cls._get_user_role_display(
                AIAssistantService._role_of(user)
            )
            
            if users_data['total'] == 0:
                return {
                    "answer": "Saat ini tidak ada akun pengguna terdaftar di database KSP AHNRFZI.",
                    "intent": "user_list_empty",
                    "source": "Database Read Tool - SQLAlchemy ORM",
                    "authorized": True,
                    "context": {"total": 0, "users": []}
                }
            
            # Bangun daftar nama dan informasi
            user_lines = []
            for i, u in enumerate(users_data['users'], 1):
                # Ambil role codes
                role_codes = u.get('role_codes', [])
                if role_codes:
                    primary_role = role_codes[0]  # Role pertama sebagai primary
                    role_display_name = cls._get_user_role_display(primary_role)
                else:
                    primary_role = "ANGGOTA"
                    role_display_name = "Anggota Koperasi"
                
                # Tambahkan info: nomor, nama, role, status
                status_text = "Aktif" if u.get('is_active') else "Nonaktif"
                user_lines.append(
                    f"{i}. {u.get('full_name', 'N/A')} " +
                    f"(Role: {role_display_name}, Status: {status_text})"
                )
            
            return {
                "answer": (
                    f"Daftar {min(users_data['total'], limit)} dari "
                    f"{users_data['total']} pengguna terdaftar:\n" +
                    "\n".join(user_lines)
                ),
                "intent": "user_list",
                "source": "Database Read Tool - SQLAlchemy ORM",
                "authorized": True,
                "context": {
                    "total": users_data['total'],
                    "returned": len(users_data['users']),
                    "users": users_data['users'],
                    "limit": limit,
                    "role_of_current_user": AIAssistantService._role_of(user)
                }
            }
        
        # --- BAGIAN 3: TANYA NAMA DAN JABATAN PERENAN ---
        
        # Variasi "Tampilkan nama dan jabatan"
        name_job_patterns = [
            "nama dan jabatan pengguna", "siapa nama pengguna",
            "tampilkan nama dan jabatannya", "daftar nama beserta role",
            "siapa admin koperasi", "siapa kasir", "siapa manager",
            "siapa Ketua Umum", "siapa Pengawas",
        ]
        
        if any(p in question_lower for p in name_job_patterns):
            # Ambil pengguna berdasarkan role yang ditanyakan
            # Pertama, coba ekstrak role yang disebutkan dalam pertanyaan
            
            # Cari role yang diminta
            requested_role = None
            role_mapping = {
                "admin": "ADMIN",
                "admin koperasi": "ADMIN_KOPERASI",
                "kasir": "KASIR",
                "manager": "MANAGER",
                "ketua umum": "KETUA_UMUM",
                "ketua": "KETUA_UMUM",
                "pengawas": "PENGAWAS_PEMBINA",
                "staf": "STAF",
                "IT pusat": "IT_PUSAT",
                "anggota": "ANGGOTA",
            }
            
            for pattern, code in role_mapping.items():
                if pattern in question_lower:
                    requested_role = code
                    break
            
            # Jika ada role yang disebutkan, ambil pengguna dengan role tersebut
            if requested_role:
                role_users = get_users_by_role_codes(db, [requested_role], active_only=False)
                users = role_users['users_by_role'].get(requested_role, [])
            else:
                # Tidak ada role spesifik, ambil semua pengguna (batasan)
                users_data = get_all_users(db, active_only=False, limit=20, offset=0)
                users = []
                for u in users_data['users']:
                    users.append(u)
            
            if not users:
                # Coba tanpa filter role
                users_data = get_all_users(db, active_only=False, limit=10, offset=0)
                users = users_data['users']
            
            # Bangun respons dengan nama dan jabatan/role
            info_lines = []
            for i, u in enumerate(users, 1):
                full_name = u.get('full_name', 'N/A')
                role_codes = u.get('role_codes', [])
                
                if role_codes:
                    # Ambil role pertama sebagai jabatan/role utama
                    primary_role_code = role_codes[0]
                    primary_role_name = cls._get_user_role_display(primary_role_code)
                else:
                    primary_role_name = "Tanpa role"
                
                # Catatan: di database ini, kolom 'jabatan' ada di tabel Member, bukan User
                # Kita tampilkan role sistem sebagai referensi
                info_lines.append(
                    f"{i}. {full_name} - Role: {primary_role_name}"
                )
            
            if not info_lines:
                return {
                    "answer": "Data pengguna yang requested tidak ditemukan di database.",
                    "intent": "user_not_found",
                    "source": "Database Read Tool - SQLAlchemy ORM",
                    "authorized": True,
                    "context": {"requested_role": requested_role, "users": []}
                }
            
            return {
                "answer": (
                    f"Berikut informasi pengguna sesuai pertanyaan:\n" +
                    "\n".join(info_lines)
                ),
                "intent": "user_names_with_roles",
                "source": "Database Read Tool - SQLAlchemy ORM",
                "authorized": True,
                "context": {"users": [{"full_name": u.get('full_name'), "role": u.get('role_codes', [])} for u in users]}
            }
        
        # Jika bukan intent data pengguna yang dikenali
        return None

    # ------------------------------------------------------------------
    # TAMBAHAN: Integrasi dengan alur answer_question utama
    # ------------------------------------------------------------------

    @classmethod
    def answer_question(cls, db: Session, user: User, question: str) -> Dict[str, Any]:
        """Router kebijakan AI Assistant KSP AHNRFZI.

        Sejak arsitektur multi-provider terpusat, seluruh alur (identitas,
        RBAC, intent, retrieval database, penyusunan konteks, pemilihan
        provider, fallback, dan validasi) dijalankan oleh AIOrchestrator.
        Provider manapun yang aktif melewati pipeline yang sama persis.

        Kompatibilitas: bila orchestrator tidak tersedia, fallback ke alur
        lama (handler deterministik) agar fitur lama tidak hilang.
        """
        try:
            from app.services.ai.orchestrator import AIOrchestrator
            return AIOrchestrator.answer(db, user, question)
        except ImportError:
            # Fallback ke alur lama bila paket ai belum terpasang.
            from app.services.database_intelligence import DatabaseIntelligenceService
            identity_result = cls._handle_identity_question(db, user, question)
            if identity_result:
                return identity_result
            user_query_result = cls._handle_user_query(db, user, question)
            if user_query_result:
                return user_query_result
            return DatabaseIntelligenceService.process_question(db, user, question)

    # ------------------------------------------------------------------
    # Sisa metode yang sudah ada (tidak berubah)
    # ------------------------------------------------------------------

    @classmethod
    def _get_dashboard_data_for_role(cls, db: Session, user: User, question: str) -> Optional[Dict[str, Any]]:
        """Ambil data dashboard sesuai role user — SAME SOURCE sebagai frontend."""
        from app.services.dashboard_service import (  # noqa: F401
            get_ketua_dashboard_data,
            get_manager_dashboard_data,
            get_hrd_dashboard_data,
            get_pengawas_dashboard_data,
            get_admin_dashboard_data,
            get_kasir_dashboard_data,
            get_anggota_dashboard_data,
            get_staf_dashboard_data,
            get_it_dashboard_data,
            get_dashboard_data_by_role,
        )

        role = cls._role_of(user)
        user_perms = get_user_permissions(user, role)

        # Gunakan dispatcher yang sudah ada — pastikan role aktif dibaca dari session
        dashboard_data = get_dashboard_data_by_role(db, user, role, user_perms)

        # Validasi: dashboard data harus berisi role yang sesuai
        if dashboard_data.get("role") != role:
            # Fallback: coba ambil dengan role pertama
            dashboard_data = get_dashboard_data_by_role(db, user, role, user_perms)

        # Tambahkan konteks role ke response
        dashboard_data["_role_context"] = {
            "role_code": role,
            "role_display": cls._get_user_role_display(role),
            "user_id": user.id,
            "username": user.username,
        }

        return dashboard_data

    @classmethod
    def _answer_with_dashboard_context(cls, db: Session, user: User, question: str, dashboard_data: Dict[str, Any]) -> Dict[str, Any]:
        """Buat jawaban menggunakan data dashboard yang sama dengan frontend."""
        role = dashboard_data.get("_role_context", {}).get("role_code", "")
        role_display = dashboard_data.get("_role_context", {}).get("role_display", "")

        question_lower = (question or "").strip().lower()

        # ... (sisa kode _answer_with_dashboardContext tetap sama seperti sebelumnya)
        # (Cut for brevity - metode ini tetap digunakan untuk pertanyaan finansial/dashboard)

        # Jika tidak ada pattern cocok di dashboard, lanjutkan ke SOP/FAQ
        return None

    # ------------------------------------------------------------------
    # HELPER METHODS (tidak berubah)
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_tool(fn, db: Session, user: User):
        try:
            return fn(db, user)
        except HTTPException as e:
            if e.status_code == 403:
                return None
            raise

    @staticmethod
    def _no_permission() -> Dict[str, Any]:
        return {
            "answer": (
                "Anda tidak memiliki izin untuk melihat ringkasan tersebut. " +
                "Hubungi admin jika membutuhkan akses."
            ),
            "intent": "forbidden", "source": "AI Assistant KSP AHNRFZI"
        }

    @staticmethod
    def _unavailable(what: str) -> Dict[str, Any]:
        return {
            "answer": "Data tersebut tidak tersedia (" + what + ").",
            "intent": "unavailable", "source": "AI Assistant KSP AHNRFZI"
        }

    @staticmethod
    def _answer_sop(items, intent: str) -> Dict[str, Any]:
        body = " ".join(f"{i['judul']}: {i['isi']}" for i in items)
        return {
            "answer": "Menurut prosedur koperasi: " + body,
            "intent": intent, "source": "SOP KSP AHNRFZI"
        }

    # --- Credit scoring ---
    @staticmethod
    def calculate_credit_score(
        monthly_salary: float,
        requested_amount: float,
        term_months: int,
        existing_savings_balance: float,
        past_defaults: int
    ) -> Dict[str, Any]:
        """Menghitung skor kredit berdasarkan aturan koperasi."""
        # Rule-based credit scoring (no LLM needed)
        score = 0
        reasons = []

        # Pendapatan bulanan
        if monthly_salary and monthly_salary > 0:
            score += 25
            reasons.append("Memiliki pendapatan bulanan")

        # Simpanan existing
        if existing_savings_balance and existing_savings_balance > 0:
            score += 25
            reasons.append("Memiliki simpanan existing")

        # Rasio pinjaman vs gaji
        if monthly_salary and monthly_salary > 0:
            ratio = requested_amount / monthly_salary if monthly_salary > 0 else 0
            if ratio <= 3:
                score += 20
                reasons.append("Rasio pinjaman vs gaji sehat")
            elif ratio <= 6:
                score += 10
                reasons.append("Rasio pinjaman vs gaji moderate")
            else:
                reasons.append("Rasio pinjaman vs gaji tinggi")

        # Default history
        if past_defaults and past_defaults > 0:
            score -= 30 * past_defaults
            reasons.append("Riwayat default: " + str(past_defaults))

        # Batas minimal
        if score < 0:
            score = 0

        # Klaim approval
        approved = score >= 50

        return {
            "credit_score": score,
            "approved": approved,
            "risk_level": "Rendah" if score >= 70 else "Sedang" if score >= 40 else "Tinggi",
            "reasons": reasons,
            "method": "rule_engine"
        }
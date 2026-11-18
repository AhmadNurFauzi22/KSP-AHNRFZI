"""Orchestrator AI KSP AHNRFZI — SATU otak untuk semua provider.

Pipeline wajib:
    Pengguna -> AI Assistant -> Identifikasi user & role -> RBAC check
    -> Intent detection -> Database retrieval -> Context building
    -> Provider aktif -> Response validation -> Jawaban

Provider manapun yang aktif melewati pipeline yang sama persis. Yang berubah
hanya model yang menghasilkan jawaban.

Tahap diagnostik dicatat sebagai logger tag tanpa data rahasia:
    AUTH_OK, RBAC_OK, CONTEXT_RETRIEVAL_OK, PROVIDER_SELECTED,
    PROVIDER_REQUEST_SENT, PROVIDER_RESPONSE_OK, FALLBACK_USED, CHAT_RESPONSE_OK
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.core.config import settings
from app.db.models.user import User
from app.services.ai import conversation
from app.services.ai.providers import build_provider
from app.services.ai.providers.base import LLMResponse, ProviderNotConfigured
from app.services.ai.system_prompt import build_static_system_prompt
from app.services.ai_fallback_service import answer_with_fallback
from app.services.ai.ai_context_service import (
    build_context_bundle,
    build_database_context,
    build_user_context,
    get_active_role,
)
from app.services.ai_intent import (
    INTENT_AUDIT_STATUS,
    INTENT_CASH_FLOW,
    INTENT_DASHBOARD_SUMMARY,
    INTENT_GENERAL,
    INTENT_INSTALLMENTS,
    INTENT_LOANS,
    INTENT_MEMBER_INCOMPLETE,
    INTENT_MEMBER_LIST,
    INTENT_MEMBER_STATISTICS,
    INTENT_PENDING_APPLICATIONS,
    INTENT_ROLE_LIST,
    INTENT_SAVINGS,
    INTENT_SYSTEM_STATUS,
    INTENT_TECHNICAL,
    INTENT_TRANSACTIONS,
    INTENT_USER_COUNT,
    INTENT_USER_IDENTITY,
    INTENT_USER_LIST,
    INTENT_USER_ROLE_LOOKUP,
    SESSION_ONLY_INTENTS,
    detect_intent,
)


#: Pola yang menandakan pertanyaan di luar lingkup koperasi
_OUT_OF_SCOPE_MARKERS = (
    "coding", "koding", "program python", "python", "javascript", "typescript",
    "buatkan kode", "source code", "kode sumber", "debug kode",
    "html", "css", "sql query", "algoritma", "framework",
)

#: Pola permintaan manipulasi data / privilege escalation
_ACTION_MARKERS = (
    "abaikan semua", "abaikan aturan", "ignore all", "ignore previous",
    "tampilkan semua data anggota", "tampilkan database", "semua anggota",
    "bypass", "system prompt", "kamu sekarang", "berpura-pura",
    "anggap saya admin", "anggap saya manager", "angkat saya ketua",
    "jadi admin", "escalate", "sudo",
    "api key", "apikey", "kunci api", "secret", "credential",
    "bearer token", "access token", "password", "password hash",
)


#: Intent yang mewakili pertanyaan data terstruktur (butuh sumber data modul).
_DATA_INTENTS = {
    INTENT_USER_COUNT, INTENT_USER_LIST, INTENT_ROLE_LIST, INTENT_USER_ROLE_LOOKUP,
    INTENT_MEMBER_STATISTICS, INTENT_MEMBER_LIST, INTENT_MEMBER_INCOMPLETE,
    INTENT_SAVINGS, INTENT_LOANS, INTENT_INSTALLMENTS, INTENT_CASH_FLOW,
    INTENT_TRANSACTIONS, INTENT_PENDING_APPLICATIONS, INTENT_AUDIT_STATUS,
    INTENT_SYSTEM_STATUS, INTENT_TECHNICAL, INTENT_DASHBOARD_SUMMARY,
}

#: Kata kunci yang menandakan pertanyaan benar-benar tentang data
_DATA_KEYWORDS = (
    "berapa", "jumlah", "total", "siapa", "daftar", "tugas", "wewenang",
    "fungsi", "cara kerja", "bagaimana", "kondisi", "ringkasan",
    "sudah lengkap", "belum lengkap", "aktif", "berjalan", "jatuh tempo",
)


#: Intent dari handler lama yang SEJUJURNYA menjawab pertanyaan dengan intent
#: kita. Bila intent handler lama TIDAK ada di sini, maka pipeline memakai
#: jalur context routing (yang menarik sumber data yang tepat).
_COMPATIBLE_DET_INTENTS = {
    # identitas
    "user_identity", "user_role", "role_info",
    # pengguna aplikasi
    "user_count", "it_user_metrics", "user_list", "users_by_role",
    # anggota
    "membership_info", "member_count", "member_list",
    # keuangan
    "savings_summary", "loan_summary", "cash_summary", "installment_summary",
    "loan_pipeline", "loan_pipeline_summary", "financial_condition",
    # operasional
    "dashboard_summary", "role_dashboard", "audit_summary", "accounting_summary",
    "hrd_summary", "my_savings", "my_loan", "my_installments",
    # SOP / FAQ umum
    "sop", "faq", "general",
}


def _is_data_question(question: str) -> bool:
    q = (question or "").lower()
    return any(k in q for k in _DATA_KEYWORDS)


def _is_out_of_scope(question: str) -> bool:
    q = (question or "").lower()
    return any(m in q for m in _OUT_OF_SCOPE_MARKERS)


def _is_action_request(question: str) -> bool:
    q = (question or "").lower()
    return any(m in q for m in _ACTION_MARKERS)


class AIOrchestrator:
    """Pipeline terpusat Assistant AI."""

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    @classmethod
    def answer(cls, db: Session, user: User, question: str) -> Dict[str, Any]:
        """Jawab pertanyaan pengguna mengikuti pipeline terpusat.

        Tahap 1-3 (identitas, guard, intent) dijalankan di sini.
        Tahap retrieval memakai ``DatabaseIntelligenceService`` yang sudah
        terbukti (RBAC-checked, 3759 baris handler deterministik). Hanya bila
        tidak ada handler deterministik yang cocok (marker ``needs_llm``) maka
        pipeline lanjut ke penyusunan konteks + provider AI + fallback.
        """
        q = (question or "").strip()

        # --- AUTH_OK ---------------------------------------------------------
        if not user or not getattr(user, "is_active", False):
            raise HTTPException(status_code=401, detail="Anda harus login terlebih dahulu.")
        logger.info("[AI_PIPE] AUTH_OK user=%s", user.id)

        # --- RBAC_OK ---------------------------------------------------------
        role = get_active_role(user)
        logger.info("[AI_PIPE] RBAC_OK user=%s role=%s", user.id, role)

        # --- Guard kebijakan (lapisan tambahan, bukan pengganti RBAC) -------
        if _is_action_request(q):
            return cls._refuse(
                "Saya tidak dapat mengeksekusi permintaan tersebut. "
                "Saya hanya asisten informasi koperasi yang read-only."
            )
        if _is_out_of_scope(q):
            return cls._refuse(
                "Maaf, saya adalah AI Assistant KSP AHNRFZI. Saya hanya membantu "
                "informasi seputar koperasi, data yang Anda berhak akses, dan prosedur koperasi."
            )

        # --- Intent detection (dengan subjek percakapan untuk follow-up) -----
        subject = conversation.get_subject(user.id)
        intent = detect_intent(q, subject=subject)
        logger.info("[AI_PIPE] INTENT=%s user=%s subject=%s", intent, user.id, subject or "-")

        # --- PERBAIKAN INTI: pertanyaan identitas -> session, BUKAN dashboard
        # "Siapa saya?", "Apa role saya?", "Nama akun saya?" dijawab murni dari
        # session server. Ringkasan dashboard TIDAK PERNAH ikut untuk intent ini.
        if intent in SESSION_ONLY_INTENTS:
            logger.info("[AI_PIPE] IDENTITY_ROUTE intent=%s (session only)", intent)
            return cls._answer_identity(db, user, q, intent, role)

        # --- Tahap 1: retrieval deterministik (RBAC-checked) ---------------
        # DatabaseIntelligenceService menjalankan handler yang sudah ada
        # (SOP/FAQ/prosedural). Untuk pertanyaan DATA kita TIDAK memakai
        # handler lama: pipeline memakai context service terpusat agar
        # semua provider menarik sumber data yang sama.
        from app.services.database_intelligence import DatabaseIntelligenceService

        deterministic = None
        if intent not in _DATA_INTENTS:
            try:
                deterministic = DatabaseIntelligenceService.process_question(db, user, q)
            except HTTPException:
                raise
            except Exception as e:  # pragma: no cover - pengaman
                logger.error(f"[AI_PIPE] retrieval exception: {type(e).__name__}")
                deterministic = None

            if deterministic and not deterministic.get("needs_llm"):
                det_intent = deterministic.get("intent") or ""
                det_answer = (deterministic.get("answer") or "").strip()
                logger.info("[AI_PIPE] DETERMINISTIC_ANSWER intent=%s", det_intent)
                if det_answer:
                    conversation.add_turn(
                        user.id, q, det_answer,
                        subject=cls._subject_for(intent) or cls._subject_for(det_intent),
                    )
                deterministic.setdefault("provider", "rule_engine")
                deterministic.setdefault("model", "local_rule_based")
                deterministic.setdefault("role", role)
                return deterministic

            logger.info("[AI_PIPE] INTENT=%s user=%s (jalur context routing)", intent, user.id)

        # --- Database retrieval untuk konteks LLM ---------------------------
        bundle = build_context_bundle(db, user, q, subject=subject)
        database_context = bundle["database_context"]
        user_context = bundle["user_context"]
        logger.info("[AI_PIPE] CONTEXT_RETRIEVAL_OK intent=%s", intent)

        # Penolakan RBAC dari retrieval: jangan lanjut ke LLM dengan data kosong
        if database_context.strip().startswith("[DITOLAK]"):
            return cls._refuse(database_context.replace("[DITOLAK] ", ""))

        # --- Provider selection ---------------------------------------------
        primary = (settings.AI_PROVIDER or "rule_engine").lower().strip()
        chain = [primary]
        if settings.AI_FALLBACK_PROVIDER and settings.AI_FALLBACK_PROVIDER != primary:
            chain.append(settings.AI_FALLBACK_PROVIDER)
        logger.info("[AI_PIPE] PROVIDER_SELECTED chain=%s", ",".join(chain))

        # Rule Engine: tanpa API eksternal, jawab dari konteks database saja
        if primary == "rule_engine" and not settings.AI_FALLBACK_PROVIDER:
            logger.info("[AI_PIPE] RULE_ENGINE_ANSWER")
            answer_text = cls._rule_engine_answer(q, database_context, user_context)
            return cls._ok(answer_text, "rule_engine", intent, role,
                           provider="rule_engine", model="local_rule_based")

        # --- Provider call (dengan fallback) --------------------------------
        logger.info("[AI_PIPE] PROVIDER_REQUEST_SENT provider=%s", primary)
        result = answer_with_fallback(
            q,
            user_id=user.id,
            user_context=user_context,
            database_context=database_context,
        )

        if result.response is None:
            # Semua provider LLM gagal -> coba Rule Engine (fallback lokal)
            logger.warning("[AI_PIPE] FALLBACK_USED provider=rule_engine")
            answer_text = cls._rule_engine_answer(q, database_context, user_context)
            if answer_text:
                conversation.add_turn(
                    user.id, q, answer_text,
                    subject=cls._subject_for(intent),
                )
                return cls._ok(
                    answer_text, intent, role,
                    provider="rule_engine", model="local_rule_based",
                    fallback_from=",".join(a.get("provider", "") for a in result.attempts),
                )
            logger.error("[AI_PIPE] CHAT_FAILED semua provider gagal")
            raise HTTPException(
                status_code=503,
                detail=(
                    "Layanan AI sedang mengalami gangguan. "
                    "Provider utama dan cadangan tidak dapat dihubungi. "
                    "Silakan coba lagi nanti."
                ),
            )

        used = result.provider_used
        if used != primary:
            logger.warning("[AI_PIPE] FALLBACK_USED provider=%s", used)

        # --- Response validation --------------------------------------------
        text = cls._validate(result.response.text)
        if not text:
            logger.error("[AI_PIPE] CHAT_FAILED jawaban kosong dari %s", used)
            raise HTTPException(
                status_code=502,
                detail="Provider AI mengembalikan jawaban kosong. Silakan coba lagi.",
            )

        # Simpan ke riwayat percakapan (server-side, identik untuk semua provider)
        conversation.add_turn(
            user.id, q, text,
            subject=cls._subject_for(intent),
        )
        logger.info("[AI_PIPE] CHAT_RESPONSE_OK provider=%s model=%s",
                    used, result.response.model)

        return cls._ok(
            text, intent, role,
            provider=used,
            model=result.response.model,
            usage=result.response.usage,
            attempts=result.attempts,
        )

    # ------------------------------------------------------------------
    # Identitas pengguna (session only - tanpa ringkasan dashboard)
    # ------------------------------------------------------------------
    @classmethod
    def _answer_identity(cls, db: Session, user: User, question: str,
                         intent: str, role: str) -> Dict[str, Any]:
        """Jawab pertanyaan identitas dari session server.

        Sumber: ``user_context.get_current_authenticated_user_context`` (session
        terautentikasi) + permission RBAC. TIDAK memakai ringkasan dashboard
        dan TIDAK pernah mengarang nama/username/jabatan/status.
        """
        from app.services.user_context import get_current_authenticated_user_context

        ctx = get_current_authenticated_user_context(db, user)
        identity = build_user_context(db, user)

        full_name = ctx.get("full_name") or identity.get("full_name") or "-"
        username = identity.get("username") or "-"
        jabatan = ctx.get("jabatan")
        perms = identity.get("permissions") or []
        all_roles = identity.get("all_roles") or []
        q_low = (question or "").lower()

        # Tentukan fokus jawaban berdasarkan frasa pertanyaan.
        fokus_role = any(k in q_low for k in ("role", "peran", "hak akses", "permission"))
        fokus_nama = any(k in q_low for k in ("nama", "username", "akun", "profil"))

        lines = [f"Anda sedang login ke Sistem Informasi KSP AHNRFZI.", ""]

        if fokus_role:
            perms_txt = ", ".join(perms) if perms else "tidak ada"
            lines.append(f"Role aktif    : {identity['role_display']} ({identity['role_code']})")
            lines.append(f"Seluruh role  : {', '.join(all_roles) if all_roles else '-'}")
            lines.append(f"Jumlah hak akses aktif: {len(perms)}")
            lines.append(f"Hak akses     : {perms_txt}")
        else:
            lines.append(f"Nama pengguna : {full_name}")
            lines.append(f"Username      : {username}")
            lines.append(f"Role aktif    : {identity['role_display']} ({identity['role_code']})")
            lines.append(f"Status akun   : {'Aktif' if identity.get('is_active') else 'Nonaktif'}")
            if jabatan:
                lines.append(f"Jabatan       : {jabatan}")
            if ctx.get("is_member") and ctx.get("member_no"):
                lines.append(f"No. anggota    : {ctx['member_no']}")
            if all_roles:
                lines.append(f"Seluruh role  : {', '.join(all_roles)}")

        if fokus_nama and not fokus_role:
            lines.insert(2, f"Nama pengguna : {full_name}")

        lines.append("")
        lines.append(
            f"Anda memiliki akses sesuai permission {identity['role_display']} "
            "yang diberikan oleh sistem."
        )
        answer = "\n".join(lines)

        # Simpan ke riwayat (subject = identitas, agar pertanyaan lanjutan
        # "apa tugas role tersebut?" tetap punya konteks).
        conversation.add_turn(user.id, question, answer, subject="identitas")
        logger.info("[AI_PIPE] CHAT_RESPONSE_OK provider=rule_engine model=local_rule_based")

        return cls._ok(
            answer, intent, role,
            provider="rule_engine", model="local_rule_based",
        )

    # ------------------------------------------------------------------
    # Rule Engine (fallback lokal, tanpa API eksternal)
    # ------------------------------------------------------------------
    @classmethod
    def _rule_engine_answer(cls, question: str, database_context: str,
                            user_context: Dict[str, Any]) -> str:
        """Jawaban deterministik dari konteks database yang sudah diambil.

        Tidak pernah mengarang angka: bila konteks kosong/tidak memuat data,
        kembalikan string kosong agar pemanggil memilih pesan gangguan.
        """
        ctx = (database_context or "").strip()
        if not ctx or ctx.startswith("[DITOLAK]"):
            return ""
        role = user_context.get("role_code", "")
        role_display = user_context.get("role_display", role)
        return (
            f"Berdasarkan data resmi KSP AHNRFZI (role Anda: {role_display}):\n\n"
            f"{ctx}\n\n"
            "Catatan: jawaban ini disusun dari hasil pembacaan database oleh sistem, "
            "bukan oleh model AI eksternal."
        )

    # ------------------------------------------------------------------
    # Validasi jawaban
    # ------------------------------------------------------------------
    @classmethod
    def _validate(cls, text: str, max_chars: int = 4000) -> str:
        """Validasi & bersihkan jawaban model."""
        if not text:
            return ""
        out = text.strip()
        # Potong bila terlalu panjang
        if len(out) > max_chars:
            out = out[: max_chars - 1].rstrip() + "…"
        return out

    # ------------------------------------------------------------------
    # Response shaping (kompatibel dengan API yang ada)
    # ------------------------------------------------------------------
    @classmethod
    def _ok(cls, answer: str, intent: str, role: str, *,
            provider: str, model: str, usage: Optional[Dict[str, int]] = None,
            attempts: Optional[List[Dict[str, Any]]] = None,
            fallback_from: str = "") -> Dict[str, Any]:
        resp: Dict[str, Any] = {
            "answer": answer,
            "intent": intent,
            "intent_category": cls._category(intent),
            "source": f"AI Assistant KSP AHNRFZI ({provider})",
            "authorized": True,
            "provider": provider,
            "model": model,
            "role": role,
        }
        if usage:
            resp["usage"] = usage
        if attempts:
            resp["provider_attempts"] = attempts
        if fallback_from:
            resp["fallback_from"] = fallback_from
        return resp

    @classmethod
    def _refuse(cls, message: str) -> Dict[str, Any]:
        return {
            "answer": message,
            "intent": "refused",
            "intent_category": "RESTRICTED",
            "source": "Kebijakan Sistem KSP AHNRFZI",
            "authorized": False,
            "provider": (settings.AI_PROVIDER or "rule_engine"),
            "model": "",
            "role": "",
        }

    @staticmethod
    def _category(intent: str) -> str:
        mapping = {
            INTENT_USER_IDENTITY: "IDENTITY",
            INTENT_USER_COUNT: "OPERATIONAL",
            INTENT_USER_LIST: "OPERATIONAL",
            INTENT_ROLE_LIST: "GENERAL",
            INTENT_USER_ROLE_LOOKUP: "OPERATIONAL",
            INTENT_MEMBER_STATISTICS: "OPERATIONAL",
            INTENT_MEMBER_LIST: "OPERATIONAL",
            INTENT_MEMBER_INCOMPLETE: "OPERATIONAL",
            INTENT_SAVINGS: "FINANCIAL_SUMMARY",
            INTENT_LOANS: "FINANCIAL_SUMMARY",
            INTENT_INSTALLMENTS: "FINANCIAL_SUMMARY",
            INTENT_CASH_FLOW: "FINANCIAL_SUMMARY",
            INTENT_TRANSACTIONS: "FINANCIAL_SUMMARY",
            INTENT_PENDING_APPLICATIONS: "FINANCIAL_SUMMARY",
            INTENT_AUDIT_STATUS: "AUDIT",
            INTENT_SYSTEM_STATUS: "IT_SYSTEM",
            INTENT_TECHNICAL: "IT_SYSTEM",
            INTENT_DASHBOARD_SUMMARY: "OPERATIONAL",
            INTENT_GENERAL: "FAQ",
        }
        return mapping.get(intent, "FAQ")

    @staticmethod
    def _subject_for(intent: str) -> str:
        """Subjek kontekstual untuk intent lanjutan deterministik."""
        return {
            INTENT_USER_IDENTITY: "identitas",
            INTENT_USER_COUNT: "pengguna",
            INTENT_USER_LIST: "pengguna",
            INTENT_ROLE_LIST: "role",
            INTENT_USER_ROLE_LOOKUP: "pengguna",
            INTENT_MEMBER_STATISTICS: "anggota",
            INTENT_MEMBER_LIST: "anggota",
            INTENT_MEMBER_INCOMPLETE: "anggota",
            INTENT_SAVINGS: "simpanan",
            INTENT_LOANS: "pinjaman",
            INTENT_INSTALLMENTS: "angsuran",
            INTENT_CASH_FLOW: "kas",
            INTENT_TRANSACTIONS: "transaksi",
            INTENT_PENDING_APPLICATIONS: "pengajuan",
            INTENT_AUDIT_STATUS: "aktivitas",
        }.get(intent, "")


# ---------------------------------------------------------------------
# Facade untuk kompatibilitas
# ---------------------------------------------------------------------

def answer_question(db: Session, user: User, question: str) -> Dict[str, Any]:
    """Fasad: titik masuk tunggal Assistant AI."""
    return AIOrchestrator.answer(db, user, question)

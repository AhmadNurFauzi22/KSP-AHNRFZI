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
from app.services.ai_context_service import (
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
    INTENT_INSTALLMENT,
    INTENT_IT_SYSTEM_STATUS,
    INTENT_LOAN,
    INTENT_MEMBER_COUNT,
    INTENT_MEMBER_INCOMPLETE,
    INTENT_MEMBER_LIST,
    INTENT_SAVINGS,
    INTENT_TRANSACTION,
    INTENT_USER_IDENTITY,
    INTENT_USER_LIST,
    INTENT_USER_PROFILE,
    INTENT_USER_ROLE,
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


#: Intent yang mewakili pertanyaan data terstruktur
_DATA_INTENTS = {
    "user_count", "user_list", "user_by_role", "role_task",
    "membership", "savings", "loan", "installment", "cashier", "hrd",
    "rbac", "installment_module", "dashboard_summary",
}

#: Kata kunci yang menandakan pertanyaan benar-benar tentang data
_DATA_KEYWORDS = (
    "berapa", "jumlah", "total", "siapa", "daftar", "tugas", "wewenang",
    "fungsi", "cara kerja", "bagaimana", "kondisi", "ringkasan",
    "sudah lengkap", "belum lengkap", "aktif", "berjalan", "jatuh tempo",
)


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

        # --- Intent detection ------------------------------------------------
        intent = detect_intent(q)
        logger.info("[AI_PIPE] INTENT=%s user=%s", intent, user.id)

        # --- PERBAIKAN INTI: pertanyaan identitas -> session, BUKAN dashboard
        # "Siapa saya?", "Apa role saya?", "Nama akun saya?" dijawab murni dari
        # session server. Ringkasan dashboard TIDAK PERNAH ikut untuk intent ini.
        if intent in SESSION_ONLY_INTENTS:
            logger.info("[AI_PIPE] IDENTITY_ROUTE intent=%s (session only)", intent)
            return cls._answer_identity(db, user, q, intent, role)

        # --- Tahap 1: retrieval deterministik (RBAC-checked) ---------------
        # DatabaseIntelligenceService menjalankan handler yang sudah ada:
        # identitas, data pengguna, anggota, simpanan, pinjaman, angsuran,
        # kasir, HRD, audit, SOP, dan FAQ. Semua query memakai ORM/service.
        from app.services.database_intelligence import DatabaseIntelligenceService

        try:
            deterministic = DatabaseIntelligenceService.process_question(db, user, q)
        except HTTPException:
            raise
        except Exception as e:  # pragma: no cover - pengaman
            logger.error(f"[AI_PIPE] retrieval exception: {type(e).__name__}")
            deterministic = None

        if deterministic and not deterministic.get("needs_llm"):
            # Jawaban deterministik siap. Namun bila intent terdeteksi sebagai
            # pertanyaan DATA (pengguna/anggota/simpanan/pinjaman/angsuran/kas/
            # hrd/role/rbac) sementara handler lama hanya menjawab lewat SOP/FAQ
            # yang tidak relevan, pipeline lanjut ke jalur LLM dengan konteks
            # database yang benar.
            det_intent = deterministic.get("intent") or ""
            det_answer = (deterministic.get("answer") or "").strip()

            data_intent = intent in _DATA_INTENTS and _is_data_question(q)
            weak_deterministic = det_intent in ("sop", "faq", "unknown", "general")

            if not (data_intent and weak_deterministic):
                logger.info("[AI_PIPE] DETERMINISTIC_ANSWER intent=%s", det_intent)
                # Catat ke riwayat agar pertanyaan lanjutan punya konteks.
                if det_answer:
                    conversation.add_turn(
                        user.id, q, det_answer,
                        subject=cls._subject_for(det_intent),
                    )
                # Lengkapi metadata provider agar respons konsisten
                deterministic.setdefault("provider", "rule_engine")
                deterministic.setdefault("model", "local_rule_based")
                deterministic.setdefault("role", role)
                return deterministic

            logger.info(
                "[AI_PIPE] SOP_TIDAK_RELEVAN intent=%s det=%s -> lanjut LLM",
                intent, det_intent,
            )
        else:
            logger.info("[AI_PIPE] INTENT=%s user=%s (jalur LLM)", intent, user.id)

        # --- Database retrieval untuk konteks LLM ---------------------------
        bundle = build_context_bundle(db, user, q)
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
        all_roles = ctx.get("all_roles") or []

        if intent == INTENT_USER_ROLE:
            perms_txt = ", ".join(perms) if perms else "tidak ada"
            answer = (
                f"Anda sedang login ke Sistem Informasi KSP AHNRFZI.\n\n"
                f"Role aktif   : {identity['role_display']} ({identity['role_code']})\n"
                f"Seluruh role: {', '.join(all_roles) if all_roles else '-'}\n"
                f"Jumlah hak akses aktif: {len(perms)}\n"
                f"Permission   : {perms_txt}"
            )
        elif intent == INTENT_USER_PROFILE:
            lines = [
                f"Anda sedang login ke Sistem Informasi KSP AHNRFZI.\n\n"
                f"Nama pengguna : {full_name}\n"
                f"Username      : {username}\n"
                f"Role aktif    : {identity['role_display']} ({identity['role_code']})"
            ]
            if jabatan:
                lines.append(f"Jabatan       : {jabatan}")
            lines.append(f"Status akun   : {'Aktif' if identity.get('is_active') else 'Nonaktif'}")
            answer = "\n".join(lines)
        else:  # INTENT_USER_IDENTITY
            lines = [
                f"Anda sedang login ke Sistem Informasi KSP AHNRFZI.\n\n"
                f"Nama pengguna : {full_name}\n"
                f"Username      : {username}\n"
                f"Role aktif    : {identity['role_display']} ({identity['role_code']})\n"
                f"Status akun   : {'Aktif' if identity.get('is_active') else 'Nonaktif'}"
            ]
            if jabatan:
                lines.append(f"Jabatan       : {jabatan}")
            if ctx.get("is_member") and ctx.get("member_no"):
                lines.append(f"No. anggota    : {ctx['member_no']}")
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
        if not database_context.strip() or database_context.strip().startswith("[DITOLAK]"):
            return ""
        role = user_context.get("role_code", "")
        role_display = user_context.get("role_display", role)
        return (
            f"Berdasarkan data resmi KSP AHNRFZI (role Anda: {role_display}):\n\n"
            f"{database_context.strip()}\n\n"
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
            INTENT_USER_ROLE: "IDENTITY",
            INTENT_USER_PROFILE: "IDENTITY",
            INTENT_USER_LIST: "OPERATIONAL",
            INTENT_MEMBER_COUNT: "OPERATIONAL",
            INTENT_MEMBER_LIST: "OPERATIONAL",
            INTENT_MEMBER_INCOMPLETE: "OPERATIONAL",
            INTENT_SAVINGS: "FINANCIAL_SUMMARY",
            INTENT_LOAN: "FINANCIAL_SUMMARY",
            INTENT_INSTALLMENT: "FINANCIAL_SUMMARY",
            INTENT_CASH_FLOW: "FINANCIAL_SUMMARY",
            INTENT_TRANSACTION: "FINANCIAL_SUMMARY",
            INTENT_IT_SYSTEM_STATUS: "IT_SYSTEM",
            INTENT_AUDIT_STATUS: "AUDIT",
            INTENT_DASHBOARD_SUMMARY: "OPERATIONAL",
            INTENT_GENERAL: "FAQ",
        }
        return mapping.get(intent, "FAQ")

    @staticmethod
    def _subject_for(intent: str) -> str:
        """Subjek kontekstual untuk intent lanjutan deterministik."""
        return {
            INTENT_USER_IDENTITY: "identitas",
            INTENT_USER_ROLE: "identitas",
            INTENT_USER_PROFILE: "identitas",
            INTENT_USER_LIST: "pengguna",
            INTENT_MEMBER_COUNT: "anggota",
            INTENT_MEMBER_LIST: "anggota",
            INTENT_MEMBER_INCOMPLETE: "anggota",
            INTENT_SAVINGS: "simpanan",
            INTENT_LOAN: "pinjaman",
            INTENT_INSTALLMENT: "angsuran",
            INTENT_CASH_FLOW: "kas",
            INTENT_TRANSACTION: "transaksi",
        }.get(intent, "")


# ---------------------------------------------------------------------
# Facade untuk kompatibilitas
# ---------------------------------------------------------------------

def answer_question(db: Session, user: User, question: str) -> Dict[str, Any]:
    """Fasad: titik masuk tunggal Assistant AI."""
    return AIOrchestrator.answer(db, user, question)

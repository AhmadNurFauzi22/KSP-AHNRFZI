from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Tuple
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.permissions import get_current_user, require_permission
from app.services.ai_service import AIAssistantService
from app.services.audit_service import AuditService
from app.db.models.user import User

router = APIRouter(prefix="/ai", tags=["AI Assistant"])


class CreditScoreRequest(BaseModel):
    monthly_salary: float = Field(..., gt=0, le=10_000_000_000)
    requested_amount: float = Field(..., gt=0, le=10_000_000_000)
    term_months: int = Field(..., ge=1, le=120)
    existing_savings_balance: float = Field(0.0, ge=0, le=10_000_000_000)
    past_defaults: int = Field(0, ge=0, le=1000)


class AskAIRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


@router.post("/credit-score")
def assess_credit_score(
    payload: CreditScoreRequest,
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant"))
):
    """Calculate AI Credit Scoring & Risk analysis."""
    result = AIAssistantService.calculate_credit_score(
        monthly_salary=payload.monthly_salary,
        requested_amount=payload.requested_amount,
        term_months=payload.term_months,
        existing_savings_balance=payload.existing_savings_balance,
        past_defaults=payload.past_defaults
    )
    return result


@router.get("/history")
def ai_conversation_history(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant")),
):
    """Riwayat percakapan pengguna (dikelola backend, bukan memori model)."""
    from app.services.ai.conversation import CONVERSATION_STORE
    return {
        "turns": CONVERSATION_STORE.stats(current_user.id).get("turns", 0),
        "subject": CONVERSATION_STORE.stats(current_user.id).get("subject"),
        "max_turns": 12,
    }


@router.delete("/history")
def ai_clear_history(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant")),
):
    """Hapus riwayat percakapan pengguna."""
    from app.services.ai.conversation import clear_history
    cleared = clear_history(current_user.id)
    return {"cleared": cleared}


@router.get("/providers")
def ai_provider_diagnostics(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant")),
):
    """Diagnostik provider AI (tanpa API key).

    Menampilkan provider aktif, rantai fallback, dan status konfigurasi.
    Berguna untuk menjelaskan penyebab kegagalan chatbot.
    """
    from app.services.ai.providers import provider_list
    from app.services.ai_fallback_service import _candidate_providers
    from app.core.config import settings as _s

    info = provider_list()
    return {
        "active_provider": _s.AI_PROVIDER,
        "active_model": _s.ai_model_name,
        "llm_enabled": _s.llm_enabled,
        "fallback_provider": _s.AI_FALLBACK_PROVIDER,
        "fallback_chain": _candidate_providers(),
        "providers": info,
    }


@router.get("/status")
def ai_status(current_user: User = Depends(get_current_user)):
    """Status backend AI untuk badge chatbot (key tidak pernah dikirim)."""
    from app.core.config import settings as _settings
    return {
        "provider": _settings.AI_PROVIDER,
        "model": _settings.ai_model_name if _settings.llm_enabled else "rule_engine",
        "llm_ready": _settings.llm_enabled,
    }


@router.get("/context")
def ai_user_context(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant")),
    db: Session = Depends(get_db)
):
    """Mendapatkan identitas user dari sesi server, role aktif, daftar permission, greeting, dan dynamic suggested questions."""
    from app.services.database_intelligence import DatabaseIntelligenceService
    from app.core.config import settings as _settings
    ctx = DatabaseIntelligenceService.get_user_role_context(db, current_user)
    ctx["provider"] = _settings.AI_PROVIDER
    ctx["llm_ready"] = _settings.llm_enabled
    return ctx


@router.get("/catalog")
def get_ai_database_catalog(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant"))
):
    """Mendapatkan Database Knowledge Catalog terotorisasi."""
    from app.services.database_knowledge_catalog import DatabaseKnowledgeCatalog
    role = getattr(current_user, "active_role", None) or (current_user.roles[0].code if current_user.roles else "ANGGOTA")
    tables = DatabaseKnowledgeCatalog.get_all_tables()
    formulas = DatabaseKnowledgeCatalog.get_all_financial_formulas()
    flows = DatabaseKnowledgeCatalog.get_transaction_flows()
    
    # Anggota mendapatkan ringkasan domain publik; staf/admin mendapatkan metadata teknis lengkap
    is_staff = role in ("ADMIN_KOPERASI", "IT_PUSAT", "MANAGER", "KETUA_UMUM", "PENGAWAS_PEMBINA", "STAF", "KASIR", "HRD")
    return {
        "total_tables": len(tables),
        "tables": tables if is_staff else [t for t in tables if not t.startswith("role") and not t.startswith("user_role")],
        "formulas": list(formulas.keys()),
        "transaction_flows": [f["flow_name"] for f in flows],
        "is_staff_view": is_staff
    }


@router.get("/catalog/table/{table_name}")
def get_ai_table_catalog(
    table_name: str,
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant"))
):
    """Mendapatkan metadata mendalam satu tabel dari Database Knowledge Catalog."""
    from app.services.database_knowledge_catalog import DatabaseKnowledgeCatalog
    meta = DatabaseKnowledgeCatalog.get_table_metadata(table_name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Tabel '{table_name}' tidak ditemukan dalam katalog.")
    return meta


@router.get("/schema")
def get_live_database_schema(
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant"))
):
    """Introspeksi skema aktual database secara dinamis via DatabaseSchemaDiscovery."""
    role = getattr(current_user, "active_role", None) or (current_user.roles[0].code if current_user.roles else "ANGGOTA")
    if role not in ("ADMIN_KOPERASI", "IT_PUSAT", "MANAGER", "KETUA_UMUM", "PENGAWAS_PEMBINA"):
        raise HTTPException(status_code=403, detail="Akses skema teknis database hanya untuk peran administrator dan manajerial.")
    from app.services.schema_discovery import DatabaseSchemaDiscovery
    return DatabaseSchemaDiscovery.get_complete_schema_snapshot()


@router.post("/ask")
def ask_ai_assistant(
    payload: AskAIRequest,
    current_user: User = Depends(get_current_user),
    authorized: bool = Depends(require_permission("ai.assistant")),
    db: Session = Depends(get_db)
):
    """Asisten percakapan READ-ONLY: identitas dari sesi server, tool terotorisasi.

    Rate limit per user + audit metadata (tanpa menyimpan isi percakapan).
    """
    _ai_rate_limit(current_user.id)
    try:
        # Identitas (user/role/permission/member) diambil dari sesi server,
        # bukan dari input user.
        result = AIAssistantService.answer_question(db, current_user, payload.question)
        status_ok = "OK"
    except HTTPException:
        raise
    except Exception as e:
        from app.core.logging import logger as _logger
        _logger.error(f"[AI] gagal menjawab user={current_user.id}: {e}")
        AuditService.log_event(db, action="AI_ASK", entity_name="AI",
                               user_id=current_user.id,
                               notes="AI_ASK status=ERROR (detail di log server)")
        raise HTTPException(status_code=500,
                            detail="Layanan AI sementara tidak tersedia. Coba lagi nanti.")
    AuditService.log_event(db, action="AI_ASK", entity_name="AI",
                           user_id=current_user.id,
                           notes=(f"AI_ASK role={getattr(current_user, 'active_role', None) or (current_user.roles[0].code if current_user.roles else '-')} "
                                  f"intent={result.get('intent')} status={status_ok}"))
    return {"question": payload.question, **result}


# Prompt #12/#16: batasi penyalahgunaan (30 pertanyaan/menit per user, in-memory)
_AI_CALLS: Dict[int, Tuple[int, float]] = {}
_AI_LOCK = Lock()
_AI_LIMIT = 30
_AI_WINDOW = 60.0


def _ai_rate_limit(user_id: int) -> None:
    now = datetime.now(timezone.utc).timestamp()
    with _AI_LOCK:
        count, start = _AI_CALLS.get(user_id, (0, now))
        if now - start >= _AI_WINDOW:
            count, start = 0, now
        if count >= _AI_LIMIT:
            raise HTTPException(status_code=429,
                                detail="Terlalu banyak pertanyaan. Tunggu sebentar.")
        _AI_CALLS[user_id] = (count + 1, start)

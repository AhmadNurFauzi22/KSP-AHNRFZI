"""Router Konfigurasi Assistant AI KSP AHNRFZI.

Menyediakan endpoint untuk mengelola konfigurasi AI Provider,
API Key, dan model. Hanya dapat diakses oleh Admin.

Fitur:
- Multi-provider support (rule_engine, openai, gemini, anthropic, nvidia_nim)
- Per-provider API Key management dengan masking
- Provider activation/deactivation
- Connection testing per-provider (permintaan HTTP nyata ke provider)
- Enhanced security: API Key tidak pernah keluar ke frontend secara utuh
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings, AI_PROVIDER_CHOICES, DEFAULT_MODELS, mask_sensitive
from app.core.permissions import get_current_user, get_user_permissions, RoleChecker, SystemRole
from app.db.models.user import User
from app.services.auth_service import AuthService
from app.services.llm_service import chat_complete, LLMError
from app.schemas.auth import LoginRequest

router = APIRouter(prefix="/ai-config", tags=["AI Configuration"])


# === SCHEMA UTAMA (DINILIMAI) ===

# Schema untuk request konfigurasi provider
class ProviderConfig(BaseModel):
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None
    temperature: float = 0.3


class ProviderTestResult(BaseModel):
    success: bool
    message: str
    model: str


# Schema untuk simpan konfigurasi
class AIConfigSave(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: Optional[str] = None
    timeout: Optional[int] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    description: Optional[str] = None
    provider_type: Optional[str] = None


# Schema untuk request tes koneksi (JSON body)
class AIConfigTest(BaseModel):
    provider: str
    model: str = ""
    api_key: str = ""
    base_url: Optional[str] = None
    timeout: Optional[int] = None


# Schema untuk request aktivasi (JSON body)
class AIConfigActivate(BaseModel):
    provider: str


# Schema untuk status
class AIStatus(BaseModel):
    provider: str
    model: str
    is_configured: bool
    last_updated: Optional[str] = None


# Schema untuk daftar provider
class ProviderInfo(BaseModel):
    key: str
    label: str
    description: str
    requires_key: bool
    is_active: bool
    current_model: str
    current_api_key_masked: str


# === HELPER FUNCTIONS ===

# Helper: cek apakah user adalah Admin
def _is_admin(user: User) -> bool:
    role_codes = [r.code for r in user.roles] if user.roles else []
    return "ADMIN_KOPERASI" in role_codes or "ADMIN" in role_codes


# Helper: dapatkan info provider saat ini (singkat)
def _get_current_provider_info() -> Dict[str, Any]:
    """Dapatkan info provider AI yang sedang aktif (versi ringkas)."""
    provider = (settings.AI_PROVIDER or "rule_engine").lower().strip()
    api_key = settings.ai_api_key
    model_name = settings.ai_model_name

    # Mask API key untuk log (jangan pernah bocor)
    masked_key = settings.mask_sensitive(api_key) if api_key else ""

    return {
        "provider": provider,
        "model": model_name,
        "api_key_masked": masked_key,
        "is_configured": bool(api_key and api_key.strip()),
    }


# Helper: dapatkan deskripsi provider
def _get_provider_description(provider: str) -> str:
    """Dapatkan deskripsi singkat provider."""
    descriptions = {
        "rule_engine": "Logika berbasis aturan koperasi, tidak butuh API Key",
        "openai": "OpenAI API, akses via GPT-4o-mini dan model lainnya",
        "gemini": "Google Gemini API, akses via Gemini-1.5-flash",
        "anthropic": "Anthropic Claude API, akses via Claude-3-haiku",
        "nvidia_nim": "NVIDIA NIM API (OpenAI-compatible), akses via model NVIDIA Nemotron",
    }
    return descriptions.get(provider, "")


# Helper: label tampilan provider
def _get_provider_label(provider: str) -> str:
    labels = {
        "rule_engine": "Rule Engine",
        "openai": "OpenAI",
        "gemini": "Google Gemini",
        "anthropic": "Anthropic Claude",
        "nvidia_nim": "NVIDIA NIM",
    }
    return labels.get(provider, provider.upper())


# Helper: dapatkan konfigurasi lengkap per provider
def _get_provider_config_details() -> Dict[str, Dict[str, Any]]:
    """Dapatkan konfigurasi lengkap untuk semua provider."""
    configs = {}
    for provider in AI_PROVIDER_CHOICES:
        configs[provider] = {
            "model": settings.AI_MODEL_NAMES.get(provider, DEFAULT_MODELS.get(provider, "local_rule_based")),
            "base_url": settings.AI_BASE_URLS.get(provider, ""),
            "timeout": settings.AI_TIMEOUT_SECONDS,
            "max_tokens": settings.AI_MAX_TOKENS.get(provider, 1000),
            "temperature": settings.AI_TEMPERATURES.get(provider, 0.3),
        }
    return configs


# === ENDPOINT: GET /api/ai-config/status ===

@router.get("/status", response_model=AIStatus)
def get_ai_config_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cek status konfigurasi Assistant AI."""
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Admin yang dapat mengakses konfigurasi AI."
        )

    info = _get_current_provider_info()
    from datetime import datetime
    return AIStatus(
        provider=info["provider"],
        model=info["model"],
        is_configured=info["is_configured"],
        last_updated=datetime.now().isoformat()
    )


# === ENDPOINT: GET /api/ai-config/providers ===

@router.get("/providers")
def get_ai_providers(current_user: User = Depends(get_current_user)):
    """Dapatkan daftar provider AI yang didukung dan detail konfigurasi masing-masing."""
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Admin yang dapat melihat konfigurasi AI."
        )

    provider_configs = _get_provider_config_details()
    active_provider = (settings.AI_PROVIDER or "rule_engine").lower().strip()

    providers = []
    for provider in AI_PROVIDER_CHOICES:
        config = provider_configs[provider]
        stored_key = settings.AI_API_KEYS.get(provider, "") or ""
        providers.append({
            "value": provider,
            "label": _get_provider_label(provider),
            "models": [DEFAULT_MODELS.get(provider, "local_rule_based")],
            "default_model": DEFAULT_MODELS.get(provider, "local_rule_based"),
            "description": _get_provider_description(provider),
            "requires_key": provider != "rule_engine",
            # is_active: provider yang sedang dipakai (tanpa syarat key)
            "is_active": provider == active_provider,
            # is_configured: provider punya API key tersimpan
            "is_configured": bool(stored_key.strip()),
            "has_api_key": bool(stored_key.strip()),
            # masked saja - API key lengkap TIDAK pernah dikirim ke frontend
            "current_api_key_masked": mask_sensitive(stored_key),
            "current_model": config["model"],
            "base_url": config["base_url"],
            "timeout": config["timeout"],
            "max_tokens": config["max_tokens"],
            "temperature": config["temperature"],
        })

    return {
        "providers": providers,
        "active_provider": active_provider,
        "count": len(providers),
    }


# === ENDPOINT: POST /api/ai-config/test ===

@router.post("/test", response_model=ProviderTestResult)
def test_ai_connection(
    payload: AIConfigTest,
    current_user: User = Depends(get_current_user),
):
    """Tes koneksi NYATA ke provider AI.

    - Jika `api_key` diisi, gunakan key tersebut (belum tersimpan).
    - Jika `api_key` kosong, gunakan API Key yang sudah tersimpan.
    - Melakukan permintaan HTTP sungguhan ke endpoint provider.
    """
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Admin yang dapat melakukan tes AI."
        )

    provider = (payload.provider or "").lower().strip()

    # Validasi provider
    if provider not in AI_PROVIDER_CHOICES:
        return ProviderTestResult(
            success=False,
            message="Provider AI tidak valid. Pilih provider yang tersedia.",
            model="",
        )

    # Rule Engine berjalan lokal tanpa API Key
    if provider == "rule_engine":
        return ProviderTestResult(
            success=True,
            message="Rule Engine berjalan lokal di server dan tidak memerlukan API Key.",
            model=payload.model or DEFAULT_MODELS.get(provider, "local_rule_based"),
        )

    # Tentukan key: yang baru diketik, atau key tersimpan
    typed_key = (payload.api_key or "").strip()
    stored_key = (settings.AI_API_KEYS.get(provider, "") or "").strip()
    effective_key = typed_key or stored_key

    if not effective_key:
        return ProviderTestResult(
            success=False,
            message="API Key belum tersedia. Masukkan API Key terlebih dahulu.",
            model=payload.model,
        )

    # Mask untuk log internal (tidak pernah dicetak utuh)
    masked_key = mask_sensitive(effective_key)

    provider_config = settings.get_provider_config(provider)
    base_url = (payload.base_url or provider_config["base_url"] or "").strip().rstrip("/")
    model_name = (payload.model or provider_config["model"] or "").strip()
    timeout = payload.timeout or provider_config["timeout"] or 30

    if not base_url:
        return ProviderTestResult(
            success=False,
            message=f"Endpoint Base URL untuk provider {provider} belum diisi.",
            model=model_name,
        )

    if not model_name:
        return ProviderTestResult(
            success=False,
            message="Model Identifier belum diisi.",
            model="",
        )

    # --- Permintaan HTTP nyata ke provider (OpenAI-compatible) ---
    import json
    import socket
    import urllib.error
    import urllib.request

    url = f"{base_url}/chat/completions"
    body = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {effective_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return ProviderTestResult(
            success=True,
            message=(
                f"Koneksi berhasil. Provider {provider} menerima permintaan "
                f"untuk model {model_name} (API Key {masked_key})."
            ),
            model=model_name,
        )
    except urllib.error.HTTPError as e:
        # 401/403 = kredensial ditolak. 404 = endpoint/model salah.
        if e.code in (401, 403):
            msg = "Kredensial ditolak oleh provider (API Key tidak valid atau tidak punya akses)."
        elif e.code == 404:
            msg = "Endpoint atau model tidak ditemukan. Periksa Model Identifier dan Endpoint Base URL."
        elif e.code == 429:
            msg = "Rate limit provider tercapai. Coba lagi beberapa saat lagi."
        else:
            msg = f"Provider menolak permintaan dengan HTTP {e.code}."
        return ProviderTestResult(
            success=False,
            message=f"Gagal: {msg}",
            model=model_name,
        )
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            msg = f"Permintaan melewati batas waktu {timeout} detik."
        else:
            msg = "Tidak dapat menghubungi server provider. Periksa endpoint dan koneksi internet."
        return ProviderTestResult(
            success=False,
            message=f"Gagal: {msg}",
            model=model_name,
        )
    except Exception:
        return ProviderTestResult(
            success=False,
            message="Gagal melakukan koneksi ke provider.",
            model=model_name,
        )


# === ENDPOINT: POST /api/ai-config/save ===

@router.post("/save")
def save_ai_config(
    config: AIConfigSave,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Simpan konfigurasi provider yang dipilih saja.

    Aturan penting:
    - API Key kosong => API Key lama provider tersebut DIPERTAHANKAN.
    - Konfigurasi provider lain TIDAK tersentuh.
    - Penyimpanan gagal => konfigurasi lama utuh.
    """
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Admin yang dapat menyimpan konfigurasi AI."
        )

    provider = (config.provider or "").lower().strip()

    # Validasi provider
    if provider not in AI_PROVIDER_CHOICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider AI tidak valid. Pilih dari yang tersedia."
        )

    # Model: boleh kosong (tetap pakai model tersimpan), atau model baru dari dashboard.
    model_name = (config.model or "").strip()
    if not model_name:
        model_name = settings.AI_MODEL_NAMES.get(provider, DEFAULT_MODELS.get(provider, "local_rule_based"))

    # Siapkan salinan state lama sebagai cadangan (rollback bila gagal)
    backup_keys = dict(settings.AI_API_KEYS)
    backup_models = dict(settings.AI_MODEL_NAMES)
    backup_urls = dict(settings.AI_BASE_URLS)
    backup_temps = dict(settings.AI_TEMPERATURES)
    backup_tokens = dict(settings.AI_MAX_TOKENS)

    try:
        # --- API KEY ---
        typed_key = (config.api_key or "").strip()
        existing_key = settings.AI_API_KEYS.get(provider, "") or ""
        if typed_key:
            # Key baru -> hanya untuk provider ini
            settings.AI_API_KEYS[provider] = typed_key
        else:
            # Kosong -> pertahankan key lama (jangan hapus)
            settings.AI_API_KEYS[provider] = existing_key

        # --- PARAMETER LAIN ---
        settings.AI_MODEL_NAMES[provider] = model_name
        if config.base_url and config.base_url.strip():
            settings.AI_BASE_URLS[provider] = config.base_url.strip().rstrip("/")
        if config.temperature is not None:
            settings.AI_TEMPERATURES[provider] = float(config.temperature)
        if config.max_tokens is not None:
            settings.AI_MAX_TOKENS[provider] = int(config.max_tokens)

    except Exception:
        # Rollback: konfigurasi lama harus utuh bila penyimpanan gagal
        settings.AI_API_KEYS = backup_keys
        settings.AI_MODEL_NAMES = backup_models
        settings.AI_BASE_URLS = backup_urls
        settings.AI_TEMPERATURES = backup_temps
        settings.AI_MAX_TOKENS = backup_tokens
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal menyimpan konfigurasi. Konfigurasi sebelumnya tidak berubah.",
        )

    from datetime import datetime
    last_updated = datetime.now().isoformat()

    key_note = "API Key lama dipertahankan." if not typed_key else "API Key baru disimpan."

    return {
        "status": "success",
        "message": (
            f"Konfigurasi {provider} berhasil disimpan. "
            f"Model: {model_name}. {key_note}"
        ),
        "provider": provider,
        "model": model_name,
        "api_key_updated": bool(typed_key),
        "last_updated": last_updated,
    }


# === ENDPOINT: POST /api/ai-config/activate ===

@router.post("/activate")
def activate_ai_config(
    payload: AIConfigActivate,
    current_user: User = Depends(get_current_user),
):
    """Aktifkan konfigurasi AI Provider baru (JSON body)."""
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya Admin yang dapat mengaktifkan konfigurasi."
        )

    provider = (payload.provider or "").lower().strip()

    if provider not in AI_PROVIDER_CHOICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider AI tidak valid."
        )

    # Verifikasi bahwa provider telah dikonfigurasi dengan API Key
    if provider != "rule_engine":
        api_key = settings.AI_API_KEYS.get(provider, "") or ""
        if not api_key.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider AI belum dikonfigurasi dengan API Key. Silakan simpan konfigurasi terlebih dahulu."
            )

    # Aktifkan provider
    settings.AI_PROVIDER = provider

    return {
        "status": "success",
        "message": (
            f"Konfigurasi AI {provider} berhasil diaktifkan. "
            "Asisten AI akan menggunakan provider baru untuk request berikutnya."
        ),
        "active_provider": provider,
        "model": settings.AI_MODEL_NAMES.get(provider, DEFAULT_MODELS.get(provider, "")),
    }
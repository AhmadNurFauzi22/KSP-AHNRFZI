"""Registry & Factory adapter provider AI.

Satu titik keputusan: provider mana yang dipakai untuk nama provider tertentu.
Orchestrator tidak pernah mengimpor adapter secara langsung.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.config import settings
from app.services.ai.providers.anthropic import AnthropicProvider
from app.services.ai.providers.base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
    ProviderNotConfigured,
)
from app.services.ai.providers.gemini import GeminiProvider
from app.services.ai.providers.openai_compatible import OpenAICompatibleProvider


#: Provider yang didukung sistem.
SUPPORTED_PROVIDERS = ("rule_engine", "openai", "gemini", "anthropic", "nvidia_nim")


def build_provider(
    provider: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[int] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> BaseProvider:
    """Bangun adapter provider berdasarkan nama.

    Nilai parameter default diambil dari ``settings`` bila tidak diberikan,
    sehingga pemanggil cukup menyebut nama provider.
    """
    name = (provider or settings.AI_PROVIDER or "rule_engine").strip().lower()

    if name not in SUPPORTED_PROVIDERS:
        raise ProviderNotConfigured(
            f"Provider '{provider}' tidak didukung. Pilih: {', '.join(SUPPORTED_PROVIDERS)}.",
            provider=str(provider or ""),
        )

    if name == "rule_engine":
        raise ProviderNotConfigured(
            "Rule Engine tidak memakai adapter API eksternal.",
            provider="rule_engine",
        )

    cfg = settings.get_provider_config(name)
    key = api_key if api_key is not None else cfg["api_key"]
    url = base_url if base_url is not None else cfg["base_url"]
    mdl = model if model is not None else cfg["model"]
    tmo = timeout if timeout is not None else cfg["timeout"]
    mtok = max_tokens if max_tokens is not None else cfg["max_tokens"]

    common = dict(
        api_key=key or "",
        base_url=url or "",
        model=mdl or "",
        timeout=tmo,
        max_tokens=mtok,
        retry_attempts=settings.AI_RETRY_ATTEMPTS,
        retry_delay=settings.AI_RETRY_DELAY,
    )

    if name in ("openai", "nvidia_nim"):
        return OpenAICompatibleProvider(name=name, **common)
    if name == "gemini":
        return GeminiProvider(**common)
    if name == "anthropic":
        return AnthropicProvider(**common)

    # Seharusnya tidak tercapai karena pengecekan SUPPORTED_PROVIDERS di atas.
    raise ProviderNotConfigured(f"Provider {name} tidak dikenal.", provider=name)


def provider_list() -> Dict[str, Any]:
    """Metadata ringkas semua provider (untuk UI / diagnostik, tanpa API key)."""
    out: Dict[str, Any] = {}
    for name in SUPPORTED_PROVIDERS:
        cfg = settings.get_provider_config(name)
        key = settings.AI_API_KEYS.get(name, "") or ""
        out[name] = {
            "label": name.upper(),
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "timeout": cfg["timeout"],
            "max_tokens": cfg["max_tokens"],
            "temperature": cfg["temperature"],
            "has_key": bool(key.strip()),
            "key_masked": settings.mask_sensitive(key),
            "is_active": settings.AI_PROVIDER == name,
        }
    return out


__all__ = [
    "build_provider",
    "provider_list",
    "SUPPORTED_PROVIDERS",
    "BaseProvider",
    "LLMRequest",
    "LLMResponse",
    "ProviderError",
    "ProviderNotConfigured",
]

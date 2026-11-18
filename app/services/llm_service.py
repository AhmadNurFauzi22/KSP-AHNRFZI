"""Klien LLM KSP AHNRFZI.

Sebelumnya modul ini memanggil satu endpoint OpenAI-compatible untuk SEMUA
provider dan tidak menyediakan ``answer_with_context`` yang dipakai
``database_intelligence`` — sehingga jalur LLM selalu gagal.

Sekarang modul ini adalah FASAD tipis:

- ``chat_complete()``          : dipakai kompatibilitas lama (OpenAI-compatible)
- ``answer_with_context()``    : jawaban berbasis konteks database + riwayat,
                                 melewati orchestrator terpusat (semua provider)

Semua pemanggilan provider nyata ada di ``app.services.ai.providers``.
Key hanya dipakai di server — tidak pernah dikirim ke browser.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from app.core.config import DEFAULT_MODELS, AI_PROVIDER_CHOICES, settings
from app.core.logging import logger
from app.services.ai.providers import build_provider, provider_list
from app.services.ai.providers.base import LLMRequest, LLMResponse, ProviderError


class LLMError(Exception):
    """Kegagalan generik saat menghubungi provider AI."""

    def __init__(self, message: str, *, provider: str = "", status_code: int = 0,
                 retryable: bool = True):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


# ======================================================================
# System prompt kanonik (delegasi ke modul bersama)
# ======================================================================
from app.services.ai.system_prompt import (  # noqa: E402
    build_static_system_prompt,
    build_system_instruction,
    summarize_for_history,
)


# ======================================================================
# Compat: chat_complete (OpenAI-compatible)
# ======================================================================
def chat_complete(messages: List[Dict[str, str]],
                  temperature: float = 0.3,
                  max_tokens: int = 600) -> str:
    """Panggil provider aktif dengan format OpenAI-compatible.

    Dipakai untuk kompatibilitas dengan pemanggil lama. Provider Gemini dan
    Anthropic dipetakan ke adapter native mereka bila memungkinkan.
    """
    provider_name = (settings.AI_PROVIDER or "rule_engine").lower().strip()
    if provider_name not in AI_PROVIDER_CHOICES:
        provider_name = "rule_engine"

    if provider_name == "rule_engine":
        raise LLMError(
            "Rule Engine tidak memakai model AI eksternal. "
            "Aktifkan provider LLM untuk fitur ini."
        )

    system = build_static_system_prompt()
    full_messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    full_messages.extend(messages or [])

    cfg = settings.get_provider_config(provider_name)
    request = LLMRequest(
        system=system,
        messages=full_messages,
        temperature=cfg["temperature"] if temperature is None else temperature,
        max_tokens=cfg["max_tokens"] if max_tokens is None else max_tokens,
        model=cfg["model"],
        timeout=cfg["timeout"],
    )

    provider = build_provider(provider_name)
    provider.validate()

    built = provider.build_request(request)
    req = urllib.request.Request(
        built["url"], data=built.get("body"), headers=built["headers"], method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=provider.timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise LLMError(
            _human_message(e.code, provider_name),
            provider=provider_name, status_code=e.code, retryable=(e.code == 429 or e.code >= 500),
        )
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        raise LLMError(
            f"Tidak dapat menghubungi provider {provider_name}.",
            provider=provider_name, retryable=True,
        )
    except Exception as e:
        raise LLMError(
            f"Provider {provider_name} mengembalikan respons yang tidak dapat diproses.",
            provider=provider_name, retryable=True,
        )

    try:
        payload = json.loads(raw) if raw else {}
        return provider.parse_response(payload).text
    except ProviderError as e:
        raise LLMError(str(e), provider=provider_name,
                       status_code=e.status_code, retryable=e.retryable)
    except Exception as e:
        raise LLMError(
            f"Gagal memproses respons provider {provider_name}.",
            provider=provider_name, retryable=True,
        )


def _human_message(code: int, provider: str) -> str:
    if code in (401, 403):
        return f"API Key provider {provider} ditolak atau tidak punya akses."
    if code == 404:
        return f"Model atau endpoint provider {provider} tidak ditemukan."
    if code == 400:
        return f"Provider {provider} menolak permintaan (parameter/model tidak valid)."
    if code == 429:
        return f"Provider {provider} sedang membatasi permintaan (rate limit)."
    return f"Provider {provider} mengalami gangguan (HTTP {code})."


# ======================================================================
# Konteks-aware answer (dipakai database_intelligence)
# ======================================================================
def answer_with_context(
    question: str,
    context: str,
    *,
    db=None,
    user=None,
    user_context: Optional[Dict[str, Any]] = None,
    database_context: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Jawab pertanyaan dengan konteks database + riwayat percakapan.

    Inilah perbaikan akar masalah: fungsi ini kini BENAR-BENAR memanggil
    provider aktif melalui orchestrator terpusat, dengan fallback.

    Bila ``db`` dan ``user`` diberikan, retrieval database dan RBAC dijalankan
    ulang oleh orchestrator agar konteks selalu segar dan terotorisasi.
    """
    from app.services.ai.orchestrator import AIOrchestrator

    # Bila pemanggil sudah menyediakan user (jalur database_intelligence),
    # serahkan penuh ke orchestrator agar RBAC + retrieval + history konsisten.
    if db is not None and user is not None:
        result = AIOrchestrator.answer(db, user, question)
        return result.get("answer", "")

    # Fallback minimal: bangun system prompt + context, lalu panggil provider chain.
    from app.services.ai_fallback_service import answer_with_fallback

    system = build_system_instruction(
        user_context=user_context,
        database_context=database_context or context or None,
    )
    cfg = settings.get_provider_config(settings.AI_PROVIDER or "openai")
    request = LLMRequest(
        system=system,
        messages=[{"role": "user", "content": question}],
        temperature=cfg["temperature"] if temperature is None else temperature,
        max_tokens=cfg["max_tokens"] if max_tokens is None else max_tokens,
        model=cfg["model"],
        timeout=cfg["timeout"],
    )

    result = answer_with_fallback(
        question,
        user_id=int((user_context or {}).get("user_id") or 0),
        user_context=user_context or {},
        database_context=database_context or context or "",
    )
    return result.text


# ======================================================================
# Metadata (tanpa API key)
# ======================================================================
def get_active_model() -> str:
    return settings.AI_MODEL_NAMES.get(settings.AI_PROVIDER, DEFAULT_MODELS.get(settings.AI_PROVIDER, ""))


def describe_providers() -> Dict[str, Any]:
    return provider_list()

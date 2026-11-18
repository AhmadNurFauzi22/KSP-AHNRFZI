"""Layanan fallback provider AI.

Rantai percobaan: provider utama -> fallback terkonfigurasi -> rule_engine.
System prompt, konteks database, dan riwayat percakapan TIDAK berubah di
sepanjang rantai, sehingga pergantian provider tidak merusak percakapan
maupun menghilangkan data.

Pencatatan kegagalan TIDAK pernah memuat API key.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import logger
from app.services.ai.conversation import get_history
from app.services.ai.providers import build_provider
from app.services.ai.providers.base import (
    LLMRequest,
    LLMResponse,
    ProviderError,
    ProviderNotConfigured,
)
from app.services.ai.system_prompt import build_system_instruction


#: Maksimal panjang jawaban yang dikirim ke pengguna
MAX_ANSWER_CHARS = 4000


class FallbackResult:
    """Hasil akhir rantai provider."""

    def __init__(self, response: Optional[LLMResponse], provider_used: str,
                 attempts: List[Dict[str, Any]], error: Optional[str] = None):
        self.response = response
        self.provider_used = provider_used
        self.attempts = attempts
        self.error = error

    @property
    def text(self) -> str:
        return (self.response.text if self.response else "") or ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_used,
            "model": self.response.model if self.response else "",
            "usage": self.response.usage if self.response else {},
            "attempts": self.attempts,
            "failed_attempts": len(self.attempts) - (1 if self.response else 0),
        }


def _candidate_providers() -> List[str]:
    """Urutan provider yang akan dicoba.

    Provider aktif dulu, lalu fallback bila terkonfigurasi dan berbeda.
    ``rule_engine`` TIDAK dimasukkan di sini (ditangani orchestrator sebagai
    fallback deterministik terakhir).
    """
    primary = (settings.AI_PROVIDER or "").lower().strip()
    fallback = (settings.AI_FALLBACK_PROVIDER or "").lower().strip()

    chain: List[str] = []
    if primary and primary != "rule_engine":
        chain.append(primary)
    if fallback and fallback != "rule_engine" and fallback not in chain:
        chain.append(fallback)
    return chain


def _build_request(question: str, *, user_context: Dict[str, Any],
                   database_context: str, user_id: int,
                   temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None) -> LLMRequest:
    """Susun ``LLMRequest`` yang IDENTIK untuk semua provider."""
    system = build_system_instruction(
        user_context=user_context,
        database_context=database_context or None,
    )

    history = get_history(user_id)
    messages = list(history)
    messages.append({"role": "user", "content": question})

    cfg = settings.get_provider_config(settings.AI_PROVIDER or "openai")
    return LLMRequest(
        system=system,
        messages=[m if isinstance(m, dict) else m.to_dict() for m in messages],
        temperature=cfg["temperature"] if temperature is None else temperature,
        max_tokens=cfg["max_tokens"] if max_tokens is None else max_tokens,
        model=cfg["model"],
        timeout=cfg["timeout"],
    )


def _call_provider(provider_name: str, request: LLMRequest) -> LLMResponse:
    """Panggil satu provider dengan retry internal."""
    import json
    import socket
    import time
    import urllib.error
    import urllib.request

    provider = build_provider(provider_name)
    provider.validate()

    built = provider.build_request(request)
    last_error: Optional[Exception] = None

    for attempt in range(provider.retry_attempts + 1):
        try:
            req = urllib.request.Request(
                built["url"],
                data=built.get("body"),
                headers=built["headers"],
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=provider.timeout) as resp:
                raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            result = provider.parse_response(payload)
            if result.is_empty():
                raise ProviderError(
                    f"Provider {provider_name} mengembalikan jawaban kosong.",
                    provider=provider_name,
                )
            return result
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (400, 401, 403, 404):
                # Kesalahan permintaan/kredensial/model: retry tidak membantu.
                try:
                    body = e.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    body = ""
                raise ProviderError(
                    _human_message(e.code, provider_name),
                    provider=provider_name,
                    status_code=e.code,
                    detail=body,
                    retryable=False,
                )
            if e.code == 429 or e.code >= 500:
                last_error = e
                if attempt < provider.retry_attempts:
                    time.sleep(provider.retry_delay * (attempt + 1))
                    continue
                raise ProviderError(
                    _human_message(e.code, provider_name),
                    provider=provider_name,
                    status_code=e.code,
                    retryable=True,
                )
            raise ProviderError(
                f"Provider {provider_name} menolak permintaan (HTTP {e.code}).",
                provider=provider_name,
                status_code=e.code,
                retryable=False,
            )
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            last_error = e
            if attempt < provider.retry_attempts:
                time.sleep(provider.retry_delay * (attempt + 1))
                continue
            raise ProviderError(
                f"Koneksi ke provider {provider_name} gagal atau melebihi batas waktu.",
                provider=provider_name,
                detail=type(e).__name__,
                retryable=True,
            )
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                f"Provider {provider_name} mengembalikan respons yang tidak dapat diproses.",
                provider=provider_name,
                detail=type(e).__name__,
                retryable=True,
            )

    raise ProviderError(
        f"Provider {provider_name} gagal setelah beberapa percobaan.",
        provider=provider_name,
        detail=type(last_error).__name__ if last_error else "",
        retryable=True,
    )


def _human_message(code: int, provider: str) -> str:
    if code in (401, 403):
        return f"API Key provider {provider} ditolak atau tidak punya akses."
    if code == 404:
        return f"Model/endpoint provider {provider} tidak ditemukan."
    if code == 400:
        return f"Provider {provider} menolak permintaan (parameter atau model tidak valid)."
    if code == 429:
        return f"Provider {provider} sedang membatasi permintaan (rate limit)."
    return f"Provider {provider} mengalami gangguan (HTTP {code})."


def answer_with_fallback(
    question: str,
    *,
    user_id: int,
    user_context: Dict[str, Any],
    database_context: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> FallbackResult:
    """Jalankan rantai provider: utama -> fallback.

    Mengembalikan ``FallbackResult``; bila semua provider gagal,
    ``response`` bernilai ``None`` dan ``error`` berisi penyebab yang aman.
    """
    request = _build_request(
        question,
        user_context=user_context,
        database_context=database_context,
        user_id=user_id,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    attempts: List[Dict[str, Any]] = []
    chain = _candidate_providers()

    if not chain:
        return FallbackResult(
            None, "rule_engine", attempts,
            error="Belum ada provider LLM yang dikonfigurasi.",
        )

    for name in chain:
        try:
            resp = _call_provider(name, request)
            attempts.append({"provider": name, "ok": True})
            return FallbackResult(resp, name, attempts)
        except ProviderNotConfigured as e:
            attempts.append({
                "provider": name, "ok": False,
                "reason": "not_configured",
                "message": str(e),
            })
            logger.warning(f"[AI_FALLBACK] {name} belum dikonfigurasi: {e}")
        except ProviderError as e:
            attempts.append({
                "provider": name, "ok": False,
                "reason": "provider_error",
                "status": e.status_code,
                "message": str(e),
            })
            logger.warning(
                f"[AI_FALLBACK] provider {name} gagal (HTTP {e.status_code}): {e}"
            )
        except Exception as e:  # pragma: no cover - pengaman terakhir
            attempts.append({
                "provider": name, "ok": False,
                "reason": "unexpected",
                "message": type(e).__name__,
            })
            logger.error(f"[AI_FALLBACK] provider {name} unexpected: {type(e).__name__}")

    return FallbackResult(
        None, "rule_engine", attempts,
        error="Seluruh provider LLM gagal merespons.",
    )

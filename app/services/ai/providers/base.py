"""Kontrak bersama untuk seluruh adapter provider AI.

Semua provider dinormalisasi ke dalam bentuk ``LLMRequest`` -> ``LLMResponse``
sehingga orchestrator tidak perlu tahu-menahu tentang perbedaan API tiap vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ProviderError(RuntimeError):
    """Kegagalan saat memanggil provider AI.

    Pesan error TIDAK boleh memuat API key. Detail asli dibungkus di
    ``detail`` yang hanya dipakai untuk logging server-side.
    """

    def __init__(self, message: str, *, provider: str = "", status_code: int = 0,
                 detail: str = "", retryable: bool = True):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.detail = detail
        self.retryable = retryable


class ProviderNotConfigured(ProviderError):
    """Provider tidak memiliki API key / endpoint yang valid."""

    def __init__(self, message: str, *, provider: str = ""):
        super().__init__(message, provider=provider, retryable=False)


@dataclass
class ChatMessage:
    """Satu giliran percakapan (role + konten)."""

    role: str          # "user" | "assistant"
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMRequest:
    """Permintaan generik yang dinormalisasi untuk semua provider."""

    system: str = ""
    messages: List[ChatMessage] = field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 1000
    model: str = ""
    timeout: int = 30
    # Metadata internal (tidak dikirim ke provider)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def last_user_message(self) -> str:
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg.content
        return ""

    def estimated_tokens(self) -> int:
        """Estimasi kasar jumlah token (sekitar 4 karakter = 1 token)."""
        total = len(self.system) // 4
        for m in self.messages:
            total += len(m.content) // 4 + 4
        return total


@dataclass
class LLMResponse:
    """Respons generik yang dinormalisasi dari semua provider."""

    text: str
    provider: str
    model: str
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.text or "").strip()


class BaseProvider:
    """Kontrak adapter provider.

    Subclass wajib mengimplementasikan ``name``, ``build_request``,
    ``parse_response``, dan ``extract_text``.
    """

    name: str = "base"
    #: Format API: "openai" | "gemini" | "anthropic"
    api_format: str = "openai"

    def __init__(self, api_key: str, base_url: str, model: str,
                 timeout: int = 30, retry_attempts: int = 2,
                 retry_delay: float = 1.0, max_tokens: int = 1000):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.model = (model or "").strip()
        self.timeout = int(timeout or 30)
        self.retry_attempts = max(0, int(retry_attempts or 0))
        self.retry_delay = float(retry_delay or 1.0)
        self.max_tokens = int(max_tokens or 1000)

    # ------------------------------------------------------------------
    # Kontrak yang wajib diimplementasikan subclass
    # ------------------------------------------------------------------
    def build_request(self, request: LLMRequest) -> Dict[str, Any]:
        """Bentuk payload HTTP + endpoint + headers."""
        raise NotImplementedError

    def parse_response(self, payload: Dict[str, Any]) -> LLMResponse:
        """Normalisasi payload provider menjadi ``LLMResponse``."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helper bersama
    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Pastikan konfigurasi provider cukup untuk memanggil API."""
        if not self.api_key:
            raise ProviderNotConfigured(
                f"Provider {self.name} belum memiliki API Key.", provider=self.name)
        if not self.base_url:
            raise ProviderNotConfigured(
                f"Provider {self.name} belum memiliki Endpoint Base URL.", provider=self.name)
        if not self.model:
            raise ProviderNotConfigured(
                f"Provider {self.name} belum memiliki Model Identifier.", provider=self.name)

    def build_messages_payload(self, request: LLMRequest) -> List[Dict[str, str]]:
        """Normalisasi riwayat percakapan ke format umum.

        Menerima ``ChatMessage`` maupun dict biasa (``{"role":..,"content":..}``).
        """
        out: List[Dict[str, str]] = []
        for m in request.messages:
            if isinstance(m, dict):
                out.append({"role": str(m.get("role", "user")),
                            "content": str(m.get("content", ""))})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def extract_text(self, payload: Dict[str, Any]) -> str:
        """Ambil teks jawaban dari payload mentah provider."""
        raise NotImplementedError

    def extract_usage(self, payload: Dict[str, Any]) -> Dict[str, int]:
        """Ambil penggunaan token bila tersedia."""
        usage = payload.get("usage") or {}
        out: Dict[str, int] = {}
        for src, dst in (("prompt_tokens", "prompt_tokens"),
                         ("completion_tokens", "completion_tokens"),
                         ("total_tokens", "total_tokens")):
            val = usage.get(src)
            if isinstance(val, (int, float)):
                out[dst] = int(val)
        return out

    def __repr__(self) -> str:  # pragma: no cover - untuk debug
        return f"<{self.__class__.__name__} name={self.name} model={self.model!r}>"

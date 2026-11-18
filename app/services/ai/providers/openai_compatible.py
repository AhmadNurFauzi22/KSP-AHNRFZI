"""Adapter OpenAI Chat Completions.

Kompatibel dengan OpenAI dan semua gateway OpenAI-compatible
(termasuk NVIDIA NIM di https://integrate.api.nvidia.com/v1).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.services.ai.providers.base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
)


class OpenAICompatibleProvider(BaseProvider):
    """Adapter untuk API berformat OpenAI Chat Completions."""

    api_format = "openai"

    def __init__(self, name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name

    # ------------------------------------------------------------------
    def build_request(self, request: LLMRequest) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend(self.build_messages_payload(request))

        payload = {
            "url": f"{self.base_url}/chat/completions",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            "body": json.dumps({
                "model": request.model or self.model,
                "messages": messages,
                "temperature": max(0.0, min(2.0, float(request.temperature or 0.0))),
                "max_tokens": int(request.max_tokens or self.max_tokens),
            }).encode("utf-8"),
        }
        return payload

    # ------------------------------------------------------------------
    def parse_response(self, payload: Dict[str, Any]) -> LLMResponse:
        text = self.extract_text(payload)
        choices = payload.get("choices") or []
        finish = ""
        if choices:
            finish = (choices[0].get("finish_reason") or "") if isinstance(choices[0], dict) else ""

        return LLMResponse(
            text=text,
            provider=self.name,
            model=(payload.get("model") or self.model),
            usage=self.extract_usage(payload),
            finish_reason=finish,
            raw=payload,
        )

    # ------------------------------------------------------------------
    def extract_text(self, payload: Dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError(
                f"Provider {self.name} tidak mengembalikan pilihan jawaban.",
                provider=self.name,
                detail="choices kosong",
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderError(
                f"Provider {self.name} mengembalikan format jawaban yang tidak dikenal.",
                provider=self.name,
            )
        message = first.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            # Beberapa gateway mengembalikan content sebagai list of parts.
            return "".join(
                (part.get("text") or "") for part in content if isinstance(part, dict)
            )
        if content is None:
            raise ProviderError(
                f"Provider {self.name} mengembalikan jawaban kosong.",
                provider=self.name,
            )
        return str(content)

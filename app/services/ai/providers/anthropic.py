"""Adapter Anthropic Claude (Messages API native).

Endpoint: POST {base_url}/messages
Headers: x-api-key, anthropic-version, content-type
Body: { model, max_tokens, system, messages, temperature }
Response: { content: [ { type: "text", text } ], usage, stop_reason }

Catatan: Anthropic TIDAK memakai header "Authorization: Bearer".
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


class AnthropicProvider(BaseProvider):
    """Adapter untuk Anthropic Claude Messages API."""

    name = "anthropic"
    api_format = "anthropic"
    API_VERSION = "2023-06-01"

    # ------------------------------------------------------------------
    def build_request(self, request: LLMRequest) -> Dict[str, Any]:
        messages = self._to_messages(request)

        body: Dict[str, Any] = {
            "model": request.model or self.model,
            "max_tokens": int(request.max_tokens or self.max_tokens),
            "messages": messages,
        }
        if request.system:
            body["system"] = request.system
        if request.temperature is not None:
            body["temperature"] = max(0.0, min(1.0, float(request.temperature)))

        return {
            "url": f"{self.base_url}/messages",
            "headers": {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
            },
            "body": json.dumps(body).encode("utf-8"),
        }

    # ------------------------------------------------------------------
    def _to_messages(self, request: LLMRequest) -> List[Dict[str, str]]:
        """Anthropic menolak role 'system' di array messages (dipisah ke field system)."""
        out: List[Dict[str, str]] = []
        for m in self.build_messages_payload(request):
            if m["role"] not in ("user", "assistant"):
                continue
            out.append({"role": m["role"], "content": m["content"]})
        return out

    # ------------------------------------------------------------------
    def parse_response(self, payload: Dict[str, Any]) -> LLMResponse:
        text = self.extract_text(payload)
        usage = payload.get("usage") or {}
        mapped = {}
        for src, dst in (("input_tokens", "prompt_tokens"),
                         ("output_tokens", "completion_tokens")):
            val = usage.get(src)
            if isinstance(val, (int, float)):
                mapped[dst] = int(val)
        if "prompt_tokens" in mapped and "completion_tokens" in mapped:
            mapped["total_tokens"] = mapped["prompt_tokens"] + mapped["completion_tokens"]

        return LLMResponse(
            text=text,
            provider=self.name,
            model=(payload.get("model") or self.model),
            usage=mapped,
            finish_reason=(payload.get("stop_reason") or ""),
            raw=payload,
        )

    # ------------------------------------------------------------------
    def extract_text(self, payload: Dict[str, Any]) -> str:
        content = payload.get("content") or []
        if isinstance(content, str):
            return content.strip()
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        joined = "".join(texts).strip()
        if not joined:
            # Anthropic mengembalikan error terstruktur bila gagal
            err = payload.get("error") or {}
            if err:
                raise ProviderError(
                    f"Anthropic menolak permintaan: {err.get('type', 'error')}.",
                    provider=self.name,
                    detail=str(err.get("message", ""))[:200],
                )
            raise ProviderError(
                "Anthropic mengembalikan jawaban kosong.",
                provider=self.name,
            )
        return joined

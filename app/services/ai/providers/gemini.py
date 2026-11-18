"""Adapter Google Gemini (REST API native).

Endpoint: POST {base_url}/models/{model}:generateContent?key=API_KEY
Body: { systemInstruction, contents, generationConfig }
Response: { candidates: [ { content: { parts: [ { text } ] } } ] }

Referensi: https://ai.google.dev/api/generate-content
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from urllib.parse import quote

from app.services.ai.providers.base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
)


class GeminiProvider(BaseProvider):
    """Adapter untuk Google Gemini generateContent."""

    name = "gemini"
    api_format = "gemini"

    # ------------------------------------------------------------------
    def build_request(self, request: LLMRequest) -> Dict[str, Any]:
        contents = self._to_contents(request)

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": max(0.0, min(2.0, float(request.temperature or 0.0))),
                "maxOutputTokens": int(request.max_tokens or self.max_tokens),
            },
        }
        if request.system:
            body["systemInstruction"] = {
                "parts": [{"text": request.system}]
            }

        # Model name pada URL: ambil segmen terakhir "models/<id>"
        model_path = self.model or request.model
        if model_path.startswith("models/"):
            model_path = model_path.split("/", 1)[1]

        return {
            "url": (
                f"{self.base_url}/models/{quote(model_path, safe='')}"
                f":generateContent?key={self.api_key}"
            ),
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body).encode("utf-8"),
        }

    # ------------------------------------------------------------------
    def _to_contents(self, request: LLMRequest) -> List[Dict[str, Any]]:
        """Gemini memakai role 'model' bukan 'assistant'."""
        out: List[Dict[str, Any]] = []
        for m in self.build_messages_payload(request):
            role = "model" if m["role"] == "assistant" else "user"
            out.append({"role": role, "parts": [{"text": m["content"]}]})
        return out

    # ------------------------------------------------------------------
    def parse_response(self, payload: Dict[str, Any]) -> LLMResponse:
        text = self.extract_text(payload)
        usage = payload.get("usageMetadata") or {}
        mapped = {}
        for src, dst in (("promptTokenCount", "prompt_tokens"),
                         ("candidatesTokenCount", "completion_tokens"),
                         ("totalTokenCount", "total_tokens")):
            val = usage.get(src)
            if isinstance(val, (int, float)):
                mapped[dst] = int(val)

        finish = ""
        cands = payload.get("candidates") or []
        if cands and isinstance(cands[0], dict):
            finish = cands[0].get("finishReason") or ""

        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            usage=mapped,
            finish_reason=finish,
            raw=payload,
        )

    # ------------------------------------------------------------------
    def extract_text(self, payload: Dict[str, Any]) -> str:
        cands = payload.get("candidates") or []
        if not cands:
            # Gemini bisa menolak dengan promptFeedback (mis. safety block)
            fb = payload.get("promptFeedback") or {}
            reason = fb.get("blockReason") or "tidak diketahui"
            raise ProviderError(
                f"Gemini menolak permintaan: {reason}.",
                provider=self.name,
                detail=f"promptFeedback={reason}",
            )
        first = cands[0]
        content = first.get("content") or {}
        parts = content.get("parts") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        joined = "".join(texts).strip()
        if not joined:
            raise ProviderError(
                "Gemini mengembalikan jawaban kosong.",
                provider=self.name,
            )
        return joined

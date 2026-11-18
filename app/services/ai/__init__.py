"""Mesin AI KSP AHNRFZI — satu otak, banyak provider.

Modul ini berisi:
- ``system_prompt``     : system prompt kanonik untuk semua provider
- ``conversation``      : riwayat percakapan server-side
- ``orchestrator``     : pipeline terpusat (auth -> rbac -> retrieval -> provider -> validasi)
"""

from __future__ import annotations

from app.services.ai.orchestrator import AIOrchestrator, answer_question

__all__ = ["AIOrchestrator", "answer_question"]

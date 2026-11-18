"""Shim kompatibilitas.

Implementasi context service yang sebenarnya berada di
``app/services/ai/ai_context_service.py`` (paket AI terpusat).

Modul ini dipertahankan agar pemanggil lama
``from app.services.ai_context_service import ...`` tetap bekerja.
"""

from __future__ import annotations

from app.services.ai.ai_context_service import (  # noqa: F401
    ROLE_LABELS,
    _CONTEXT_ROUTER,
    _safe,
    build_context_bundle,
    build_database_context,
    build_user_context,
    get_active_role,
    has_perm,
)

__all__ = [
    "build_context_bundle",
    "build_database_context",
    "build_user_context",
    "get_active_role",
    "has_perm",
    "ROLE_LABELS",
]

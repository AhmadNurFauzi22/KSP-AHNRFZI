"""Manajemen Riwayat Percakapan AI (server-side).

Riwayat disimpan di backend per ``user_id``, TIDAK bergantung pada memori
internal model provider, sehingga pergantian provider/model tidak merusak
percakapan.

Batasan konteks:
- Maksimal ``max_turns`` giliran (1 giliran = 1 user + 1 assistant).
- Total estimasi token dibatasi ``max_tokens``; giliran tertua dipangkas
  dari ujung depan (FIFO) namun system prompt & konteks database selalu
  dibangun ulang oleh orchestrator untuk setiap request.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from app.services.ai.providers.base import ChatMessage


# ---------------------------------------------------------------------
# Batas default
# ---------------------------------------------------------------------
DEFAULT_MAX_TURNS = 12          # 12 giliran = 24 pesan
DEFAULT_MAX_TOKENS = 6000       # estimasi kasar token riwayat
TTL_SECONDS = 3600 * 2          # riwayat hangat selama 2 jam


class ConversationStore:
    """Penyimpanan riwayat percakapan per pengguna (in-memory, thread-safe).

    Struktur: {user_id: {"turns": [(q, a), ...], "updated": float, "subject": str}}
    """

    def __init__(self) -> None:
        self._data: Dict[int, Dict[str, Any]] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    def _prune_locked(self, user_id: int) -> None:
        """Buang entri kedaluwarsa (dipanggil di dalam lock)."""
        now = time.time()
        expired = [uid for uid, v in self._data.items()
                   if now - float(v.get("updated", now)) > TTL_SECONDS]
        for uid in expired:
            self._data.pop(uid, None)

    # ------------------------------------------------------------------
    def get(self, user_id: int,
            max_turns: int = DEFAULT_MAX_TURNS,
            max_tokens: int = DEFAULT_MAX_TOKENS) -> List[ChatMessage]:
        """Ambil riwayat sebagai daftar ``ChatMessage`` (user/assistant).

        Giliran terlama dipangkas bila melewati ``max_turns`` atau ``max_tokens``.
        """
        with self._lock:
            self._prune_locked(user_id)
            entry = self._data.get(user_id)
            if not entry:
                return []

            turns: List[Tuple[str, str]] = list(entry.get("turns") or [])
            messages: List[ChatMessage] = []

            # Bangun dari paling baru ke paling lama agar pemangkasan FIFO
            # menyisakan giliran yang paling relevan.
            budget = max_tokens
            for q, a in reversed(turns[-max_turns:]):
                cost = (len(q) + len(a)) // 4 + 8
                if budget - cost < 0:
                    break
                budget -= cost
                messages.append(ChatMessage(role="user", content=q))
                messages.append(ChatMessage(role="assistant", content=a))

            messages.reverse()
            return messages

    # ------------------------------------------------------------------
    def append(self, user_id: int, question: str, answer: str,
               subject: Optional[str] = None) -> None:
        """Tambahkan satu giliran percakapan."""
        with self._lock:
            entry = self._data.setdefault(
                user_id, {"turns": [], "updated": time.time(), "subject": None}
            )
            entry["turns"].append((question or "", answer or ""))
            entry["updated"] = time.time()
            if subject:
                entry["subject"] = subject
            # Jaga ukuran mentah
            while len(entry["turns"]) > DEFAULT_MAX_TURNS * 2:
                entry["turns"].pop(0)

    # ------------------------------------------------------------------
    def get_subject(self, user_id: int) -> Optional[str]:
        """Subjek kontekstual terakhir (dipakai intent lanjutan deterministik)."""
        with self._lock:
            entry = self._data.get(user_id)
            if not entry:
                return None
            return entry.get("subject")

    def set_subject(self, user_id: int, subject: str) -> None:
        with self._lock:
            entry = self._data.setdefault(
                user_id, {"turns": [], "updated": time.time(), "subject": None}
            )
            entry["subject"] = subject
            entry["updated"] = time.time()

    # ------------------------------------------------------------------
    def clear(self, user_id: int) -> bool:
        with self._lock:
            return self._data.pop(user_id, None) is not None

    # ------------------------------------------------------------------
    def stats(self, user_id: int) -> Dict[str, Any]:
        with self._lock:
            entry = self._data.get(user_id)
            if not entry:
                return {"turns": 0, "subject": None}
            return {
                "turns": len(entry.get("turns") or []),
                "subject": entry.get("subject"),
            }


# ---------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------
CONVERSATION_STORE = ConversationStore()


def get_history(user_id: int,
                max_turns: int = DEFAULT_MAX_TURNS,
                max_tokens: int = DEFAULT_MAX_TOKENS) -> List[ChatMessage]:
    return CONVERSATION_STORE.get(user_id, max_turns=max_turns, max_tokens=max_tokens)


def add_turn(user_id: int, question: str, answer: str,
             subject: Optional[str] = None) -> None:
    CONVERSATION_STORE.append(user_id, question, answer, subject=subject)


def get_subject(user_id: int) -> Optional[str]:
    return CONVERSATION_STORE.get_subject(user_id)


def set_subject(user_id: int, subject: str) -> None:
    CONVERSATION_STORE.set_subject(user_id, subject)


def clear_history(user_id: int) -> bool:
    return CONVERSATION_STORE.clear(user_id)

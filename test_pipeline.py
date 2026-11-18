"""Uji pipeline AI terpusat: retrieval, intent, RBAC, fallback, konteks."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.core.config import settings
from app.db.models.user import User
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai import conversation
from app.services.ai_context_service import (
    build_context_bundle, detect_intent, build_user_context, build_database_context,
)

QUESTIONS = [
    "Berapa total anggota aktif?",
    "Berapa total pengguna aplikasi?",
    "Siapa saja pengguna aplikasi dan apa role mereka?",
    "Berapa total simpanan anggota?",
    "Berapa total pinjaman berjalan?",
    "Apa tugas Kasir?",
    "Apa tugas Pengawas?",
    "Apa fungsi modul angsuran?",
    "Bagaimana cara kerja sistem RBAC?",
    "Apa saja data anggota yang belum lengkap?",
    "Jelaskan ringkasan dashboard saya.",
]

db = SessionLocal()
try:
    admin = db.query(User).filter(User.id == 1).first()
    print('=' * 76)
    print('PROVIDER AKTIF:', settings.AI_PROVIDER, '| llm_enabled:', settings.llm_enabled)
    print('=' * 76)

    print()
    print('=== A. INTENT DETECTION ===')
    for q in QUESTIONS:
        print(f'  {detect_intent(q):20s} <- {q}')

    print()
    print('=== B. USER CONTEXT (tanpa data sensitif) ===')
    uc = build_user_context(db, admin)
    for k, v in uc.items():
        print(f'  {k}: {v}')
    assert 'hashed_password' not in str(uc).lower()
    assert 'api_key' not in str(uc).lower()

    print()
    print('=== C. DATABASE CONTEXT per intent (sumber sama dengan dashboard) ===')
    for q in QUESTIONS[:8]:
        ctx = build_database_context(db, admin, q)
        preview = ctx.replace('\n', ' | ')[:150]
        print(f'  [{detect_intent(q)}] {preview}')

    print()
    print('=== D. ORCHESTRATOR (jalur nyata) ===')
    for q in QUESTIONS:
        conversation.clear_history(admin.id)
        try:
            r = AIOrchestrator.answer(db, admin, q)
            ans = (r.get('answer') or '').replace('\n', ' ')
            print(f'  [{r.get("intent"):16s}] {r.get("provider", "?"):12s} '
                  f'{r.get("model", "?"):26s} {ans[:95]}')
        except Exception as e:
            print(f'  [ERROR] {q}: {type(e).__name__}: {e}')

    print()
    print('=== E. RIWAYAT PERCAKAPAN (server-side) ===')
    conversation.clear_history(admin.id)
    r1 = AIOrchestrator.answer(db, admin, "Berapa total pengguna aplikasi?")
    print(f'  T1 -> intent={r1.get("intent")} provider={r1.get("provider")}')
    r2 = AIOrchestrator.answer(db, admin, "Bagaimana pembagian berdasarkan role?")
    print(f'  T2 -> intent={r2.get("intent")} provider={r2.get("provider")}')
    print(f'  history stats: {conversation.CONVERSATION_STORE.stats(admin.id)}')
    print(f'  subject: {conversation.get_subject(admin.id)}')

    print()
    print('=== F. RBAC: role non-admin ===')
    mgr = db.query(User).filter(User.id == 3).first()
    if mgr:
        for q in ["Berapa total simpanan anggota?", "Siapa saja pengguna aplikasi?"]:
            conversation.clear_history(mgr.id)
            r = AIOrchestrator.answer(db, mgr, q)
            ans = (r.get('answer') or '').replace('\n', ' ')
            print(f'  role={mgr.roles[0].code if mgr.roles else "?"} '
                  f'intent={r.get("intent"):16s} {ans[:100]}')

    print()
    print('=== G. PERTANYAAN DI LUAR LINGKUP ===')
    for q in ["Buatkan program python untuk sorting", "Apa itu machine learning?"]:
        r = AIOrchestrator.answer(db, admin, q)
        print(f'  intent={r.get("intent"):10s} authorized={r.get("authorized")} '
              f'{(r.get("answer") or "")[:80]}')

    print()
    print('=== H. FALLBACK (semua provider gagal -> rule_engine) ===')
    # Paksa: provider aktif tanpa key
    original = settings.AI_PROVIDER
    settings.AI_PROVIDER = "openai"  # key kosong -> provider gagal
    settings.AI_FALLBACK_PROVIDER = ""
    conversation.clear_history(admin.id)
    r = AIOrchestrator.answer(db, admin, "Berapa total anggota?")
    print(f'  intent={r.get("intent")} provider={r.get("provider")} '
          f'model={r.get("model")} fallback_from={r.get("fallback_from")}')
    print(f'  answer: {(r.get("answer") or "")[:160]}')
    settings.AI_PROVIDER = original

finally:
    db.close()

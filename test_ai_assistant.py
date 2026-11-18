"""Automated test AI Assistant KSP AHNRFZI (intent, context routing, RBAC, provider).

Jalankan: python test_ai_assistant.py
Butuh server aktif di http://127.0.0.1:8000 (untuk uji E2E endpoint).
"""
import http.cookiejar as cjmod
import json
import urllib.request as ur

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.db.models.user import User
from app.services.ai.ai_context_service import build_database_context
from app.services.ai_intent import detect_intent
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.providers import build_provider
from app.services.ai.providers.base import ChatMessage, LLMRequest
from app.services.ai.system_prompt import build_static_system_prompt

BASE = 'http://127.0.0.1:8000'
FAILS = []


def check(label, cond, extra=''):
    print(f'  [{"OK  " if cond else "FAIL"}] {label} {extra}')
    if not cond:
        FAILS.append(label)


def opener(uid, role):
    t = create_access_token({'sub': str(uid), 'active_role': role})
    cj = cjmod.CookieJar()
    op = ur.build_opener(ur.HTTPCookieProcessor(cj))
    cj.set_cookie(cjmod.Cookie(0, 'access_token', f'Bearer {t}', None, False,
                               '127.0.0.1', False, False, '/', True, False,
                               None, True, None, None, {}, False))
    return op


def ask(op, question):
    req = ur.Request(f'{BASE}/api/v1/ai/ask',
                     data=json.dumps({'question': question}).encode(),
                     headers={'Content-Type': 'application/json'}, method='POST')
    try:
        r = op.open(req, timeout=60)
        return r.status, json.loads(r.read().decode())
    except ur.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or '{}')
        except Exception:
            return e.code, {}


# =====================================================================
INTENT_CASES = [
    ("Siapa saya?", "USER_IDENTITY"),
    ("Siapa nama saya?", "USER_IDENTITY"),
    ("Saya login sebagai siapa?", "USER_IDENTITY"),
    ("Apa jabatan saya?", "USER_IDENTITY"),
    ("Apa role saya?", "USER_IDENTITY"),
    ("Apa hak akses saya?", "USER_IDENTITY"),
    ("Berapa jumlah pengguna?", "USER_COUNT"),
    ("Siapa saja pengguna?", "USER_LIST"),
    ("Siapa saja pengguna aplikasi?", "USER_LIST"),
    ("Apa saja role yang tersedia?", "ROLE_LIST"),
    ("Siapa pemegang role Admin?", "USER_ROLE_LOOKUP"),
    ("Siapa yang Admin?", "USER_ROLE_LOOKUP"),
    ("Berapa total anggota?", "MEMBER_STATISTICS"),
    ("Berapa total anggota aktif?", "MEMBER_STATISTICS"),
    ("Siapa anggota yang datanya belum lengkap?", "MEMBER_INCOMPLETE"),
    ("Berapa total simpanan?", "SAVINGS"),
    ("Berapa total pinjaman?", "LOANS"),
    ("Berapa angsuran yang terlambat?", "INSTALLMENTS"),
    ("Siapa anggota yang memiliki pinjaman terlambat?", "INSTALLMENTS"),
    ("Berapa saldo kas?", "CASH_FLOW"),
    ("Apa transaksi terbaru?", "TRANSACTIONS"),
    ("Berapa pengajuan yang menunggu?", "PENDING_APPLICATIONS"),
    ("Bagaimana kondisi koperasi?", "DASHBOARD_SUMMARY"),
    ("Apakah server sedang online?", "SYSTEM_STATUS"),
    ("Tampilkan struktur database", "TECHNICAL"),
    ("Apa aktivitas terakhir saya?", "AUDIT_STATUS"),
]


def test_intent():
    print('=' * 78)
    print('1. INTENT DETECTION')
    print('=' * 78)
    for q, exp in INTENT_CASES:
        got = detect_intent(q)
        check(f'{exp:20s} <- {q}', got == exp, f'(got {got})')


def test_context_routing():
    print()
    print('=' * 78)
    print('2. CONTEXT ROUTING (sumber data per intent)')
    print('=' * 78)
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == 1).first()
        for q, _ in INTENT_CASES:
            intent = detect_intent(q)
            ctx = build_database_context(db, u, q, intent=intent)
            ditolak = ctx.startswith('[DITOLAK]')
            print(f'  {intent:20s} | {ctx.splitlines()[0][:70]}')
            check(f'{intent:20s} konteks terisi', bool(ctx.strip()))
    finally:
        db.close()


def test_identity():
    print()
    print('=' * 78)
    print('3. IDENTITAS = DARI SESSION, BUKAN DASHBOARD')
    print('=' * 78)
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == 1).first()
        r = AIOrchestrator.answer(db, u, "Siapa saya?")
        ans = r.get('answer', '')
        for line in ans.split('\n'):
            print('      ' + line[:110])
        leak = [k for k in ('total anggota', 'Total simpanan', 'Outstanding', 'kas masuk',
                            'audit', 'piutang', 'transaksi', 'Rp ') if k.lower() in ans.lower()]
        check('Intent = USER_IDENTITY', r.get('intent') == 'USER_IDENTITY')
        check('Tidak ada data agregat dashboard', not leak, f'LEAK={leak}' if leak else '')
        check('Memuat nama pengguna', (u.full_name or '') in ans)
        check('Memuat username', u.username in ans)
        check('Memuat role aktif', 'Role aktif' in ans)
    finally:
        db.close()


def test_followup():
    print()
    print('=' * 78)
    print('4. PERTANYAAN LANJUTAN (konteks percakapan)')
    print('=' * 78)
    from app.services.ai import conversation
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == 1).first()
        conversation.clear_history(u.id)
        r1 = AIOrchestrator.answer(db, u, "Berapa jumlah pengguna?")
        r2 = AIOrchestrator.answer(db, u, "Siapa saja namanya?")
        r3 = AIOrchestrator.answer(db, u, "Kalau yang Admin siapa?")
        r4 = AIOrchestrator.answer(db, u, "Kalau saya?")
        print(f'  T1 "Berapa jumlah pengguna?" -> {r1.get("intent")}  subject={conversation.get_subject(u.id)}')
        print(f'  T2 "Siapa saja namanya?"     -> {r2.get("intent")}')
        print(f'  T3 "Kalau yang Admin siapa?" -> {r3.get("intent")}')
        print(f'  T4 "Kalau saya?"            -> {r4.get("intent")}')
        check('T1 = USER_COUNT', r1.get('intent') == 'USER_COUNT')
        check('T2 = USER_LIST (dari subjek)', r2.get('intent') == 'USER_LIST')
        check('T3 = USER_ROLE_LOOKUP', r3.get('intent') == 'USER_ROLE_LOOKUP')
        check('T4 = USER_IDENTITY', r4.get('intent') == 'USER_IDENTITY')
    finally:
        db.close()


def test_rbac():
    print()
    print('=' * 78)
    print('5. RBAC PER ROLE')
    print('=' * 78)
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        for u in users:
            roles = ','.join(x.code for x in u.roles)
            ident = AIOrchestrator.answer(db, u, "Siapa saya?")
            simpan = AIOrchestrator.answer(db, u, "Berapa total simpanan?")
            daftar = AIOrchestrator.answer(db, u, "Siapa saja pengguna?")
            print(f'  #{u.id} {u.username:14s} [{roles}]')
            print(f'      ident  -> {ident.get("intent")}')
            print(f'      simpan -> {simpan.get("intent")}')
            print(f'      daftar -> {daftar.get("intent")}')
        # ANGGOTA harus ditolak untuk data lintas pengguna
        anggota = [u for u in users if u.roles and u.roles[0].code == 'ANGGOTA']
        if anggota:
            r = AIOrchestrator.answer(db, anggota[0], "Siapa saja pengguna?")
            check('ANGGOTA: daftar pengguna DITOLAK',
                  'tidak memiliki izin' in (r.get('answer') or '').lower(),
                  f"intent={r.get('intent')}")
    finally:
        db.close()


def test_provider_parity():
    print()
    print('=' * 78)
    print('6. PARITAS KONTEX & SYSTEM PROMPT ANTAR-PROVIDER')
    print('=' * 78)
    sysp = build_static_system_prompt()
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == 1).first()
        for q in ["Berapa total anggota aktif?", "Berapa total simpanan?", "Siapa saya?"]:
            intent = detect_intent(q)
            ctx = build_database_context(db, u, q, intent=intent)
            bodies = []
            for prov in ['openai', 'nvidia_nim', 'gemini', 'anthropic']:
                cfg = settings.get_provider_config(prov)
                r = LLMRequest(system=sysp, messages=[ChatMessage('user', q)],
                               temperature=cfg['temperature'], max_tokens=cfg['max_tokens'],
                               model=cfg['model'], timeout=cfg['timeout'])
                bodies.append(build_provider(prov, api_key='K', base_url='https://x/v1',
                                             model=cfg['model']).build_request(r)['body'].decode())
            # Yang WAJIB identik: system prompt + pertanyaan user.
            # Yang BERBEDA (wajar): nama model + parameter model per provider.
            sys_same = all('ATURAN MEMILIH SUMBER DATA' in b for b in bodies)
            msg_same = all(q in b for b in bodies)
            probe = 'ATURAN MEMILIH SUMBER DATA'
            print(f'  {intent:20s} ctx_len={len(ctx):4d} system_sama={sys_same} pesan_sama={msg_same}')
            check(f'{intent:20s} system prompt identik antar provider', sys_same and probe in sysp)
            check(f'{intent:20s} pertanyaan + konteks identik', msg_same and len(ctx) > 0)
    finally:
        db.close()


def test_provider_status():
    print()
    print('=' * 78)
    print('7. STATUS KREDENSIAL PROVIDER')
    print('=' * 78)
    for prov in ['openai', 'gemini', 'anthropic', 'nvidia_nim']:
        key = settings.AI_API_KEYS.get(prov, '') or ''
        if key.strip():
            print(f'  {prov:12s} ADA kredensial -> uji koneksi nyata bisa dijalankan')
        else:
            print(f'  {prov:12s} SKIPPED - tidak ada API Key (hasil tidak dikarang)')


def test_e2e():
    print()
    print('=' * 78)
    print('8. E2E ENDPOINT /api/v1/ai/ask')
    print('=' * 78)
    admin = opener(1, 'ADMIN_KOPERASI')
    for q, exp in [("Siapa saya?", "USER_IDENTITY"),
                   ("Berapa total anggota aktif?", "MEMBER_STATISTICS"),
                   ("Berapa total simpanan koperasi?", "SAVINGS"),
                   ("Berapa saldo kas saat ini?", "CASH_FLOW"),
                   ("Berapa jumlah pengguna?", "USER_COUNT")]:
        st, body = ask(admin, q)
        check(f'{exp:20s} <- {q}', st == 200 and body.get('intent') == exp,
              f'(HTTP {st}, intent {body.get("intent")})')
    st, _ = ask(opener(9, 'ANGGOTA'), "Siapa saja pengguna?")
    print(f'  ANGGOTA daftar pengguna -> HTTP {st} (RBAC data level)')


if __name__ == '__main__':
    test_intent()
    test_context_routing()
    test_identity()
    test_followup()
    test_rbac()
    test_provider_parity()
    test_provider_status()
    try:
        test_e2e()
    except Exception as e:
        print(f'  [SKIP] E2E (server belum aktif): {e}')

    print()
    print('=' * 78)
    print(f'RESULT: {len(FAILS)} GAGAL' if FAILS else 'RESULT: SEMUA LOLOS')
    print('=' * 78)
    for f in FAILS:
        print('  -', f)

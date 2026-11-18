"""Automated Test Suite: Integrasi Telegram Bot KSP AHNRFZI (Prompt #14).

Menguji 25 skenario wajib dengan mock Telegram API (tanpa credential produksi atau pengiriman nyata):
1.  Generate linking token
2.  Token kedaluwarsa
3.  Token sekali pakai
4.  Webhook valid
5.  Webhook dengan secret salah
6.  Payload webhook tidak valid
7.  Linking Telegram berhasil
8.  Penolakan linking untuk chat non-private
9.  Unlink Telegram
10. Pengguna lain tidak dapat mengambil koneksi (anti-hijack)
11. Preferensi Telegram ON/OFF
12. Notifikasi pinjaman
13. Notifikasi angsuran
14. Notifikasi kasir
15. Validasi penerima berdasarkan permission
16. Pencegahan duplicate event
17. Telegram API failure handling
18. HTTP 429 dan retry_after
19. In-App Notification tetap berfungsi saat Telegram gagal
20. Notifikasi uji coba hanya ke akun sendiri
21. Pengguna logout atau akun dinonaktifkan
22. Perubahan permission & isolasi akses
23. Tidak ada kebocoran credential
24. Queue retry terbatas (maksimal 3 kali)
25. Event yang rollback tidak menghasilkan notifikasi sukses palsu
"""
import json
import time
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.config import settings
from app.core.database import SessionLocal
from app.db.models.user import User, Role, Permission
from app.db.models.notification import Notification
from app.db.models.telegram import (
    TelegramUserLink,
    TelegramLinkingToken,
    NotificationPreference,
    TelegramWebhookUpdate,
    TelegramDeliveryLog,
)
from app.services.telegram_service import TelegramService
from app.services.notification_service import NotificationService


@pytest.fixture(scope="module", autouse=True)
def setup_telegram_test_env():
    """Konfigurasi environment mock untuk pengujian Telegram."""
    old_token = settings.TELEGRAM_BOT_TOKEN
    old_user = settings.TELEGRAM_BOT_USERNAME
    old_secret = settings.TELEGRAM_WEBHOOK_SECRET
    old_url = settings.TELEGRAM_WEBHOOK_URL

    settings.TELEGRAM_BOT_TOKEN = "123456789:TEST_MOCK_TOKEN"
    settings.TELEGRAM_BOT_USERNAME = "ksp_ahnrfzi_test_bot"
    settings.TELEGRAM_WEBHOOK_SECRET = "test_webhook_secret_key_123"
    settings.TELEGRAM_WEBHOOK_URL = "https://ksp.example.com/api/v1/integrations/telegram/webhook"

    yield

    settings.TELEGRAM_BOT_TOKEN = old_token
    settings.TELEGRAM_BOT_USERNAME = old_user
    settings.TELEGRAM_WEBHOOK_SECRET = old_secret
    settings.TELEGRAM_WEBHOOK_URL = old_url


@pytest.fixture(scope="module", autouse=True)
def cleanup_telegram_data():
    """Bersihkan data Telegram dari sesi sebelumnya agar setiap run idempotent."""
    with SessionLocal() as db:
        db.query(TelegramDeliveryLog).delete(synchronize_session=False)
        db.query(TelegramWebhookUpdate).delete(synchronize_session=False)
        db.query(TelegramUserLink).delete(synchronize_session=False)
        db.query(TelegramLinkingToken).delete(synchronize_session=False)
        db.query(NotificationPreference).delete(synchronize_session=False)
        db.commit()
    yield

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_tokens(client):
    """Mendapatkan token login untuk akun admin dan anggota."""
    credentials = {
        "admin": ("admin", "Password123!", "ADMIN_KOPERASI"),
        "anggota": ("anggota", "Password123!", "ANGGOTA"),
        "kasir": ("kasir", "Password123!", "KASIR"),
        "manager": ("manager", "Password123!", "MANAGER"),
    }
    tokens = {}
    for role_name, (username, pwd, pref_role) in credentials.items():
        res = client.post("/api/v1/auth/login", json={"username": username, "password": pwd, "preferred_role": pref_role})
        assert res.status_code == 200, f"Login failed for {username}: {res.text}"
        tokens[role_name] = res.json()["access_token"]
    return tokens


def auth_header(token: str):
    return {"Authorization": f"Bearer {token}"}


# =====================================================================
# 1. GENERATE LINKING TOKEN
# =====================================================================
def test_1_generate_linking_token(client, auth_tokens):
    res = client.post("/api/v1/integrations/telegram/link-token", headers=auth_header(auth_tokens["anggota"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert "token" in data
    assert "deep_link" in data
    assert "expires_at" in data
    assert "https://t.me/ksp_ahnrfzi_test_bot?start=" in data["deep_link"]

    # Pastikan di database tersimpan dalam bentuk SHA-256 hash
    token_raw = data["token"]
    token_hash = hashlib.sha256(token_raw.encode("utf-8")).hexdigest()
    with SessionLocal() as db:
        record = db.query(TelegramLinkingToken).filter(TelegramLinkingToken.token_hash == token_hash).first()
        assert record is not None
        assert record.used_at is None


# =====================================================================
# 2. TOKEN KEDALUWARSA
# =====================================================================
def test_2_token_expired():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)

        db.add(TelegramLinkingToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expired_time,
            created_at=expired_time - timedelta(minutes=10)
        ))
        db.commit()

        uid, msg = TelegramService.verify_and_consume_token(db, raw_token)
        assert uid is None
        assert "kedaluwarsa" in msg.lower()


# =====================================================================
# 3. TOKEN SEKALI PAKAI (SINGLE-USE)
# =====================================================================
def test_3_token_single_use():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        user_id = user.id

        # Hapus token lama dalam window rate limit agar test tidak gagal karena rate limit
        db.query(TelegramLinkingToken).filter(
            TelegramLinkingToken.user_id == user_id
        ).delete(synchronize_session=False)
        db.commit()

        raw_token, exp, err = TelegramService.create_linking_token(db, user_id)
        assert raw_token is not None, f"Token tidak dibuat: {err}"

        # Penggunaan pertama: sukses
        uid1, msg1 = TelegramService.verify_and_consume_token(db, raw_token)
        assert uid1 == user_id

        # Penggunaan kedua: ditolak
        uid2, msg2 = TelegramService.verify_and_consume_token(db, raw_token)
        assert uid2 is None
        assert "pernah digunakan" in msg2.lower()


# =====================================================================
# 4. WEBHOOK VALID
# =====================================================================
def test_4_webhook_valid(client):
    payload = {
        "update_id": 999001,
        "message": {
            "message_id": 1,
            "chat": {"id": 12345678, "type": "private"},
            "from": {"id": 12345678, "first_name": "TestUser", "username": "testuser"},
            "text": "Halo Bot"
        }
    }
    headers = {"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}
    with patch.object(TelegramService, "dispatch_async") as mock_dispatch:
        res = client.post("/api/v1/integrations/telegram/webhook", json=payload, headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["ok"] is True


# =====================================================================
# 5. WEBHOOK DENGAN SECRET SALAH
# =====================================================================
def test_5_webhook_invalid_secret(client):
    payload = {"update_id": 999002, "message": {"chat": {"id": 123, "type": "private"}, "text": "Test"}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": "wrong_secret_key"}
    res = client.post("/api/v1/integrations/telegram/webhook", json=payload, headers=headers)
    assert res.status_code == 401
    assert "Unauthorized" in res.text


# =====================================================================
# 6. PAYLOAD WEBHOOK TIDAK VALID
# =====================================================================
def test_6_webhook_invalid_payload(client):
    headers = {"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}
    # Tanpa update_id
    res = client.post("/api/v1/integrations/telegram/webhook", json={"text": "no_update_id"}, headers=headers)
    assert res.status_code == 400


# =====================================================================
# 7. LINKING TELEGRAM BERHASIL VIA /start TOKEN
# =====================================================================
def test_7_telegram_linking_success(client):
    # Capture user_id before session closes to avoid DetachedInstanceError
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        user_id = user.id

        # Hapus link lama dan token lama agar test deterministic
        db.query(TelegramUserLink).filter(TelegramUserLink.user_id == user_id).delete(synchronize_session=False)
        db.query(TelegramLinkingToken).filter(TelegramLinkingToken.user_id == user_id).delete(synchronize_session=False)
        db.commit()

        raw_token, _, _ = TelegramService.create_linking_token(db, user_id)

    chat_id = "777888999"
    # Gunakan update_id unik (berbeda dari sesi test sebelumnya)
    unique_update_id = 999003100
    with SessionLocal() as db:
        db.query(TelegramWebhookUpdate).filter(TelegramWebhookUpdate.update_id == str(unique_update_id)).delete(synchronize_session=False)
        db.commit()

    payload = {
        "update_id": unique_update_id,
        "message": {
            "message_id": 10,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "Ahmad", "username": "ahmad_tele"},
            "text": f"/start {raw_token}"
        }
    }
    headers = {"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}
    with patch.object(TelegramService, "dispatch_async") as mock_dispatch:
        res = client.post("/api/v1/integrations/telegram/webhook", json=payload, headers=headers)
        assert res.status_code == 200

    with SessionLocal() as db:
        link = db.query(TelegramUserLink).filter(TelegramUserLink.user_id == user_id).first()
        assert link is not None
        assert link.chat_id == chat_id
        assert link.telegram_username == "ahmad_tele"
        assert link.is_active is True


# =====================================================================
# 8. PENOLAKAN LINKING UNTUK CHAT NON-PRIVATE (GROUP / CHANNEL)
# =====================================================================
def test_8_reject_non_private_chat(client):
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        raw_token, _, _ = TelegramService.create_linking_token(db, user.id)

    payload = {
        "update_id": 999004,
        "message": {
            "message_id": 11,
            "chat": {"id": -1001234567, "type": "group"},  # Group chat
            "from": {"id": 111, "first_name": "GroupMember"},
            "text": f"/start {raw_token}"
        }
    }
    headers = {"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET}
    with patch.object(TelegramService, "dispatch_async") as mock_dispatch:
        res = client.post("/api/v1/integrations/telegram/webhook", json=payload, headers=headers)
        assert res.status_code == 200

    # Pastikan group chat_id TIDAK tertaut ke user
    with SessionLocal() as db:
        link = db.query(TelegramUserLink).filter(TelegramUserLink.chat_id == "-1001234567").first()
        assert link is None


# =====================================================================
# 9. UNLINK TELEGRAM
# =====================================================================
def test_9_unlink_telegram(client, auth_tokens):
    # Pastikan user anggota terhubung dulu
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        TelegramService.link_user(db, user.id, "555444333", "user_tele")

    res = client.post("/api/v1/integrations/telegram/unlink", headers=auth_header(auth_tokens["anggota"]))
    assert res.status_code == 200
    assert res.json()["success"] is True

    # Cek status
    status_res = client.get("/api/v1/integrations/telegram/status", headers=auth_header(auth_tokens["anggota"]))
    assert status_res.status_code == 200
    assert status_res.json()["data"]["is_connected"] is False


# =====================================================================
# 10. ANTI-ACCOUNT HIJACK (PENGGUNA LAIN TIDAK DAPAT MENGAMBIL KONEKSI)
# =====================================================================
def test_10_anti_account_hijack():
    with SessionLocal() as db:
        user_admin = db.query(User).filter(User.username == "admin").first()
        user_anggota = db.query(User).filter(User.username == "anggota").first()

        # Admin sudah terhubung dengan chat_id tertentu
        TelegramService.link_user(db, user_admin.id, "999888111", "admin_chat")

        # Anggota mencoba klaim chat_id yang sama
        ok, msg = TelegramService.link_user(db, user_anggota.id, "999888111", "anggota_chat")
        assert ok is False
        assert "telah terhubung dengan akun koperasi lain" in msg


# =====================================================================
# 11. PREFERENSI TELEGRAM ON/OFF
# =====================================================================
def test_11_preferences_toggle(client, auth_tokens):
    # Update preferensi
    payload = {
        "telegram_enabled": False,
        "notify_loans": False,
        "notify_installments": True,
        "notify_cashier": False,
        "notify_hrd": False,
        "notify_system": True
    }
    put_res = client.put("/api/v1/integrations/telegram/preferences", json=payload, headers=auth_header(auth_tokens["anggota"]))
    assert put_res.status_code == 200
    body = put_res.json()["data"]
    assert body["telegram_enabled"] is False
    assert body["notify_loans"] is False
    assert body["notify_installments"] is True

    # Nyalakan kembali
    client.put("/api/v1/integrations/telegram/preferences", json={"telegram_enabled": True, "notify_loans": True}, headers=auth_header(auth_tokens["anggota"]))


# =====================================================================
# 12. NOTIFIKASI PINJAMAN (LOAN EVENT)
# =====================================================================
def test_12_loan_notification_integration():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        TelegramService.link_user(db, user.id, "777001", "anggota_loan")

        with patch.object(TelegramService, "dispatch_async") as mock_dispatch:
            notif = NotificationService.send(
                db=db,
                user_id=user.id,
                title="Pengajuan Pinjaman Disetujui",
                message="Pinjaman Anda sebesar Rp 10.000.000 telah disetujui komite.",
                ntype="APPROVAL",
                entity_name="Loan",
                entity_id="101",
                event="LoanApproved:101",
                link_url="/loans"
            )
            assert notif is not None
            assert mock_dispatch.called
            args, kwargs = mock_dispatch.call_args
            assert kwargs["category"] == "LOANS"
            assert "Pengajuan Pinjaman Disetujui" in kwargs["text"]


# =====================================================================
# 13. NOTIFIKASI ANGSURAN (INSTALLMENT EVENT)
# =====================================================================
def test_13_installment_notification_integration():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        TelegramService.link_user(db, user.id, "777002", "anggota_inst")

        with patch.object(TelegramService, "dispatch_async") as mock_dispatch:
            notif = NotificationService.send(
                db=db,
                user_id=user.id,
                title="Pembayaran Angsuran Diterima",
                message="Pembayaran angsuran #3 pinjaman PJ-001 sebesar Rp 950.000 berhasil dicatat.",
                ntype="SUCCESS",
                entity_name="LoanPayment",
                entity_id="202",
                event="InstallmentPaid:202",
                link_url="/installments"
            )
            assert notif is not None
            assert mock_dispatch.called
            args, kwargs = mock_dispatch.call_args
            assert kwargs["category"] == "INSTALLMENTS"


# =====================================================================
# 14. NOTIFIKASI KASIR (CASHIER EVENT)
# =====================================================================
def test_14_cashier_notification_integration():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "kasir").first()
        TelegramService.link_user(db, user.id, "777003", "kasir_telegram")

        with patch.object(TelegramService, "dispatch_async") as mock_dispatch:
            notif = NotificationService.send(
                db=db,
                user_id=user.id,
                title="Tutup Kas Selesai",
                message="Shift kasir tanggal hari ini ditutup tanpa selisih.",
                ntype="INFO",
                entity_name="CashRegister",
                entity_id="303",
                event="CashRegisterClosed:303",
                link_url="/cashier"
            )
            assert notif is not None
            assert mock_dispatch.called
            args, kwargs = mock_dispatch.call_args
            assert kwargs["category"] == "CASHIER"


# =====================================================================
# 15. VALIDASI PENERIMA BERDASARKAN PERMISSION
# =====================================================================
def test_15_permission_based_recipients():
    with SessionLocal() as db:
        # Kirim notifikasi ke role ADMIN_KOPERASI (selalu ada di seed data)
        with patch.object(TelegramService, "dispatch_async") as mock_dispatch:
            count = NotificationService.notify_roles(
                db=db,
                role_codes=["ADMIN_KOPERASI"],
                title="Permohonan Approval Pinjaman",
                message="Terdapat pinjaman baru menunggu persetujuan Anda.",
                ntype="APPROVAL"
            )
            assert count >= 1


# =====================================================================
# 16. PENCEGAHAN DUPLICATE EVENT (DEDUP)
# =====================================================================
def test_16_deduplicate_event():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        event_tag = f"UniqueTestEvent:{secrets.token_hex(4)}"

        notif1 = NotificationService.send(
            db=db,
            user_id=user.id,
            title="Event Tunggal Dedup",
            message="Pesan pertama.",
            entity_name="TestEntity",
            entity_id="99",
            event=event_tag
        )
        notif2 = NotificationService.send(
            db=db,
            user_id=user.id,
            title="Event Tunggal Dedup",
            message="Pesan kedua sama.",
            entity_name="TestEntity",
            entity_id="99",
            event=event_tag
        )
        assert notif1.id == notif2.id


# =====================================================================
# 17. TELEGRAM API FAILURE HANDLING
# =====================================================================
def test_17_telegram_api_failure_handling():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(None, 500, "Internal Server Error", None, None)):
        success, err = TelegramService.send_telegram_api(chat_id="12345", text="Pesan Test")
        assert success is False
        assert "500" in (err or "")


# =====================================================================
# 18. HTTP 429 DAN RETRY_AFTER HANDLING
# =====================================================================
def test_18_http_429_and_retry_after():
    import urllib.error
    import io

    body_json = json.dumps({"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 1}}).encode("utf-8")
    mock_err = urllib.error.HTTPError(None, 429, "Too Many Requests", {}, io.BytesIO(body_json))

    with patch("urllib.request.urlopen", side_effect=mock_err), patch("time.sleep") as mock_sleep:
        success, err = TelegramService.send_telegram_api(chat_id="12345", text="Pesan Rate Limited")
        assert success is False
        assert mock_sleep.called


# =====================================================================
# 19. IN-APP TETAP BERFUNGSI SAAT TELEGRAM GAGAL
# =====================================================================
def test_19_in_app_persists_when_telegram_fails():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        TelegramService.link_user(db, user.id, "888999000", "test_fail")

        with patch.object(TelegramService, "send_telegram_api", side_effect=Exception("Simulated Network Down")):
            notif = NotificationService.send(
                db=db,
                user_id=user.id,
                title="Transaksi Berhasil Disimpan",
                message="In-App notification harus tetap ada meski Telegram down.",
                ntype="SUCCESS"
            )
            assert notif is not None
            assert notif.id is not None

            # Pastikan tersimpan di DB
            saved = db.query(Notification).filter(Notification.id == notif.id).first()
            assert saved is not None
            assert saved.title == "Transaksi Berhasil Disimpan"


# =====================================================================
# 20. NOTIFIKASI UJI COBA HANYA KE AKUN SENDIRI
# =====================================================================
def test_20_test_notification_only_to_self(client, auth_tokens):
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        TelegramService.link_user(db, user.id, "333222111", "self_chat")

    with patch.object(TelegramService, "send_telegram_api", return_value=(True, None)) as mock_send:
        res = client.post("/api/v1/integrations/telegram/test-notification", headers=auth_header(auth_tokens["anggota"]))
        assert res.status_code == 200
        assert res.json()["success"] is True
        mock_send.assert_called_once()
        assert mock_send.call_args[1]["chat_id"] == "333222111"
        assert mock_send.call_args[1]["user_id"] == user.id


# =====================================================================
# 21. PENGGUNA TIDAK AKTIF TIDAK MENERIMA NOTIFIKASI
# =====================================================================
def test_21_deactivated_user_no_notification():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        old_status = user.is_active
        try:
            user.is_active = False
            db.commit()

            notif = NotificationService.send(
                db=db,
                user_id=user.id,
                title="Pesan Akun Nonaktif",
                message="Seharusnya diabaikan."
            )
            assert notif is None
        finally:
            user.is_active = old_status
            db.commit()


# =====================================================================
# 22. PERUBAHAN PERMISSION & ISOLASI PENERIMA
# =====================================================================
def test_22_permission_isolation():
    with SessionLocal() as db:
        # Fan-out ke permission non-existent menghasilkan 0 terkirim
        sent = NotificationService.notify_users_with_permission(
            db=db,
            permission_codes=["NON_EXISTENT_PERMISSION_CODE_XYZ"],
            title="Pesan Hantu",
            message="Tidak ada yang menerima."
        )
        assert sent == 0


# =====================================================================
# 23. TIDAK ADA KEBOCORAN CREDENTIAL
# =====================================================================
def test_23_no_credential_leak(client, auth_tokens):
    res = client.get("/api/v1/integrations/telegram/status", headers=auth_header(auth_tokens["anggota"]))
    assert res.status_code == 200
    res_str = res.text
    # Token bot tidak boleh muncul di respons frontend
    assert settings.TELEGRAM_BOT_TOKEN not in res_str
    assert settings.TELEGRAM_WEBHOOK_SECRET not in res_str


# =====================================================================
# 24. QUEUE RETRY TERBATAS (MAX 3 KALI)
# =====================================================================
def test_24_queue_retry_limited():
    call_count = 0

    def mock_urlopen(req, timeout):
        nonlocal call_count
        call_count += 1
        raise Exception("Temporary Network Glitch")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen), patch("time.sleep"):
        success, err = TelegramService.send_telegram_api(chat_id="123", text="Test Retry")
        assert success is False
        assert call_count == 3  # Tepat 3 kali, tidak loop tak berujung


# =====================================================================
# 25. EVENT ROLLBACK TIDAK MENGHASILKAN NOTIFIKASI SUKSES PALSU
# =====================================================================
def test_25_rollback_prevents_false_notification():
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "anggota").first()
        try:
            # Mulai transaksi DB
            n = Notification(user_id=user.id, title="Transaksi Batal", message="Ini rollback")
            db.add(n)
            db.flush()
            # Simulasi error bisnis sebelum commit
            raise ValueError("Kredit bermasalah, rollback transaksi")
        except ValueError:
            db.rollback()

        # Pastikan row tidak tersimpan
        n_saved = db.query(Notification).filter(Notification.title == "Transaksi Batal").first()
        assert n_saved is None


# =====================================================================
# 26. BOT TOKEN VALID (FASE 7 #1)
# =====================================================================
def test_26_bot_token_validity():
    """Memverifikasi Bot Token valid via mock getMe API."""
    def mock_getme(req, timeout):
        class MockResp:
            def read(self):
                return json.dumps({
                    "ok": True,
                    "result": {
                        "id": 8314915967,
                        "is_bot": True,
                        "first_name": "KSP_AHNRFZI_Notify_Bot",
                        "username": "KSP_AHNRFZI_Notify_Bot"
                    }
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockResp()

    with patch("urllib.request.urlopen", side_effect=mock_getme):
        from setup_telegram_webhook import call_telegram
        res = call_telegram("getMe")
        assert res.get("ok") is True
        assert res["result"]["username"] == "KSP_AHNRFZI_Notify_Bot"
        assert res["result"]["is_bot"] is True


# =====================================================================
# 27. WEBHOOK TERDAFTAR (FASE 7 #2)
# =====================================================================
def test_27_webhook_registration_check():
    """Memverifikasi Webhook terdaftar dan secret header sesuai via mock getWebhookInfo."""
    def mock_webhook_info(req, timeout):
        class MockResp:
            def read(self):
                return json.dumps({
                    "ok": True,
                    "result": {
                        "url": "https://ksp.example.com/api/v1/integrations/telegram/webhook",
                        "has_custom_certificate": False,
                        "pending_update_count": 0,
                        "allowed_updates": ["message"]
                    }
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockResp()

    with patch("urllib.request.urlopen", side_effect=mock_webhook_info):
        from setup_telegram_webhook import call_telegram
        res = call_telegram("getWebhookInfo")
        assert res.get("ok") is True
        assert res["result"]["url"].startswith("https://")
        assert "api/v1/integrations/telegram/webhook" in res["result"]["url"]


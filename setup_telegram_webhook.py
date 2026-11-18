"""
Script: setup_telegram_webhook.py
Manajemen & Pendaftaran Webhook Telegram Bot KSP AHNRFZI secara aman.

Penggunaan:
  python setup_telegram_webhook.py status
  python setup_telegram_webhook.py set <TUNNEL_HTTPS_URL>
  python setup_telegram_webhook.py delete
  python setup_telegram_webhook.py <TUNNEL_HTTPS_URL>
"""
import sys
import os
import json
import urllib.request
import urllib.error
from urllib.parse import urlparse

# Load settings from app or fallback to .env directly
try:
    from app.core.config import settings
    BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
    WEBHOOK_SECRET = settings.TELEGRAM_WEBHOOK_SECRET
    CURRENT_WEBHOOK_URL = settings.TELEGRAM_WEBHOOK_URL
    API_BASE = getattr(settings, "TELEGRAM_API_BASE_URL", "https://api.telegram.org")
except Exception:
    BOT_TOKEN = ""
    WEBHOOK_SECRET = ""
    CURRENT_WEBHOOK_URL = ""
    API_BASE = "https://api.telegram.org"
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    BOT_TOKEN = line.split("=", 1)[1].strip()
                elif line.startswith("TELEGRAM_WEBHOOK_SECRET="):
                    WEBHOOK_SECRET = line.split("=", 1)[1].strip()
                elif line.startswith("TELEGRAM_WEBHOOK_URL="):
                    CURRENT_WEBHOOK_URL = line.split("=", 1)[1].strip()
                elif line.startswith("TELEGRAM_API_BASE_URL="):
                    API_BASE = line.split("=", 1)[1].strip()

WEBHOOK_PATH = "/api/v1/integrations/telegram/webhook"


def mask_token(token: str) -> str:
    """Mask credential token for safe logging/display."""
    if not token or len(token) < 8:
        return "***"
    return f"{token[:4]}****{token[-4:]}"


def call_telegram(method: str, data: dict = None) -> dict:
    """Safely call Telegram Bot API."""
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN belum terisi di .env atau konfigurasi server.")

    base_url = (API_BASE or "https://api.telegram.org").rstrip("/")
    url = f"{base_url}/bot{BOT_TOKEN}/{method}"
    body = json.dumps(data).encode("utf-8") if data else None
    headers = {"Content-Type": "application/json"} if body else {}

    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_content = e.read().decode("utf-8")
        try:
            return json.loads(error_content)
        except Exception:
            return {"ok": False, "error_code": e.code, "description": error_content}
    except Exception as ex:
        return {"ok": False, "description": str(ex)}


def validate_webhook_url(url: str) -> str:
    """Validate webhook URL meets security and Telegram requirements."""
    url = url.strip()
    if not url.startswith("https://"):
        raise ValueError("URL webhook WAJIB menggunakan protokol HTTPS yang aman (https://...)!")

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    # Cegah pendaftaran localhost ke Telegram webhook
    disallowed_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
    if hostname in disallowed_hosts or hostname.endswith(".local") or hostname.endswith(".internal"):
        raise ValueError(
            f"Telegram tidak dapat mengakses '{hostname}'. "
            "Jangan mendaftarkan localhost sebagai webhook Telegram. "
            "Gunakan tunnel HTTPS publik (Cloudflare Tunnel, localhost.run, dll) atau domain staging/produksi."
        )

    # Format akhir endpoint webhook
    base_url = f"https://{parsed.netloc}"
    if not url.endswith(WEBHOOK_PATH):
        return f"{base_url}{WEBHOOK_PATH}"
    return url


def show_status():
    """Tampilkan status Bot getMe dan getWebhookInfo secara aman."""
    print("=======================================================")
    print("  STATUS INTEGRASI TELEGRAM BOT KSP AHNRFZI")
    print("=======================================================")
    print(f"Token Configured: {'Ya (' + mask_token(BOT_TOKEN) + ')' if BOT_TOKEN else 'TIDAK'}")
    print(f"Secret Configured: {'Ya (' + mask_token(WEBHOOK_SECRET) + ')' if WEBHOOK_SECRET else 'TIDAK'}")
    print(f"Configured Webhook URL (.env): {CURRENT_WEBHOOK_URL or '(kosong)'}")

    print("\n[1] Memeriksa Telegram getMe API...")
    res_me = call_telegram("getMe")
    if res_me.get("ok"):
        bot = res_me["result"]
        print(f"  Status: OK")
        print(f"  Bot ID: {bot.get('id')}")
        print(f"  Username: @{bot.get('username')}")
        print(f"  Nama: {bot.get('first_name')}")
    else:
        print(f"  Status: GAGAL")
        print(f"  Detail: {res_me.get('description', 'Unknown error')}")
        return

    print("\n[2] Memeriksa Telegram getWebhookInfo API...")
    res_wh = call_telegram("getWebhookInfo")
    if res_wh.get("ok"):
        info = res_wh["result"]
        wh_url = info.get("url", "")
        print(f"  Status: OK")
        print(f"  Terdaftar di Telegram: {wh_url or '(Belum ada webhook terdaftar)'}")
        print(f"  Pending Update Count: {info.get('pending_update_count', 0)}")
        if info.get("last_error_message"):
            print(f"  Last Error ({info.get('last_error_date', '-')}): {info['last_error_message']}")
        else:
            print("  Last Error: Tidak ada (sehat)")
    else:
        print(f"  Status: GAGAL")
        print(f"  Detail: {res_wh.get('description')}")
    print("=======================================================\n")


def delete_webhook():
    """Hapus pendaftaran webhook dari Telegram."""
    print("Menghapus webhook Telegram...")
    res = call_telegram("deleteWebhook", {"drop_pending_updates": True})
    if res.get("ok"):
        print("  Webhook berhasil dihapus dari Telegram.")
    else:
        print(f"  Gagal menghapus webhook: {res.get('description')}")


def set_webhook(raw_url: str):
    """Daftarkan webhook baru ke Telegram dan update file .env."""
    webhook_url = validate_webhook_url(raw_url)
    print(f"\nTarget Webhook URL: {webhook_url}")

    # 1. Hapus webhook lama
    print("1. Menghapus konfigurasi webhook lama...")
    call_telegram("deleteWebhook", {"drop_pending_updates": True})

    # 2. Daftarkan webhook baru
    print("2. Mendaftarkan webhook baru ke Telegram...")
    payload = {
        "url": webhook_url,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    }
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET

    res = call_telegram("setWebhook", payload)
    if not res.get("ok"):
        print(f"\n[ERROR] Telegram menolak webhook: {res.get('description')}")
        sys.exit(1)

    print(f"   Sukses: {res.get('description', 'Webhook was set')}")

    # 3. Update file .env
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith("TELEGRAM_WEBHOOK_URL="):
                new_lines.append(f"TELEGRAM_WEBHOOK_URL={webhook_url}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"TELEGRAM_WEBHOOK_URL={webhook_url}")

        with open(env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
        print(f"3. File .env diperbarui dengan TELEGRAM_WEBHOOK_URL={webhook_url}")

    # 4. Verifikasi ulang
    print("4. Verifikasi status webhook...")
    verif = call_telegram("getWebhookInfo")
    if verif.get("ok"):
        v_res = verif["result"]
        print(f"   URL Aktif: {v_res.get('url')}")
        print(f"   Pending Updates: {v_res.get('pending_update_count', 0)}")
        if v_res.get("last_error_message"):
            print(f"   Perhatian: {v_res['last_error_message']}")
        else:
            print("   Status Webhook: AKTIF & SEHAT")

    print("\n=======================================================")
    print("  WEBHOOK TELEGRAM BERHASIL TERHUBUNG DENGAN APLIKASI!")
    print("=======================================================\n")


def main():
    if len(sys.argv) < 2:
        show_status()
        print("Gunakan:")
        print("  python setup_telegram_webhook.py status")
        print("  python setup_telegram_webhook.py set <TUNNEL_HTTPS_URL>")
        print("  python setup_telegram_webhook.py delete")
        return

    cmd = sys.argv[1].lower().strip()
    if cmd in ("status", "info"):
        show_status()
    elif cmd in ("delete", "remove"):
        delete_webhook()
    elif cmd in ("set", "register"):
        if len(sys.argv) < 3:
            print("[ERROR] Masukkan URL HTTPS tunnel. Contoh: python setup_telegram_webhook.py set https://abc.lhr.life")
            sys.exit(1)
        try:
            set_webhook(sys.argv[2])
        except Exception as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
    else:
        # Jika argumen langsung berupa URL
        try:
            set_webhook(sys.argv[1])
        except Exception as e:
            print(f"[ERROR] {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()

"""
Runner Tunnel HTTPS & Telegram Webhook KSP AHNRFZI.
Menggunakan SSH reverse tunnel (localhost.run) yang kompatibel dengan OpenSSH Windows native.
Secara otomatis mendaftarkan Webhook ke Telegram dan memperbarui .env.
"""
import sys
import os
import re
import time
import subprocess
import signal

# Tambahkan root path agar modul app dan setup_telegram_webhook dapat diimpor
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from setup_telegram_webhook import set_webhook, call_telegram, mask_token, BOT_TOKEN, WEBHOOK_SECRET


def is_server_running(port: int = 8000) -> bool:
    """Cek apakah server lokal aktif pada port tertentu."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run_tunnel():
    print("=======================================================")
    print("  KSP AHNRFZI - TELEGRAM TUNNEL & WEBHOOK RUNNER")
    print("=======================================================")

    if not is_server_running(8000):
        print("[PERINGATAN] Server FastAPI di http://127.0.0.1:8000 belum aktif.")
        print("Pastikan Anda sudah menjalankan start_server.bat terlebih dahulu.")
        print("Melanjutkan tunnel...\n")

    print("[1/3] Menghubungkan SSH tunnel ke localhost.run (port 8000)...")
    cmd = [
        "ssh.exe",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-R", "80:127.0.0.1:8000",
        "nokey@localhost.run"
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
    except Exception as e:
        print(f"[ERROR] Gagal menjalankan ssh.exe: {e}")
        sys.exit(1)

    tunnel_url = None
    start_time = time.time()
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.lhr\.life")

    print("[2/3] Menunggu alokasi domain publik HTTPS...")
    while time.time() - start_time < 20:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            clean_line = line.strip()
            # Cari URL https://*.lhr.life
            match = url_pattern.search(clean_line)
            if match:
                tunnel_url = match.group(0)
                break

    if not tunnel_url:
        print("[ERROR] Gagal mendapatkan URL tunnel dari localhost.run.")
        proc.kill()
        sys.exit(1)

    print(f"\n[OK] Tunnel HTTPS Aktif: {tunnel_url}")
    print("\n[3/3] Mendaftarkan Webhook ke Telegram...")
    try:
        set_webhook(tunnel_url)
    except Exception as e:
        print(f"[ERROR] Gagal mendaftarkan webhook: {e}")
        proc.kill()
        sys.exit(1)

    print("=======================================================")
    print("  TUNNEL & WEBHOOK AKTIF!")
    print(f"  URL: {tunnel_url}")
    print("  Pesan dari Telegram akan langsung diteruskan ke aplikasi.")
    print("  Tekan Ctrl+C untuk menghentikan tunnel.")
    print("=======================================================\n")

    try:
        # Loop menjaga process tetap hidup
        while proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nMenutup tunnel...")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        print("Tunnel dihentikan.")


if __name__ == "__main__":
    run_tunnel()

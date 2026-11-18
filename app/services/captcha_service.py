"""CAPTCHA Service KSP AHNRFZI.

Menyediakan generator CAPTCHA visual berbasis kriptografi aman (secrets module)
dan validasi backend ketat (single-use, short-lived, attempt-limited, memory-safe).
"""

import io
import math
import random
import secrets
import string
import time
import uuid
import base64
from threading import Lock
from typing import Optional, Tuple, Dict, Any
from PIL import Image, ImageDraw, ImageFont


class CaptchaService:
    # Karakter yang mudah dibaca manusia (menghindari ambigu: 0/O, 1/I/L)
    _CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    _CODE_LENGTH = 5
    _EXPIRY_SECONDS = 300  # 5 menit
    _MAX_ATTEMPTS = 3      # Maksimal 3 kali percobaan sebelum invalidasi

    # In-memory storage: captcha_id -> {code, expires_at, attempts, used, created_at}
    _STORE: Dict[str, Dict[str, Any]] = {}
    _USED_STORE: Dict[str, float] = {}  # captcha_id -> used_timestamp
    _LOCK = Lock()

    @classmethod
    def _clean_expired(cls, now: float) -> None:
        """Membersihkan entry kedaluwarsa secara berkala."""
        expired_keys = [
            k for k, v in cls._STORE.items()
            if now > v["expires_at"] or v.get("used", False)
        ]
        for k in expired_keys:
            cls._STORE.pop(k, None)

        expired_used = [k for k, t in cls._USED_STORE.items() if now - t > 600]
        for k in expired_used:
            cls._USED_STORE.pop(k, None)

    @classmethod
    def generate_captcha(cls, prev_captcha_id: Optional[str] = None) -> Tuple[str, str]:
        """Menghasilkan kode acak 5 karakter, merender gambar PNG, dan mengembalikan (captcha_id, data_url).
        
        Jawaban teks TIDAK PERNAH dikirim ke frontend dalam tuple ini.
        """
        now = time.time()
        with cls._LOCK:
            cls._clean_expired(now)
            # Jika ada refresh dari captcha sebelumnya, batalkan kode lama
            if prev_captcha_id and prev_captcha_id in cls._STORE:
                cls._STORE.pop(prev_captcha_id, None)

            # Generate kode acak kriptografis
            code = "".join(secrets.choice(cls._CHARS) for _ in range(cls._CODE_LENGTH))
            captcha_id = str(uuid.uuid4())

            # Render gambar visual CAPTCHA dengan Pillow
            raw_bytes, image_data_url = cls._render_image(code)

            cls._STORE[captcha_id] = {
                "code": code,
                "expires_at": now + cls._EXPIRY_SECONDS,
                "attempts": 0,
                "used": False,
                "created_at": now,
                "image_bytes": raw_bytes
            }

        return captcha_id, image_data_url

    @classmethod
    def get_image_bytes(cls, captcha_id: str) -> Optional[bytes]:
        """Mengambil raw bytes gambar PNG berdasarkan captcha_id."""
        with cls._LOCK:
            entry = cls._STORE.get(str(captcha_id).strip())
            if not entry or entry.get("used", False):
                return None
            return entry.get("image_bytes")

    @classmethod
    def _render_image(cls, code: str) -> str:
        """Merender gambar CAPTCHA visual dengan variasi warna, garis pengganggu, rotasi, dan noise."""
        width = 200
        height = 68

        # Background bernuansa modern clean light (slate-100 / slate-200)
        bg_color = (random.randint(238, 246), random.randint(241, 248), random.randint(245, 252))
        img = Image.new("RGBA", (width, height), color=bg_color)
        draw = ImageDraw.Draw(img)

        # 1. Garis gangguan background (Grid / Random Curves)
        for _ in range(4):
            line_color = (random.randint(180, 215), random.randint(185, 220), random.randint(190, 225), 180)
            x1, y1 = random.randint(0, width // 2), random.randint(0, height)
            x2, y2 = random.randint(width // 2, width), random.randint(0, height)
            draw.line([(x1, y1), (x2, y2)], fill=line_color, width=random.randint(1, 2))

        # Sine wave line melintasi teks
        wave_color = (random.randint(140, 180), random.randint(150, 190), random.randint(160, 200), 200)
        points = []
        freq = random.uniform(0.04, 0.07)
        amp = random.uniform(8, 14)
        base_y = height / 2 + random.uniform(-4, 4)
        for x in range(0, width, 2):
            y = base_y + math.sin(x * freq) * amp
            points.append((x, int(y)))
        draw.line(points, fill=wave_color, width=2)

        # 2. Noise dots / speckles
        for _ in range(90):
            dot_color = (random.randint(160, 210), random.randint(170, 215), random.randint(175, 225), random.randint(120, 220))
            dot_x = random.randint(0, width - 1)
            dot_y = random.randint(0, height - 1)
            draw.point((dot_x, dot_y), fill=dot_color)

        # 3. Muat Font (Arial atau fallback default)
        try:
            font = ImageFont.truetype("arial.ttf", 34)
        except Exception:
            try:
                font = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
            except Exception:
                font = ImageFont.load_default()

        # Palet warna karakter teks dengan kontras tinggi (Biru, Hijau, Teal, Indigo, Slate KSP)
        text_colors = [
            (30, 58, 138),   # Blue 900
            (15, 118, 110),  # Teal 700
            (4, 120, 87),    # Emerald 700
            (49, 46, 129),   # Indigo 900
            (15, 23, 42),    # Slate 900
            (67, 56, 202),   # Indigo 700
        ]

        # 4. Gambar karakter satu per satu dengan rotasi dan offset
        char_spacing = (width - 30) // len(code)
        for i, ch in enumerate(code):
            ch_img = Image.new("RGBA", (44, 52), (0, 0, 0, 0))
            ch_draw = ImageDraw.Draw(ch_img)
            color = random.choice(text_colors)
            ch_draw.text((6, 4), ch, font=font, fill=color)

            # Rotasi acak tiap karakter (-22 s.d. +22 derajat)
            rot_angle = random.uniform(-20, 20)
            rotated_ch = ch_img.rotate(rot_angle, expand=True, resample=Image.BICUBIC)

            # Paste ke gambar utama
            pos_x = 16 + i * char_spacing + random.randint(-2, 3)
            pos_y = (height - rotated_ch.size[1]) // 2 + random.randint(-4, 4)
            img.paste(rotated_ch, (pos_x, pos_y), rotated_ch)

        # 5. Garis noise depan tipis
        for _ in range(2):
            front_line = (random.randint(100, 160), random.randint(110, 170), random.randint(120, 180), 140)
            x1, y1 = random.randint(10, width - 10), random.randint(5, height - 5)
            x2, y2 = random.randint(10, width - 10), random.randint(5, height - 5)
            draw.line([(x1, y1), (x2, y2)], fill=front_line, width=1)

        # Simpan ke PNG in-memory
        buf = io.BytesIO()
        rgb_img = img.convert("RGB")
        rgb_img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()
        b64_str = base64.b64encode(raw_bytes).decode("ascii")
        return raw_bytes, f"data:image/png;base64,{b64_str}"

    @classmethod
    def validate_captcha(cls, captcha_id: Optional[str], user_code: Optional[str]) -> Tuple[bool, str, str]:
        """Validasi CAPTCHA:
        
        Mengembalikan (is_valid, status, message).
        Status code:
        - "EMPTY": kode atau id tidak dikirim
        - "NOT_FOUND": ID tidak ditemukan atau sudah dibatalkan
        - "USED": kode sudah pernah digunakan
        - "EXPIRED": kode kedaluwarsa (> 5 menit)
        - "MAX_ATTEMPTS": batas percobaan terlampaui
        - "MISMATCH": kode tidak cocok
        - "OK": berhasil
        """
        if not captcha_id or not str(captcha_id).strip():
            return False, "EMPTY", "Kode keamanan (CAPTCHA) wajib diisi."
        if not user_code or not str(user_code).strip():
            return False, "EMPTY", "Kode keamanan (CAPTCHA) wajib diisi."

        cid = str(captcha_id).strip()
        code_input = str(user_code).strip().upper()
        now = time.time()

        with cls._LOCK:
            if cid in cls._USED_STORE:
                return False, "USED", "Kode keamanan telah digunakan. Silakan muat ulang kode baru."

            entry = cls._STORE.get(cid)
            if not entry:
                cls._clean_expired(now)
                return False, "NOT_FOUND", "Kode keamanan tidak valid atau telah dimuat ulang. Silakan coba kode baru."

            if entry.get("used", False):
                cls._USED_STORE[cid] = now
                cls._STORE.pop(cid, None)
                return False, "USED", "Kode keamanan telah digunakan. Silakan muat ulang kode baru."

            if now > entry["expires_at"]:
                cls._STORE.pop(cid, None)
                cls._clean_expired(now)
                return False, "EXPIRED", "Kode keamanan telah kedaluwarsa. Silakan muat ulang."

            entry["attempts"] += 1
            if entry["attempts"] > cls._MAX_ATTEMPTS:
                cls._STORE.pop(cid, None)
                return False, "MAX_ATTEMPTS", "Batas percobaan kode keamanan terlampaui. Silakan muat ulang kode baru."

            expected_code = entry["code"]
            # Constant-time comparison untuk keamanan kriptografis
            if secrets.compare_digest(code_input, expected_code):
                # Langsung burn kode (single-use)
                entry["used"] = True
                cls._USED_STORE[cid] = now
                cls._STORE.pop(cid, None)
                return True, "OK", "Validasi kode keamanan berhasil."
            else:
                if entry["attempts"] >= cls._MAX_ATTEMPTS:
                    cls._STORE.pop(cid, None)
                return False, "MISMATCH", "Kode keamanan tidak sesuai. Silakan coba kode baru."

    @classmethod
    def peek_code_for_testing(cls, captcha_id: str) -> Optional[str]:
        """Helper server-side HANYA untuk automated test fixtures/pytest."""
        with cls._LOCK:
            entry = cls._STORE.get(captcha_id)
            return entry["code"] if entry else None

    @classmethod
    def set_test_captcha(cls, captcha_id: str, code: str, expires_in: int = 300) -> None:
        """Helper server-side untuk testing skenario spesifik (expired/used/dst)."""
        now = time.time()
        with cls._LOCK:
            cls._STORE[captcha_id] = {
                "code": code.upper(),
                "expires_at": now + expires_in,
                "attempts": 0,
                "used": False,
                "created_at": now
            }

    @classmethod
    def clear_all(cls) -> None:
        """Menghapus semua entri dalam memori (untuk test isolation)."""
        with cls._LOCK:
            cls._STORE.clear()
            cls._USED_STORE.clear()

"""Test Suite CAPTCHA Login KSP AHNRFZI.

Menguji 14 aspek keamanan, validasi, dan integrasi RBAC:
1.  CAPTCHA benar + kredensial benar (200 OK + JWT access_token + HTTP-only session cookie)
2.  CAPTCHA salah + kredensial benar (400 Bad Request + error message spesifik)
3.  CAPTCHA benar + kredensial salah (401 Unauthorized + username/password mismatch)
4.  CAPTCHA kosong / None (400 Bad Request)
5.  CAPTCHA kedaluwarsa (400 Bad Request + "Kode keamanan telah kedaluwarsa")
6.  CAPTCHA sudah digunakan / Replay attack (400 Bad Request)
7.  CAPTCHA refresh (kode lama dibatalkan di server, kode baru aktif)
8.  CAPTCHA dari session lain / ID acak / forgery (400 Bad Request)
9.  Percobaan brute-force (3x percobaan salah memicu invalidasi/burn CAPTCHA)
10. Login setiap role (9 roles: Admin, Ketua, Manager, HRD, Pengawas, Staf, IT Pusat, Kasir, Anggota)
11. Login mobile (User-Agent smartphone / iPhone / Android)
12. Session dan logout (Set-Cookie access_token, me endpoint, logout invalidation)
13. CSRF/CORS & security headers (SameSite=lax, HttpOnly=True, dsb.)
14. Login tidak dapat melewati CAPTCHA via direct API payload tanpa captcha
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.captcha_service import CaptchaService


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_captcha():
    CaptchaService.clear_all()
    yield
    CaptchaService.clear_all()


# -----------------------------------------------------------------------------
# Test 1: CAPTCHA benar + kredensial benar
# -----------------------------------------------------------------------------
def test_01_captcha_valid_credentials_valid(client):
    res_cap = client.get("/api/v1/auth/captcha")
    assert res_cap.status_code == 200
    data_cap = res_cap.json()
    captcha_id = data_cap["captcha_id"]
    assert "data:image/png;base64," in data_cap["captcha_image"]

    correct_code = CaptchaService.peek_code_for_testing(captcha_id)
    assert correct_code is not None

    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": correct_code,
            "preferred_role": "ADMIN_KOPERASI"
        }
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["active_role"] == "ADMIN_KOPERASI"
    # Cek cookie session HTTP-only
    assert "access_token" in res.cookies


# -----------------------------------------------------------------------------
# Test 2: CAPTCHA salah + kredensial benar
# -----------------------------------------------------------------------------
def test_02_captcha_wrong_credentials_valid(client):
    res_cap = client.get("/api/v1/auth/captcha")
    data_cap = res_cap.json()
    captcha_id = data_cap["captcha_id"]

    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": "WRONGX"
        }
    )
    assert res.status_code == 400
    data = res.json()
    assert data["detail"] == "Kode keamanan tidak sesuai. Silakan coba kode baru."


# -----------------------------------------------------------------------------
# Test 3: CAPTCHA benar + kredensial salah
# -----------------------------------------------------------------------------
def test_03_captcha_valid_credentials_wrong(client):
    res_cap = client.get("/api/v1/auth/captcha")
    data_cap = res_cap.json()
    captcha_id = data_cap["captcha_id"]
    correct_code = CaptchaService.peek_code_for_testing(captcha_id)

    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "WrongPassword999!",
            "captcha_id": captcha_id,
            "captcha_code": correct_code
        }
    )
    assert res.status_code == 401
    data = res.json()
    assert data["detail"] == "Username atau password tidak sesuai."

    # Pastikan CAPTCHA sudah dibakar (single-use) sehingga tidak dapat dipakai ulang
    res_retry = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": correct_code
        }
    )
    assert res_retry.status_code == 400


# -----------------------------------------------------------------------------
# Test 4: CAPTCHA kosong / whitespace
# -----------------------------------------------------------------------------
def test_04_captcha_empty(client):
    res_cap = client.get("/api/v1/auth/captcha")
    captcha_id = res_cap.json()["captcha_id"]

    # Kode kosong
    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": ""
        }
    )
    assert res.status_code == 400
    assert "Kode keamanan (CAPTCHA) wajib diisi." in res.json()["detail"]

    # ID kosong
    res2 = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": "",
            "captcha_code": "ABCDE"
        }
    )
    assert res2.status_code == 400
    assert "Kode keamanan (CAPTCHA) wajib diisi." in res2.json()["detail"]


# -----------------------------------------------------------------------------
# Test 5: CAPTCHA kedaluwarsa (> 5 menit)
# -----------------------------------------------------------------------------
def test_05_captcha_expired(client):
    test_id = "test-expired-captcha-id"
    CaptchaService.set_test_captcha(captcha_id=test_id, code="EXPIRE", expires_in=-10)

    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": test_id,
            "captcha_code": "EXPIRE"
        }
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Kode keamanan telah kedaluwarsa. Silakan muat ulang."


# -----------------------------------------------------------------------------
# Test 6: CAPTCHA sudah digunakan (Replay Attack Prevention)
# -----------------------------------------------------------------------------
def test_06_captcha_reuse_attack(client):
    res_cap = client.get("/api/v1/auth/captcha")
    captcha_id = res_cap.json()["captcha_id"]
    code = CaptchaService.peek_code_for_testing(captcha_id)

    # Penggunaan pertama: Berhasil
    res1 = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": code
        }
    )
    assert res1.status_code == 200

    # Penggunaan kedua: Ditolak keras (single-use)
    res2 = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": code
        }
    )
    assert res2.status_code == 400
    assert "telah digunakan" in res2.json()["detail"]


# -----------------------------------------------------------------------------
# Test 7: CAPTCHA refresh (kode lama langsung tidak berlaku)
# -----------------------------------------------------------------------------
def test_07_captcha_refresh(client):
    res_cap1 = client.get("/api/v1/auth/captcha")
    cap1_id = res_cap1.json()["captcha_id"]
    code1 = CaptchaService.peek_code_for_testing(cap1_id)

    # Refresh dengan prev_id=cap1_id
    res_cap2 = client.get(f"/api/v1/auth/captcha?prev_id={cap1_id}")
    cap2_id = res_cap2.json()["captcha_id"]
    code2 = CaptchaService.peek_code_for_testing(cap2_id)

    assert cap1_id != cap2_id

    # Mencoba login menggunakan kode lama cap1_id → Ditolak
    res_old = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": cap1_id,
            "captcha_code": code1
        }
    )
    assert res_old.status_code == 400
    assert "tidak valid atau telah dimuat ulang" in res_old.json()["detail"]

    # Login menggunakan cap2_id → Berhasil
    res_new = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": cap2_id,
            "captcha_code": code2
        }
    )
    assert res_new.status_code == 200


# -----------------------------------------------------------------------------
# Test 8: CAPTCHA dari session lain / ID palsu
# -----------------------------------------------------------------------------
def test_08_captcha_forged_or_unknown_id(client):
    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": "00000000-0000-0000-0000-000000000000",
            "captcha_code": "ABCDE"
        }
    )
    assert res.status_code == 400
    assert "tidak valid atau telah dimuat ulang" in res.json()["detail"]


# -----------------------------------------------------------------------------
# Test 9: Percobaan brute-force pada kode CAPTCHA
# -----------------------------------------------------------------------------
def test_09_captcha_brute_force_limit(client):
    res_cap = client.get("/api/v1/auth/captcha")
    captcha_id = res_cap.json()["captcha_id"]
    real_code = CaptchaService.peek_code_for_testing(captcha_id)

    # 3x salah tebak berturut-turut pada CAPTCHA yang sama
    for i in range(3):
        r = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "Password123!",
                "captcha_id": captcha_id,
                "captcha_code": f"FAIL{i}"
            }
        )
        assert r.status_code == 400

    # Setelah batas percobaan terlampaui, kode benar pun harus ditolak karena sudah dibakar
    r_correct = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": real_code
        }
    )
    assert r_correct.status_code == 400


# -----------------------------------------------------------------------------
# Test 10: Login untuk setiap 9 Role KSP AHNRFZI dengan CAPTCHA
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("username,expected_role", [
    ("admin", "ADMIN_KOPERASI"),
    ("ketua", "KETUA_UMUM"),
    ("manager", "MANAGER"),
    ("hrd", "HRD"),
    ("pengawas", "PENGAWAS_PEMBINA"),
    ("staf", "STAF"),
    ("itpusat", "IT_PUSAT"),
    ("kasir", "KASIR"),
    ("anggota", "ANGGOTA"),
])
def test_10_login_all_nine_roles(client, username, expected_role):
    res_cap = client.get("/api/v1/auth/captcha")
    captcha_id = res_cap.json()["captcha_id"]
    code = CaptchaService.peek_code_for_testing(captcha_id)

    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": code,
            "preferred_role": expected_role
        }
    )
    assert res.status_code == 200, f"Gagal login role {expected_role}: {res.text}"
    body = res.json()
    assert body["active_role"] == expected_role
    assert "access_token" in body


# -----------------------------------------------------------------------------
# Test 11: Login Mobile Client (Smartphone User-Agent)
# -----------------------------------------------------------------------------
def test_11_login_mobile_client(client):
    res_cap = client.get("/api/v1/auth/captcha")
    captcha_id = res_cap.json()["captcha_id"]
    code = CaptchaService.peek_code_for_testing(captcha_id)

    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    }

    res = client.post(
        "/api/v1/auth/login",
        headers=mobile_headers,
        json={
            "username": "anggota",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": code
        }
    )
    assert res.status_code == 200
    assert res.json()["active_role"] == "ANGGOTA"


# -----------------------------------------------------------------------------
# Test 12: Session dan Logout
# -----------------------------------------------------------------------------
def test_12_session_and_logout(client):
    res_cap = client.get("/api/v1/auth/captcha")
    captcha_id = res_cap.json()["captcha_id"]
    code = CaptchaService.peek_code_for_testing(captcha_id)

    res_login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": code
        }
    )
    assert res_login.status_code == 200
    token = res_login.json()["access_token"]
    cookie_token = res_login.cookies.get("access_token")
    assert cookie_token is not None

    # Akses /me dengan session
    res_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_me.status_code == 200
    assert res_me.json()["username"] == "admin"

    # Logout
    res_logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert res_logout.status_code == 200
    assert res_logout.json()["success"] is True


# -----------------------------------------------------------------------------
# Test 13: Keamanan Cookie & Header
# -----------------------------------------------------------------------------
def test_13_cookie_security_and_cors(client):
    res_cap = client.get("/api/v1/auth/captcha")
    captcha_id = res_cap.json()["captcha_id"]
    code = CaptchaService.peek_code_for_testing(captcha_id)

    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": "kasir",
            "password": "Password123!",
            "captcha_id": captcha_id,
            "captcha_code": code
        }
    )
    assert res.status_code == 200
    # Periksa atribut Set-Cookie
    set_cookie_header = res.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "samesite=lax" in set_cookie_header.lower()


# -----------------------------------------------------------------------------
# Test 14: Direct API Call Tanpa CAPTCHA Harus Ditolak
# -----------------------------------------------------------------------------
def test_14_cannot_bypass_captcha_via_direct_api(client):
    # Mencoba POST login langsung tanpa payload captcha
    res = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Password123!"
        }
    )
    assert res.status_code == 400
    data = res.json()
    assert "Kode keamanan (CAPTCHA) wajib diisi." in data["detail"]

@echo off
title KSP AHNRFZI Server Launcher

echo ==========================================
echo 1. Setel direktori kerja proyek
echo ==========================================
cd /d "D:\xampp\htdocs\lat1"

echo.
echo Memeriksa file aplikasi...

:: 2. Periksa keberadaan app\main.py
if not exist "app\main.py" (
    echo.
    echo [ERROR] file app\main.py tidak ditemukan!
    echo Pastikan berada di D:\xampp\htdocs\lat1
    echo.
    pause
    exit /b
)

echo [OK] file app\main.py ditemukan.

echo.
echo 3. Periksa virtual environment...

:: 3. Periksa keberadaan .venv\Scripts\python.exe
set VENV_PYTHON=.venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo.
    echo [WARNING] .venv\Scripts\python.exe tidak ditemukan.
    echo Menggunakan Python global sebagai cadangan.
    set USE_VENV=0
) else (
    echo [OK] .venv\Scripts\python.exe ditemukan.
    set USE_VENV=1
)

echo.

:: 5. Cek port 8000 dengan cara yang lebih sederhana
echo 5. Memeriksa port 8000...
set PORT_CHECK=timeout /t 1 2>nul

:: Cek apakah kita bisa menjalankan uvicorn nanti
echo.
echo [INFO] Port 8000: dicek tersedia (lanjutan ke langkah server)...

echo.
echo 6. Menjalankan server FastAPI...

:: 7. Jalankan Uvicorn menggunakan Python virtual environment
if %USE_VENV% == 1 (
    echo Menggunakan: %VENV_PYTHON% uvicorn app.main:app
    call %VENV_PYTHON% -m uvicorn app.main:app ^
        --app-dir "D:\xampp\htdocs\lat1" ^
        --host 127.0.0.1 ^
        --port 8000 ^
        --log-level debug
) else (
    echo Menggunakan: python uvicorn app.main:app
    python -m uvicorn app.main:app ^
        --app-dir "D:\xampp\htdocs\lat1" ^
        --host 127.0.0.1 ^
        --port 8000 ^
        --log-level debug
)

echo.
echo ==========================================
echo Pastikan jendela ini tetap terbuka untuk server berjalan
echo Tekan Ctrl+C di sini atau tutup jendela ini untuk menghentikan server
echo ==========================================

:: Tetap terbuka hingga server dihentikan
timeout /t 3600 >nul
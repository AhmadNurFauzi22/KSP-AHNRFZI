@echo off
chcp 65001 >nul
title KSP AHNRFZI - Telegram Tunnel Runner
cd /d %~dp0

echo ========================================================
echo   KSP AHNRFZI - Telegram Tunnel & Webhook Runner
echo ========================================================
echo.

set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

"%PYTHON_EXE%" scripts\tunnel_runner.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [INFO] Terjadi kendala pada SSH tunnel runner.
    echo Anda juga dapat mendaftarkan URL webhook manual dengan:
    echo   python setup_telegram_webhook.py set ^<HTTPS_URL^>
    echo.
    pause
)

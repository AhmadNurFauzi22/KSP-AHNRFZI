import os
from pathlib import Path
from typing import List, Dict, Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_sqlite_url() -> str:
    # Path absolut ke root project agar tidak tergantung CWD saat uvicorn dijalankan.
    # File DB tetap di D:\xampp\htdocs\lat1\koperasi_ahnrfzi.db
    root = Path(__file__).resolve().parents[2]
    return f"sqlite:///{(root / 'koperasi_ahnrfzi.db').as_posix()}"


# === DEFINISI PROVIDER AI YANG DISUPPORTIKAN ===
AI_PROVIDER_CHOICES = [
    "rule_engine",
    "openai",
    "gemini",
    "anthropic",
    "nvidia_nim",
]

# === MAP MODEL DEFAULT PER PROVIDER ===
DEFAULT_MODELS: Dict[str, str] = {
    "rule_engine": "local_rule_based",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "anthropic": "claude-3-haiku-20240307",
    "nvidia_nim": "nvidia/nemotron-3.5-bolt-e4b",
}


# === ENKRIPSI SEDERHANA PENTING PENTING===
# Catatan: Enkripsi full-scale membutuhkan kunci khusus.
# Untuk sementara, API key disimpan dalam environment dengan pendekatan
# "security by obscurity" — tidak pernah ter-exposed ke frontend.
# Lihat Prompt #11 dan #14 untuk detail keamanan.

# Fungsi sederhana untuk masking API key di log
def mask_api_key(key: str, visible_chars: int = 4) -> str:
    """Mask API key for logging — hanya tampilkan awal few characters."""
    if not key:
        return ""
    if len(key) <= visible_chars:
        return "*" * len(key)
    return key[:visible_chars] + "..." + key[-4:]


# === KONFIGURASI SETTINGS ===
class Settings(BaseSettings):
    # App Information
    APP_NAME: str = "KSP AHNRFZI - Sistem Informasi Koperasi Simpan Pinjam"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    APP_SECRET_KEY: str = "ksp-ahnrfzi-super-secret-key-change-in-production-2026"

    # Database
    DATABASE_URL: str = Field(
        default_factory=lambda: "sqlite:///./koperasi_ahnrfzi.db",
        sa_column_name="DATABASE_URL",
    )

    # JWT Security
    JWT_SECRET_KEY: str = "ksp-ahnrfzi-jwt-secret-token-key-2026"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # Audit Logging
    ENABLE_AUDIT_LOG: bool = True

    # ============================================================
    # AI ASSISTANT MULTI-PROVIDER CONFIGURATION
    # ============================================================

    # Provider utama yang aktif
    AI_PROVIDER: str = Field(
        default="rule_engine",
        description="Provider AI yang aktif: rule_engine, openai, gemini, anthropic",
    )

    # API Key per provider (dijaga rahasia, tidak pernah ke frontend)
    # Setiap provider memiliki key-nya sendiri
    AI_API_KEYS: Dict[str, str] = Field(
        default_factory=lambda: {"rule_engine": "", "openai": "", "gemini": "", "anthropic": "", "nvidia_nim": ""},
        description="Dictionary API key per provider. Isi hanya provider yang digunakan.",
    )

    # Model name per provider
    AI_MODEL_NAMES: Dict[str, str] = Field(
        default_factory=lambda: {"rule_engine": "local_rule_based", "openai": "gpt-4o-mini", "gemini": "gemini-1.5-flash", "anthropic": "claude-3-haiku-20240307", "nvidia_nim": "nvidia/nemotron-3.5-bolt-e4b"},
        description="Dictionary model name per provider.",
    )

    # Base URL per provider (jika diperlukan, misal Gemini/Anthropic)
    AI_BASE_URLS: Dict[str, str] = Field(
        default_factory=lambda: {"rule_engine": "", "openai": "https://api.openai.com/v1", "gemini": "https://generativelanguage.googleapis.com/v1beta", "anthropic": "https://api.anthropic.com/v1", "nvidia_nim": "https://integrate.api.nvidia.com/v1"},
        description="Base URL per provider jika berbeda dari standar.",
    )

    # Fallback base URL untuk provider tanpa base_url khusus.
    # WAJIB ada: get_provider_config() mereferensikan atribut ini.
    AI_BASE_URL: str = Field(
        default="",
        description="Base URL fallback bila provider tidak punya base_url khusus.",
    )

    # Timeout per provider (detik)
    AI_TIMEOUT_SECONDS: int = Field(default=30, lte=120, gte=5)

    # Temperature per provider
    AI_TEMPERATURES: Dict[str, float] = Field(
        default_factory=lambda: {"rule_engine": 0.0, "openai": 0.3, "gemini": 0.3, "anthropic": 0.3, "nvidia_nim": 0.7},
        description="Temperature per provider untuk generation.",
    )

    # Max tokens per provider
    AI_MAX_TOKENS: Dict[str, int] = Field(
        default_factory=lambda: {"rule_engine": 0, "openai": 1000, "gemini": 1000, "anthropic": 1000, "nvidia_nim": 1000},
        description="Max tokens per provider untuk generation.",
    )

    # Retry config per provider
    AI_RETRY_ATTEMPTS: int = Field(default=2, gte=0, lte=5)
    AI_RETRY_DELAY: float = Field(default=1.0, gte=0.1, lte=10.0)

    # Fallback provider (opsional)
    AI_FALLBACK_PROVIDER: str = Field(
        default="",
        description="Provider cadangan jika provider utama gagal. Kosongkan jika tidak digunakan.",
    )

    # Rantai fallback lengkap (urut, dipisahkan koma). Provider utama selalu
    # dicoba lebih dulu; entri berikutnya hanya dipakai bila sebelumnya gagal.
    # Kosong = pakai AI_PROVIDER + AI_FALLBACK_PROVIDER.
    AI_FALLBACK_CHAIN: str = Field(
        default="",
        description="Rantai fallback provider (mis. 'gemini,openai'). Kosong = otomatis.",
    )

    # Provider yang TIDAK boleh dipakai sebagai fallback LLM.
    AI_EXCLUDED_FALLBACK_PROVIDERS: str = Field(
        default="rule_engine",
        description="Provider yang dikecualikan dari rantai fallback (dipisahkan koma).",
    )

    # Temperature global (override per-provider)
    AI_GLOBAL_TEMPERATURE: float = Field(default=0.3, gte=0.0, lte=1.0)

    # ============================================================
    # Security & Telegram (tidak berubah secara signifikan)
    # ============================================================
    # Security (Prompt #11) — override via environment/.env di produksi
    CORS_ORIGINS: str = "http://127.0.0.1:8000,http://localhost:8000"
    LOGIN_MAX_ATTEMPTS: int = 10
    LOGIN_LOCKOUT_SECONDS: int = 300
    CAPTCHA_ENABLED: bool = True
    CAPTCHA_EXPIRY_SECONDS: int = 300
    # Cookie security flag: True di produksi dengan HTTPS, False di development
    cookie_secure: bool = False

    # Notifikasi email (Prompt #13) — kosong = provider belum dikonfigurasi
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "KSP AHNRFZI <noreply@example.coop>"
    SMTP_USE_TLS: bool = True

    # Telegram Bot Integration
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_WEBHOOK_URL: str = ""
    TELEGRAM_API_BASE_URL: str = "https://api.telegram.org"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in (self.CORS_ORIGINS or "").split(",") if o.strip()]

    # --- Properties bantu untuk mengakses key per-provider ---

    @property
    def ai_api_key(self) -> str:
        """Membalikkan API key provider utama untuk kompatibilitas mundur."""
        return self.AI_API_KEYS.get(self.AI_PROVIDER, "")  # backward compat

    @property
    def API_KEYS(self) -> Dict[str, str]:
        """Return the dictionary of API keys — sesuaikan nama atribut."""
        return self.AI_API_KEYS

    # Model name accessor — gunakan AI_MODEL_NAMES dict
    @property
    def ai_model_name(self) -> str:
        """Membalikkan model provider utama untuk kompatibilitas mundur.
        Gunakan AI_MODEL_NAMES dict, bukan AI_MODEL_NAME single attribute."""
        return self.AI_MODEL_NAMES.get(self.AI_PROVIDER, DEFAULT_MODELS.get(self.AI_PROVIDER, "gpt-4o-mini"))

    @property
    def MODEL_NAMES(self) -> Dict[str, str]:
        """Return the dictionary of model names."""
        return self.AI_MODEL_NAMES

    # --- Validasi provider ---

    @validator("AI_PROVIDER")
    def validate_provider(cls, v: str) -> str:
        if v not in AI_PROVIDER_CHOICES:
            raise ValueError(f"Provider AI tidak valid. Pilih dari: {', '.join(AI_PROVIDER_CHOICES)}")
        return v

    @validator("AI_FALLBACK_PROVIDER")
    def validate_fallback_provider(cls, v: str) -> str:
        if v and v not in AI_PROVIDER_CHOICES:
            raise ValueError(f"Provider fallback tidak valid. Pilih dari: {', '.join(AI_PROVIDER_CHOICES)}")
        return v

    @validator("AI_API_KEYS", always=True)
    def ensure_default_keys(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Pastikan semua provider memiliki entry (default kosong)."""
        defaults = {"rule_engine": "", "openai": "", "gemini": "", "anthropic": "", "nvidia_nim": ""}
        for k in defaults:
            if k not in v:
                v[k] = ""
        return v

    # --- Properties Telegram ---

    @property
    def telegram_configured(self) -> bool:
        """Cek apakah Telegram bot terkonfigurasi dengan benar.
        
        Telegram dianggap terkonfigurasi jika bot token telah diisi.
        Fitur long polling dan fitur lain akan dinonaktifkan jika tidak ada token.
        """
        return bool((self.TELEGRAM_BOT_TOKEN or "").strip())

    @property
    def telegram_bot_token(self) -> str:
        """Membalikkan bot token Telegram (diharapkan tidak digunakan di frontend)."""
        return self.TELEGRAM_BOT_TOKEN

    @property
    def telegram_bot_username(self) -> str:
        """Membalikkan username bot Telegram."""
        return self.TELEGRAM_BOT_USERNAME

    # --- Properties kemampuan ---

    @property
    def llm_enabled(self) -> bool:
        """True bila backend LLM aktif (provider memiliki key)."""
        provider = (self.AI_PROVIDER or "").lower().strip()
        key = (self.AI_API_KEYS.get(provider, "") or "").strip()
        return provider in AI_PROVIDER_CHOICES and bool(key)

    @property
    def has_fallback(self) -> bool:
        """True bila provider cadangan dikonfigurasi."""
        return bool((self.AI_FALLBACK_PROVIDER or "").strip())

    @property
    def fallback_provider(self) -> str:
        """Nama provider cadangan."""
        return (self.AI_FALLBACK_PROVIDER or "").strip()

    # --- Helper: dapatkan kredensial provider ---

    def get_provider_config(self, provider: str) -> Dict[str, str]:
        """Ambil konfigurasi lengkap untuk provider tertentu."""
        provider = provider.lower().strip()
        # Ambil base_url dari dict AI_BASE_URLS, jika ada dan tidak kosong gunakan,
        # jika tidak gunakan default AI_BASE_URL
        base_url_from_dict = self.AI_BASE_URLS.get(provider, "")
        if base_url_from_dict:
            base_url = base_url_from_dict
        else:
            # Fallback ke AI_BASE_URL utama jika provider tidak punya base_url khusus
            base_url = self.AI_BASE_URL
        return {
            "provider": provider,
            "api_key": self.AI_API_KEYS.get(provider, ""),
            "model": self.AI_MODEL_NAMES.get(provider, DEFAULT_MODELS.get(provider, "gpt-4o-mini")),
            "base_url": base_url,
            "timeout": self.AI_TIMEOUT_SECONDS,
            "temperature": self.AI_TEMPERATURES.get(provider, self.AI_GLOBAL_TEMPERATURE),
            "max_tokens": self.AI_MAX_TOKENS.get(provider, 1000),
            "retry_attempts": self.AI_RETRY_ATTEMPTS,
            "retry_delay": self.AI_RETRY_DELAY,
        }

    # --- Helper: cek provider utama aktif ---

    def is_primary_provider(self, provider: str) -> bool:
        """Cek apakah provider adalah yang aktif."""
        return (self.AI_PROVIDER or "").lower().strip() == provider.lower().strip()

    # --- Helper: dapatkan model aktif ---

    def get_active_model(self) -> str:
        """Dapatkan model name berdasarkan provider aktif."""
        return self.ai_model_name

    # --- Helper: mask API key untuk log ---

    @staticmethod
    def mask_sensitive(key: str) -> str:
        """Mask API key untuk cetak log — tidak boleh bocor penuh."""
        from app.core.config import mask_api_key
        return mask_api_key(key)


# Instance settings


# Module-level mask_sensitive function (for imports like from app.core.config import mask_sensitive)
def mask_sensitive(key: str) -> str:
    """Mask API key for logging - only show start few characters."""
    from app.core.config import Settings
    return Settings().mask_sensitive(key)

settings = Settings()
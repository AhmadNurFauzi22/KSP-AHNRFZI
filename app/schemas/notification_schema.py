"""Schema untuk notifikasi WhatsApp Fonnte."""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, validator


# ============================================================================
# REQUEST SCHEMA: Kirim pesan WhatsApp
# ============================================================================

class FonnteSendRequest(BaseModel):
    """Request untuk mengirim pesan WhatsApp melalui Fonnte."""

    phone_number: str = Field(
        ...,
        description="Nomor telepon pengirim tujuan dalam format internasional",
        example="81234567890",
    )
    message: str = Field(
        ...,
        description="Isi pesan WhatsApp",
        min_length=1,
        example="Pembayaran angsuran berhasil dicatat.",
    )
    reference_id: Optional[str] = Field(
        None,
        description="ID referensi transaksi/event untuk idempotensi",
        example="deposit-20261105-001",
    )

    @validator("phone_number")
    def validate_phone_number(cls, v):
        """Validasi format nomor telepon."""
        digits = "".join(filter(str.isdigit, v))
        if not digits:
            raise ValueError("Nomor telepon tidak boleh kosong")
        if len(digits) < 7:
            raise ValueError("Nomor telepon terlalu pendek")
        return v


# ============================================================================
# RESPONSE SCHEMA: Respons Fonnte
# ============================================================================

class FonnteSuccessResponse(BaseModel):
    """Respons sukses dari Fonnte API."""

    status: str = Field(..., description="Status pengiriman", example="success")
    message_id: Optional[str] = Field(
        None, description="ID pesan dari Fonnte", example="msg-123456"
    )
    sent: bool = Field(
        False, description="Apakah pesan berhasil dikirim", example=True
    )
    cost: Optional[float] = Field(
        None, description="Biaya pengiriman", example=0.0
    )
    reference_id: Optional[str] = Field(
        None, description="Referensi dari request", example="deposit-20261105-001"
    )


class FonnteErrorResponse(BaseModel):
    """Respons error dari Fonnte API."""

    status: str = Field(..., description="Status pengiriman", example="failed")
    error: str = Field(..., description="Pesan error", example="Invalid phone number")
    error_code: Optional[str] = Field(
        None, description="Kode error Fonnte", example="INVALID_NUMBER"
    )
    reference_id: Optional[str] = Field(
        None, description="Referensi dari request", example="deposit-20261105-001"
    )


# ============================================================================
# NOTIFICATION TYPE CONSTANTS
# ============================================================================

NOTIF_SIM_PAYMENT_CONFIRMATION = "sim_payment_confirmation"
NOTIF_LOAN_APPROVAL = "loan_approval"
NOTIF_LOAN_REJECTION = "loan_rejection"
NOTIF_LOAN_READY_DISBURSE = "loan_ready_disbursement"
NOTIF_INSTALLMENT_REMINDER = "installment_reminder"
NOTIF_INSTALLMENT_DUE_Soon = "installment_due_soon"
NOTIF_INSTALLMENT_OVERDUE = "installment_overdue"
NOTIF_LOAN_FULLY_PAID = "loan_fully_paid"
NOTIF_CASHIER_TRANSACTION = "cashier_transaction"
NOTIF_SYSTEM_ALERT = "system_alert"
NOTIF_ADMIN_NOTIFICATION = "admin_notification"


# ============================================================================
# NOTIFICATION CONTEXT DATA
# ============================================================================

class NotificationContext(BaseModel):
    """Context data untuk memformat template pesan."""

    nama_anggota: str = ""
    nomor_pinjaman: str = ""
    tanggal_pembayaran: str = ""
    nominal_pembayaran: float = 0.0
    sisa_tagihan: float = 0.0
    tanggal_jatuh_tempo: str = ""
    nominal_tagihan: float = 0.0
    tanggal_persetujuan: str = ""
    nominal_disetujui: float = 0.0
    # Field tambahan untuk kasir
    transaksi_count: int = 0
    total_masuk: float = 0.0
    total_keluar: float = 0.0
    saldo: float = 0.0


# ============================================================================
# NOTIFICATION HISTORY SCHEMA (untuk logging/riwayat)
# ============================================================================

class NotificationHistoryCreate(BaseModel):
    """Schema untuk mencatat riwayat pengiriman notifikasi."""

    notification_type: str = Field(
        ...,
        description="Jenis notifikasi",
        example=NOTIF_SIM_PAYMENT_CONFIRMATION,
    )
    phone_number: str = Field(
        ...,
        description="Nomor telepon tujuan",
        example="81234567890",
    )
    message: str = Field(
        ...,
        description="Isi pesan yang dikirim",
        min_length=1,
    )
    reference_id: Optional[str] = Field(
        None,
        description="ID transaksi atau event referensi",
        example="deposit-20261105-001",
    )
    status: str = Field(
        "pending",
        description="Status pengiriman",
        example="sent",
    )
    fonnte_message_id: Optional[str] = Field(
        None,
        description="ID pesan dari Fonnte jika tersedia",
        example="msg-123456",
    )
    error_message: Optional[str] = Field(
        None,
        description="Pesan error jika gagal",
        example="Invalid phone number",
    )


# ============================================================================
# RESPONSE SCHEMA: API Response
# ============================================================================

class NotificationSendResponse(BaseModel):
    """Response API untuk pengiriman notifikasi."""

    success: bool = Field(..., description="Apakah pengiriman berhasil")
    notification_type: str = Field(
        ..., description="Jenis notifikasi"
    )
    message: str = Field(..., description="Pesan pengguna")
    phone_number: str = Field(..., description="Nomor tujuan")
    fonnte_status: str = Field(
        ..., description="Status dari Fonnte API"
    )
    fonnte_message_id: Optional[str] = Field(
        None, description="ID pesan Fonnte"
    )
    forwarded_message: Optional[str] = Field(
        None, description="Pesan yang diformat untuk ditampilkan"
    )
    timestamp: str = Field(
        ..., description="Waktu pengiriman"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Daftar kesalahan jika ada",
    )


# ============================================================================
# SETTINGS SCHEMA
# ============================================================================

class FonnteSettings(BaseModel):
    """Schema konfigurasi Fonnte."""

    enabled: bool = Field(
        False,
        description="Aktifkan notifikasi WhatsApp Fonnte",
        example=False,
    )
    admin_number: Optional[str] = Field(
        None,
        description="Nomor WhatsApp admin tujuan notifikasi",
        example="81234567890",
    )
    default_country_code: str = Field(
        "62",
        description="Kode negara default untuk nomor Indonesia",
        example="62",
    )
    last_test: Optional[str] = Field(
        None,
        description="Waktu test terakhir",
        example="2026-11-05T10:00:00",
    )
    test_result: Optional[str] = Field(
        None,
        description="Hasil test terakhir (success/failed)",
        example="success",
    )


class SettingsUpdate(BaseModel):
    """Schema untuk update konfigurasi."""

    enabled: Optional[bool] = Field(None, description="Aktifkan/matikan notifikasi")
    admin_number: Optional[str] = Field(
        None, description="Update nomor admin", example="81234567890"
    )
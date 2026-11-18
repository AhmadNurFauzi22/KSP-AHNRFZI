"""Intent Classifier untuk AI Assistant KSP AHNRFZI.

Pencocokan dilakukan pada FRASA, bukan kata tunggal, dan diurutkan dari
paling spesifik ke paling umum. Ini mencegah kasus "Siapa saya?" salah
diklasifikasikan sebagai pertanyaan umum/dashboard.

Kategori:
    USER_IDENTITY      - "Siapa saya?", "Siapa aku?"
    USER_ROLE          - "Apa role saya?", "Peran saya apa?"
    USER_PROFILE       - "Nama akun saya?", "Data akun saya"
    USER_LIST          - "Siapa saja pengguna aplikasi?"
    MEMBER_COUNT       - "Berapa jumlah anggota?"
    MEMBER_LIST        - "Siapa saja anggota?"
    MEMBER_INCOMPLETE  - "Siapa anggota yang datanya belum lengkap?"
    SAVINGS            - "Berapa total simpanan?"
    LOAN               - "Berapa pinjaman berjalan?"
    INSTALLMENT        - "Berapa angsuran?"
    CASH_FLOW          - "Arus kas / kas masuk / kas keluar"
    TRANSACTION        - "Transaksi kasir hari ini"
    DASHBOARD_SUMMARY  - "Bagaimana kondisi koperasi?"
    IT_SYSTEM_STATUS   - "Bagaimana status sistem aplikasi?"
    AUDIT_STATUS       - "Audit trail / log audit"
    GENERAL            - pertanyaan lain ( dijawab SOP / LLM )
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# --- daftar kategori resmi (dipakai juga oleh validasi) ------------------
INTENT_USER_IDENTITY = "USER_IDENTITY"
INTENT_USER_ROLE = "USER_ROLE"
INTENT_USER_PROFILE = "USER_PROFILE"
INTENT_USER_LIST = "USER_LIST"
INTENT_MEMBER_COUNT = "MEMBER_COUNT"
INTENT_MEMBER_LIST = "MEMBER_LIST"
INTENT_MEMBER_INCOMPLETE = "MEMBER_INCOMPLETE"
INTENT_SAVINGS = "SAVINGS"
INTENT_LOAN = "LOAN"
INTENT_INSTALLMENT = "INSTALLMENT"
INTENT_CASH_FLOW = "CASH_FLOW"
INTENT_TRANSACTION = "TRANSACTION"
INTENT_DASHBOARD_SUMMARY = "DASHBOARD_SUMMARY"
INTENT_IT_SYSTEM_STATUS = "IT_SYSTEM_STATUS"
INTENT_AUDIT_STATUS = "AUDIT_STATUS"
INTENT_GENERAL = "GENERAL"

ALL_INTENTS: Tuple[str, ...] = (
    INTENT_USER_IDENTITY,
    INTENT_USER_ROLE,
    INTENT_USER_PROFILE,
    INTENT_USER_LIST,
    INTENT_MEMBER_COUNT,
    INTENT_MEMBER_LIST,
    INTENT_MEMBER_INCOMPLETE,
    INTENT_SAVINGS,
    INTENT_LOAN,
    INTENT_INSTALLMENT,
    INTENT_CASH_FLOW,
    INTENT_TRANSACTION,
    INTENT_DASHBOARD_SUMMARY,
    INTENT_IT_SYSTEM_STATUS,
    INTENT_AUDIT_STATUS,
    INTENT_GENERAL,
)

# --- pola frasa -----------------------------------------------------------
# Urutan penting: paling spesifik -> paling umum.
_PATTERNS: List[Tuple[str, str]] = [
    # --- identitas diri (paling spesifik, checked lebih dulu) -------------
    (INTENT_USER_IDENTITY, r"\b(siapa|siapakah)\s+(saya|aku|aq|ini|kami)\b"),
    (INTENT_USER_IDENTITY, r"\bidentitas\s+(saya|aku|anda|kami)\b"),
    (INTENT_USER_IDENTITY, r"\b(akun|user|pengguna)\s+(saya|aku)\s+(itu|ini|yang)\b"),
    (INTENT_USER_IDENTITY, r"\bapa\s+identitas\s+saya\b"),
    (INTENT_USER_IDENTITY, r"\bsaya\s+(adalah|ini|siapa)\b"),
    (INTENT_USER_IDENTITY, r"\bprofil\s+saya\b"),
    (INTENT_USER_IDENTITY, r"\bsaya\s+adalah\s+siapa\b"),

    (INTENT_USER_ROLE, r"\b(role|peran|jabatan\s+sistem)\s+(saya|aku|aktif\s+saya|anda)\b"),
    (INTENT_USER_ROLE, r"\b(saya|aku)\s+(punya|memiliki|memegang)\s+(role|peran)\b"),
    (INTENT_USER_ROLE, r"\bapa\s+(role|peran)\s+(saya|aku|yang\s+saya)\b"),
    (INTENT_USER_ROLE, r"\b(role|peran)\s+aktif\s+(saya|aku)\b"),
    (INTENT_USER_ROLE, r"\bhak\s+akses\s+(saya|aku)\b"),
    (INTENT_USER_ROLE, r"\bsaya\s+(adalah|bert-role|berperan)\b"),
    (INTENT_USER_ROLE, r"\bapa\s+(tugas|wewenang|kewenangan|tanggung\s+jawab)\s+(role\s+(saya|tersebut)|saya)\b"),
    (INTENT_USER_ROLE, r"\btugas\s+(role\s+)?(saya|tersebut)\b"),

    (INTENT_USER_PROFILE, r"\b(nama|username|akun|email)\s+(akun|login|pengguna)?\s*(saya|aku)\b"),
    (INTENT_USER_PROFILE, r"\bsaya\s+(pakai|gunakan|guna)\s+akun\b"),
    (INTENT_USER_PROFILE, r"\bdata\s+(akun|profil|diri)\s+(saya|aku)\b"),
    (INTENT_USER_PROFILE, r"\bprofil\s+(akun|pengguna)\s+saya\b"),

    # --- daftar pengguna APLIKASI ----------------------------------------
    (INTENT_USER_LIST, r"\b(siapa\s+(saja|siapa)|daftar|list)\s+(semua\s+)?(pengguna|user|pegawai\s+admin|akun|admin|operator)\b"),
    (INTENT_USER_LIST, r"\b(siapa\s+(saja|siapa)|daftar|list)\s+(pengguna|user|akun)\s+(aplikasi|sistem|yang\s+terdaftar)\b"),
    (INTENT_USER_LIST, r"\b(jumlah|berapa)\s+(pengguna|user)\s+(aplikasi|sistem)\b"),
    (INTENT_USER_LIST, r"\bdata\s+pengguna\b"),
    (INTENT_USER_LIST, r"\buser\s+yang\s+terdaftar\b"),

    # --- anggota BELUM LENGKAP (lebih spesifik dari member list) ----------
    (INTENT_MEMBER_INCOMPLETE, r"\b(anggota|pelanggan)\s+(yang\s+)?(datanya\s+|data\s+)?(belum|tdk|tidak)\s+(lengkap|terisi|lengkap)\b"),
    (INTENT_MEMBER_INCOMPLETE, r"\b(data\s+anggota|anggota)\s+(yang\s+)?(belum\s+lengkap|kurang\s+lengkap)\b"),
    (INTENT_MEMBER_INCOMPLETE, r"\bsiapa\s+(anggota|orang)\s+(yang\s+)?(datanya|data)\s+belum\b"),
    (INTENT_MEMBER_INCOMPLETE, r"\bkelengkapan\s+data\s+anggota\b"),
    (INTENT_MEMBER_INCOMPLETE, r"\banggota\s+(yg\s+)?data\s+belum\b"),

    # --- daftar anggota ---------------------------------------------------
    (INTENT_MEMBER_LIST, r"\b(siapa\s+(saja|siapa)|daftar|list)\s+(semua\s+)?(anggota|pelanggan)\b"),
    (INTENT_MEMBER_LIST, r"\banggota\s+(yang\s+)?terdaftar\b"),

    # --- jumlah anggota ---------------------------------------------------
    (INTENT_MEMBER_COUNT, r"\b(berapa|jumlah|total)\s+(jumlah\s+|total\s+)?(semua\s+)?(anggota|pelanggan)\b"),
    (INTENT_MEMBER_COUNT, r"\b(anggota|pelanggan)\s+(aktif|nonaktif|calon|terdaftar)\s+(saat\s+ini|sekarang)?\s*(yg\s+)?(ada|berapa|jumlah)?\b"),
    (INTENT_MEMBER_COUNT, r"\bkeanggotaan\b"),

    # --- simpanan ---------------------------------------------------------
    (INTENT_SAVINGS, r"\b(berapa|jumlah|total)\s+(total\s+)?(simpanan|tabungan|saldo\s+simpanan)\b"),
    (INTENT_SAVINGS, r"\b(total\s+)?simpanan\s+(anggota|koperasi|seluruh|yang\s+terhimpun)\b"),
    (INTENT_SAVINGS, r"\bsimpanan\s+(pokok|wajib|sukarela)\b"),
    (INTENT_SAVINGS, r"\bsaya\s+(punya|having)\s+simpanan\b"),

    # --- pinjaman ---------------------------------------------------------
    (INTENT_LOAN, r"\b(berapa|jumlah|total)\s+(total\s+)?(pinjaman|kredit)\b"),
    (INTENT_LOAN, r"\b(pinjaman|kredit)\s+(yang\s+)?(berjalan|aktif|belum\s+lunas|berjalan)\b"),
    (INTENT_LOAN, r"\b(pinjaman|kredit)\s+(outstanding|berjalan|tersalurkan)\b"),
    (INTENT_LOAN, r"\bpiutang\s+(berjalan|outstanding)\b"),
    (INTENT_LOAN, r"\bsaya\s+(punya|having)\s+(pinjaman|kredit)\b"),
    (INTENT_LOAN, r"\bapa\s+yang\s+(saya|anggota)\s+(punyakan|pinjam)\b"),

    # --- angsuran ---------------------------------------------------------
    (INTENT_INSTALLMENT, r"\bangsuran\b"),
    (INTENT_INSTALLMENT, r"\bcicilan\b"),
    (INTENT_INSTALLMENT, r"\bjadwal\s+(pembayaran|angsuran)\b"),
    (INTENT_INSTALLMENT, r"\bjatuh\s+tempo\b"),
    (INTENT_INSTALLMENT, r"\bterlambat\b"),
    (INTENT_INSTALLMENT, r"\b(?:berapa\s+)?(?:jumlah\s+)?angsuran\s+(yang\s+)?(sudah\s+dibayar|belum\s+dibayar|terlambat|jatuh\s+tempo)\b"),

    # --- arus kas (lebih spesifik dari transaksi) -------------------------
    (INTENT_CASH_FLOW, r"\b(arus\s+kas|kas\s+masuk|kas\s+keluar|saldo\s+kas)\b"),
    (INTENT_CASH_FLOW, r"\b(kas|kas\s+koperasi)\s+(hari\s+ini|minggu\s+ini|bulan\s+ini)\b"),

    # --- transaksi --------------------------------------------------------
    (INTENT_TRANSACTION, r"\btransaksi\b"),
    (INTENT_TRANSACTION, r"\bmutasi\s+(kas|rekening)\b"),
    (INTENT_TRANSACTION, r"\bkasir\b"),

    # --- status sistem IT -------------------------------------------------
    (INTENT_IT_SYSTEM_STATUS, r"\b(status\s+(sistem|aplikasi|server|layanan)|server\s+(sedang\s+)?(online|aktif|jalan))\b"),
    (INTENT_IT_SYSTEM_STATUS, r"\baplikasi\s+(sedang\s+)?(online|aktif|normal|sehat)\b"),
    (INTENT_IT_SYSTEM_STATUS, r"\b(database|db)\s+(terkoneksi|terhubung|koneksi|status)\b"),
    (INTENT_IT_SYSTEM_STATUS, r"\berror\s+(sistem|aplikasi|log)\b"),
    (INTENT_IT_SYSTEM_STATUS, r"\blog\s+error\b"),
    (INTENT_IT_SYSTEM_STATUS, r"\bmonitoring\s+sistem\b"),

    # --- audit ------------------------------------------------------------
    (INTENT_AUDIT_STATUS, r"\b(audit\s+trail|audit\s+log|log\s+audit|jejak\s+audit|riwayat\s+aktivitas)\b"),
    (INTENT_AUDIT_STATUS, r"\baktivitas\s+(sistem|tercatat)\b"),

    # --- ringkasan dashboard ----------------------------------------------
    (INTENT_DASHBOARD_SUMMARY, r"\b(kondisi|ringkasan|gambaran|overview|statistik)\s+(seluruh\s+)?(koperasi|sistem|data)\b"),
    (INTENT_DASHBOARD_SUMMARY, r"\b(bagaimana|kondisi)\s+(seluruh\s+)?(koperasi|keadaan\s+koperasi)\b"),
    (INTENT_DASHBOARD_SUMMARY, r"\bring[k]?asan\s+dashboard\b"),
    (INTENT_DASHBOARD_SUMMARY, r"\bsaya\s+login\b"),
    (INTENT_DASHBOARD_SUMMARY, r"\bmenu\s+(apa\s+)?yang\s+(bisa|boleh)\s+saya\s+akses\b"),
]

_COMPILED = [(intent, re.compile(pat, re.IGNORECASE)) for intent, pat in _PATTERNS]


def detect_intent(question: str) -> str:
    """Klasifikasikan maksud pertanyaan.

    Mengembalikan salah satu dari ``ALL_INTENTS``.
    """
    q = (question or "").strip().lower()
    if not q:
        return INTENT_GENERAL

    for intent, pattern in _COMPILED:
        if pattern.search(q):
            return intent

    return INTENT_GENERAL


def detect_intent_detail(question: str) -> Dict[str, object]:
    """Versi debugging: intent + pola yang cocok."""
    q = (question or "").strip().lower()
    for intent, pattern in _COMPILED:
        m = pattern.search(q)
        if m:
            return {"intent": intent, "matched": m.group(0), "pattern": pattern.pattern}
    return {"intent": INTENT_GENERAL, "matched": None, "pattern": None}


#: Intent yang HANYA boleh dijawab dari session (tanpa data dashboard).
SESSION_ONLY_INTENTS = {
    INTENT_USER_IDENTITY,
    INTENT_USER_ROLE,
    INTENT_USER_PROFILE,
}

#: Intent yang memakai data agregat modul (bukan dashboard penuh).
MODULE_INTENTS = {
    INTENT_MEMBER_COUNT,
    INTENT_MEMBER_LIST,
    INTENT_MEMBER_INCOMPLETE,
    INTENT_SAVINGS,
    INTENT_LOAN,
    INTENT_INSTALLMENT,
    INTENT_CASH_FLOW,
    INTENT_TRANSACTION,
    INTENT_AUDIT_STATUS,
    INTENT_IT_SYSTEM_STATUS,
}

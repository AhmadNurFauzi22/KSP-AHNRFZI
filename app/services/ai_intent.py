"""Intent Classifier untuk AI Assistant KSP AHNRFZI.

Pencocokan dilakukan pada FRASA (bukan kata tunggal) dan diurutkan dari paling
spesifik ke paling umum. Ini mencegah kasus "Siapa saya?" salah diklasifikasikan
sebagai pertanyaan umum/dashboard.

Kategori intent:
    USER_IDENTITY        - "Siapa saya?", "Apa jabatan saya?"
    USER_COUNT           - "Berapa jumlah pengguna?"
    USER_LIST            - "Siapa saja pengguna aplikasi?"
    ROLE_LIST            - "Apa saja role yang tersedia?"
    USER_ROLE_LOOKUP     - "Siapa pemegang role Admin?"
    MEMBER_STATISTICS    - "Berapa total anggota aktif?"
    MEMBER_LIST          - "Siapa saja anggota?"
    MEMBER_INCOMPLETE    - "Siapa anggota yang datanya belum lengkap?"
    SAVINGS              - "Berapa total simpanan?"
    LOANS                - "Berapa total pinjaman?"
    INSTALLMENTS         - "Siapa anggota yang terlambat membayar?"
    CASH_FLOW            - "Berapa saldo kas?"
    TRANSACTIONS         - "Apa transaksi terbaru?"
    PENDING_APPLICATIONS - "Berapa pengajuan yang menunggu?"
    DASHBOARD_SUMMARY    - "Bagaimana kondisi koperasi?"
    SYSTEM_STATUS        - "Apakah server sedang online?"
    TECHNICAL            - "Tampilkan struktur database"
    GENERAL              - pertanyaan umum / prosedural
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------
# Konstanta intent
# ---------------------------------------------------------------------
INTENT_USER_IDENTITY = "USER_IDENTITY"
INTENT_USER_COUNT = "USER_COUNT"
INTENT_USER_LIST = "USER_LIST"
INTENT_ROLE_LIST = "ROLE_LIST"
INTENT_USER_ROLE_LOOKUP = "USER_ROLE_LOOKUP"
INTENT_MEMBER_STATISTICS = "MEMBER_STATISTICS"
INTENT_MEMBER_LIST = "MEMBER_LIST"
INTENT_MEMBER_INCOMPLETE = "MEMBER_INCOMPLETE"
INTENT_SAVINGS = "SAVINGS"
INTENT_LOANS = "LOANS"
INTENT_INSTALLMENTS = "INSTALLMENTS"
INTENT_CASH_FLOW = "CASH_FLOW"
INTENT_TRANSACTIONS = "TRANSACTIONS"
INTENT_PENDING_APPLICATIONS = "PENDING_APPLICATIONS"
INTENT_AUDIT_STATUS = "AUDIT_STATUS"
INTENT_DASHBOARD_SUMMARY = "DASHBOARD_SUMMARY"
INTENT_SYSTEM_STATUS = "SYSTEM_STATUS"
INTENT_TECHNICAL = "TECHNICAL"
INTENT_GENERAL = "GENERAL"

ALL_INTENTS: Tuple[str, ...] = (
    INTENT_USER_IDENTITY,
    INTENT_USER_COUNT,
    INTENT_USER_LIST,
    INTENT_ROLE_LIST,
    INTENT_USER_ROLE_LOOKUP,
    INTENT_MEMBER_STATISTICS,
    INTENT_MEMBER_LIST,
    INTENT_MEMBER_INCOMPLETE,
    INTENT_SAVINGS,
    INTENT_LOANS,
    INTENT_INSTALLMENTS,
    INTENT_CASH_FLOW,
    INTENT_TRANSACTIONS,
    INTENT_PENDING_APPLICATIONS,
    INTENT_AUDIT_STATUS,
    INTENT_DASHBOARD_SUMMARY,
    INTENT_SYSTEM_STATUS,
    INTENT_TECHNICAL,
    INTENT_GENERAL,
)

#: Intent yang HANYA boleh dijawab dari session (tanpa data operasional).
SESSION_ONLY_INTENTS = {INTENT_USER_IDENTITY}

#: Intent aggregate per-modul (bukan dashboard penuh).
MODULE_INTENTS = {
    INTENT_USER_COUNT, INTENT_USER_LIST, INTENT_ROLE_LIST, INTENT_USER_ROLE_LOOKUP,
    INTENT_MEMBER_STATISTICS, INTENT_MEMBER_LIST, INTENT_MEMBER_INCOMPLETE,
    INTENT_SAVINGS, INTENT_LOANS, INTENT_INSTALLMENTS, INTENT_CASH_FLOW,
    INTENT_TRANSACTIONS, INTENT_PENDING_APPLICATIONS, INTENT_AUDIT_STATUS,
    INTENT_SYSTEM_STATUS, INTENT_TECHNICAL,
}


# ---------------------------------------------------------------------
# Pola frasa (urutan = prioritas)
# ---------------------------------------------------------------------
_PATTERNS: List[Tuple[str, str]] = [
    # --- 0. PRIORITAS TINGGI: gabungan data modul ---------------------------
    # "Siapa anggota yang memiliki pinjaman terlambat?" -> INSTALLMENTS
    (INTENT_INSTALLMENTS, r"\bsiapa\s+(anggota|pelanggan|nasabah)\s+(yang\s+)?(memiliki|ada|terlambat|punya)\b.*\b(terlambat|jatuh\s+tempo|angsuran|cicilan)\b"),
    (INTENT_INSTALLMENTS, r"\b(terlambat|tertunggak)\b.*\b(angsuran|cicilan|pinjaman)\b"),
    (INTENT_INSTALLMENTS, r"\b(angsuran|cicilan)\b.*\b(terlambat|tertunggak)\b"),

    # --- 1. IDENTITAS DIRI (paling spesifik) ------------------------------
    (INTENT_USER_IDENTITY, r"\b(siapa|siapakah)\s+(saya|aku|aq|ini|diri|kami)\b"),
    (INTENT_USER_IDENTITY, r"\bidentitas\s+(saya|aku|anda|kami|diri)\b"),
    (INTENT_USER_IDENTITY, r"\bsaya\s+(ini|adalah|ini)\s+(siapa|apa)\b"),
    (INTENT_USER_IDENTITY, r"\b(nama|username|akun|email)\s+(saya|aku)\b"),
    (INTENT_USER_IDENTITY, r"\bsaya\s+login\s+(sebagai|sebagai\s+apa)\b"),
    (INTENT_USER_IDENTITY, r"\bsedang\s+login\s+(sebagai|apa|dengan)\b"),
    (INTENT_USER_IDENTITY, r"\bsaya\s+adalah\s+siapa\b"),
    (INTENT_USER_IDENTITY, r"\bprofil\s+(saya|aku)\b"),
    (INTENT_USER_IDENTITY, r"\bdata\s+(akun|profil|diri)\s+(saya|aku)\b"),
    (INTENT_USER_IDENTITY, r"\b(jabatan|role|peran)\s+(saya|aku|yang\s+saya)\b"),
    (INTENT_USER_IDENTITY, r"\bhak\s+akses\s+(saya|aku)\b"),
    (INTENT_USER_IDENTITY, r"\bapa\s+(saja\s+)?(fitur|menu)\s+yang\s+(bisa|boleh)\s+saya\s+akses\b"),

    # --- 2. JUMLAH PENGGUNA APLIKASI --------------------------------------
    (INTENT_USER_COUNT, r"\b(berapa|jumlah|total)\s+(jumlah\s+|total\s+)?(pengguna|user|akun|pegawai\s+admin)\b"),
    (INTENT_USER_COUNT, r"\b(berapa\s+)?banyak\s+(pengguna|user|akun)\b"),
    (INTENT_USER_COUNT, r"\bpengguna\s+(aktif|nonaktif|terdaftar)\s+(ada|berapa|jumlah)?\b"),

    # --- 3. DAFTAR PENGGUNA APLIKASI --------------------------------------
    (INTENT_USER_LIST, r"\b(siapa\s+(saja|siapa|namanya|mereka)|daftar|list|tampilkan)\s+(semua\s+)?(pengguna|user|akun|admin)\b"),
    (INTENT_USER_LIST, r"\b(siapa\s+(saja|siapa)|daftar)\s+(nama\s+)?(pengguna|user)\s+(aplikasi|sistem|yang\s+terdaftar)\b"),
    (INTENT_USER_LIST, r"\bdata\s+pengguna\b"),
    (INTENT_USER_LIST, r"\buser\s+yang\s+terdaftar\b"),

    # --- 4. DAFTAR ROLE TERSEDIA ------------------------------------------
    (INTENT_ROLE_LIST, r"\b(apa\s+saja|daftar|list|siapa\s+saja)\s+(role|peran)\b"),
    (INTENT_ROLE_LIST, r"\b(role|peran)\s+(apa\s+saja|yang\s+ada|yang\s+tersedia|terdaftar)\b"),
    (INTENT_ROLE_LIST, r"\bdaftar\s+role\b"),

    # --- 5. PEMEGANG ROLE (lookup orang) -----------------------------------
    # CATATAN: pola ini diletakkan SETELAH intent data modul (lihat bawah)
    # agar pertanyaan seperti "Siapa anggota yang terlambat?" tidak salah
    # diklasifikasikan sebagai lookup role.
    # --- 6. ANGGOTA BELUM LENGKAP (lebih spesifik dari member list) --------
    (INTENT_MEMBER_INCOMPLETE, r"\b(anggota|pelanggan)\s+(yang\s+)?(datanya\s+|data\s+)?(belum|tdk|tidak)\s+(lengkap|terisi)\b"),
    (INTENT_MEMBER_INCOMPLETE, r"\b(data\s+anggota|anggota)\s+(yang\s+)?(belum\s+lengkap|kurang\s+lengkap)\b"),
    (INTENT_MEMBER_INCOMPLETE, r"\bsiapa\s+(anggota|orang)\s+(yang\s+)?(datanya|data)\s+belum\b"),
    (INTENT_MEMBER_INCOMPLETE, r"\bkelengkapan\s+data\s+anggota\b"),
    (INTENT_MEMBER_INCOMPLETE, r"\banggota\s+(yg\s+)?data\s+belum\b"),

    # --- 7. STATISTIK ANGGOTA ---------------------------------------------
    (INTENT_MEMBER_STATISTICS, r"\b(berapa|jumlah|total)\s+(jumlah\s+|total\s+)?(semua\s+)?(anggota|pelanggan)\b"),
    (INTENT_MEMBER_STATISTICS, r"\b(anggota|pelanggan)\s+(aktif|nonaktif|calon|terdaftar)\s+(saat\s+ini|sekarang)?\s*(yg\s+)?(ada|berapa|jumlah)?\b"),
    (INTENT_MEMBER_STATISTICS, r"\bkeanggotaan\b"),
    (INTENT_MEMBER_STATISTICS, r"\bjumlah\s+anggota\b"),

    # --- 8. DAFTAR ANGGOTA --------------------------------------------------
    (INTENT_MEMBER_LIST, r"\b(siapa\s+(saja|siapa|namanya|mereka)|daftar|list)\s+(semua\s+)?(anggota|pelanggan)\b"),
    (INTENT_MEMBER_LIST, r"\banggota\s+(yang\s+)?terdaftar\b"),

    # --- 9. SIMPANAN ---------------------------------------------------------
    (INTENT_SAVINGS, r"\b(berapa|jumlah|total)\s+(total\s+)?(simpanan|tabungan)\b"),
    (INTENT_SAVINGS, r"\b(total\s+)?simpanan\s+(anggota|koperasi|seluruh|yang\s+terhimpun|pokok|wajib|sukarela)\b"),
    (INTENT_SAVINGS, r"\bsimpanan\s+(pokok|wajib|sukarela)\b"),

    # --- 10. PINJAMAN ---------------------------------------------------------
    (INTENT_LOANS, r"\b(berapa|jumlah|total)\s+(total\s+)?(pinjaman|kredit)\b"),
    (INTENT_LOANS, r"\b(pinjaman|kredit)\s+(yang\s+)?(berjalan|aktif|belum\s+lunas|tersalurkan)\b"),
    (INTENT_LOANS, r"\b(pinjaman|kredit)\s+(outstanding|berjalan|tersalurkan)\b"),
    (INTENT_LOANS, r"\bpiutang\s+(berjalan|outstanding|total)\b"),
    (INTENT_LOANS, r"\bplafon\b"),

    # --- 11. ANGSURAN ---------------------------------------------------------
    (INTENT_INSTALLMENTS, r"\bangsuran\b"),
    (INTENT_INSTALLMENTS, r"\bcicilan\b"),
    (INTENT_INSTALLMENTS, r"\bjadwal\s+(pembayaran|angsuran)\b"),
    (INTENT_INSTALLMENTS, r"\bjatuh\s+tempo\b"),
    (INTENT_INSTALLMENTS, r"\bterlambat\b"),
    (INTENT_INSTALLMENTS, r"\btertunggak\b"),

    # --- 12. ARUS KAS ---------------------------------------------------------
    (INTENT_CASH_FLOW, r"\b(arus\s+kas|saldo\s+kas|kas\s+masuk|kas\s+keluar)\b"),
    (INTENT_CASH_FLOW, r"\b(kas|kas\s+koperasi)\s+(hari\s+ini|minggu\s+ini|bulan\s+ini)\b"),

    # --- 13. TRANSAKSI --------------------------------------------------------
    (INTENT_TRANSACTIONS, r"\btransaksi\b"),
    (INTENT_TRANSACTIONS, r"\bmutasi\s+(kas|rekening)\b"),
    (INTENT_TRANSACTIONS, r"\bkasir\b"),
    (INTENT_TRANSACTIONS, r"\btransaksi\s+terbaru\b"),

    # --- 14. PENGAJUAN & PERSETUJUAN -----------------------------------------
    (INTENT_PENDING_APPLICATIONS, r"\b(pengajuan|pengaju)\b"),
    (INTENT_PENDING_APPLICATIONS, r"\b(menunggu|antrean|pending)\s+(verifikasi|persetujuan|approval)\b"),
    (INTENT_PENDING_APPLICATIONS, r"\bpipeline\s+(pinjaman|persetujuan)\b"),
    (INTENT_PENDING_APPLICATIONS, r"\bsiap\s+dicairkan\b"),

    # --- 14b. PEMEGANG ROLE (lookup orang) ----------------------------------
    # Diletakkan setelah intent data modul supaya "Siapa anggota yang
    # terlambat?" tetap menjadi INSTALLMENTS, bukan lookup role.
    (INTENT_USER_ROLE_LOOKUP, r"\bsiapa\s+yang\s+(admin|manager|kasir|ketua|pengawas|pembina|staf|it\s+pusat|hrd)\b"),
    (INTENT_USER_ROLE_LOOKUP, r"\bsiapa\s+(yang\s+)?(pemegang|menempati|memegang|adalah|bertugas)\s+.*\b(role|jabatan|admin|manager|kasir|ketua|pengawas|pembina|staf)\b"),
    (INTENT_USER_ROLE_LOOKUP, r"\b(jabatan|role)\s+(apa|siapa)\s+yang\s+(menempati|memegang)\b"),
    (INTENT_USER_ROLE_LOOKUP, r"\bsiapa\s+(yang\s+)?(menjadi|berperan\s+sebagai)\s+(admin|manager|kasir|ketua|pengawas|pembina|staf|it\s+pusat|hrd)\b"),
    (INTENT_USER_ROLE_LOOKUP, r"\b(admin|manager|kasir|ketua\s+umum|pengawas|pembina|staf|it\s+pusat|hrd)\s+(yang\s+)?mana\b"),
    (INTENT_USER_ROLE_LOOKUP, r"\bsiapa\s+(admin|manager|kasir|ketua|pengawas|pembina|staf|it\s+pusat|hrd)\b"),

    # --- 15. AKTIVITAS & AUDIT ------------------------------------------------
    (INTENT_AUDIT_STATUS, r"\b(audit\s+trail|audit\s+log|log\s+audit|jejak\s+audit|riwayat\s+aktivitas)\b"),
    (INTENT_AUDIT_STATUS, r"\baktivitas\s+(terakhir|terkini|recent|system|saya|sebelumnya)\b"),
    (INTENT_AUDIT_STATUS, r"\b(terakhir|terkini)\s+(aktivitas|riwayat|transaksi)\b"),
    (INTENT_AUDIT_STATUS, r"\bapa\s+yang\s+(pernah\s+)?(saya|anda)\s+(lakukan|akses|lakukan)\b"),

    # --- 16. STATUS SISTEM ----------------------------------------------------
    (INTENT_SYSTEM_STATUS, r"\b(status\s+(sistem|aplikasi|server|layanan|program)|server\s+(sedang\s+)?(online|aktif|jalan|up))\b"),
    (INTENT_SYSTEM_STATUS, r"\baplikasi\s+(sedang\s+)?(online|aktif|normal|sehat|jalan)\b"),
    (INTENT_SYSTEM_STATUS, r"\b(database|db)\s+(terkoneksi|terhubung|koneksi|status|terkonek)\b"),
    (INTENT_SYSTEM_STATUS, r"\berror\s+(sistem|aplikasi|log)\b"),
    (INTENT_SYSTEM_STATUS, r"\blog\s+error\b"),
    (INTENT_SYSTEM_STATUS, r"\bmonitoring\s+sistem\b"),
    (INTENT_SYSTEM_STATUS, r"\bkondisi\s+(server|sistem|aplikasi)\b"),

    # --- 17. TEKNIS / SCHEMA -------------------------------------------------
    (INTENT_TECHNICAL, r"\b(schema|struktur)\s+(tabel|database|data)\b"),
    (INTENT_TECHNICAL, r"\btabel\s+(apa|yaitu|yang)\b"),
    (INTENT_TECHNICAL, r"\b(nama|daftar)\s+(tabel|kolom)\b"),
    (INTENT_TECHNICAL, r"\bsql\s+(query|perintah)\b"),
    (INTENT_TECHNICAL, r"\bdatabase\s+(terkoneksi|koneksi)\b"),

    # --- 18. RINGKASAN DASHBOARD ---------------------------------------------
    (INTENT_DASHBOARD_SUMMARY, r"\b(kondisi|ringkasan|gambaran|overview|statistik)\s+(seluruh\s+)?(koperasi|sistem|data)\b"),
    (INTENT_DASHBOARD_SUMMARY, r"\b(bagaimana|kondisi)\s+(seluruh\s+)?(koperasi|keadaan\s+koperasi)\b"),
    (INTENT_DASHBOARD_SUMMARY, r"\bring[k]?asan\s+dashboard\b"),
    (INTENT_DASHBOARD_SUMMARY, r"\bsaya\s+login\b"),
    (INTENT_DASHBOARD_SUMMARY, r"\bmenu\s+(apa\s+)?yang\s+(bisa|boleh)\s+saya\s+akses\b"),
]

_COMPILED = [(intent, re.compile(pat, re.IGNORECASE)) for intent, pat in _PATTERNS]

#: Intent yang dapat menjadi subjek pertanyaan lanjutan.
#: Kunci = nilai subjek yang disimpan di riwayat percakapan.
_FOLLOWUP_SUBJECTS = {
    "pengguna": INTENT_USER_LIST,
    "anggota": INTENT_MEMBER_LIST,
    "simpanan": INTENT_SAVINGS,
    "pinjaman": INTENT_LOANS,
    "angsuran": INTENT_INSTALLMENTS,
    "kas": INTENT_CASH_FLOW,
    "transaksi": INTENT_TRANSACTIONS,
    "pengajuan": INTENT_PENDING_APPLICATIONS,
    "aktivitas": INTENT_AUDIT_STATUS,
    "role": INTENT_ROLE_LIST,
}

_FOLLOWUP_MARKERS = (
    "namanya", "nama mereka", "mereka", "detailnya", "rinciannya", "seluruhnya",
    "sebutkan", "sebut", "dan siapa", "masing-masing", "satu per satu",
)

#: Kata kunci yang menunjuk ke data modul (bukan lookup role / daftar).
_MODULE_WORDS = (
    "terlambat", "angsuran", "cicilan", "jatuh tempo", "tertunggak",
    "pinjaman", "kredit", "simpanan", "tabungan", "transaksi", "pengajuan",
    "dicairkan", "saldo", "kas masuk", "kas keluar",
)


def detect_intent(question: str, subject: Optional[str] = None) -> str:
    """Klasifikasikan maksud pertanyaan.

    ``subject`` = subjek dari giliran sebelumnya (untuk pertanyaan lanjutan).
    """
    q = (question or "").strip().lower()
    if not q:
        return INTENT_GENERAL

    # --- Pertanyaan lanjutan yang merujuk pada jawaban sebelumnya ----------
    # "Kalau saya?", "Kalau saya sendiri?" -> identitas pengguna aktif
    if re.search(r"\b(kalau|kalau\s+kita|jika\s+saya|dan\s+saya|berarti\s+saya)\b", q) \
            and not re.search(r"\b(admin|manager|kasir|ketua|pengawas|pembina|staf|anggota|hrd)\b", q):
        return INTENT_USER_IDENTITY

    # "Kalau yang Admin siapa?" -> lookup pemegang role.
    # Hanya bila pertanyaan TIDAK menunjuk ke data modul (angsuran/terlambat/dll).
    if not any(w in q for w in _MODULE_WORDS):
        if re.search(r"\b(admin|manager|kasir|ketua|pengawas|pembina|staf|it\s+pusat|hrd)\b", q) \
                and any(m in q for m in ("kalau", "yang", "siapa", "pemegang", "mana")):
            return INTENT_USER_ROLE_LOOKUP

    if subject and any(m in q for m in _FOLLOWUP_MARKERS):
        mapped = _FOLLOWUP_SUBJECTS.get(subject)
        if mapped:
            return mapped

    for intent, pattern in _COMPILED:
        if pattern.search(q):
            return intent

    return INTENT_GENERAL


def detect_intent_detail(question: str, subject: Optional[str] = None) -> Dict[str, object]:
    """Versi debugging: intent + frasa yang cocok."""
    q = (question or "").strip().lower()
    for intent, pattern in _COMPILED:
        m = pattern.search(q)
        if m:
            return {"intent": intent, "matched": m.group(0), "pattern": pattern.pattern}
    return {"intent": INTENT_GENERAL, "matched": None, "pattern": None}

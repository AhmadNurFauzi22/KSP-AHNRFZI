"""Knowledge base statis KSP AHNRFZI (Prompt #12).

Hanya berisi aturan/prosedur yang memang berlaku di project ini
(nilai produk sesuai seed: simpanan & pinjaman). BUKAN aturan fiktif.
AI dilarang mengarang kebijakan di luar daftar ini.
"""
import re
from typing import List, Dict

SOP_ITEMS: List[Dict[str, str]] = [
    {"id": "simpanan-pokok", "judul": "Simpanan Pokok",
     "isi": "Simpanan Pokok Rp 500.000 dibayar sekali saat pendaftaran anggota dan tidak dapat ditarik selama masih menjadi anggota aktif."},
    {"id": "simpanan-wajib", "judul": "Simpanan Wajib",
     "isi": "Simpanan Wajib rutin Rp 100.000 per bulan, disetor via Kasir atau dipotong otomatis dari gaji (HRD payroll deduction), tidak dapat ditarik selama anggota aktif."},
    {"id": "simpanan-sukarela", "judul": "Simpanan Sukarela",
     "isi": "Simpanan Sukarela setoran awal minimal Rp 50.000, bebas setor dan tarik kapan saja melalui kasir (saldo cukup)."},
    {"id": "simpanan-berjangka", "judul": "Simpanan Berjangka",
     "isi": "Deposito koperasi setoran minimal Rp 5.000.000 dengan imbal hasil; penarikan mengikuti tenor yang disepakati."},
    {"id": "pengajuan-pinjaman", "judul": "Cara Mengajukan Pinjaman",
     "isi": "Anggota mengajukan via menu Pinjaman (isi produk, nominal, tenor, tujuan; dapat disimpan sebagai DRAFT lalu diajukan). Produk: Reguler Rp 1–50 juta tenor 6–36 bulan bunga 12% flat; Darurat Rp 0,5–10 juta tenor 1–6 bulan bunga 6%; Kendaraan Rp 10–150 juta tenor 12–48 bulan bunga 10% anuitas. Biaya admin ±1% dan provisi ±0,5% dipotong dari pencairan."},
    {"id": "alur-persetujuan", "judul": "Alur Persetujuan Pinjaman",
     "isi": "Alur resmi: DRAFT → DIAJUKAN → VERIFIKASI (Staf) → DISETUJUI/DITOLAK (Manager/Ketua) → DICAIRKAN/BERJALAN (Kasir) → LUNAS. Pengaju dilarang memverifikasi/menyetujui/mencairkan pinjamannya sendiri. Penolakan wajib disertai alasan."},
    {"id": "pembayaran-angsuran", "judul": "Cara Membayar Angsuran",
     "isi": "Pembayaran dilakukan di loket kasir (tunai/transfer) atau potong gaji HRD. Jatuh tempo tiap 30 hari sejak pencairan; keterlambatan dikenakan denda harian sesuai produk. Kuitansi diterbitkan setiap pembayaran."},
    {"id": "pencairan", "judul": "Pencairan Pinjaman",
     "isi": "Pencairan oleh Kasir setelah status DISETUJUI. Dana cair bersih = plafon − biaya admin − provisi. Jadwal angsuran terbentuk otomatis saat pencairan."},
    {"id": "keanggotaan", "judul": "Keanggotaan Koperasi",
     "isi": "Calon anggota didaftarkan Admin/Manager/HRD/Staf (status awal CALON), diaktifkan menjadi AKTIF setelah memenuhi syarat. Anggota berasal dari pegawai aktif; pegawai nonaktif (RESIGNED) tidak dapat diproses."},
    {"id": "shu", "judul": "SHU",
     "isi": "Sisa Hasil Usaha (SHU) dibagikan pada Rapat Anggota Tahunan (RAT) berdasarkan kontribusi simpanan dan jasa transaksi masing-masing anggota."},
    {"id": "peran", "judul": "Peran Pengguna",
     "isi": "Peran sistem: Admin Koperasi, Ketua Umum, Manager, HRD, Pengawas/Pembina, Staf, IT Pusat, Kasir, Anggota. Setiap aksi penting (verifikasi, approval, pencairan, tutup kas) memerlukan permission dan dicatat di audit log."},
]


def search_sop(keyword: str, limit: int = 3) -> List[Dict[str, str]]:
    """Pencarian SOP berbasis kata kunci (tanpa LLM, tanpa data sensitif).

    Matching pakai word boundary — "apa" TIDAK cocok dengan "dapat",
    sehingga retrieval tidak salah tarik SOP.
    """
    kw = (keyword or "").lower().strip()
    if not kw:
        return []
    # Tokenisasi: abaikan token < 3 huruf agar tidak cocok parsial.
    words = [w for w in re.split(r"[^a-z0-9]+", kw) if len(w) >= 3]
    if not words:
        return []
    scored = []
    for item in SOP_ITEMS:
        text = (item["judul"] + " " + item["isi"]).lower()
        hits = sum(1 for w in words
                   if re.search(r"\b" + re.escape(w) + r"\b", text))
        if hits:
            scored.append((hits, item))
    scored.sort(key=lambda x: -x[0])
    return [{"judul": i["judul"], "isi": i["isi"]} for _, i in scored[:limit]]

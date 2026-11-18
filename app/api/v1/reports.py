"""
API: Modul Pelaporan (Reporting Module) KSP AHNRFZI
===================================================
Menyediakan 6 laporan resmi manajerial koperasi dengan filter, date range, pagination,
serta fitur ekspor langsung ke Excel (.xlsx) dan PDF (A4 Landscape):
1. Laporan Anggota
2. Laporan Simpanan
3. Laporan Pinjaman
4. Laporan Angsuran
5. Laporan Buku Kas
6. Laporan Tunggakan & Kredit Bermasalah (Overdue)

RBAC & Financial Privacy:
- HRD hanya dapat mengakses Laporan Anggota (data keuangan dimasking), dan ditolak mengakses laporan keuangan.
- Anggota biasa ditolak mengakses endpoint laporan manajerial.
"""
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, get_user_permissions
from app.db.models.user import User
from app.services import report_service
from app.services.audit_service import AuditService

router = APIRouter(prefix="/reports", tags=["Reports"])


def _log_export(db, user: User, report_name: str, fmt: str, request=None):
    try:
        AuditService.log_event(
            db, action="REPORT_EXPORT", entity_name="Report",
            entity_id=report_name, user_id=user.id,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
            notes=f"Export {report_name} format={fmt} oleh {user.username}",
        )
    except Exception:
        pass


def _check_report_permission(current_user: User, financial_report: bool = False):
    """
    Verifikasi izin akses laporan dan penegakan batas wewenang:
    - Anggota biasa: Ditolak (403)
    - HRD: Ditolak pada laporan keuangan (403) kecuali memiliki izin khusus
    """
    roles = set(current_user.role_codes)
    perms = get_user_permissions(current_user, getattr(current_user, "active_role", None))

    # Superadmin & Pimpinan
    if bool({"ADMIN_KOPERASI", "ADMIN", "KETUA_UMUM", "KETUA", "MANAGER", "PENGAWAS_PEMBINA", "PENGAWAS"} & roles):
        return

    # Check permission
    if "*" in perms or "report.view" in perms:
        if financial_report and "HRD" in roles and not bool({"saving.view", "loan.view", "cashier.view"} & perms):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak. Peran HRD tidak diizinkan mengakses laporan keuangan koperasi."
            )
        return

    if "HRD" in roles:
        if financial_report:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak. Peran HRD tidak diizinkan mengakses laporan keuangan koperasi."
            )
        return

    # Anggota atau peran tanpa izin
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Akses ditolak. Anda tidak memiliki izin untuk mengakses laporan manajerial koperasi."
    )


# =============================================================================
# 1. LAPORAN ANGGOTA
# =============================================================================
@router.get("/members")
def get_members_report(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=500),
    export: Optional[str] = Query(None, description="excel atau pdf"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _check_report_permission(current_user, financial_report=False)
    perms = get_user_permissions(current_user, getattr(current_user, "active_role", None))
    roles = set(current_user.role_codes)

    # Financial masking: HRD tanpa saving.view/loan.view disembunyikan kolom keuangannya
    is_hrd = "HRD" in roles and not bool({"saving.view", "loan.view", "*"} & perms)
    hide_financial = is_hrd

    skip = (page - 1) * limit
    fetch_limit = 5000 if export else limit

    rows, total_count, summary = report_service.get_members_report(
        db, search=search, status_filter=status, unit_filter=unit,
        start_date=start_date, end_date=end_date, skip=skip if not export else 0,
        limit=fetch_limit, hide_financial=hide_financial
    )

    headers = ["No", "No. Anggota", "NIK KTP", "Nama Lengkap", "Unit / Divisi", "Jabatan", "Status", "Telepon", "Tanggal Bergabung"]
    keys = ["no", "no_anggota", "nik", "nama_lengkap", "unit_divisi", "jabatan", "status", "telepon", "tanggal_gabung"]

    if not hide_financial:
        headers.extend(["Total Simpanan (Rp)", "Sisa Pinjaman (Rp)"])
        keys.extend(["total_simpanan", "sisa_pinjaman"])

    today_str = datetime.now().strftime("%Y%m%d")

    if export in ("excel", "pdf"):
        _log_export(db, current_user, "report", export, request)
    if export == "excel":
        sum_text = f"Total Anggota: {summary['total_anggota']} | Aktif: {summary['aktif']} | Calon: {summary['calon']} | Nonaktif: {summary['nonaktif']}"
        buf = report_service.export_to_excel("Laporan Keanggotaan KSP AHNRFZI", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Anggota_{today_str}.xlsx"}
        )
    elif export == "pdf":
        sum_text = f"Total Anggota: {summary['total_anggota']} (Aktif: {summary['aktif']}, Calon: {summary['calon']}, Nonaktif: {summary['nonaktif']})"
        buf = report_service.export_to_pdf("Laporan Keanggotaan KSP AHNRFZI", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Anggota_{today_str}.pdf"}
        )

    return {
        "metadata": {
            "report_name": "Laporan Keanggotaan",
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M WIB"),
            "total_records": total_count,
            "current_page": page,
            "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
            "limit": limit
        },
        "summary": summary,
        "data": rows
    }


# =============================================================================
# 2. LAPORAN SIMPANAN
# =============================================================================
@router.get("/savings")
def get_savings_report(
    search: Optional[str] = Query(None),
    product_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=500),
    export: Optional[str] = Query(None),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _check_report_permission(current_user, financial_report=True)
    skip = (page - 1) * limit
    fetch_limit = 5000 if export else limit

    rows, total_count, summary = report_service.get_savings_report(
        db, search=search, product_id=product_id, status_filter=status,
        start_date=start_date, end_date=end_date, skip=skip if not export else 0,
        limit=fetch_limit
    )

    headers = ["No", "No. Rekening", "No. Anggota", "Nama Anggota", "Produk Simpanan", "Saldo (Rp)", "Status", "Tanggal Buka"]
    keys = ["no", "no_rekening", "no_anggota", "nama_anggota", "produk", "saldo", "status", "tanggal_buka"]
    today_str = datetime.now().strftime("%Y%m%d")

    if export in ("excel", "pdf"):
        _log_export(db, current_user, "report", export, request)
    if export == "excel":
        sum_text = f"Total Rekening: {summary['total_rekening']} | Total Saldo Terhimpun: Rp {summary['total_saldo']:,.2f}"
        buf = report_service.export_to_excel("Laporan Rekening & Saldo Simpanan", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Simpanan_{today_str}.xlsx"}
        )
    elif export == "pdf":
        sum_text = f"Total Rekening: {summary['total_rekening']} | Total Saldo: Rp {summary['total_saldo']:,.0f}"
        buf = report_service.export_to_pdf("Laporan Rekening & Saldo Simpanan", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Simpanan_{today_str}.pdf"}
        )

    return {
        "metadata": {
            "report_name": "Laporan Simpanan",
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M WIB"),
            "total_records": total_count,
            "current_page": page,
            "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
            "limit": limit
        },
        "summary": summary,
        "data": rows
    }


# =============================================================================
# 3. LAPORAN PINJAMAN
# =============================================================================
@router.get("/loans")
def get_loans_report(
    search: Optional[str] = Query(None),
    product_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=500),
    export: Optional[str] = Query(None),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _check_report_permission(current_user, financial_report=True)
    skip = (page - 1) * limit
    fetch_limit = 5000 if export else limit

    rows, total_count, summary = report_service.get_loans_report(
        db, search=search, product_id=product_id, status_filter=status,
        start_date=start_date, end_date=end_date, skip=skip if not export else 0,
        limit=fetch_limit
    )

    headers = ["No", "No. Pinjaman", "No. Anggota", "Nama Anggota", "Produk", "Plafon (Rp)", "Tenor", "Bunga", "Sisa Pokok (Rp)", "Status", "Tanggal Cair"]
    keys = ["no", "no_pinjaman", "no_anggota", "nama_anggota", "produk", "nominal_plafon", "tenor_bulan", "bunga", "sisa_pokok", "status", "tanggal_cair"]
    today_str = datetime.now().strftime("%Y%m%d")

    if export in ("excel", "pdf"):
        _log_export(db, current_user, "report", export, request)
    if export == "excel":
        sum_text = f"Total Pinjaman: {summary['total_pinjaman_count']} | Plafon Tersalurkan: Rp {summary['total_plafon']:,.2f} | Outstanding: Rp {summary['total_outstanding']:,.2f}"
        buf = report_service.export_to_excel("Laporan Portofolio Pembiayaan Kredit Pinjaman", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Pinjaman_{today_str}.xlsx"}
        )
    elif export == "pdf":
        sum_text = f"Total Berkas: {summary['total_pinjaman_count']} | Plafon: Rp {summary['total_plafon']:,.0f} | Outstanding: Rp {summary['total_outstanding']:,.0f}"
        buf = report_service.export_to_pdf("Laporan Portofolio Pembiayaan Kredit Pinjaman", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Pinjaman_{today_str}.pdf"}
        )

    return {
        "metadata": {
            "report_name": "Laporan Pinjaman",
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M WIB"),
            "total_records": total_count,
            "current_page": page,
            "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
            "limit": limit
        },
        "summary": summary,
        "data": rows
    }


# =============================================================================
# 4. LAPORAN ANGSURAN
# =============================================================================
@router.get("/installments")
def get_installments_report(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=500),
    export: Optional[str] = Query(None),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _check_report_permission(current_user, financial_report=True)
    skip = (page - 1) * limit
    fetch_limit = 5000 if export else limit

    rows, total_count, summary = report_service.get_installments_report(
        db, search=search, status_filter=status,
        start_date=start_date, end_date=end_date, skip=skip if not export else 0,
        limit=fetch_limit
    )

    headers = ["No", "No. Pinjaman", "Cicilan", "Nama Anggota", "Jatuh Tempo", "Pokok (Rp)", "Bunga (Rp)", "Total Tagihan (Rp)", "Total Dibayar (Rp)", "Sisa (Rp)", "Status"]
    keys = ["no", "no_pinjaman", "angsuran_ke", "nama_anggota", "jatuh_tempo", "pokok", "bunga", "total_tagihan", "total_dibayar", "sisa_tagihan", "status"]
    today_str = datetime.now().strftime("%Y%m%d")

    if export in ("excel", "pdf"):
        _log_export(db, current_user, "report", export, request)
    if export == "excel":
        sum_text = f"Total Tagihan: Rp {summary['total_tagihan']:,.2f} | Total Dibayar: Rp {summary['total_dibayar']:,.2f} | Sisa Tagihan: Rp {summary['total_sisa']:,.2f}"
        buf = report_service.export_to_excel("Laporan Realisasi & Tagihan Angsuran", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Angsuran_{today_str}.xlsx"}
        )
    elif export == "pdf":
        sum_text = f"Total Tagihan: Rp {summary['total_tagihan']:,.0f} | Realisasi Bayar: Rp {summary['total_dibayar']:,.0f} | Sisa: Rp {summary['total_sisa']:,.0f}"
        buf = report_service.export_to_pdf("Laporan Realisasi & Tagihan Angsuran", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Angsuran_{today_str}.pdf"}
        )

    return {
        "metadata": {
            "report_name": "Laporan Angsuran",
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M WIB"),
            "total_records": total_count,
            "current_page": page,
            "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
            "limit": limit
        },
        "summary": summary,
        "data": rows
    }


# =============================================================================
# 5. LAPORAN KAS
# =============================================================================
@router.get("/cash")
def get_cash_report(
    search: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=500),
    export: Optional[str] = Query(None),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _check_report_permission(current_user, financial_report=True)
    skip = (page - 1) * limit
    fetch_limit = 5000 if export else limit

    rows, total_count, summary = report_service.get_cash_report(
        db, search=search, direction=direction, category=category,
        start_date=start_date, end_date=end_date, skip=skip if not export else 0,
        limit=fetch_limit
    )

    headers = ["No", "No. Transaksi", "Slip", "Waktu", "Kasir", "Arah Kas", "Kategori", "Nominal (Rp)", "Metode", "Anggota", "Status"]
    keys = ["no", "no_transaksi", "no_kuitansi", "waktu", "kasir", "arah", "kategori", "nominal", "metode", "anggota", "status"]
    today_str = datetime.now().strftime("%Y%m%d")

    if export in ("excel", "pdf"):
        _log_export(db, current_user, "report", export, request)
    if export == "excel":
        sum_text = f"Total Masuk: Rp {summary['total_kas_masuk']:,.2f} | Total Keluar: Rp {summary['total_kas_keluar']:,.2f} | Net Cash: Rp {summary['net_cash_flow']:,.2f}"
        buf = report_service.export_to_excel("Laporan Buku Kas & Mutasi Loket", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Kas_{today_str}.xlsx"}
        )
    elif export == "pdf":
        sum_text = f"Total Masuk: Rp {summary['total_kas_masuk']:,.0f} | Total Keluar: Rp {summary['total_kas_keluar']:,.0f} | Net: Rp {summary['net_cash_flow']:,.0f}"
        buf = report_service.export_to_pdf("Laporan Buku Kas & Mutasi Loket", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Kas_{today_str}.pdf"}
        )

    return {
        "metadata": {
            "report_name": "Laporan Buku Kas",
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M WIB"),
            "total_records": total_count,
            "current_page": page,
            "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
            "limit": limit
        },
        "summary": summary,
        "data": rows
    }


# =============================================================================
# 6. LAPORAN TUNGGAKAN & KREDIT BERMASALAH (OVERDUE)
# =============================================================================
@router.get("/overdue")
def get_overdue_report(
    search: Optional[str] = Query(None),
    min_days: int = Query(1, ge=1, description="Minimal hari keterlambatan"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=500),
    export: Optional[str] = Query(None),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _check_report_permission(current_user, financial_report=True)
    skip = (page - 1) * limit
    fetch_limit = 5000 if export else limit

    rows, total_count, summary = report_service.get_overdue_report(
        db, search=search, min_days=min_days,
        start_date=start_date, end_date=end_date, skip=skip if not export else 0,
        limit=fetch_limit
    )

    headers = ["No", "No. Pinjaman", "Cicilan", "No. Anggota", "Nama Anggota", "Unit / Divisi", "Telepon", "Jatuh Tempo", "Hari Terlambat", "Tunggakan Pokok+Bunga (Rp)", "Estimasi Denda (Rp)", "Total Kewajiban (Rp)"]
    keys = ["no", "no_pinjaman", "angsuran_ke", "no_anggota", "nama_anggota", "unit_divisi", "telepon", "jatuh_tempo", "hari_terlambat", "tunggakan_pokok_bunga", "estimasi_denda", "total_kewajiban"]
    today_str = datetime.now().strftime("%Y%m%d")

    if export in ("excel", "pdf"):
        _log_export(db, current_user, "report", export, request)
    if export == "excel":
        sum_text = f"Total Angsuran Menunggak: {summary['total_angsuran_menunggak']} berkas | Total Tunggakan Pokok + Bunga: Rp {summary['total_tunggakan_pokok_bunga']:,.2f}"
        buf = report_service.export_to_excel("Laporan Kredit Bermasalah & Tunggakan Angsuran", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Tunggakan_{today_str}.xlsx"}
        )
    elif export == "pdf":
        sum_text = f"Total Menunggak: {summary['total_angsuran_menunggak']} berkas | Pokok + Bunga: Rp {summary['total_tunggakan_pokok_bunga']:,.0f}"
        buf = report_service.export_to_pdf("Laporan Kredit Bermasalah & Tunggakan Angsuran", headers, keys, rows, sum_text)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Laporan_Tunggakan_{today_str}.pdf"}
        )

    return {
        "metadata": {
            "report_name": "Laporan Tunggakan & Kredit Bermasalah",
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M WIB"),
            "total_records": total_count,
            "current_page": page,
            "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
            "limit": limit
        },
        "summary": summary,
        "data": rows
    }

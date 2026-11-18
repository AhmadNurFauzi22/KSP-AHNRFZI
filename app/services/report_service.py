import io
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_, and_

# Excel & PDF Libraries
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from app.db.models.member import Member, MemberStatus
from app.db.models.employee import Employee
from app.db.models.savings import SavingsAccount, SavingsProduct, SavingsTransaction
from app.db.models.loan import Loan, LoanInstallment, LoanPayment, LoanStatus, LoanProduct
from app.db.models.transaction import CashTransaction, CashDirection, CashCategory
from app.services import cashier_service


def format_currency_idr(amount: Any) -> str:
    """Format nominal ke format standar mata uang Rupiah Indonesia."""
    try:
        val = float(amount or 0)
        return f"Rp {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"Rp {amount}"


# =============================================================================
# 1. QUERY REPORT DATA
# =============================================================================

def get_members_report(
    db: Session,
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    unit_filter: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
    hide_financial: bool = False
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """Laporan Data Keanggotaan KSP AHNRFZI."""
    query = db.query(Member)

    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                Member.full_name.ilike(s),
                Member.member_no.ilike(s),
                Member.nik.ilike(s),
                Member.phone_number.ilike(s)
            )
        )
    if status_filter:
        query = query.filter(Member.status == status_filter.upper())
    if unit_filter:
        query = query.filter(Member.unit_divisi.ilike(f"%{unit_filter}%"))
    if start_date:
        query = query.filter(Member.join_date >= start_date)
    if end_date:
        query = query.filter(Member.join_date <= end_date)

    total_count = query.count()
    members = query.order_by(Member.member_no.asc()).offset(skip).limit(limit).all()

    # Summaries
    active_count = db.query(func.count(Member.id)).filter(Member.status.in_([MemberStatus.AKTIF.value, "ACTIVE"])).scalar() or 0
    candidate_count = db.query(func.count(Member.id)).filter(Member.status.in_([MemberStatus.CALON.value, "PENDING"])).scalar() or 0
    inactive_count = db.query(func.count(Member.id)).filter(Member.status.in_([MemberStatus.NONAKTIF.value, MemberStatus.KELUAR.value, "SUSPENDED", "RESIGNED"])).scalar() or 0

    rows = []
    # Prompt #14: agregat batch sekali jalan (ganti 2 query per baris)
    sav_map: Dict[int, float] = {}
    loan_map: Dict[int, float] = {}
    if not hide_financial and members:
        mids = [m.id for m in members]
        for mid, tot in db.query(
                SavingsAccount.member_id,
                func.coalesce(func.sum(SavingsAccount.balance), 0)
        ).filter(SavingsAccount.member_id.in_(mids),
                 SavingsAccount.status == "ACTIVE"
                 ).group_by(SavingsAccount.member_id).all():
            sav_map[mid] = float(tot or 0)
        for mid, tot in db.query(
                Loan.member_id,
                func.coalesce(func.sum(Loan.remaining_principal), 0)
        ).filter(Loan.member_id.in_(mids),
                 Loan.status.in_([LoanStatus.BERJALAN.value, "ACTIVE"])
                 ).group_by(Loan.member_id).all():
            loan_map[mid] = float(tot or 0)
    for idx, m in enumerate(members, start=skip + 1):
        row = {
            "no": idx,
            "no_anggota": m.member_no,
            "nik": m.nik,
            "nama_lengkap": m.full_name,
            "unit_divisi": m.unit_divisi or "-",
            "jabatan": m.jabatan or "-",
            "status": m.status,
            "telepon": m.phone_number,
            "tanggal_gabung": m.join_date.strftime("%d/%m/%Y") if m.join_date else "-"
        }
        if not hide_financial:
            row["total_simpanan"] = sav_map.get(m.id, 0.0)
            row["sisa_pinjaman"] = loan_map.get(m.id, 0.0)
        rows.append(row)

    summary = {
        "total_anggota": total_count,
        "aktif": active_count,
        "calon": candidate_count,
        "nonaktif": inactive_count,
        "hide_financial": hide_financial
    }
    return rows, total_count, summary


def get_savings_report(
    db: Session,
    search: Optional[str] = None,
    product_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """Laporan Rekening & Saldo Simpanan KSP AHNRFZI."""
    query = db.query(SavingsAccount).join(Member).join(SavingsProduct)

    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                SavingsAccount.account_no.ilike(s),
                Member.full_name.ilike(s),
                Member.member_no.ilike(s)
            )
        )
    if product_id:
        query = query.filter(SavingsAccount.product_id == product_id)
    if status_filter:
        query = query.filter(SavingsAccount.status == status_filter.upper())
    if start_date:
        query = query.filter(SavingsAccount.opened_date >= start_date)
    if end_date:
        query = query.filter(SavingsAccount.opened_date <= end_date)

    total_count = query.count()
    total_balance = query.with_entities(func.coalesce(func.sum(SavingsAccount.balance), 0)).scalar() or Decimal("0.0")

    accounts = query.order_by(SavingsAccount.account_no.asc()).offset(skip).limit(limit).all()

    rows = []
    for idx, acc in enumerate(accounts, start=skip + 1):
        rows.append({
            "no": idx,
            "no_rekening": acc.account_no,
            "no_anggota": acc.member.member_no if acc.member else "-",
            "nama_anggota": acc.member.full_name if acc.member else "-",
            "produk": acc.product.name if acc.product else "-",
            "saldo": float(acc.balance or 0),
            "status": acc.status,
            "tanggal_buka": acc.opened_date.strftime("%d/%m/%Y") if acc.opened_date else "-"
        })

    summary = {
        "total_rekening": total_count,
        "total_saldo": float(total_balance)
    }
    return rows, total_count, summary


def get_loans_report(
    db: Session,
    search: Optional[str] = None,
    product_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """Laporan Portofolio Pinjaman KSP AHNRFZI."""
    query = db.query(Loan).join(Member).join(LoanProduct)

    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                Loan.loan_no.ilike(s),
                Member.full_name.ilike(s),
                Member.member_no.ilike(s)
            )
        )
    if product_id:
        query = query.filter(Loan.product_id == product_id)
    if status_filter:
        query = query.filter(Loan.status == status_filter.upper())
    if start_date:
        q_start = datetime(start_date.year, start_date.month, start_date.day)
        query = query.filter(Loan.created_at >= q_start)
    if end_date:
        q_end = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
        query = query.filter(Loan.created_at <= q_end)

    total_count = query.count()
    loans = query.order_by(desc(Loan.id)).offset(skip).limit(limit).all()

    total_plafon = query.with_entities(func.coalesce(func.sum(Loan.approved_amount), 0)).scalar() or Decimal("0.0")
    total_outstanding = query.with_entities(func.coalesce(func.sum(Loan.remaining_principal), 0)).scalar() or Decimal("0.0")

    rows = []
    for idx, l in enumerate(loans, start=skip + 1):
        rows.append({
            "no": idx,
            "no_pinjaman": l.loan_no,
            "no_anggota": l.member.member_no if l.member else "-",
            "nama_anggota": l.member.full_name if l.member else "-",
            "produk": l.product.name if l.product else "-",
            "nominal_plafon": float(l.approved_amount or l.requested_amount or 0),
            "tenor_bulan": l.tenor_months,
            "bunga": f"{l.interest_rate_percent}% ({l.calculation_type})",
            "sisa_pokok": float(l.remaining_principal or 0),
            "status": l.status,
            "tanggal_cair": l.disbursed_at.strftime("%d/%m/%Y") if l.disbursed_at else "-"
        })

    summary = {
        "total_pinjaman_count": total_count,
        "total_plafon": float(total_plafon),
        "total_outstanding": float(total_outstanding)
    }
    return rows, total_count, summary


def get_installments_report(
    db: Session,
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """Laporan Realisasi & Tagihan Angsuran KSP AHNRFZI."""
    query = db.query(LoanInstallment).join(Loan).join(Member)

    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                Loan.loan_no.ilike(s),
                Member.full_name.ilike(s),
                Member.member_no.ilike(s)
            )
        )
    if status_filter:
        query = query.filter(LoanInstallment.status == status_filter.upper())
    if start_date:
        query = query.filter(LoanInstallment.due_date >= start_date)
    if end_date:
        query = query.filter(LoanInstallment.due_date <= end_date)

    total_count = query.count()
    installments = query.order_by(LoanInstallment.due_date.asc()).offset(skip).limit(limit).all()

    total_due = query.with_entities(func.coalesce(func.sum(LoanInstallment.total_due), 0)).scalar() or Decimal("0.0")
    total_paid = query.with_entities(func.coalesce(func.sum(LoanInstallment.total_paid), 0)).scalar() or Decimal("0.0")

    rows = []
    for idx, inst in enumerate(installments, start=skip + 1):
        sisa = float(inst.total_due or 0) - float(inst.total_paid or 0)
        rows.append({
            "no": idx,
            "no_pinjaman": inst.loan.loan_no if inst.loan else "-",
            "angsuran_ke": f"{inst.installment_no}/{inst.loan.tenor_months if inst.loan else '-'}",
            "nama_anggota": inst.loan.member.full_name if (inst.loan and inst.loan.member) else "-",
            "jatuh_tempo": inst.due_date.strftime("%d/%m/%Y"),
            "pokok": float(inst.principal_due or 0),
            "bunga": float(inst.interest_due or 0),
            "total_tagihan": float(inst.total_due or 0),
            "total_dibayar": float(inst.total_paid or 0),
            "sisa_tagihan": max(0.0, sisa),
            "status": inst.status
        })

    summary = {
        "total_jadwal_count": total_count,
        "total_tagihan": float(total_due),
        "total_dibayar": float(total_paid),
        "total_sisa": float(total_due - total_paid)
    }
    return rows, total_count, summary


def get_cash_report(
    db: Session,
    search: Optional[str] = None,
    direction: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """Laporan Mutasi Buku Kas KSP AHNRFZI."""
    query = db.query(CashTransaction)

    if search:
        s = f"%{search}%"
        query = query.outerjoin(Member, CashTransaction.member_id == Member.id).filter(
            or_(
                CashTransaction.transaction_no.ilike(s),
                CashTransaction.receipt_no.ilike(s),
                CashTransaction.notes.ilike(s),
                Member.full_name.ilike(s)
            )
        )
    if direction:
        query = query.filter(CashTransaction.direction == direction.upper())
    if category:
        query = query.filter(CashTransaction.category == category.upper())
    if start_date:
        start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
        query = query.filter(CashTransaction.created_at >= start_dt)
    if end_date:
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
        query = query.filter(CashTransaction.created_at <= end_dt)

    total_count = query.count()
    txs = query.order_by(desc(CashTransaction.created_at)).offset(skip).limit(limit).all()

    total_in = query.filter(CashTransaction.direction == CashDirection.CASH_IN.value).with_entities(
        func.coalesce(func.sum(CashTransaction.amount), 0)
    ).scalar() or Decimal("0.0")

    total_out = query.filter(CashTransaction.direction == CashDirection.CASH_OUT.value).with_entities(
        func.coalesce(func.sum(CashTransaction.amount), 0)
    ).scalar() or Decimal("0.0")

    rows = []
    for idx, tx in enumerate(txs, start=skip + 1):
        cat_label = cashier_service.CATEGORY_LABELS.get(tx.category, tx.category)
        rows.append({
            "no": idx,
            "no_transaksi": tx.transaction_no,
            "no_kuitansi": tx.receipt_no,
            "waktu": tx.created_at.strftime("%d/%m/%Y %H:%M"),
            "kasir": tx.cashier.full_name if tx.cashier else "Kasir",
            "arah": "KAS MASUK" if tx.direction == "CASH_IN" else "KAS KELUAR",
            "kategori": cat_label,
            "nominal": float(tx.amount or 0),
            "metode": tx.payment_method,
            "anggota": tx.member.full_name if tx.member else "-",
            "status": "DIBATALKAN" if tx.is_reversed else "FINAL"
        })

    summary = {
        "total_transaksi_count": total_count,
        "total_kas_masuk": float(total_in),
        "total_kas_keluar": float(total_out),
        "net_cash_flow": float(total_in - total_out)
    }
    return rows, total_count, summary


def get_overdue_report(
    db: Session,
    search: Optional[str] = None,
    min_days: int = 1,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """Laporan Kredit Bermasalah / Tunggakan Angsuran KSP AHNRFZI."""
    today = datetime.now(timezone.utc).date()
    cutoff_date = today - timedelta(days=min_days - 1)

    query = db.query(LoanInstallment).join(Loan).join(Member).filter(
        LoanInstallment.due_date <= cutoff_date,
        LoanInstallment.total_paid < LoanInstallment.total_due
    )

    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                Loan.loan_no.ilike(s),
                Member.full_name.ilike(s),
                Member.member_no.ilike(s)
            )
        )
    if start_date:
        query = query.filter(LoanInstallment.due_date >= start_date)
    if end_date:
        query = query.filter(LoanInstallment.due_date <= end_date)

    total_count = query.count()
    overdue_items = query.order_by(LoanInstallment.due_date.asc()).offset(skip).limit(limit).all()

    total_overdue = query.with_entities(
        func.coalesce(func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0)
    ).scalar() or Decimal("0.0")

    rows = []
    for idx, inst in enumerate(overdue_items, start=skip + 1):
        days_late = (today - inst.due_date).days
        sisa = float(inst.total_due or 0) - float(inst.total_paid or 0)
        # Kalkulasi estimasi denda
        rate = float(inst.loan.product.penalty_rate_daily or 0.001) if inst.loan and inst.loan.product else 0.001
        penalty = sisa * rate * days_late

        rows.append({
            "no": idx,
            "no_pinjaman": inst.loan.loan_no if inst.loan else "-",
            "angsuran_ke": f"{inst.installment_no}/{inst.loan.tenor_months if inst.loan else '-'}",
            "no_anggota": inst.loan.member.member_no if (inst.loan and inst.loan.member) else "-",
            "nama_anggota": inst.loan.member.full_name if (inst.loan and inst.loan.member) else "-",
            "unit_divisi": inst.loan.member.unit_divisi if (inst.loan and inst.loan.member) else "-",
            "telepon": inst.loan.member.phone_number if (inst.loan and inst.loan.member) else "-",
            "jatuh_tempo": inst.due_date.strftime("%d/%m/%Y"),
            "hari_terlambat": days_late,
            "tunggakan_pokok_bunga": sisa,
            "estimasi_denda": round(penalty, 2),
            "total_kewajiban": round(sisa + penalty, 2)
        })

    summary = {
        "total_angsuran_menunggak": total_count,
        "total_tunggakan_pokok_bunga": float(total_overdue)
    }
    return rows, total_count, summary


# =============================================================================
# 2. EXCEL EXPORT GENERATOR (OPENPYXL)
# =============================================================================

def export_to_excel(
    report_title: str,
    headers: List[str],
    keys: List[str],
    rows: List[Dict[str, Any]],
    summary_text: Optional[str] = None
) -> io.BytesIO:
    """
    Menghasilkan file Excel (.xlsx) resmi KSP AHNRFZI dengan styling profesional:
    - Kop Koperasi Simpan Pinjam AHNRFZI
    - Header berlatar biru korporat (#1E3A8A)
    - Auto column width
    - Format number & currency
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Laporan KSP AHNRFZI"

    # 1. Header Lembaga
    ws.merge_cells("A1:H1")
    title_cell = ws["A1"]
    title_cell.value = "KOPERASI SIMPAN PINJAM AHNRFZI"
    title_cell.font = Font(name="Arial", size=15, bold=True, color="1E3A8A")
    title_cell.alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:H2")
    sub_cell = ws["A2"]
    sub_cell.value = f"LAPORAN RESMI: {report_title.upper()}"
    sub_cell.font = Font(name="Arial", size=11, bold=True, color="333333")
    sub_cell.alignment = Alignment(horizontal="center")

    ws.merge_cells("A3:H3")
    date_cell = ws["A3"]
    date_cell.value = f"Waktu Cetak: {datetime.now().strftime('%d/%m/%Y %H:%M WIB')} | AHU-0012948.AH.01.26.TAHUN 2026"
    date_cell.font = Font(name="Arial", size=8, italic=True, color="666666")
    date_cell.alignment = Alignment(horizontal="center")

    # 2. Table Headers
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Arial", size=9, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )

    start_row = 5
    for col_idx, h_text in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col_idx, value=h_text)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 3. Data Rows
    for r_idx, row_data in enumerate(rows, start=start_row + 1):
        alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid") if r_idx % 2 == 0 else None
        for c_idx, k in enumerate(keys, start=1):
            val = row_data.get(k, "-")
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = Font(name="Arial", size=8.5)
            cell.border = thin_border
            if alt_fill:
                cell.fill = alt_fill

            # Formatting
            if isinstance(val, (int, float, Decimal)):
                if any(curr_kw in k.lower() for curr_kw in ["saldo", "plafon", "pokok", "bunga", "tagihan", "dibayar", "nominal", "tunggakan", "denda", "kewajiban", "simpanan", "pinjaman"]):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal="right")
                else:
                    cell.alignment = Alignment(horizontal="center")
            elif k in ["no", "status", "jatuh_tempo", "tanggal_gabung", "tanggal_buka", "tanggal_cair", "waktu", "arah"]:
                cell.alignment = Alignment(horizontal="center")

    # 4. Summary Text Row
    if summary_text:
        last_row = start_row + len(rows) + 2
        ws.cell(row=last_row, column=1, value=f"* Catatan: {summary_text}").font = Font(name="Arial", size=8, italic=True)

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 35)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


# =============================================================================
# 3. PDF EXPORT GENERATOR (REPORTLAB)
# =============================================================================

def export_to_pdf(
    report_title: str,
    headers: List[str],
    keys: List[str],
    rows: List[Dict[str, Any]],
    summary_text: Optional[str] = None
) -> io.BytesIO:
    """
    Menghasilkan file PDF resmi KSP AHNRFZI (A4 Landscape) dengan layout kop surat,
    tabel bergaris rapi, penomoran halaman, dan blok tanda tangan pengurus.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=25,
        leftMargin=25,
        topMargin=25,
        bottomMargin=25
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1  # Center
    )
    sub_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#333333'),
        alignment=1
    )
    info_style = ParagraphStyle(
        'DocInfo',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#666666'),
        alignment=1
    )
    cell_style = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9
    )

    story = []

    # 1. Header Kop Surat
    story.append(Paragraph("KOPERASI SIMPAN PINJAM AHNRFZI", title_style))
    story.append(Paragraph(f"LAPORAN RESMI: {report_title.upper()}", sub_style))
    story.append(Paragraph(f"Badan Hukum: AHU-0012948.AH.01.26.TAHUN 2026 | Tanggal Cetak: {datetime.now().strftime('%d/%m/%Y %H:%M WIB')}", info_style))
    story.append(Spacer(1, 12))

    # 2. Prepare Table Data
    table_data = [[Paragraph(f"<b>{h}</b>", cell_style) for h in headers]]

    for r in rows:
        row_cells = []
        for k in keys:
            val = r.get(k, "-")
            if isinstance(val, (int, float, Decimal)) and any(kw in k.lower() for kw in ["saldo", "plafon", "pokok", "bunga", "tagihan", "dibayar", "nominal", "tunggakan", "denda", "kewajiban"]):
                val_str = f"Rp {float(val):,.0f}".replace(",", ".")
            else:
                val_str = str(val)
            row_cells.append(Paragraph(val_str, cell_style))
        table_data.append(row_cells)

    # 3. Create Styled Table
    pdf_table = Table(table_data, repeatRows=1)
    pdf_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        ('TOPPADDING', (0, 0), (-1, 0), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#FFFFFF'), colors.HexColor('#F8FAFC')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0, 1), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
    ]))
    story.append(pdf_table)

    # 4. Summary & Signatures
    story.append(Spacer(1, 15))
    if summary_text:
        story.append(Paragraph(f"<i>* Ringkasan: {summary_text}</i>", info_style))
        story.append(Spacer(1, 10))

    # Signature Block
    sig_data = [
        [
            Paragraph("<b>Dibuat Oleh:</b><br/><br/><br/>( Petugas Kasir / Staf )", info_style),
            Paragraph("<b>Diperiksa Oleh:</b><br/><br/><br/>( Manager Operasional )", info_style),
            Paragraph("<b>Disahkan Oleh:</b><br/><br/><br/>( Ketua Umum KSP AHNRFZI )", info_style)
        ]
    ]
    sig_table = Table(sig_data, colWidths=[240, 240, 240])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(sig_table)

    doc.build(story)
    buffer.seek(0)
    return buffer

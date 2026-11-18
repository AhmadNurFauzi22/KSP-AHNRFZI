import time
import os
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.core.database import get_db, Base, engine
from app.core.logging import logger
from app.core.security import decode_access_token
from app.core.permissions import get_user_permissions
from app.core.exceptions import KSPException, ksp_exception_handler, global_http_exception_handler
from app.api.api_router import api_router
from app.db.models.user import User
from app.db.models.audit_log import AuditLog

# Initialize FastAPI Application (Prompt #11: docs dimatikan di luar debug)
app = FastAPI(
    title=settings.APP_NAME,
    description="Sistem Informasi Koperasi Simpan Pinjam AHNRFZI - FinTech Backend & Portal",
    version="1.0.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url="/redoc" if settings.APP_DEBUG else None
)

# Exception handlers
app.add_exception_handler(KSPException, ksp_exception_handler)
app.add_exception_handler(HTTPException, global_http_exception_handler)


@app.exception_handler(Exception)
async def global_unhandled_exception_handler(request: Request, exc: Exception):
    """Fallback agar /api/* selalu JSON (bukan 'Internal Server Error' plain-text)."""
    logger.exception(f"Unhandled [{type(exc).__name__}] on {request.url.path}: {exc}")
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "detail": "Terjadi kesalahan internal server. Coba lagi nanti.",
                "error": {"code": "HTTP_500", "message": "Terjadi kesalahan internal server."},
            },
        )
    return HTMLResponse(content="<h1>Terjadi Kesalahan Internal</h1>", status_code=500)

# CORS Configuration (Prompt #11: tanpa wildcard + credentials)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    max_age=600,
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Header keamanan dasar yang tidak merusak SSR/inline-JS existing."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

# Static files & Jinja2 Templates setup
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Include REST API Router
app.include_router(api_router)







@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Header keamanan dasar yang tidak merusak SSR/inline-JS existing."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

# Static files & Jinja2 Templates setup
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Include REST API Router
app.include_router(api_router)


@app.on_event("startup")
async def telegram_polling_startup():
    """Ini akan dijalankan saat startup FastAPI.
    
    Sistem hanya mengkonfigurasi pengiriman notifikasi satu arah (sendMessage).
    Tidak memulai long polling (getUpdates) untuk menghindari konflik Error 409.
    Fitur linking / unlinking akun melalui webhook tetap tersedia.
    """
    from app.services.telegram_service import TelegramService
    
    # Cek konfigurasi Telegram
    # Telegram dianggap terkonfigurasi jika bot token telah diisi di environment/.env
    if settings.telegram_configured:
        logger.info("[TELEGRAM] Konfigurasi terdeteksi. Notifikasi akan dikirim via sendMessage (satu arah).")
        # Polling dinonaktifkan - gunakan sendMessage untuk notifikasi satu arah
        # Fitur linking/unlinking melalui webhook tetap tersedia saat dibutuhkan
    else:
        logger.info("[TELEGRAM] Konfigurasi Telegram belum lengkap. Notifikasi telegram dinonaktif.")
    
    # Cek JWT dan APP_SECRET
    if settings.JWT_SECRET_KEY == "ksp-ahnrfzi-jwt-secret-token-key-2026":
        logger.warning("[SECURITY] JWT_SECRET_KEY masih default — set via env JWT_SECRET_KEY di produksi!")
    if settings.APP_SECRET_KEY == "ksp-ahnrfzi-super-secret-key-change-in-production-2026":
        logger.warning("[SECURITY] APP_SECRET_KEY masih default — set via env APP_SECRET_KEY di produksi!")
    
    # Polling dinonaktifkan sepenuhnya.
    # Aplikasi hanyabutuhan notifikasi keluar melalui sendMessage ke Telegram Admin.
    # Long polling (getUpdates) dinonaktifkan untuk menghindari Error 409 konflik.
    logger.info("[TELEGRAM] Long polling (getUpdates) dinonaktif. Gunakan sendMessage untuk notifikasi satu arah.")
# Request Logging Middleware
@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} ({duration:.3f}s)")
    return response


# Helper to get authenticated user and permissions from cookie on Web Pages
def get_web_user(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        auth_hdr = request.headers.get("Authorization")
        if auth_hdr:
            token = auth_hdr
    if not token:
        return None, None, set()
    if token.startswith("Bearer "):
        token = token.split(" ")[1]
        
    payload = decode_access_token(token)
    if not payload:
        return None, None, set()
        
    user_id = payload.get("sub")
    if not user_id:
        return None, None, set()
        
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        return None, None, set()
        
    active_role = payload.get("active_role")
    if not active_role and user.roles:
        active_role = user.roles[0].code
        
    user_perms = get_user_permissions(user, active_role)
    return user, active_role, user_perms


# --------------------------------------------------------------------------
# Web Page Views
# --------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    """Render Login Page."""
    user, _, _ = get_web_user(request, db)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={}
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    """Render Main Dashboard Page (role-based, data aktual dari database)."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    from app.services import dashboard_service
    role = active_role or (user.roles[0].code if user.roles else "ANGGOTA")
    try:
        dashboard_data = dashboard_service.get_dashboard_data_by_role(db, user, role, user_perms)
    except Exception as e:
        logger.error(f"[DASHBOARD] gagal memuat data role={role}: {e}")
        dashboard_data = {"role": role, "error": "Gagal memuat data dashboard. Coba lagi nanti."}

    # Fetch recent audit logs for dashboard view
    recent_logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(8).all()

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "current_user": user,
            "active_role": role,
            "user_perms": user_perms,
            "active_page": "dashboard",
            "audit_logs": recent_logs,
            "dashboard_data": dashboard_data,
        }
    )


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: Session = Depends(get_db)):
    """Render User Profile & Security Management Page."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    return templates.TemplateResponse(
        request=request,
        name="auth/profile.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "profile"
        }
    )


@app.get("/members", response_class=HTMLResponse)
async def members_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Manajemen Keanggotaan."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    if "member.view" not in user_perms and "ADMIN_KOPERASI" not in [r.code for r in user.roles]:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    from app.db.models.member import Member
    # Statistik ringkas untuk admin
    stats = {
        "total": db.query(Member).count(),
        "aktif": db.query(Member).filter(Member.status == "AKTIF").count(),
        "calon": db.query(Member).filter(Member.status == "CALON").count(),
        "nonaktif": db.query(Member).filter(Member.status == "NONAKTIF").count(),
    }

    return templates.TemplateResponse(
        request=request,
        name="members/index.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "members",
            "stats": stats,
        }
    )


@app.get("/savings", response_class=HTMLResponse)
async def savings_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Modul Simpanan KSP AHNRFZI."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    from sqlalchemy import func
    from decimal import Decimal
    from app.db.models.savings import SavingsAccount, SavingsProduct
    from app.services import savings_service

    is_cashier = (
        bool({"ADMIN_KOPERASI", "KASIR", "MANAGER"} & set(user.role_codes))
        or "saving.transaction" in user_perms
        or "cashier.transaction" in user_perms
    )

    is_staff = bool({
        "ADMIN_KOPERASI", "KETUA_UMUM", "MANAGER",
        "KASIR", "HRD", "STAF", "PENGAWAS_PEMBINA", "IT_PUSAT"
    } & set(user.role_codes))

    # KSP Aggregate Stats — Prompt #11: hanya untuk yang berhak (staf/perm);
    # anggota hanya melihat ringkasan miliknya (my_summary).
    show_global = is_staff or "saving.view" in user_perms or "report.view" in user_perms

    def _sum_type(ptype):
        val = db.query(func.coalesce(func.sum(SavingsAccount.balance), 0)).join(SavingsProduct).filter(
            SavingsProduct.product_type == ptype
        ).scalar()
        return Decimal(str(val))

    stats = {
        "total_all": _sum_type("POKOK") + _sum_type("WAJIB") + _sum_type("SUKARELA"),
        "total_pokok": _sum_type("POKOK"),
        "total_wajib": _sum_type("WAJIB"),
        "total_sukarela": _sum_type("SUKARELA"),
    } if show_global else {
        "total_all": Decimal("0"), "total_pokok": Decimal("0"),
        "total_wajib": Decimal("0"), "total_sukarela": Decimal("0"),
    }

    # Member's own summary if has member profile
    my_summary = None
    if user.member:
        my_summary = savings_service.get_member_savings_summary(user.member.id, db)

    return templates.TemplateResponse(
        request=request,
        name="savings/index.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "savings",
            "is_cashier": is_cashier,
            "is_staff": is_staff,
            "stats": stats,
            "my_summary": my_summary,
        }
    )


@app.get("/loans", response_class=HTMLResponse)
async def loans_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Modul Pinjaman KSP AHNRFZI."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    from sqlalchemy import func
    from decimal import Decimal
    from app.db.models.loan import Loan, LoanProduct, LoanStatus

    # Active products
    products = db.query(LoanProduct).filter(LoanProduct.is_active == True).all()

    # Permissions
    is_staff = bool({
        "ADMIN_KOPERASI", "KETUA_UMUM", "MANAGER",
        "KASIR", "HRD", "STAF", "PENGAWAS_PEMBINA", "IT_PUSAT"
    } & set(user.role_codes))

    can_apply = "loan.create" in user_perms or "ADMIN_KOPERASI" in set(user.role_codes)
    can_verify = "loan.verify" in user_perms or "ADMIN_KOPERASI" in set(user.role_codes)
    can_approve = "loan.approve" in user_perms or "ADMIN_KOPERASI" in set(user.role_codes)
    can_disburse = "loan.disburse" in user_perms or "ADMIN_KOPERASI" in set(user.role_codes)

    # Statistics — Prompt #11: agregat global hanya untuk yang berhak
    show_global = is_staff or bool({"loan.view", "report.view"} & set(user_perms))
    if show_global:
        total_active_amt = db.query(func.coalesce(func.sum(Loan.remaining_principal), 0)).filter(
            Loan.status.in_([LoanStatus.BERJALAN.value, "ACTIVE"])
        ).scalar()

        count_submitted = db.query(func.count(Loan.id)).filter(
            Loan.status.in_([LoanStatus.DIAJUKAN.value, "SUBMITTED"])
        ).scalar()

        count_verified = db.query(func.count(Loan.id)).filter(
            Loan.status.in_([LoanStatus.VERIFIKASI.value, "VERIFIED_STAF"])
        ).scalar()

        count_approved = db.query(func.count(Loan.id)).filter(
            Loan.status.in_([LoanStatus.DISETUJUI.value, "APPROVED_MANAGER", "APPROVED_KETUA"])
        ).scalar()

        count_active = db.query(func.count(Loan.id)).filter(
            Loan.status.in_([LoanStatus.BERJALAN.value, "ACTIVE"])
        ).scalar()

        count_paid_off = db.query(func.count(Loan.id)).filter(
            Loan.status.in_([LoanStatus.LUNAS.value, "PAID_OFF"])
        ).scalar()

        stats = {
            "total_portfolio": Decimal(str(total_active_amt or 0)),
            "count_submitted": count_submitted or 0,
            "count_verified": count_verified or 0,
            "count_approved": count_approved or 0,
            "count_active": count_active or 0,
            "count_paid_off": count_paid_off or 0,
        }
    else:
        stats = {
            "total_portfolio": Decimal("0"), "count_submitted": 0,
            "count_verified": 0, "count_approved": 0,
            "count_active": 0, "count_paid_off": 0,
        }

    # Member's own loan check
    my_active_loan = None
    if user.member:
        my_active_loan = db.query(Loan).filter(
            Loan.member_id == user.member.id,
            Loan.status.in_([LoanStatus.BERJALAN.value, "ACTIVE"])
        ).first()

    return templates.TemplateResponse(
        request=request,
        name="loans/index.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": list(user_perms),
            "active_page": "loans",
            "is_staff": is_staff,
            "can_apply": can_apply,
            "can_verify": can_verify,
            "can_approve": can_approve,
            "can_disburse": can_disburse,
            "products": products,
            "stats": stats,
            "my_active_loan": my_active_loan,
        }
    )


@app.get("/installments", response_class=HTMLResponse)
async def installments_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Modul Angsuran & Tagihan KSP AHNRFZI."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    from sqlalchemy import func
    from decimal import Decimal
    from datetime import datetime, timezone, date, timedelta
    from app.db.models.loan import Loan, LoanInstallment, LoanPayment, LoanStatus
    from app.services import installment_service

    is_cashier = (
        bool({"ADMIN_KOPERASI", "KASIR", "MANAGER"} & set(user.role_codes))
        or "installment.payment" in user_perms
        or "cashier.transaction" in user_perms
    )

    is_staff = bool({
        "ADMIN_KOPERASI", "KETUA_UMUM", "MANAGER",
        "KASIR", "HRD", "STAF", "PENGAWAS_PEMBINA", "IT_PUSAT"
    } & set(user.role_codes))

    today = datetime.now(timezone.utc).date()
    first_day_month = date(today.year, today.month, 1)
    if today.month == 12:
        last_day_month = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day_month = date(today.year, today.month + 1, 1) - timedelta(days=1)

    # Aggregate metrics — Prompt #11: hanya untuk yang berhak melihat agregat
    # (installment.view/loan.view/report.view); anggota hanya member_summary.
    show_global = is_staff or bool({"installment.view", "loan.view", "report.view"} & set(user_perms))
    if show_global:
        due_this_month = db.query(func.coalesce(func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0)).filter(
            LoanInstallment.due_date >= first_day_month,
            LoanInstallment.due_date <= last_day_month,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).scalar()

        overdue_amt = db.query(func.coalesce(func.sum(LoanInstallment.total_due - LoanInstallment.total_paid), 0)).filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).scalar()

        overdue_count = db.query(func.count(LoanInstallment.id)).filter(
            LoanInstallment.due_date < today,
            LoanInstallment.total_paid < LoanInstallment.total_due
        ).scalar()

        total_payments = db.query(func.coalesce(func.sum(LoanPayment.amount_paid), 0)).scalar()

        total_portfolio_remaining = db.query(func.coalesce(func.sum(Loan.remaining_principal), 0)).filter(
            Loan.status.in_([LoanStatus.BERJALAN.value, "ACTIVE"])
        ).scalar()

        stats = {
            "due_this_month": Decimal(str(due_this_month or 0)),
            "overdue_amount": Decimal(str(overdue_amt or 0)),
            "overdue_count": overdue_count or 0,
            "total_payments_received": Decimal(str(total_payments or 0)),
            "total_portfolio_remaining": Decimal(str(total_portfolio_remaining or 0)),
        }
    else:
        stats = {
            "due_this_month": Decimal("0"), "overdue_amount": Decimal("0"),
            "overdue_count": 0, "total_payments_received": Decimal("0"),
            "total_portfolio_remaining": Decimal("0"),
        }

    # Member summary if user has linked member
    member_summary = None
    if user.member:
        member_summary = installment_service.get_member_installment_overview(db, user.member.id)

    return templates.TemplateResponse(
        request=request,
        name="installments/index.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": list(user_perms),
            "active_page": "installments",
            "is_cashier": is_cashier,
            "is_staff": is_staff,
            "stats": stats,
            "member_summary": member_summary,
        }
    )


@app.get("/cashier", response_class=HTMLResponse)
async def cashier_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Modul Kasir & Loket Koperasi."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    from app.db.models.transaction import CashRegister, CashTransaction, CashDirection, CashCategory
    from app.services import cashier_service

    is_cashier = bool(
        {"ADMIN_KOPERASI", "KASIR", "MANAGER"} & set(user.role_codes)
        or "cashier.view" in user_perms
        or "cashier.transaction" in user_perms
    )

    is_staff = bool({
        "ADMIN_KOPERASI", "KETUA_UMUM", "MANAGER",
        "KASIR", "HRD", "STAF", "PENGAWAS_PEMBINA", "IT_PUSAT"
    } & set(user.role_codes))

    today = datetime.now(timezone.utc).date()
    start_dt = datetime(today.year, today.month, today.day, 0, 0, 0)
    end_dt = datetime(today.year, today.month, today.day, 23, 59, 59)

    # Active shift for current user
    active_shift = cashier_service.get_active_register(db, user.id)

    # Prompt #11: agregat kas global hanya untuk yang berhak (cashier.view/dst)
    show_global = is_staff or bool({"cashier.view", "cashier.transaction", "report.view"} & set(user_perms))
    if show_global:
        # Today cash in & cash out metrics
        today_in = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.created_at >= start_dt,
            CashTransaction.created_at <= end_dt,
            CashTransaction.direction == CashDirection.CASH_IN.value
        ).scalar()

        today_out = db.query(func.coalesce(func.sum(CashTransaction.amount), 0)).filter(
            CashTransaction.created_at >= start_dt,
            CashTransaction.created_at <= end_dt,
            CashTransaction.direction == CashDirection.CASH_OUT.value
        ).scalar()

        today_count = db.query(func.count(CashTransaction.id)).filter(
            CashTransaction.created_at >= start_dt,
            CashTransaction.created_at <= end_dt
        ).scalar()

        system_cash = float(active_shift.closing_balance) if active_shift else (float(today_in or 0) - float(today_out or 0))

        stats = {
            "today_in": Decimal(str(today_in or 0)),
            "today_out": Decimal(str(today_out or 0)),
            "today_net": Decimal(str(today_in or 0)) - Decimal(str(today_out or 0)),
            "today_count": today_count or 0,
            "system_cash": Decimal(str(system_cash or 0)),
            "active_shift": active_shift
        }
    else:
        stats = {
            "today_in": Decimal("0"), "today_out": Decimal("0"),
            "today_net": Decimal("0"), "today_count": 0,
            "system_cash": Decimal("0"), "active_shift": active_shift
        }

    return templates.TemplateResponse(
        request=request,
        name="cashier/index.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": list(user_perms),
            "active_page": "cashier",
            "is_cashier": is_cashier,
            "is_staff": is_staff,
            "stats": stats,
            "active_shift": active_shift,
        }
    )


@app.get("/employees", response_class=HTMLResponse)
async def employees_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Manajemen Kepegawaian (HRD)."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if "employee.view" not in user_perms and "ADMIN_KOPERASI" not in [r.code for r in user.roles]:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    can_create = "employee.create" in user_perms or "ADMIN_KOPERASI" in [r.code for r in user.roles]
    can_update = "employee.update" in user_perms or "ADMIN_KOPERASI" in [r.code for r in user.roles]
    return templates.TemplateResponse(
        request=request,
        name="employees/index.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "employees",
            "can_create": can_create,
            "can_update": can_update,
        }
    )


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Laporan Manajerial (filter, pagination, export, print)."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    # Prompt #11: selaras dengan API (report.view wajib; ADMIN bypass via perm processed)
    if "report.view" not in user_perms and "ADMIN_KOPERASI" not in [r.code for r in user.roles]:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="reports/index.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "reports",
        }
    )


@app.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Audit Trail (role yang berhak saja)."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    allowed = ({"ADMIN_KOPERASI", "PENGAWAS_PEMBINA", "IT_PUSAT"} & set(r.code for r in user.roles)) or "audit.view" in user_perms
    if not allowed:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    return templates.TemplateResponse(
        request=request,
        name="audit/index.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "audit",
            "logs": logs,
        }
    )


@app.get("/logout")
async def logout_page():
    """Logout redirect helper."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response


@app.get("/whatsapp/config", response_class=HTMLResponse)
async def whatsapp_config_page(request: Request, db: Session = Depends(get_db)):
    """Render Halaman Konfigurasi Notifikasi WhatsApp (Fonnte)."""
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if "system.manage" not in user_perms and not any(r.code in ("ADMIN_KOPERASI", "IT_PUSAT") for r in user.roles):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="whatsapp_config.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "whatsapp_config",
        }
    )


@app.get("/ai-config", response_class=HTMLResponse)
async def ai_config_page(request: Request, db: Session = Depends(get_db)):
    """Halaman Konfigurasi Assistant AI."""
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    
    from app.core.database import get_db
    from sqlalchemy.orm import Session
    
    # Get web user
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    # Cek permission - hanya Admin Koperasi dan Admin yang boleh
    if not ("ADMIN_KOPERASI" in [r.code for r in user.roles] or "ADMIN" in [r.code for r in user.roles]):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    
    return templates.TemplateResponse(
        request=request,
        name="ai_config.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "ai_config",
        }
    )


@app.get("/rbac-koperasi", response_class=HTMLResponse)
async def rbac_koperasi_page(request: Request, db: Session = Depends(get_db)):
    """Halaman RBAC Admin Koperasi."""
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    
    from app.core.database import get_db
    from sqlalchemy.orm import Session
    
    # Get web user
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    # Cek permission - hanya Admin Koperasi dan Admin yang boleh
    if not ("ADMIN_KOPERASI" in [r.code for r in user.roles] or "ADMIN" in [r.code for r in user.roles]):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    
    return templates.TemplateResponse(
        request=request,
        name="rbac_koperasi.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "rbac_koperasi",
        }
    )


@app.get("/rbac-it-pusat", response_class=HTMLResponse)
async def rbac_it_pusat_page(request: Request, db: Session = Depends(get_db)):
    """Halaman RBAC Admin IT Pusat."""
    from fastapi.responses import HTMLResponse
    from fastapi import Request
    
    from app.core.database import get_db
    from sqlalchemy.orm import Session
    
    # Get web user
    user, active_role, user_perms = get_web_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    # Cek permission - hanya IT_PUSAT dan Admin yang boleh
    has_it_pusat = "IT_PUSAT" in [r.code for r in user.roles]
    has_admin = "ADMIN_KOPERASI" in [r.code for r in user.roles] or "ADMIN" in [r.code for r in user.roles]
    
    if not (has_it_pusat or has_admin):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    
    return templates.TemplateResponse(
        request=request,
        name="rbac_it_pusat.html",
        context={
            "current_user": user,
            "active_role": active_role or (user.roles[0].code if user.roles else "ANGGOTA"),
            "user_perms": user_perms,
            "active_page": "rbac_it_pusat",
        }
    )


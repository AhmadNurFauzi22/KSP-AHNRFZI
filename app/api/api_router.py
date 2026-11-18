from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.members import router as members_router
from app.api.v1.savings import router as savings_router
from app.api.v1.loans import router as loans_router
from app.api.v1.installments import router as installments_router
from app.api.v1.cashier import router as cashier_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.employees import router as employees_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.reports import router as reports_router
from app.api.v1.audit import router as audit_router
from app.api.v1.ai import router as ai_router
from app.api.v1.ai_config import router as ai_config_router
from app.api.v1.telegram import router as telegram_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(members_router)
api_router.include_router(savings_router)
api_router.include_router(loans_router)
api_router.include_router(installments_router)
api_router.include_router(cashier_router)
api_router.include_router(dashboard_router)
api_router.include_router(employees_router)
api_router.include_router(notifications_router)
api_router.include_router(reports_router)
api_router.include_router(audit_router)
api_router.include_router(ai_router)
api_router.include_router(ai_config_router)
api_router.include_router(telegram_router)

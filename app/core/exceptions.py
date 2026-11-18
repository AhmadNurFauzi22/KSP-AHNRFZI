from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse
from app.core.logging import logger


class KSPException(Exception):
    """Base exception for KSP business logic errors."""
    def __init__(self, message: str, status_code: int = 400, details: dict = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def ksp_exception_handler(request: Request, exc: KSPException):
    logger.warning(f"KSPException on {request.url.path}: {exc.message}")
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "detail": exc.message,
                "error": {
                    "code": "BUSINESS_LOGIC_ERROR",
                    "message": exc.message,
                    "details": exc.details
                }
            }
        )
    return HTMLResponse(
        content=f"<h1>Terjadi Kesalahan</h1><p>{exc.message}</p>",
        status_code=exc.status_code
    )


async def global_http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"HTTPException [{exc.status_code}] on {request.url.path}: {exc.detail}")
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "detail": exc.detail,
                "error": {
                    "code": f"HTTP_{exc.status_code}",
                    "message": exc.detail
                }
            }
        )
    return None  # Let default or custom template handle page requests

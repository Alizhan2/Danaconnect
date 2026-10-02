from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.database import get_db
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.schema_registry import Base  # Register all feature models before routing.
from app.routers.identity import router as identity_router
from app.routers.projects import router as projects_router
from app.routers.bookings import router as bookings_router
from app.routers.governance import router as governance_router
from app.routers.results import router as results_router
from app.routers.operations import router as operations_router
from app.routers.calendar_rules import router as calendar_rules_router
from app.routers.jobs import router as jobs_router
from app.routers.growth import router as growth_router
from app.routers.collaboration import router as collaboration_router
from app.request_limits import RequestSizeLimit
from app.request_diagnostics import RequestDiagnostics
from app.routers.ai import router as ai_router
from app.routers.calendar_export import router as calendar_export_router
from app.routers.notifications import router as notifications_router
from app.routers.engagement import router as engagement_router


app = FastAPI(title="DanaConnect API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.trusted_origins, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Accept-Language"], expose_headers=["X-Request-ID"])
app.add_middleware(RequestSizeLimit)


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin not in settings.trusted_origins:
            return JSONResponse(status_code=403, content={"detail": "Недоверенный источник запроса"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


app.add_middleware(RequestDiagnostics)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Do not return raw inputs, including OTP codes or personal form fields.
    return JSONResponse(status_code=422, content={"detail": "Проверьте заполнение полей", "fields": [".".join(str(part) for part in error["loc"]) for error in exc.errors()]})


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "environment": settings.environment, "demo_mode": settings.demo_mode}


@app.get("/api/v1/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}


app.include_router(identity_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(bookings_router, prefix="/api/v1")
app.include_router(governance_router, prefix="/api/v1")
app.include_router(results_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(calendar_rules_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(growth_router, prefix="/api/v1")
app.include_router(collaboration_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(calendar_export_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(engagement_router, prefix="/api/v1")

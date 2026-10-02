"""Protected bounded scheduler entrypoint for an external cron service."""
import secrets
from fastapi import APIRouter, HTTPException, Request
from app.config import settings
from app.jobs_calendar import run_once

router = APIRouter()


@router.get("/internal/jobs", include_in_schema=False)
def scheduled_jobs(request: Request):
    if len(settings.cron_secret) < 32 or settings.cron_secret == settings.auth_secret:
        raise HTTPException(503, "Планировщик не настроен")
    expected = "Bearer " + settings.cron_secret
    if not secrets.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
        raise HTTPException(401, "Недоступно")
    return run_once()

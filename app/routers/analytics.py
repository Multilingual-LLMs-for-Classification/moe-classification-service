"""
Analytics router for DB-backed classification metrics.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import CurrentUser
from app.services import analytics_service as svc

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


@router.get("/summary")
async def get_analytics_summary(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Aggregated classification analytics across all projects."""
    return svc.get_summary(db)


@router.get("/timeseries")
async def get_timeseries(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    bucket: str = Query("hour", enum=["hour", "day", "week"]),
    days: int = Query(7, ge=1, le=90),
):
    """Request counts per time bucket for the last N days (all projects)."""
    return svc.get_timeseries(db, bucket=bucket, days=days)


@router.get("/per-task")
async def get_per_task(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Per-task metrics across all projects."""
    return svc.get_per_task(db)


@router.get("/per-language")
async def get_per_language(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Per-language metrics across all projects."""
    return svc.get_per_language(db)


@router.get("/per-user")
async def get_per_user(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Per-user usage metrics across all projects."""
    return svc.get_per_user(db)


@router.get("/per-project")
async def get_per_project(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Per-project usage metrics across all projects."""
    return svc.get_per_project(db)


@router.get("/history")
async def get_history(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    from_dt: Optional[datetime] = Query(None),
    to_dt: Optional[datetime] = Query(None),
):
    """Paginated, filterable classification history across all projects."""
    return svc.get_history(
        db,
        page=page,
        page_size=page_size,
        task=task,
        language=language,
        username=username,
        from_dt=from_dt,
        to_dt=to_dt,
    )

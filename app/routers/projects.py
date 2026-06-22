"""
Projects router: CRUD, per-project analytics, and per-project config.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import CurrentUser
from app.schemas.projects import (
    ProjectCreate, ProjectResponse, ProjectList,
    ProjectConfigResponse, ProjectConfigUpdate,
)
from app.services import analytics_service as analytics_svc
from app.services import project_service as svc


# ── Inline request bodies ──

class DefaultGenerationUpdate(BaseModel):
    model_config = {"extra": "allow"}


class TaskConfigUpdate(BaseModel):
    base_model_key: Optional[str] = None
    adapter_name: Optional[str] = None
    adapter_path: Optional[str] = None
    expert_path: Optional[str] = None
    template_path: Optional[str] = None
    strict_label_decoding: Optional[bool] = None
    constrained_single_token: Optional[bool] = None
    label_set: Optional[List[str]] = None
    generation: Optional[Dict[str, Any]] = None
    language_mapping: Optional[Dict[str, Any]] = None
    supported_languages: Optional[List[str]] = None


class LanguageMappingUpdate(BaseModel):
    base_model_key: str
    adapter_name: str
    adapter_path: str
    template_path: Optional[str] = None


router = APIRouter(prefix="/api/v1/projects", tags=["Projects"])


# ── Project CRUD ──

@router.get("", response_model=ProjectList)
async def list_projects(current_user: CurrentUser, db: Session = Depends(get_db)):
    projects = svc.list_projects(db, current_user.username)
    return {"projects": projects, "total": len(projects)}


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, current_user: CurrentUser, db: Session = Depends(get_db)
):
    return svc.create_project(db, body.name, body.description, current_user.username)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    project = svc.get_project(db, project_id, current_user.username)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    if not svc.delete_project(db, project_id, current_user.username):
        raise HTTPException(status_code=404, detail="Project not found")


# ── Per-project analytics ──

@router.get("/{project_id}/analytics/summary")
async def get_project_analytics_summary(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    _require_project(db, project_id, current_user.username)
    return analytics_svc.get_summary(db, project_id=project_id)


@router.get("/{project_id}/analytics/timeseries")
async def get_project_analytics_timeseries(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    bucket: str = Query("hour", enum=["hour", "day", "week"]),
    days: int = Query(7, ge=1, le=90),
):
    _require_project(db, project_id, current_user.username)
    return analytics_svc.get_timeseries(db, bucket=bucket, days=days, project_id=project_id)


@router.get("/{project_id}/analytics/per-task")
async def get_project_analytics_per_task(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    _require_project(db, project_id, current_user.username)
    return analytics_svc.get_per_task(db, project_id=project_id)


@router.get("/{project_id}/analytics/per-language")
async def get_project_analytics_per_language(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    _require_project(db, project_id, current_user.username)
    return analytics_svc.get_per_language(db, project_id=project_id)


@router.get("/{project_id}/analytics/per-user")
async def get_project_analytics_per_user(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    _require_project(db, project_id, current_user.username)
    return analytics_svc.get_per_user(db, project_id=project_id)


@router.get("/{project_id}/analytics/history")
async def get_project_analytics_history(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    from_dt: Optional[datetime] = Query(None),
    to_dt: Optional[datetime] = Query(None),
):
    _require_project(db, project_id, current_user.username)
    return analytics_svc.get_history(
        db, page=page, page_size=page_size, task=task, language=language,
        from_dt=from_dt, to_dt=to_dt, project_id=project_id,
    )


# ── Per-project config ──

@router.get("/{project_id}/config")
async def get_project_config(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Return full assembled config (default_generation + base_models + tasks from DB rows)."""
    _require_project(db, project_id, current_user.username)
    cfg = svc.build_inference_config(db, project_id)
    if cfg is None:
        base = svc.get_project_config(db, project_id)
        if not base:
            raise HTTPException(status_code=404, detail="Config not found for this project")
        cfg = base.get("config_data", {})
    pc = svc.get_project_config(db, project_id)
    return {
        "project_id": project_id,
        "config_data": cfg,
        "updated_at": pc["updated_at"] if pc else None,
    }


@router.put("/{project_id}/config", response_model=ProjectConfigResponse)
async def update_project_config(
    project_id: int,
    body: ProjectConfigUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    _require_project(db, project_id, current_user.username)
    return svc.update_project_config(db, project_id, body.config_data)


# ── Fine-grained config (all DB-backed, per-task rows) ──

@router.get("/{project_id}/config/overview")
async def get_project_config_overview(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Config summary: base model count, task list, language count, default generation."""
    _require_project(db, project_id, current_user.username)
    try:
        return svc.get_project_config_overview(db, project_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch("/{project_id}/config/default-generation")
async def patch_project_default_generation(
    project_id: int,
    body: DefaultGenerationUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Update default generation parameters stored in ProjectConfig."""
    _require_project(db, project_id, current_user.username)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return svc.update_project_default_generation(db, project_id, updates)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/config/reset-defaults")
async def reset_project_config_to_defaults(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Reset all project config (default_generation, base_models, all tasks) to global defaults."""
    _require_project(db, project_id, current_user.username)
    return svc.reset_project_to_defaults(db, project_id)


@router.post("/{project_id}/config/tasks/{task_key:path}/reset-default")
async def reset_project_task_config_to_default(
    project_id: int, task_key: str,
    current_user: CurrentUser, db: Session = Depends(get_db),
):
    """Reset a single task's config to the global default."""
    _require_project(db, project_id, current_user.username)
    try:
        return svc.reset_project_task_to_default(db, project_id, task_key)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id}/config/tasks")
async def list_project_task_configs(
    project_id: int, current_user: CurrentUser, db: Session = Depends(get_db)
):
    """List all task configs for this project (one row per task from ProjectTaskConfig)."""
    _require_project(db, project_id, current_user.username)
    return svc.get_project_task_configs(db, project_id)


@router.get("/{project_id}/config/tasks/{task_key:path}")
async def get_project_task_config(
    project_id: int, task_key: str,
    current_user: CurrentUser, db: Session = Depends(get_db),
):
    """Get a single task's config from ProjectTaskConfig."""
    _require_project(db, project_id, current_user.username)
    task = svc.get_project_task_config(db, project_id, task_key)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_key}' not found")
    return task


@router.patch("/{project_id}/config/tasks/{task_key:path}")
async def patch_project_task_config(
    project_id: int, task_key: str, body: TaskConfigUpdate,
    current_user: CurrentUser, db: Session = Depends(get_db),
):
    """Partial-update a task config row in ProjectTaskConfig."""
    _require_project(db, project_id, current_user.username)
    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        return svc.patch_project_task_config(db, project_id, task_key, updates)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{project_id}/config/tasks/{task_key:path}/languages/{lang}")
async def put_project_language_mapping(
    project_id: int, task_key: str, lang: str, body: LanguageMappingUpdate,
    current_user: CurrentUser, db: Session = Depends(get_db),
):
    """Add or update a language mapping in a task's ProjectTaskConfig row."""
    _require_project(db, project_id, current_user.username)
    try:
        mapping = {k: v for k, v in body.model_dump().items() if v is not None}
        return svc.update_project_task_language_mapping(
            db, project_id, task_key, lang, mapping
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete(
    "/{project_id}/config/tasks/{task_key:path}/languages/{lang}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_language_mapping(
    project_id: int, task_key: str, lang: str,
    current_user: CurrentUser, db: Session = Depends(get_db),
):
    """Delete a language mapping from a task's ProjectTaskConfig row."""
    _require_project(db, project_id, current_user.username)
    try:
        svc.delete_project_task_language_mapping(db, project_id, task_key, lang)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── System default config ──

@router.get("/system/defaults")
async def get_system_default_config(
    current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Return the DB-persisted system default config used for project resets."""
    return svc.get_default_config(db)


@router.post("/system/defaults/sync-filesystem")
async def sync_system_defaults_from_filesystem(
    current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Re-read the filesystem JSON and overwrite the stored system default."""
    return svc.sync_default_config_from_filesystem(db)


@router.put("/system/defaults")
async def update_system_default_config(
    body: ProjectConfigUpdate, current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Replace the stored system default with the provided config (e.g. from a project)."""
    return svc.update_default_config(db, body.config_data)


# ── Helper ──

def _require_project(db: Session, project_id: int, username: str) -> None:
    if not svc.get_project(db, project_id, username):
        raise HTTPException(status_code=404, detail="Project not found")

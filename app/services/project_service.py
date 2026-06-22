"""
Service for project CRUD and per-project configuration management.

Configuration is stored in two DB tables:
  - ProjectConfig       : default_generation + base_models (project-level)
  - ProjectTaskConfig   : one row per (project, task_key) with all task fields
"""

import json
from datetime import datetime, timedelta
import random
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db import ClassificationLog, Project, ProjectConfig, ProjectTaskConfig, SystemDefaultConfig


# ─────────────────────────────────────────────
# Project CRUD
# ─────────────────────────────────────────────

def list_projects(db: Session, username: str) -> List[Project]:
    return (
        db.query(Project)
        .filter(Project.owner_username == username)
        .order_by(Project.created_at.desc())
        .all()
    )


def get_project(db: Session, project_id: int, username: str) -> Optional[Project]:
    return (
        db.query(Project)
        .filter(Project.id == project_id, Project.owner_username == username)
        .first()
    )


def create_project(db: Session, name: str, description: Optional[str], username: str) -> Project:
    project = Project(
        name=name, description=description,
        owner_username=username, created_at=datetime.utcnow(),
    )
    db.add(project)
    db.flush()

    global_cfg = get_default_config(db)

    # Store default_generation + base_models in ProjectConfig
    slim_cfg = {
        "default_generation": global_cfg.get("default_generation", {}),
        "base_models": global_cfg.get("base_models", {}),
    }
    db.add(ProjectConfig(
        project_id=project.id,
        config_data=json.dumps(slim_cfg),
        updated_at=datetime.utcnow(),
    ))

    # Store each task as its own ProjectTaskConfig row
    for task_key, task_data in global_cfg.get("tasks", {}).items():
        db.add(_task_dict_to_row(project.id, task_key, task_data))

    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project_id: int, username: str) -> bool:
    project = get_project(db, project_id, username)
    if not project:
        return False
    db.delete(project)
    db.commit()
    return True


# ─────────────────────────────────────────────
# Project-level config (default_generation + base_models)
# ─────────────────────────────────────────────

def get_project_config(db: Session, project_id: int) -> Optional[Dict[str, Any]]:
    pc = db.query(ProjectConfig).filter(ProjectConfig.project_id == project_id).first()
    if not pc:
        return None
    return {"project_id": project_id, "config_data": json.loads(pc.config_data), "updated_at": pc.updated_at}


def update_project_config(db: Session, project_id: int, config_data: Dict[str, Any]) -> Dict[str, Any]:
    pc = db.query(ProjectConfig).filter(ProjectConfig.project_id == project_id).first()
    if not pc:
        pc = ProjectConfig(project_id=project_id, config_data=json.dumps(config_data), updated_at=datetime.utcnow())
        db.add(pc)
    else:
        pc.config_data = json.dumps(config_data)
        pc.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": project_id, "config_data": config_data, "updated_at": pc.updated_at}


def update_project_default_generation(db: Session, project_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    pc = db.query(ProjectConfig).filter(ProjectConfig.project_id == project_id).first()
    if not pc:
        raise KeyError(f"No config found for project {project_id}")
    cfg = json.loads(pc.config_data)
    cfg.setdefault("default_generation", {}).update(updates)
    pc.config_data = json.dumps(cfg)
    pc.updated_at = datetime.utcnow()
    db.commit()
    return cfg["default_generation"]


# ─────────────────────────────────────────────
# Per-task config (ProjectTaskConfig rows)
# ─────────────────────────────────────────────

def get_project_task_configs(db: Session, project_id: int) -> List[Dict[str, Any]]:
    """Return all task configs for a project as a list of dicts."""
    rows = (
        db.query(ProjectTaskConfig)
        .filter(ProjectTaskConfig.project_id == project_id)
        .order_by(ProjectTaskConfig.task_key)
        .all()
    )
    return [_task_row_to_dict(row) for row in rows]


def get_project_task_config(db: Session, project_id: int, task_key: str) -> Optional[Dict[str, Any]]:
    row = _get_task_row(db, project_id, task_key)
    return _task_row_to_dict(row) if row else None


def upsert_project_task_config(
    db: Session, project_id: int, task_key: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """Create or fully replace a task config row."""
    row = _get_task_row(db, project_id, task_key)
    if not row:
        row = ProjectTaskConfig(project_id=project_id, task_key=task_key)
        db.add(row)
    _apply_task_data(row, data)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _task_row_to_dict(row)


def patch_project_task_config(
    db: Session, project_id: int, task_key: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Partial-update a task config row."""
    row = _get_task_row(db, project_id, task_key)
    if not row:
        raise KeyError(f"Task '{task_key}' not found for project {project_id}")
    _apply_task_data(row, updates)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _task_row_to_dict(row)


def update_project_task_generation(
    db: Session, project_id: int, task_key: str, generation: Dict[str, Any]
) -> Dict[str, Any]:
    """Replace just the generation field of a task config."""
    row = _get_task_row(db, project_id, task_key)
    if not row:
        raise KeyError(f"Task '{task_key}' not found")
    existing = json.loads(row.generation) if row.generation else {}
    existing.update(generation)
    row.generation = json.dumps(existing)
    row.updated_at = datetime.utcnow()
    db.commit()
    return _task_row_to_dict(row)


def update_project_task_language_mapping(
    db: Session, project_id: int, task_key: str, lang: str, mapping: Dict[str, Any]
) -> Dict[str, Any]:
    row = _get_task_row(db, project_id, task_key)
    if not row:
        raise KeyError(f"Task '{task_key}' not found")
    lm = json.loads(row.language_mapping) if row.language_mapping else {}
    lm[lang] = mapping
    row.language_mapping = json.dumps(lm)
    sl = json.loads(row.supported_languages) if row.supported_languages else []
    if lang not in sl:
        sl.append(lang)
    row.supported_languages = json.dumps(sl)
    row.updated_at = datetime.utcnow()
    db.commit()
    return _task_row_to_dict(row)


def delete_project_task_language_mapping(
    db: Session, project_id: int, task_key: str, lang: str
) -> None:
    row = _get_task_row(db, project_id, task_key)
    if not row:
        raise KeyError(f"Task '{task_key}' not found")
    lm = json.loads(row.language_mapping) if row.language_mapping else {}
    if lang not in lm:
        raise KeyError(f"Language '{lang}' not found in task '{task_key}'")
    del lm[lang]
    row.language_mapping = json.dumps(lm)
    sl = json.loads(row.supported_languages) if row.supported_languages else []
    if lang in sl:
        sl.remove(lang)
    row.supported_languages = json.dumps(sl)
    row.updated_at = datetime.utcnow()
    db.commit()


# ─────────────────────────────────────────────
# System default config (DB-persisted)
# ─────────────────────────────────────────────

def seed_default_config(db: Session) -> None:
    """Called once at startup: persist the filesystem JSON to SystemDefaultConfig if not yet stored."""
    exists = db.query(SystemDefaultConfig).first()
    if exists:
        return
    cfg = _get_global_config()
    db.add(SystemDefaultConfig(
        config_data=json.dumps(cfg),
        updated_at=datetime.utcnow(),
    ))
    db.commit()


def get_default_config(db: Session) -> Dict[str, Any]:
    """Return the DB-stored system default config, falling back to the filesystem."""
    row = db.query(SystemDefaultConfig).first()
    if row:
        return json.loads(row.config_data)
    return _get_global_config()


def update_default_config(db: Session, config_data: Dict[str, Any]) -> Dict[str, Any]:
    """Overwrite the stored system default config with a new dict. Returns the saved config."""
    row = db.query(SystemDefaultConfig).first()
    if row:
        row.config_data = json.dumps(config_data)
        row.updated_at = datetime.utcnow()
    else:
        row = SystemDefaultConfig(
            config_data=json.dumps(config_data),
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    db.commit()
    return {"config_data": config_data, "updated_at": row.updated_at}


def sync_default_config_from_filesystem(db: Session) -> Dict[str, Any]:
    """Re-read the filesystem JSON and overwrite the stored default. Returns the saved config."""
    cfg = _get_global_config()
    return update_default_config(db, cfg)


# ─────────────────────────────────────────────
# Reset to defaults (reads from DB-persisted default)
# ─────────────────────────────────────────────

def reset_project_to_defaults(db: Session, project_id: int) -> Dict[str, Any]:
    """Reset ALL per-project config to the DB-persisted system default."""
    default_cfg = get_default_config(db)

    slim_cfg = {
        "default_generation": default_cfg.get("default_generation", {}),
        "base_models": default_cfg.get("base_models", {}),
    }
    pc = db.query(ProjectConfig).filter(ProjectConfig.project_id == project_id).first()
    if pc:
        pc.config_data = json.dumps(slim_cfg)
        pc.updated_at = datetime.utcnow()
    else:
        db.add(ProjectConfig(
            project_id=project_id,
            config_data=json.dumps(slim_cfg),
            updated_at=datetime.utcnow(),
        ))

    db.query(ProjectTaskConfig).filter(
        ProjectTaskConfig.project_id == project_id
    ).delete()
    for task_key, task_data in default_cfg.get("tasks", {}).items():
        db.add(_task_dict_to_row(project_id, task_key, task_data))

    db.commit()
    return {"reset": True, "tasks_reset": list(default_cfg.get("tasks", {}).keys())}


def reset_project_task_to_default(
    db: Session, project_id: int, task_key: str
) -> Dict[str, Any]:
    """Reset a single task's config to the DB-persisted system default for that task."""
    default_cfg = get_default_config(db)
    task_defaults = default_cfg.get("tasks", {}).get(task_key)
    if task_defaults is None:
        raise KeyError(f"Task '{task_key}' not found in system default config")

    db.query(ProjectTaskConfig).filter(
        ProjectTaskConfig.project_id == project_id,
        ProjectTaskConfig.task_key == task_key,
    ).delete()
    db.add(_task_dict_to_row(project_id, task_key, task_defaults))
    db.commit()
    return _task_row_to_dict(_get_task_row(db, project_id, task_key))


# ─────────────────────────────────────────────
# Build inference config (used by classify endpoint)
# ─────────────────────────────────────────────

def build_inference_config(db: Session, project_id: int) -> Optional[Dict[str, Any]]:
    """
    Assemble a complete pool.cfg-compatible dict from the two DB tables:
      - default_generation + base_models  ← ProjectConfig
      - tasks dict                        ← ProjectTaskConfig rows

    This is patched onto pool.cfg during inference so the LLM uses
    per-project settings for generation params, adapters, and language mapping.
    """
    pc = db.query(ProjectConfig).filter(ProjectConfig.project_id == project_id).first()
    if not pc:
        return None

    base = json.loads(pc.config_data)

    task_rows = (
        db.query(ProjectTaskConfig)
        .filter(ProjectTaskConfig.project_id == project_id)
        .all()
    )
    if task_rows:
        base["tasks"] = {row.task_key: _task_row_to_dict(row) for row in task_rows}

    return base if base.get("tasks") else None


def get_project_config_overview(db: Session, project_id: int) -> Dict[str, Any]:
    pc = db.query(ProjectConfig).filter(ProjectConfig.project_id == project_id).first()
    if not pc:
        raise KeyError(f"No config found for project {project_id}")
    base = json.loads(pc.config_data)

    task_rows = (
        db.query(ProjectTaskConfig)
        .filter(ProjectTaskConfig.project_id == project_id)
        .order_by(ProjectTaskConfig.task_key)
        .all()
    )
    all_langs: set = set()
    task_summaries = []
    for row in task_rows:
        sl = json.loads(row.supported_languages) if row.supported_languages else []
        all_langs.update(sl)
        task_summaries.append({
            "task_key": row.task_key,
            "base_model_key": row.base_model_key,
            "adapter_name": row.adapter_name,
            "label_count": len(json.loads(row.label_set) if row.label_set else []),
            "language_count": len(sl),
            "supported_languages": sl,
            "updated_at": row.updated_at.isoformat(),
        })

    return {
        "total_base_models": len(base.get("base_models", {})),
        "total_tasks": len(task_summaries),
        "total_languages": len(all_langs),
        "default_generation": base.get("default_generation", {}),
        "tasks": task_summaries,
    }


# ─────────────────────────────────────────────
# Startup: sync task configs for all projects
# ─────────────────────────────────────────────

def sync_all_project_task_configs(db: Session) -> None:
    """
    Called at startup.  For every project, ensure a ProjectTaskConfig row
    exists for each task defined in the system default config (experts_registry.json).

    - Existing customised rows are left untouched.
    - Missing rows are created with the default values from the JSON.
    - ProjectConfig rows (default_generation + base_models) are also created
      for projects that are missing them.
    """
    default_cfg = get_default_config(db)
    default_tasks = default_cfg.get("tasks", {})
    slim_base = {
        "default_generation": default_cfg.get("default_generation", {}),
        "base_models": default_cfg.get("base_models", {}),
    }

    if not default_tasks:
        return

    projects = db.query(Project).all()
    added = 0

    for project in projects:
        # Ensure ProjectConfig exists
        pc = db.query(ProjectConfig).filter(ProjectConfig.project_id == project.id).first()
        if not pc:
            db.add(ProjectConfig(
                project_id=project.id,
                config_data=json.dumps(slim_base),
                updated_at=datetime.utcnow(),
            ))

        # Find which task keys this project already has
        existing_keys = {
            row.task_key
            for row in db.query(ProjectTaskConfig.task_key)
            .filter(ProjectTaskConfig.project_id == project.id)
            .all()
        }

        # Add any missing task configs from the default
        for task_key, task_data in default_tasks.items():
            if task_key not in existing_keys:
                db.add(_task_dict_to_row(project.id, task_key, task_data))
                added += 1

    db.commit()
    print(f"[Startup] sync_all_project_task_configs: added {added} missing task config(s) across {len(projects)} project(s)")


# ─────────────────────────────────────────────
# Dummy data seeding
# ─────────────────────────────────────────────

_DUMMY_PROJECTS = [
    {"name": "Finance Analytics", "description": "Sentiment and news classification for financial documents"},
    {"name": "E-commerce Classifier", "description": "ESCI product relevance scoring for search results"},
    {"name": "Compliance Monitor", "description": "PII extraction and regulatory text analysis"},
]

_TASKS = ["finance/rating", "finance/pii", "finance/news", "finance/esci"]
_LANGUAGES = ["english", "german", "french", "spanish", "japanese", "dutch"]
_RESULTS_BY_TASK = {
    "finance/rating": ["1", "2", "3", "4", "5"],
    "finance/pii": ["[PERSON: John Smith]", "[ORG: Acme Corp]", "No PII detected"],
    "finance/news": ["Finance", "Technology", "Business & Management", "Government & Controls"],
    "finance/esci": ["E", "S", "C", "I"],
}


def seed_dummy_data(db: Session, owner_username: str) -> None:
    """Create demo projects with task configs and classification logs."""
    existing = db.query(Project).filter(Project.owner_username == owner_username).count()
    if existing > 0:
        return

    now = datetime.utcnow()
    global_cfg = get_default_config(db)
    slim_base = {
        "default_generation": global_cfg.get("default_generation", {}),
        "base_models": global_cfg.get("base_models", {}),
    }

    for i, proj_info in enumerate(_DUMMY_PROJECTS):
        project = Project(
            name=proj_info["name"],
            description=proj_info["description"],
            owner_username=owner_username,
            created_at=now - timedelta(days=30 - i * 5),
        )
        db.add(project)
        db.flush()

        db.add(ProjectConfig(
            project_id=project.id,
            config_data=json.dumps(slim_base),
            updated_at=now,
        ))

        for task_key, task_data in global_cfg.get("tasks", {}).items():
            db.add(_task_dict_to_row(project.id, task_key, task_data))

        num_logs = random.randint(40, 120)
        for _ in range(num_logs):
            task = random.choice(_TASKS)
            lang = random.choice(_LANGUAGES)
            is_error = random.random() < 0.04
            days_ago = random.uniform(0, 28)
            ts = now - timedelta(days=days_ago)
            db.add(ClassificationLog(
                request_id=str(uuid.uuid4()),
                timestamp=ts,
                username=owner_username,
                project_id=project.id,
                language=lang if not is_error else None,
                domain="finance" if not is_error else None,
                task=task if not is_error else None,
                result=random.choice(_RESULTS_BY_TASK.get(task, ["unknown"])) if not is_error else None,
                confidence=round(random.uniform(0.65, 0.99), 4) if not is_error else None,
                processing_time_ms=round(random.uniform(80, 800), 2) if not is_error else None,
                routing_path=f"{lang} → finance → {task.split('/')[-1]}" if not is_error else None,
                is_error=is_error,
                error_message="Timeout" if is_error else None,
            ))

    db.commit()


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _get_task_row(db: Session, project_id: int, task_key: str) -> Optional[ProjectTaskConfig]:
    return (
        db.query(ProjectTaskConfig)
        .filter(ProjectTaskConfig.project_id == project_id, ProjectTaskConfig.task_key == task_key)
        .first()
    )


def _task_row_to_dict(row: ProjectTaskConfig) -> Dict[str, Any]:
    return {
        "task_key": row.task_key,
        "base_model_key": row.base_model_key,
        "adapter_name": row.adapter_name,
        "adapter_path": row.adapter_path,
        "expert_path": row.expert_path,
        "template_path": row.template_path,
        "label_set": json.loads(row.label_set) if row.label_set else [],
        "strict_label_decoding": row.strict_label_decoding,
        "constrained_single_token": row.constrained_single_token,
        "generation": json.loads(row.generation) if row.generation else None,
        "language_mapping": json.loads(row.language_mapping) if row.language_mapping else {},
        "supported_languages": json.loads(row.supported_languages) if row.supported_languages else [],
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _task_dict_to_row(project_id: int, task_key: str, data: Dict[str, Any]) -> ProjectTaskConfig:
    """Convert a task dict (from experts_registry) into a new ProjectTaskConfig ORM object."""
    return ProjectTaskConfig(
        project_id=project_id,
        task_key=task_key,
        base_model_key=data.get("base_model_key"),
        adapter_name=data.get("adapter_name"),
        adapter_path=data.get("adapter_path"),
        expert_path=data.get("expert_path"),
        template_path=data.get("template_path"),
        label_set=json.dumps(data.get("label_set", [])),
        strict_label_decoding=bool(data.get("strict_label_decoding", True)),
        constrained_single_token=data.get("constrained_single_token"),
        generation=json.dumps(data["generation"]) if data.get("generation") else None,
        language_mapping=json.dumps(data.get("language_mapping", {})),
        supported_languages=json.dumps(data.get("supported_languages", [])),
        updated_at=datetime.utcnow(),
    )


def _apply_task_data(row: ProjectTaskConfig, data: Dict[str, Any]) -> None:
    """Apply a partial or full dict of task fields onto a ProjectTaskConfig row in-place."""
    simple_fields = ["base_model_key", "adapter_name", "adapter_path", "expert_path",
                     "template_path", "strict_label_decoding", "constrained_single_token"]
    for f in simple_fields:
        if f in data and data[f] is not None:
            setattr(row, f, data[f])
    if "label_set" in data and data["label_set"] is not None:
        row.label_set = json.dumps(data["label_set"])
    if "generation" in data and data["generation"] is not None:
        row.generation = json.dumps(data["generation"])
    if "language_mapping" in data and data["language_mapping"] is not None:
        row.language_mapping = json.dumps(data["language_mapping"])
    if "supported_languages" in data and data["supported_languages"] is not None:
        row.supported_languages = json.dumps(data["supported_languages"])


def _get_global_config() -> Dict[str, Any]:
    """Read the global experts_registry from the filesystem (used only for initial seeding)."""
    try:
        from app.services.config_service import config_service  # noqa: PLC0415
        return config_service.get_experts_registry()
    except (ImportError, AttributeError, OSError):
        return {"default_generation": {}, "base_models": {}, "tasks": {}}

"""
DB-backed analytics service for classification metrics.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db import ClassificationLog


def log_classification(
    db: Session,
    request_id: str,
    username: str,
    language: str,
    domain: str,
    task: str,
    result: str,
    confidence: Optional[float],
    processing_time_ms: float,
    routing_path: str,
    worker_id: Optional[str] = None,
    project_id: Optional[int] = None,
) -> None:
    """Write a successful classification event to the database."""
    record = ClassificationLog(
        request_id=request_id,
        timestamp=datetime.utcnow(),
        username=username,
        project_id=project_id,
        language=language,
        domain=domain,
        task=task,
        result=result,
        confidence=confidence,
        processing_time_ms=processing_time_ms,
        routing_path=routing_path,
        worker_id=worker_id,
        is_error=False,
    )
    db.add(record)
    db.commit()


def log_error(
    db: Session,
    username: str,
    error_message: str,
    request_id: Optional[str] = None,
    project_id: Optional[int] = None,
) -> None:
    """Write a failed classification event to the database."""
    record = ClassificationLog(
        request_id=request_id or str(uuid.uuid4()),
        timestamp=datetime.utcnow(),
        username=username,
        project_id=project_id,
        is_error=True,
        error_message=error_message,
    )
    db.add(record)
    db.commit()


def _base_query(db: Session, project_id: Optional[int] = None):
    q = db.query(ClassificationLog)
    if project_id is not None:
        q = q.filter(ClassificationLog.project_id == project_id)
    return q


def get_summary(db: Session, project_id: Optional[int] = None) -> Dict[str, Any]:
    """Return aggregated analytics summary from DB."""
    base = _base_query(db, project_id)

    total = base.with_entities(func.count(ClassificationLog.id)).scalar() or 0
    errors = (
        base.with_entities(func.count(ClassificationLog.id))
        .filter(ClassificationLog.is_error == True)  # noqa: E712
        .scalar()
        or 0
    )

    avg_confidence = (
        base.with_entities(func.avg(ClassificationLog.confidence))
        .filter(ClassificationLog.is_error == False)  # noqa: E712
        .scalar()
    )
    avg_latency = (
        base.with_entities(func.avg(ClassificationLog.processing_time_ms))
        .filter(ClassificationLog.is_error == False)  # noqa: E712
        .scalar()
    )

    error_rate = (errors / total) if total > 0 else 0.0

    lang_rows = (
        base.with_entities(ClassificationLog.language, func.count(ClassificationLog.id))
        .filter(ClassificationLog.is_error == False)  # noqa: E712
        .group_by(ClassificationLog.language)
        .all()
    )
    language_distribution = {r[0]: r[1] for r in lang_rows if r[0]}

    domain_rows = (
        base.with_entities(ClassificationLog.domain, func.count(ClassificationLog.id))
        .filter(ClassificationLog.is_error == False)  # noqa: E712
        .group_by(ClassificationLog.domain)
        .all()
    )
    domain_distribution = {r[0]: r[1] for r in domain_rows if r[0]}

    task_rows = (
        base.with_entities(ClassificationLog.task, func.count(ClassificationLog.id))
        .filter(ClassificationLog.is_error == False)  # noqa: E712
        .group_by(ClassificationLog.task)
        .all()
    )
    task_distribution = {r[0]: r[1] for r in task_rows if r[0]}

    task_conf_rows = (
        base.with_entities(ClassificationLog.task, func.avg(ClassificationLog.confidence))
        .filter(ClassificationLog.is_error == False)  # noqa: E712
        .group_by(ClassificationLog.task)
        .all()
    )
    task_avg_confidence = {
        r[0]: round(r[1], 4) for r in task_conf_rows if r[0] and r[1] is not None
    }

    recent = (
        base.filter(ClassificationLog.is_error == False)  # noqa: E712
        .order_by(ClassificationLog.timestamp.desc())
        .limit(50)
        .all()
    )
    recent_requests = [
        {
            "timestamp": r.timestamp.isoformat(),
            "request_id": r.request_id,
            "username": r.username,
            "language": r.language or "unknown",
            "domain": r.domain or "unknown",
            "task": r.task or "unknown",
            "confidence": r.confidence,
            "processing_time_ms": r.processing_time_ms or 0.0,
        }
        for r in recent
    ]

    return {
        "total_requests": total - errors,
        "total_errors": errors,
        "error_rate": error_rate,
        "avg_confidence": round(avg_confidence, 4) if avg_confidence else None,
        "avg_processing_time_ms": round(avg_latency, 2) if avg_latency else None,
        "language_distribution": language_distribution,
        "domain_distribution": domain_distribution,
        "task_distribution": task_distribution,
        "task_avg_confidence": task_avg_confidence,
        "recent_requests": recent_requests,
    }


def get_timeseries(
    db: Session, bucket: str = "hour", days: int = 7, project_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Return request counts grouped by time bucket for the last N days."""
    from_dt = datetime.utcnow() - timedelta(days=days)

    trunc_expr = func.date_trunc(bucket, ClassificationLog.timestamp)

    base = _base_query(db, project_id)
    rows = (
        base.with_entities(
            trunc_expr.label("bucket"),
            func.count(ClassificationLog.id).label("total"),
            func.sum(
                case((ClassificationLog.is_error == True, 1), else_=0)  # noqa: E712
            ).label("errors"),
        )
        .filter(ClassificationLog.timestamp >= from_dt)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )

    return [
        {
            "bucket": r.bucket.isoformat() if r.bucket else None,
            "total": r.total or 0,
            "errors": r.errors or 0,
            "success": (r.total or 0) - (r.errors or 0),
        }
        for r in rows
    ]


def get_per_task(db: Session, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return per-task metrics: count, avg confidence, avg latency, error rate."""
    base = _base_query(db, project_id)
    rows = (
        base.with_entities(
            ClassificationLog.task,
            func.count(ClassificationLog.id).label("total"),
            func.sum(
                case((ClassificationLog.is_error == True, 1), else_=0)  # noqa: E712
            ).label("errors"),
            func.avg(ClassificationLog.confidence).label("avg_confidence"),
            func.avg(ClassificationLog.processing_time_ms).label("avg_latency"),
        )
        .filter(ClassificationLog.task.isnot(None))
        .group_by(ClassificationLog.task)
        .order_by(func.count(ClassificationLog.id).desc())
        .all()
    )

    result = []
    for r in rows:
        total = r.total or 0
        errors = r.errors or 0
        result.append(
            {
                "task": r.task,
                "total_requests": total,
                "error_count": errors,
                "error_rate": round(errors / total, 4) if total > 0 else 0.0,
                "avg_confidence": round(r.avg_confidence, 4) if r.avg_confidence else None,
                "avg_latency_ms": round(r.avg_latency, 2) if r.avg_latency else None,
            }
        )
    return result


def get_per_language(db: Session, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return per-language metrics."""
    base = _base_query(db, project_id)
    rows = (
        base.with_entities(
            ClassificationLog.language,
            func.count(ClassificationLog.id).label("total"),
            func.sum(
                case((ClassificationLog.is_error == True, 1), else_=0)  # noqa: E712
            ).label("errors"),
            func.avg(ClassificationLog.confidence).label("avg_confidence"),
            func.avg(ClassificationLog.processing_time_ms).label("avg_latency"),
        )
        .filter(ClassificationLog.language.isnot(None))
        .group_by(ClassificationLog.language)
        .order_by(func.count(ClassificationLog.id).desc())
        .all()
    )

    result = []
    for r in rows:
        total = r.total or 0
        errors = r.errors or 0
        result.append(
            {
                "language": r.language,
                "total_requests": total,
                "error_count": errors,
                "error_rate": round(errors / total, 4) if total > 0 else 0.0,
                "avg_confidence": round(r.avg_confidence, 4) if r.avg_confidence else None,
                "avg_latency_ms": round(r.avg_latency, 2) if r.avg_latency else None,
            }
        )
    return result


def get_per_user(db: Session, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return per-user usage metrics."""
    base = _base_query(db, project_id)
    rows = (
        base.with_entities(
            ClassificationLog.username,
            func.count(ClassificationLog.id).label("total"),
            func.sum(
                case((ClassificationLog.is_error == True, 1), else_=0)  # noqa: E712
            ).label("errors"),
            func.avg(ClassificationLog.confidence).label("avg_confidence"),
            func.max(ClassificationLog.timestamp).label("last_active"),
        )
        .filter(ClassificationLog.username.isnot(None))
        .group_by(ClassificationLog.username)
        .order_by(func.count(ClassificationLog.id).desc())
        .all()
    )

    return [
        {
            "username": r.username,
            "total_requests": r.total or 0,
            "error_count": r.errors or 0,
            "avg_confidence": round(r.avg_confidence, 4) if r.avg_confidence else None,
            "last_active": r.last_active.isoformat() if r.last_active else None,
        }
        for r in rows
    ]


def get_per_project(db: Session) -> List[Dict[str, Any]]:
    """Return per-project usage metrics across all projects."""
    from app.db import Project  # local import to avoid circular
    rows = (
        db.query(
            ClassificationLog.project_id,
            Project.name,
            func.count(ClassificationLog.id).label("total"),
            func.sum(
                case((ClassificationLog.is_error == True, 1), else_=0)  # noqa: E712
            ).label("errors"),
            func.avg(ClassificationLog.confidence).label("avg_confidence"),
            func.avg(ClassificationLog.processing_time_ms).label("avg_latency"),
        )
        .join(Project, ClassificationLog.project_id == Project.id, isouter=True)
        .filter(ClassificationLog.project_id.isnot(None))
        .group_by(ClassificationLog.project_id, Project.name)
        .order_by(func.count(ClassificationLog.id).desc())
        .all()
    )
    result = []
    for r in rows:
        total = r.total or 0
        errors = r.errors or 0
        result.append({
            "project_id": r.project_id,
            "project_name": r.name or "Deleted Project",
            "total_requests": total,
            "error_count": errors,
            "error_rate": round(errors / total, 4) if total > 0 else 0.0,
            "avg_confidence": round(r.avg_confidence, 4) if r.avg_confidence else None,
            "avg_latency_ms": round(r.avg_latency, 2) if r.avg_latency else None,
        })
    return result


def get_history(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    task: Optional[str] = None,
    language: Optional[str] = None,
    username: Optional[str] = None,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    project_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Return paginated, filterable classification history."""
    query = _base_query(db, project_id)

    if task:
        query = query.filter(ClassificationLog.task == task)
    if language:
        query = query.filter(ClassificationLog.language == language)
    if username:
        query = query.filter(ClassificationLog.username == username)
    if from_dt:
        query = query.filter(ClassificationLog.timestamp >= from_dt)
    if to_dt:
        query = query.filter(ClassificationLog.timestamp <= to_dt)

    total = query.count()
    items = (
        query.order_by(ClassificationLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "items": [
            {
                "id": r.id,
                "request_id": r.request_id,
                "timestamp": r.timestamp.isoformat(),
                "username": r.username,
                "language": r.language,
                "domain": r.domain,
                "task": r.task,
                "result": r.result,
                "confidence": r.confidence,
                "processing_time_ms": r.processing_time_ms,
                "routing_path": r.routing_path,
                "worker_id": r.worker_id,
                "is_error": r.is_error,
                "error_message": r.error_message,
            }
            for r in items
        ],
    }

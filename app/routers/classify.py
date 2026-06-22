"""
Classification router for text classification endpoints.
"""

import time
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import CurrentUser, RoutingServiceDep
from app.schemas.requests import ClassifyRequest, BatchClassifyRequest
from app.schemas.responses import (
    ClassifyResponse,
    BatchClassifyResponse,
    SystemStatsResponse,
)
from app.services import analytics_service as svc

router = APIRouter(prefix="/api/v1/classify", tags=["Classification"])


def _load_project_config(db: Session, project_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Assemble the per-project experts_registry config from DB rows, or None if not applicable."""
    if project_id is None:
        return None
    from app.services.project_service import build_inference_config
    cfg = build_inference_config(db, project_id)
    # Only use if the config has the required tasks key populated
    if cfg and cfg.get("tasks"):
        return cfg
    return None


@router.post("", response_model=ClassifyResponse)
async def classify_text(
    request: ClassifyRequest,
    current_user: CurrentUser,
    routing_service: RoutingServiceDep,
    db: Session = Depends(get_db),
) -> ClassifyResponse:
    """Classify a single text input. Requires authentication via Bearer token."""
    if not routing_service.is_initialized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Classification service not ready. Models are still loading.",
        )

    project_config = _load_project_config(db, request.project_id)

    try:
        result = await routing_service.classify(request, project_config=project_config)
        svc.log_classification(
            db,
            request_id=result.request_id,
            username=current_user.username,
            language=result.language,
            domain=result.domain,
            task=result.task,
            result=result.result,
            confidence=result.confidence,
            processing_time_ms=result.processing_time_ms,
            routing_path=result.routing_path,
            project_id=request.project_id,
        )
        return result

    except TimeoutError as e:
        svc.log_error(db, username=current_user.username, error_message=str(e), project_id=request.project_id)
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e))
    except Exception as e:
        svc.log_error(db, username=current_user.username, error_message=str(e), project_id=request.project_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Classification failed: {str(e)}",
        )


@router.post("/test", response_model=ClassifyResponse)
async def classify_text_test(
    request: ClassifyRequest,
    current_user: CurrentUser,
    routing_service: RoutingServiceDep,
    db: Session = Depends(get_db),
) -> ClassifyResponse:
    """Mock classification endpoint for frontend development."""
    print("test classify method is hitting....")
    response = ClassifyResponse(
        request_id="00000000-0000-0000-0000-000000000001",
        language="english",
        domain="finance",
        task="rating",
        result="4",
        confidence=0.94,
        routing_path="english → finance → rating",
        processing_time_ms=12.5,
        domain_probabilities={"finance": 0.94, "general": 0.06},
        raw_response=request.text,
    )
    svc.log_classification(
        db,
        request_id=response.request_id,
        username=current_user.username,
        language=response.language,
        domain=response.domain,
        task=response.task,
        result=response.result,
        confidence=response.confidence,
        processing_time_ms=response.processing_time_ms,
        routing_path=response.routing_path,
        project_id=request.project_id,
    )
    return response


@router.post("/batch", response_model=BatchClassifyResponse)
async def classify_batch(
    request: BatchClassifyRequest,
    current_user: CurrentUser,
    routing_service: RoutingServiceDep,
    db: Session = Depends(get_db),
) -> BatchClassifyResponse:
    """Classify multiple text inputs in batch. Maximum 100 items per batch."""
    if not routing_service.is_initialized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Classification service not ready. Models are still loading.",
        )

    start_time = time.perf_counter()
    results: List[ClassifyResponse] = []
    failed = 0

    for item in request.items:
        project_config = _load_project_config(db, item.project_id)
        try:
            result = await routing_service.classify(item, project_config=project_config)
            svc.log_classification(
                db,
                request_id=result.request_id,
                username=current_user.username,
                language=result.language,
                domain=result.domain,
                task=result.task,
                result=result.result,
                confidence=result.confidence,
                processing_time_ms=result.processing_time_ms,
                routing_path=result.routing_path,
                project_id=item.project_id,
            )
            results.append(result)
        except Exception as e:
            svc.log_error(db, username=current_user.username, error_message=str(e), project_id=item.project_id)
            failed += 1

    total_time_ms = (time.perf_counter() - start_time) * 1000

    return BatchClassifyResponse(
        results=results,
        total_processing_time_ms=total_time_ms,
        successful=len(results),
        failed=failed,
    )


@router.get("/stats", response_model=SystemStatsResponse)
async def get_system_stats(
    current_user: CurrentUser,
    routing_service: RoutingServiceDep,
) -> SystemStatsResponse:
    """Get system statistics about the classification service."""
    if not routing_service.is_initialized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Classification service not ready",
        )

    stats = routing_service.get_system_stats()

    return SystemStatsResponse(
        total_domains=stats.get("total_domains", 0),
        total_tasks=stats.get("total_tasks", 0),
        supported_languages=stats.get("supported_languages", 0),
        all_languages=stats.get("all_languages", []),
        domains=stats.get("domains", []),
    )

"""
Classification router for text classification endpoints.
"""

import time
from typing import List

from fastapi import APIRouter, HTTPException, status

from app.dependencies import CurrentUser, RoutingServiceDep
from app.schemas.requests import ClassifyRequest, BatchClassifyRequest
from app.schemas.responses import (
    ClassifyResponse,
    BatchClassifyResponse,
    SystemStatsResponse,
)

router = APIRouter(prefix="/api/v1/classify", tags=["Classification"])


@router.post("", response_model=ClassifyResponse)
async def classify_text(
    request: ClassifyRequest,
    current_user: CurrentUser,
    routing_service: RoutingServiceDep,
) -> ClassifyResponse:
    """
    Classify a single text input.

    This endpoint routes the input through the MOE-Router system:
    1. Detects the language
    2. Classifies the domain
    3. Selects the appropriate task
    4. Executes the task expert

    Requires authentication via Bearer token.

    Args:
        request: Classification request with prompt and input data
        current_user: Authenticated user (injected)
        routing_service: Routing service (injected)

    Returns:
        ClassifyResponse with classification results

    Raises:
        HTTPException: If classification fails or times out
    """
    if not routing_service.is_initialized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Classification service not ready. Models are still loading."
        )

    try:
        result = await routing_service.classify(request)
        return result

    except TimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Classification failed: {str(e)}"
        )


@router.post("/batch", response_model=BatchClassifyResponse)
async def classify_batch(
    request: BatchClassifyRequest,
    current_user: CurrentUser,
    routing_service: RoutingServiceDep,
) -> BatchClassifyResponse:
    """
    Classify multiple text inputs in batch.

    Processes items sequentially (GPU constraint).
    Maximum 100 items per batch.

    Requires authentication via Bearer token.

    Args:
        request: Batch request with list of classification items
        current_user: Authenticated user (injected)
        routing_service: Routing service (injected)

    Returns:
        BatchClassifyResponse with all results
    """
    if not routing_service.is_initialized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Classification service not ready. Models are still loading."
        )

    start_time = time.perf_counter()
    results: List[ClassifyResponse] = []
    failed = 0

    for item in request.items:
        try:
            result = await routing_service.classify(item)
            results.append(result)
        except Exception as e:
            failed += 1
            # Continue processing remaining items

    total_time_ms = (time.perf_counter() - start_time) * 1000

    return BatchClassifyResponse(
        results=results,
        total_processing_time_ms=total_time_ms,
        successful=len(results),
        failed=failed
    )


@router.get("/stats", response_model=SystemStatsResponse)
async def get_system_stats(
    current_user: CurrentUser,
    routing_service: RoutingServiceDep,
) -> SystemStatsResponse:
    """
    Get system statistics about the classification service.

    Returns information about supported domains, tasks, and languages.

    Requires authentication via Bearer token.

    Args:
        current_user: Authenticated user (injected)
        routing_service: Routing service (injected)

    Returns:
        SystemStatsResponse with system statistics
    """
    if not routing_service.is_initialized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Classification service not ready"
        )

    stats = routing_service.get_system_stats()

    return SystemStatsResponse(
        total_domains=stats.get("total_domains", 0),
        total_tasks=stats.get("total_tasks", 0),
        supported_languages=stats.get("supported_languages", 0),
        all_languages=stats.get("all_languages", []),
        domains=stats.get("domains", [])
    )

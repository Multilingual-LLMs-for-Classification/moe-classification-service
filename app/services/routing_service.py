"""
Routing service that wraps the MOE-Router PromptRoutingSystem.
"""

import time
import asyncio
from asyncio import Semaphore
from typing import Dict, Any, Optional
from uuid import uuid4

from app.config import settings
from app.schemas.requests import ClassifyRequest, ClassifyOptions
from app.schemas.responses import ClassifyResponse


class RoutingService:
    """
    Service wrapper around PromptRoutingSystem.

    Handles:
    - Lazy initialization of the routing system
    - GPU concurrency control via semaphore
    - Request/response transformation
    - Timeout handling
    """

    def __init__(self):
        self._routing_system = None
        self._initialized = False
        self._gpu_semaphore = Semaphore(settings.max_concurrent_gpu_requests)

    def initialize(self) -> bool:
        """
        Initialize the routing system.

        Returns:
            True if initialization successful, False otherwise
        """
        if self._initialized:
            return True

        try:
            # Import PromptRoutingSystem from local moe_router package
            from moe_router.gating.components.routing_system import PromptRoutingSystem

            print("Initializing PromptRoutingSystem...")
            self._routing_system = PromptRoutingSystem(training_mode=False)
            self._initialized = True
            print("PromptRoutingSystem initialized successfully")
            return True

        except Exception as e:
            print(f"Failed to initialize routing system: {e}")
            import traceback
            traceback.print_exc()
            return False

    @property
    def is_initialized(self) -> bool:
        """Check if routing system is initialized."""
        return self._initialized and self._routing_system is not None

    def get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics from routing system."""
        if not self.is_initialized:
            return {"error": "Routing system not initialized"}
        return self._routing_system.get_system_stats()

    async def classify(
        self,
        request: ClassifyRequest,
        timeout_seconds: Optional[int] = None
    ) -> ClassifyResponse:
        """
        Classify text using the routing system.

        Args:
            request: Classification request
            timeout_seconds: Optional timeout override

        Returns:
            ClassifyResponse with classification results

        Raises:
            RuntimeError: If routing system not initialized
            TimeoutError: If classification times out
        """
        if not self.is_initialized:
            raise RuntimeError("Routing system not initialized")

        timeout = timeout_seconds or settings.request_timeout_seconds
        request_id = str(uuid4())

        # Acquire GPU semaphore for concurrency control
        async with self._gpu_semaphore:
            try:
                # Run classification in thread pool with timeout
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        self._sync_classify,
                        request,
                        request_id
                    ),
                    timeout=timeout
                )
                return result

            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Classification timed out after {timeout} seconds"
                )

    def _sync_classify(
        self,
        request: ClassifyRequest,
        request_id: str
    ) -> ClassifyResponse:
        """
        Synchronous classification (runs in thread pool).

        Args:
            request: Classification request
            request_id: Unique request identifier

        Returns:
            ClassifyResponse with results
        """
        start_time = time.perf_counter()

        # Prepare input data for routing system
        input_data = {
            "text": request.input_data.text,
        }
        if request.input_data.title:
            input_data["title"] = request.input_data.title

        # Call routing system
        result = self._routing_system.route_prompt(
            prompt=request.prompt,
            input_data=input_data
        )

        # Calculate processing time
        processing_time_ms = (time.perf_counter() - start_time) * 1000

        # Build response
        response = ClassifyResponse(
            request_id=request_id,
            language=result.get("language", "unknown"),
            domain=result.get("domain", "unknown"),
            task=result.get("task", "unknown"),
            result=str(result.get("result", "")),
            confidence=result.get("expert_confidence"),
            routing_path=result.get("routing_path", ""),
            processing_time_ms=processing_time_ms
        )

        # Add optional fields based on request options
        if request.options.return_probabilities:
            response.domain_probabilities = result.get("domain_probabilities")

        if request.options.return_raw_response:
            response.raw_response = result.get("raw_response")

        return response


# Global service instance
routing_service = RoutingService()

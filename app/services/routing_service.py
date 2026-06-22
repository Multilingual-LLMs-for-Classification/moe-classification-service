"""
Routing service that wraps the MOE-Router PromptRoutingSystem.

Handles:
- Lazy initialization of the routing system
- GPU concurrency control via semaphore
- Request/response transformation
- Timeout handling
- Per-project config injection via pool.cfg patching
"""

import time
import asyncio
from asyncio import Semaphore
from contextlib import contextmanager
from typing import Dict, Any, Optional
from uuid import uuid4

from app.config import settings
from app.schemas.requests import ClassifyRequest
from app.schemas.responses import ClassifyResponse


class RoutingService:

    def __init__(self):
        self._routing_system = None
        self._initialized = False
        self._gpu_semaphore = Semaphore(settings.max_concurrent_gpu_requests)

    def initialize(self) -> bool:
        if self._initialized:
            return True

        try:
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
        return self._initialized and self._routing_system is not None

    def get_system_stats(self) -> Dict[str, Any]:
        if not self.is_initialized:
            return {"error": "Routing system not initialized"}
        return self._routing_system.get_system_stats()

    @contextmanager
    def _project_config_patch(self, project_cfg: Dict[str, Any]):
        """
        Temporarily replace expert_pool.cfg with per-project config for one
        inference call. Safe because this is always called within the GPU
        semaphore which serialises all inference. Original cfg is restored
        in the finally block even if an exception occurs.
        """
        pool = self._routing_system.expert_pool
        original_cfg = pool.cfg
        try:
            pool.cfg = project_cfg
            print(f"[ProjectConfig] Patched pool.cfg with project config "
                  f"(tasks: {list(project_cfg.get('tasks', {}).keys())})")
            yield
        finally:
            pool.cfg = original_cfg
            print("[ProjectConfig] Restored global pool.cfg")

    async def classify(
        self,
        request: ClassifyRequest,
        timeout_seconds: Optional[int] = None,
        project_config: Optional[Dict[str, Any]] = None,
    ) -> ClassifyResponse:
        if not self.is_initialized:
            raise RuntimeError("Routing system not initialized")

        timeout = timeout_seconds or settings.request_timeout_seconds
        request_id = str(uuid4())

        async with self._gpu_semaphore:
            try:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        self._sync_classify,
                        request,
                        request_id,
                        project_config,
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
        request_id: str,
        project_config: Optional[Dict[str, Any]] = None,
    ) -> ClassifyResponse:
        start_time = time.perf_counter()

        prompt = f"{request.description}\n\n{request.text}"
        input_data = {"text": request.text}

        force_language = getattr(request, "force_language", None)
        force_task = getattr(request, "force_task", None)

        if force_language and force_task:
            # Bypass automatic routing — directly call the specified expert
            if project_config is not None:
                with self._project_config_patch(project_config):
                    result = self._routing_system.route_forced(
                        prompt=prompt,
                        input_data=input_data,
                        force_language=force_language,
                        force_task=force_task,
                    )
            else:
                result = self._routing_system.route_forced(
                    prompt=prompt,
                    input_data=input_data,
                    force_language=force_language,
                    force_task=force_task,
                )
        elif project_config is not None:
            with self._project_config_patch(project_config):
                result = self._routing_system.route_prompt(
                    prompt=prompt,
                    input_data=input_data
                )
        else:
            result = self._routing_system.route_prompt(
                prompt=prompt,
                input_data=input_data
            )

        processing_time_ms = (time.perf_counter() - start_time) * 1000

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

        if request.options.return_probabilities:
            response.domain_probabilities = result.get("domain_probabilities")

        if request.options.return_raw_response:
            response.raw_response = result.get("raw_response")

        return response


# Global service instance
routing_service = RoutingService()

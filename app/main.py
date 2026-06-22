"""
FastAPI application entry point.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import create_tables, SessionLocal
from app.routers import admin, analytics, auth, classify, health
from app.routers import projects
from app.services.routing_service import routing_service
from app.services.project_service import seed_dummy_data, seed_default_config, sync_all_project_task_configs
from app.middleware.error_handler import ErrorHandlerMiddleware, add_request_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events:
    - Startup: Initialize routing system and load models
    - Shutdown: Cleanup resources
    """
    # Startup
    create_tables()
    print("=" * 60)
    print("Starting Classification Service...")
    print("=" * 60)

    # Seed system default config from filesystem JSON (once, if not yet in DB)
    # and seed dummy project data for the first registered user (if any)
    db = SessionLocal()
    try:
        seed_default_config(db)
        sync_all_project_task_configs(db)
        from app.db import UserRecord
        first_user = db.query(UserRecord).first()
        if first_user:
            seed_dummy_data(db, first_user.username)
    finally:
        db.close()

    # Initialize routing system in background thread
    # (model loading is CPU/IO bound and can block the event loop)
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, routing_service.initialize)

    if success:
        print("=" * 60)
        print("Classification Service ready!")
        stats = routing_service.get_system_stats()
        print(f"  Domains: {stats.get('total_domains', 0)}")
        print(f"  Tasks: {stats.get('total_tasks', 0)}")
        print(f"  Languages: {stats.get('supported_languages', 0)}")
        print("=" * 60)
    else:
        print("WARNING: Failed to initialize routing system")
        print("Service will start but classification endpoints will be unavailable")

    yield  # Application runs here

    # Shutdown
    print("Shutting down Classification Service...")


# Create FastAPI application
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=settings.api_description,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add error handling middleware
app.add_middleware(ErrorHandlerMiddleware)

# Add request ID middleware
app.middleware("http")(add_request_id)

# Include routers
app.include_router(admin.router)
app.include_router(analytics.router)
app.include_router(auth.router)
app.include_router(classify.router)
app.include_router(health.router)
app.include_router(projects.router)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "docs": "/docs",
        "health": "/api/v1/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )

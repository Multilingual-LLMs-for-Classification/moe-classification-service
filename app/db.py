"""
SQLAlchemy database setup and ORM models.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    """SQLAlchemy ORM model for the users table."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    disabled = Column(Boolean, default=False, nullable=False)


class UserProfile(Base):
    """Extended profile data for a user (display name, bio, avatar)."""

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(
        String(50),
        ForeignKey("users.username", ondelete="CASCADE"),
        unique=True, nullable=False, index=True,
    )
    display_name = Column(String(100), nullable=True)
    bio = Column(Text, nullable=True)
    avatar = Column(Text, nullable=True)   # base64 data URL  e.g. "data:image/png;base64,..."
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Project(Base):
    """A project groups classifications, analytics, and config under one namespace."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    owner_username = Column(String(50), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProjectConfig(Base):
    """Per-project experts registry config stored in DB (replaces filesystem JSON per project)."""

    __tablename__ = "project_configs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    config_data = Column(Text, nullable=False)  # JSON string of experts_registry
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ProjectTaskConfig(Base):
    """Per-project, per-task configuration stored as individual DB rows.

    Each task (e.g. 'finance/rating') gets its own row per project so configs
    are independently queryable, editable, and loaded at inference time without
    parsing a large JSON blob.
    """

    __tablename__ = "project_task_configs"
    __table_args__ = (UniqueConstraint("project_id", "task_key", name="uq_project_task_key"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_key = Column(String(100), nullable=False, index=True)   # e.g. "finance/rating"
    base_model_key = Column(String(100), nullable=True)
    adapter_name = Column(String(100), nullable=True)
    adapter_path = Column(String(500), nullable=True)
    expert_path = Column(String(500), nullable=True)
    template_path = Column(String(500), nullable=True)
    label_set = Column(Text, nullable=True)           # JSON array  ["1","2","3","4","5"]
    strict_label_decoding = Column(Boolean, default=True, nullable=False)
    constrained_single_token = Column(Boolean, nullable=True)
    generation = Column(Text, nullable=True)          # JSON object {"max_new_tokens": 5, ...}
    language_mapping = Column(Text, nullable=True)    # JSON object {lang: {base_model_key, ...}}
    supported_languages = Column(Text, nullable=True) # JSON array  ["en","de","fr"]
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SystemDefaultConfig(Base):
    """Single-row table holding the default experts_registry config used for project resets.

    Seeded on first startup from the filesystem JSON; can be updated via API
    without touching the filesystem.
    """

    __tablename__ = "system_default_config"

    id = Column(Integer, primary_key=True)
    config_data = Column(Text, nullable=False)   # full JSON experts_registry
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ClassificationLog(Base):
    """SQLAlchemy ORM model for classification events."""

    __tablename__ = "classification_logs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    username = Column(String(50), index=True, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    language = Column(String(50), nullable=True)
    domain = Column(String(100), nullable=True)
    task = Column(String(100), nullable=True)
    result = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    processing_time_ms = Column(Float, nullable=True)
    routing_path = Column(String, nullable=True)
    worker_id = Column(String(100), nullable=True)
    is_error = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=True)


engine = create_engine(settings.database_url)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def create_tables() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Type alias for cleaner dependency injection
DbSession = Session

"""
Pydantic schemas for project endpoints.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    owner_username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectList(BaseModel):
    projects: List[ProjectResponse]
    total: int


class ProjectConfigResponse(BaseModel):
    project_id: int
    config_data: Dict[str, Any]
    updated_at: datetime


class ProjectConfigUpdate(BaseModel):
    config_data: Dict[str, Any]

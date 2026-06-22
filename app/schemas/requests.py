"""
Request schemas for classification endpoints.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class ClassifyOptions(BaseModel):
    """Options for classification request."""

    return_probabilities: bool = Field(
        default=False,
        description="Include domain probability distribution in response"
    )
    return_raw_response: bool = Field(
        default=False,
        description="Include raw expert model response in output"
    )


class ClassifyRequest(BaseModel):
    """Request body for single classification."""

    description: str = Field(
        ...,
        description="Task description used for language/domain/task identification",
        examples=["Rate this product review from 1 to 5 stars based on sentiment."]
    )
    text: str = Field(
        ...,
        description="The text to classify using the selected expert"
    )
    options: ClassifyOptions = Field(
        default_factory=ClassifyOptions,
        description="Optional response configuration"
    )
    project_id: Optional[int] = Field(
        None,
        description="Associate this classification with a project"
    )
    force_language: Optional[str] = Field(
        None,
        description="Force a specific language (e.g. 'english') bypassing auto-detection"
    )
    force_task: Optional[str] = Field(
        None,
        description="Force a specific task key (e.g. 'finance/rating') bypassing auto-routing"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Rate this product review from 1 to 5 stars based on sentiment.",
                    "text": "This product exceeded my expectations! Great quality and fast shipping.",
                    "options": {
                        "return_probabilities": True,
                        "return_raw_response": False
                    }
                }
            ]
        }
    }


class BatchClassifyRequest(BaseModel):
    """Request body for batch classification."""

    items: List[ClassifyRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of classification requests (max 100)"
    )

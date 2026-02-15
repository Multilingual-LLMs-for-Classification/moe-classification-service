"""
Request schemas for classification endpoints.
"""

from typing import Dict, Optional, List

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


class InputData(BaseModel):
    """Input data for classification."""

    text: str = Field(..., description="Text to classify")
    title: Optional[str] = Field(None, description="Optional title/header text")

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for routing system."""
        result = {"text": self.text}
        if self.title:
            result["title"] = self.title
        return result


class ClassifyRequest(BaseModel):
    """Request body for single classification."""

    prompt: str = Field(
        ...,
        description="Classification prompt with instructions",
        examples=["Classify the sentiment of this review as 1-5 stars."]
    )
    input_data: InputData = Field(
        ...,
        description="Data to classify"
    )
    options: ClassifyOptions = Field(
        default_factory=ClassifyOptions,
        description="Optional response configuration"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "prompt": "Rate this product review from 1 to 5 stars based on sentiment.",
                    "input_data": {
                        "text": "This product exceeded my expectations! Great quality and fast shipping.",
                        "title": "Amazing product"
                    },
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

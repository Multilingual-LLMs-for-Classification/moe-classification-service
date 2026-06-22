"""
Authentication schemas for OAuth2/JWT.
"""

from typing import Optional

from pydantic import BaseModel, Field


class Token(BaseModel):
    """OAuth2 token response."""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Data extracted from JWT token."""

    username: Optional[str] = None


class User(BaseModel):
    """User model."""

    username: str
    disabled: bool = False


class UserInDB(User):
    """User model with hashed password (internal use)."""

    hashed_password: str


class UserCreate(BaseModel):
    """Schema for user registration."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class UserProfile(BaseModel):
    """Public profile data."""

    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar: Optional[str] = None   # base64 data URL
    updated_at: Optional[str] = None


class ProfileUpdate(BaseModel):
    """Fields that can be updated in a profile."""

    display_name: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None, max_length=500)


class AvatarUpdate(BaseModel):
    """Avatar update — expects a base64 data URL."""

    avatar: str   # "data:image/png;base64,..."


class PasswordChange(BaseModel):
    """Password change request."""

    current_password: str
    new_password: str = Field(..., min_length=8)

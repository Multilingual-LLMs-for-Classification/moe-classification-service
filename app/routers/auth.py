"""
Authentication router for OAuth2/JWT endpoints and user profile management.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import CurrentUser
from app.schemas.auth import (
    Token, UserCreate, User,
    UserProfile, ProfileUpdate, AvatarUpdate, PasswordChange,
)
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    create_user,
    get_user,
    get_profile,
    update_profile,
    update_avatar,
    change_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
) -> Token:
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
async def register_user(user_data: UserCreate, db: Session = Depends(get_db)) -> User:
    if get_user(db, user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )
    user = create_user(db, user_data.username, user_data.password)
    return User(username=user.username, disabled=user.disabled)


# ── Profile endpoints ──

@router.get("/profile", response_model=UserProfile)
async def get_my_profile(current_user: CurrentUser, db: Session = Depends(get_db)):
    """Return the current user's profile."""
    return get_profile(db, current_user.username)


@router.patch("/profile", response_model=UserProfile)
async def update_my_profile(
    body: ProfileUpdate, current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Update display_name and/or bio."""
    return update_profile(db, current_user.username, body.display_name, body.bio)


@router.put("/profile/avatar", response_model=UserProfile)
async def update_my_avatar(
    body: AvatarUpdate, current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Replace the profile avatar with a base64 data URL."""
    if not body.avatar.startswith("data:image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="avatar must be a base64 image data URL (data:image/...;base64,...)",
        )
    return update_avatar(db, current_user.username, body.avatar)


@router.delete("/profile/avatar", response_model=UserProfile)
async def delete_my_avatar(current_user: CurrentUser, db: Session = Depends(get_db)):
    """Remove the profile avatar."""
    return update_avatar(db, current_user.username, None)


@router.post("/profile/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    body: PasswordChange, current_user: CurrentUser, db: Session = Depends(get_db)
):
    """Change the current user's password."""
    if not change_password(db, current_user.username, body.current_password, body.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

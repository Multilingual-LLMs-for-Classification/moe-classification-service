"""
Authentication service for JWT token management.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import UserRecord, UserProfile as UserProfileRecord
from app.schemas.auth import TokenData, UserInDB, UserProfile


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def get_user(db: Session, username: str) -> Optional[UserInDB]:
    """Get user from database by username."""
    record = db.query(UserRecord).filter(UserRecord.username == username).first()
    if record is None:
        return None
    return UserInDB(
        username=record.username,
        hashed_password=record.hashed_password,
        disabled=record.disabled,
    )


def authenticate_user(db: Session, username: str, password: str) -> Optional[UserInDB]:
    """Authenticate user with username and password."""
    user = get_user(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_user(db: Session, username: str, password: str) -> UserInDB:
    """Create a new user in the database."""
    if db.query(UserRecord).filter(UserRecord.username == username).first():
        raise ValueError(f"User {username} already exists")

    hashed_password = get_password_hash(password)
    record = UserRecord(username=username, hashed_password=hashed_password, disabled=False)
    db.add(record)
    db.commit()
    db.refresh(record)
    return UserInDB(
        username=record.username,
        hashed_password=record.hashed_password,
        disabled=record.disabled,
    )


def get_profile(db: Session, username: str) -> UserProfile:
    """Return a user's profile, creating a blank one if it doesn't exist yet."""
    record = db.query(UserProfileRecord).filter(UserProfileRecord.username == username).first()
    if not record:
        record = UserProfileRecord(username=username, updated_at=datetime.now(timezone.utc))
        db.add(record)
        db.commit()
        db.refresh(record)
    return UserProfile(
        username=record.username,
        display_name=record.display_name,
        bio=record.bio,
        avatar=record.avatar,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
    )


def update_profile(
    db: Session, username: str,
    display_name: Optional[str], bio: Optional[str],
) -> UserProfile:
    """Update display_name and/or bio for a user."""
    record = db.query(UserProfileRecord).filter(UserProfileRecord.username == username).first()
    if not record:
        record = UserProfileRecord(username=username)
        db.add(record)
    if display_name is not None:
        record.display_name = display_name
    if bio is not None:
        record.bio = bio
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return UserProfile(
        username=record.username,
        display_name=record.display_name,
        bio=record.bio,
        avatar=record.avatar,
        updated_at=record.updated_at.isoformat(),
    )


def update_avatar(db: Session, username: str, avatar: str) -> UserProfile:
    """Replace the stored avatar (base64 data URL)."""
    record = db.query(UserProfileRecord).filter(UserProfileRecord.username == username).first()
    if not record:
        record = UserProfileRecord(username=username)
        db.add(record)
    record.avatar = avatar
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return UserProfile(
        username=record.username,
        display_name=record.display_name,
        bio=record.bio,
        avatar=record.avatar,
        updated_at=record.updated_at.isoformat(),
    )


def change_password(db: Session, username: str, current_password: str, new_password: str) -> bool:
    """Verify current password then set new password. Returns False if current is wrong."""
    record = db.query(UserRecord).filter(UserRecord.username == username).first()
    if not record or not verify_password(current_password, record.hashed_password):
        return False
    record.hashed_password = get_password_hash(new_password)
    db.commit()
    return True


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        data: Data to encode in the token (typically {"sub": username})
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[TokenData]:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token string

    Returns:
        TokenData with username if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        username: str = payload.get("sub")
        if username is None:
            return None
        return TokenData(username=username)
    except JWTError:
        return None

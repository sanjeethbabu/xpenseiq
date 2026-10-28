from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import User

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"
COOKIE_NAME = "xpenziq_session"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored: str) -> bool:
    return password_hash.verify(password, stored)


def set_session(response: Response, user_id: UUID) -> None:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)},
        settings.auth_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )
    is_prod = settings.app_env == "production"
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=is_prod,
        samesite="lax", max_age=settings.access_token_minutes * 60, path="/",
        domain="localhost" if not is_prod else None,
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    try:
        payload = jwt.decode(token, settings.auth_secret.get_secret_value(), algorithms=[ALGORITHM])
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session is no longer valid.")
    if user.must_change_password and request.url.path not in {
        "/api/v1/auth/me",
        "/api/v1/auth/change-password",
        "/api/v1/auth/logout",
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Change your temporary password before continuing.",
        )
    return user

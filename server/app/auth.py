import uuid

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.user import User


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
        )
    return authorization.split(None, 1)[1]


def _decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.nextauth_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            options={"verify_aud": settings.jwt_audience is not None},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
        )


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = _decode_token(_extract_token(authorization))
    github_id = payload.get("sub")
    if not github_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
        )
    email = payload.get("email")
    user = (
        await db.execute(select(User).where(User.github_id == github_id))
    ).scalar_one_or_none()
    if user is not None:
        return user
    user = User(id=uuid.uuid4(), github_id=github_id, email=email)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        user = (
            await db.execute(select(User).where(User.github_id == github_id))
        ).scalar_one()
    return user

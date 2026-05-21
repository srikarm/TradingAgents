import jwt
from fastapi import Depends, Header, HTTPException, status
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
    from app.models.user import find_or_create_by_identity

    payload = _decode_token(_extract_token(authorization))
    sub = payload.get("sub")
    email = payload.get("email")
    provider = payload.get("provider") or "github"  # legacy default

    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated"},
        )

    github_id = sub if provider in ("github", "e2e") else None
    google_sub = sub if provider == "google" else None

    return await find_or_create_by_identity(
        db,
        email=email,
        github_id=github_id,
        google_sub=google_sub,
    )

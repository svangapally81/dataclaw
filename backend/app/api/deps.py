from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import verify_session
from app.db.session import get_session
from app.models.domain import User


async def _local_default_user(session: AsyncSession) -> User:
    settings = get_settings()
    user = await session.scalar(select(User).where(User.email == settings.admin_email))
    if user is None:
        user = await session.scalar(select(User).order_by(User.created_at.asc()).limit(1))
    if user is None:
        raise HTTPException(
            status_code=503,
            detail="No bootstrap user. Run `dataclaw bootstrap-admin` or unset DATACLAW_AUTH_DISABLED.",
        )
    return user


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    settings = get_settings()
    if settings.auth_disabled:
        return await _local_default_user(session)
    token = request.cookies.get("dataclaw_session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user_id = verify_session(settings.session_secret, token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session.")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user.")
    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    settings = get_settings()
    if settings.auth_disabled:
        return user
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return user

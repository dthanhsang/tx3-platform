"""TX3 Management Server - Authentication & Authorization"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.config import settings
from database import get_db
from database.models import AuditLog, SessionToken, User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: str, extra: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    result = await db.execute(
        select(User).options(selectinload(User.roles).selectinload(UserRole.role)).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")
    return user


def check_permission(user: User, required_role: str, scope_type: str = "global", scope_id: str | None = None) -> bool:
    """Check if user has at least the required role level."""
    role_hierarchy = {"owner": 4, "admin": 3, "technician": 2, "viewer": 1}
    required_level = role_hierarchy.get(required_role, 0)

    for user_role in user.roles:
        user_level = role_hierarchy.get(user_role.role.name, 0)
        if user_level >= required_level:
            if user_role.scope_type == "global":
                return True
            if scope_type == user_role.scope_type and (scope_id is None or str(user_role.scope_id) == scope_id):
                return True
    return False


def require_role(required_role: str, scope_type: str = "global"):
    """Dependency factory for role-based access control."""
    async def _check(user: User = Depends(get_current_user)) -> User:
        if not check_permission(user, required_role, scope_type):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return _check


async def audit_log(
    db: AsyncSession,
    action: str,
    category: str = "general",
    severity: str = "info",
    user_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    metadata: dict | None = None,
):
    log = AuditLog(
        action=action,
        category=category,
        severity=severity,
        user_id=user_id,
        device_id=device_id,
        ip_address=ip_address,
        metadata=metadata or {},
    )
    db.add(log)
    await db.flush()

"""TX3 Management Server - Auth Routes"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.config import settings
from api.schemas import LoginRequest, LoginResponse, RefreshRequest, UserCreate, UserResponse, UserUpdate
from auth import (
    audit_log, create_access_token, create_refresh_token, get_current_user,
    hash_password, hash_token, require_role, verify_password,
)
from database import get_db
from database.models import Role, SessionToken, User, UserRole

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).options(selectinload(User.roles).selectinload(UserRole.role)).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= settings.max_failed_logins:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.lockout_minutes)
                user.status = "locked"
            await db.commit()
        await audit_log(db, "login_failed", "auth", "warning",
                        user_id=user.id if user else None,
                        ip_address=request.client.host if request.client else None,
                        metadata={"username": body.username})
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.status == "locked":
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked")
        user.status = "active"
        user.locked_until = None

    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user.failed_logins = 0
    user.last_login = datetime.now(timezone.utc)

    access_token = create_access_token(str(user.id))
    refresh = create_refresh_token()
    refresh_expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    session_token = SessionToken(
        user_id=user.id,
        token_hash=hash_token(refresh),
        device_info=request.headers.get("user-agent", "")[:255],
        ip_address=request.client.host if request.client else None,
        expires_at=refresh_expires,
    )
    db.add(session_token)

    await audit_log(db, "login_success", "auth", "info",
                    user_id=user.id,
                    ip_address=request.client.host if request.client else None)
    await db.commit()

    roles = [ur.role.name for ur in user.roles]
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse(
            id=user.id, username=user.username, email=user.email,
            display_name=user.display_name, status=user.status,
            roles=roles, last_login=user.last_login, created_at=user.created_at,
        ),
    )


@router.post("/refresh", response_model=dict)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    hashed = hash_token(body.refresh_token)
    result = await db.execute(select(SessionToken).where(SessionToken.token_hash == hashed))
    token = result.scalar_one_or_none()

    if not token or token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    token.last_used = datetime.now(timezone.utc)
    access_token = create_access_token(str(token.user_id))
    await db.commit()
    return {"access_token": access_token, "token_type": "bearer", "expires_in": settings.access_token_expire_minutes * 60}


@router.post("/logout")
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    hashed = hash_token(body.refresh_token)
    result = await db.execute(select(SessionToken).where(SessionToken.token_hash == hashed))
    token = result.scalar_one_or_none()
    if token:
        await db.delete(token)
        await db.commit()
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    roles = [ur.role.name for ur in user.roles]
    return UserResponse(
        id=user.id, username=user.username, email=user.email,
        display_name=user.display_name, status=user.status,
        roles=roles, last_login=user.last_login, created_at=user.created_at,
    )


@router.post("/users", response_model=UserResponse)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_role("admin"))):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        organization_id=admin.organization_id,
    )
    db.add(user)
    await db.flush()

    role_result = await db.execute(select(Role).where(Role.name == body.role))
    role = role_result.scalar_one_or_none()
    if role:
        db.add(UserRole(user_id=user.id, role_id=role.id))

    await audit_log(db, "user_created", "admin", "info", user_id=admin.id,
                    metadata={"new_user": body.username, "role": body.role})
    await db.commit()

    return UserResponse(
        id=user.id, username=user.username, email=user.email,
        display_name=user.display_name, status=user.status,
        roles=[body.role], last_login=None, created_at=user.created_at,
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(db: AsyncSession = Depends(get_db), admin: User = Depends(require_role("admin"))):
    result = await db.execute(
        select(User).options(selectinload(User.roles).selectinload(UserRole.role)).order_by(User.username)
    )
    users = result.scalars().all()
    return [
        UserResponse(
            id=u.id, username=u.username, email=u.email,
            display_name=u.display_name, status=u.status,
            roles=[ur.role.name for ur in u.roles],
            last_login=u.last_login, created_at=u.created_at,
        )
        for u in users
    ]

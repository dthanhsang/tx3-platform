"""TX3 Management Server - Audit Routes"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import AuditLogResponse
from auth import get_current_user, require_role
from database import get_db
from database.models import AuditLog, User

router = APIRouter()


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    device_id: Optional[uuid.UUID] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    action: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    stmt = select(AuditLog)
    if device_id:
        stmt = stmt.where(AuditLog.device_id == device_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if category:
        stmt = stmt.where(AuditLog.category == category)

    stmt = stmt.order_by(AuditLog.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(stmt)
    return [
        AuditLogResponse(
            id=log.id, user_id=log.user_id, device_id=log.device_id,
            action=log.action, category=log.category, severity=log.severity,
            ip_address=log.ip_address, metadata=log.metadata, created_at=log.created_at,
        )
        for log in result.scalars().all()
    ]

"""TX3 Management Server - Batch Operation Routes"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import BatchRequest, BatchResponse
from auth import audit_log, get_current_user, require_role
from database import get_db
from database.models import BatchOperation, Device, User

router = APIRouter()

MAX_BATCH_CONCURRENCY = 10


@router.post("", response_model=BatchResponse)
async def create_batch(
    body: BatchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    if len(body.device_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 devices per batch")

    # Verify all devices exist and are online
    result = await db.execute(
        select(Device).where(Device.id.in_(body.device_ids))
    )
    devices = result.scalars().all()
    found_ids = {d.id for d in devices}
    missing = [str(did) for did in body.device_ids if did not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Devices not found: {', '.join(missing[:5])}")

    batch = BatchOperation(
        user_id=user.id,
        operation_type=body.operation_type,
        total_count=len(body.device_ids),
        status="pending",
        payload={**body.payload, "device_ids": [str(d) for d in body.device_ids]},
    )
    db.add(batch)

    await audit_log(db, f"batch_{body.operation_type}", "admin", "info",
                    user_id=user.id,
                    metadata={"count": len(body.device_ids), "operation": body.operation_type})
    await db.commit()
    await db.refresh(batch)

    # TODO: Queue batch execution in background worker
    return BatchResponse(
        id=batch.id, operation_type=batch.operation_type,
        total_count=batch.total_count, status=batch.status,
    )


@router.get("/{batch_id}", response_model=BatchResponse)
async def get_batch(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(BatchOperation).where(BatchOperation.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchResponse(
        id=batch.id, operation_type=batch.operation_type,
        total_count=batch.total_count, status=batch.status,
    )


@router.get("", response_model=list[BatchResponse])
async def list_batches(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(BatchOperation).order_by(BatchOperation.started_at.desc()).limit(50)
    )
    return [
        BatchResponse(
            id=b.id, operation_type=b.operation_type,
            total_count=b.total_count, status=b.status,
        )
        for b in result.scalars().all()
    ]


@router.post("/{batch_id}/cancel")
async def cancel_batch(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(BatchOperation).where(BatchOperation.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Batch is not cancellable")
    batch.status = "cancelled"
    await db.commit()
    return {"status": "cancelled"}

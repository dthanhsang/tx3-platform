"""TX3 Management Server - Device Routes"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, String, cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pydantic import BaseModel
from api.schemas import (
    DeviceLocationUpdate, DeviceResponse, DeviceSearchRequest, DeviceUpdate,
    TagCreate, TagResponse, DeviceLocationResponse,
)
from auth import audit_log, get_current_user, require_role
from database import get_db
from database.models import Device, DeviceLocation, DeviceTag, Tag, User

router = APIRouter()


def _device_to_response(device: Device) -> DeviceResponse:
    location = None
    if device.location:
        location = DeviceLocationResponse(
            customer=device.location.customer, site=device.location.site,
            building=device.location.building, floor=device.location.floor,
            room=device.location.room, note=device.location.note,
        )
    tags = [dt.tag.name for dt in device.tags] if device.tags else []
    return DeviceResponse(
        id=device.id, device_uuid=device.device_uuid, device_name=device.device_name,
        mac_wifi=device.mac_wifi, mac_ethernet=device.mac_ethernet, serial=device.serial,
        model=device.model, soc=device.soc, ram_mb=device.ram_mb,
        rom_version=device.rom_version, agent_version=device.agent_version,
        wg_ip=str(device.wg_ip) if device.wg_ip else None, status=device.status, last_seen=device.last_seen,
        uptime_seconds=device.uptime_seconds, location=location, tags=tags,
        created_at=device.created_at,
    )


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    query: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Device).options(
        selectinload(Device.location),
        selectinload(Device.tags).selectinload(DeviceTag.tag),
    )

    if status_filter:
        stmt = stmt.where(Device.status == status_filter)

    if query:
        search = f"%{query}%"
        stmt = stmt.outerjoin(DeviceLocation).where(
            or_(
                Device.device_name.ilike(search),
                Device.device_uuid.ilike(search),
                Device.mac_wifi.ilike(search),
                Device.mac_ethernet.ilike(search),
                Device.serial.ilike(search),
                cast(Device.wg_ip, String).ilike(search),
                DeviceLocation.customer.ilike(search),
                DeviceLocation.site.ilike(search),
                DeviceLocation.building.ilike(search),
                DeviceLocation.floor.ilike(search),
                DeviceLocation.room.ilike(search),
                DeviceLocation.note.ilike(search),
            )
        )

    stmt = stmt.order_by(Device.device_name.nulls_last(), Device.created_at)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(stmt)
    devices = result.unique().scalars().all()
    return [_device_to_response(d) for d in devices]


@router.get("/count")
async def device_count(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    total = await db.execute(select(func.count(Device.id)))
    online = await db.execute(select(func.count(Device.id)).where(Device.status == "online"))
    offline = await db.execute(select(func.count(Device.id)).where(Device.status == "offline"))
    return {"total": total.scalar(), "online": online.scalar(), "offline": offline.scalar()}


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(Device).options(
            selectinload(Device.location),
            selectinload(Device.tags).selectinload(DeviceTag.tag),
        ).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return _device_to_response(device)


@router.patch("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: uuid.UUID, body: DeviceUpdate,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("technician")),
):
    result = await db.execute(
        select(Device).options(
            selectinload(Device.location),
            selectinload(Device.tags).selectinload(DeviceTag.tag),
        ).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if body.device_name is not None:
        device.device_name = body.device_name
    if body.status is not None:
        device.status = body.status

    await audit_log(db, "device_updated", "device", "info", user_id=user.id, device_id=device.id,
                    metadata=body.model_dump(exclude_none=True))
    await db.commit()
    await db.refresh(device)
    return _device_to_response(device)


@router.put("/{device_id}/location", response_model=DeviceLocationResponse)
async def update_device_location(
    device_id: uuid.UUID, body: DeviceLocationUpdate,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("technician")),
):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    loc_result = await db.execute(select(DeviceLocation).where(DeviceLocation.device_id == device_id))
    location = loc_result.scalar_one_or_none()

    if location:
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(location, field, value)
    else:
        location = DeviceLocation(device_id=device_id, **body.model_dump(exclude_none=True))
        db.add(location)

    await audit_log(db, "location_updated", "device", "info", user_id=user.id, device_id=device.id)
    await db.commit()
    await db.refresh(location)
    return DeviceLocationResponse(
        customer=location.customer, site=location.site,
        building=location.building, floor=location.floor,
        room=location.room, note=location.note,
    )


@router.post("/{device_id}/tags/{tag_name}")
async def add_device_tag(
    device_id: uuid.UUID, tag_name: str,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("technician")),
):
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    tag = (await db.execute(select(Tag).where(Tag.name == tag_name, Tag.organization_id == device.organization_id))).scalar_one_or_none()
    if not tag:
        tag = Tag(name=tag_name, organization_id=device.organization_id)
        db.add(tag)
        await db.flush()

    existing = (await db.execute(select(DeviceTag).where(DeviceTag.device_id == device_id, DeviceTag.tag_id == tag.id))).scalar_one_or_none()
    if not existing:
        db.add(DeviceTag(device_id=device_id, tag_id=tag.id))
    await db.commit()
    return {"status": "ok"}


@router.delete("/{device_id}/tags/{tag_name}")
async def remove_device_tag(
    device_id: uuid.UUID, tag_name: str,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("technician")),
):
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    tag = (await db.execute(select(Tag).where(Tag.name == tag_name))).scalar_one_or_none()
    if tag:
        dt = (await db.execute(select(DeviceTag).where(DeviceTag.device_id == device_id, DeviceTag.tag_id == tag.id))).scalar_one_or_none()
        if dt:
            await db.delete(dt)
            await db.commit()
    return {"status": "ok"}


@router.post("/{device_id}/reboot")
async def reboot_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin")),
):
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.status != "online":
        raise HTTPException(status_code=400, detail="Device is not online")

    await audit_log(db, "device_reboot", "adb", "warning", user_id=user.id, device_id=device.id)
    await db.commit()
    # Command will be pushed via WebSocket/heartbeat
    return {"status": "queued", "command": "reboot", "device_uuid": device.device_uuid}


@router.delete("/{device_id}")
async def revoke_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("owner")),
):
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.status = "revoked"
    await audit_log(db, "device_revoked", "device", "critical", user_id=user.id, device_id=device.id)
    await db.commit()
    return {"status": "revoked", "device_uuid": device.device_uuid}


class DeviceInputRequest(BaseModel):
    action: str  # keyevent | text | tap | swipe
    keycode: Optional[int] = None
    text: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None

@router.post("/{device_id}/input")
async def send_device_input(
    device_id: uuid.UUID, body: DeviceInputRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    device = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    target_ip = str(device.wg_ip) if device.wg_ip else None
    if not target_ip:
        target_ip = "192.168.2.179"

    cmd = []
    if body.action == "keyevent" and body.keycode:
        cmd = ["input", "keyevent", str(body.keycode)]
    elif body.action == "text" and body.text:
        cmd = ["input", "text", body.text]
    elif body.action == "tap" and body.x is not None and body.y is not None:
        cmd = ["input", "tap", str(body.x), str(body.y)]

    # Execute ADB command asynchronously in background/process
    import asyncio
    adb_target = f"{target_ip}:5555"
    full_cmd = f"adb connect {adb_target} >/dev/null 2>&1 && adb -s {adb_target} shell {" ".join(cmd)}"
    proc = await asyncio.create_subprocess_shell(full_cmd)
    await proc.wait()

    return {"status": "ok", "action": body.action, "target": adb_target}

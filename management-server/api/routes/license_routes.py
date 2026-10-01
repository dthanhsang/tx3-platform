"""TX3 Management Server - License Routes"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.schemas import LicenseCreate, LicenseResponse, LicenseValidateRequest, LicenseValidateResponse
from auth import audit_log, get_current_user, hash_token, require_role
from database import get_db
from database.models import License, Organization, User

router = APIRouter()


@router.post("", response_model=LicenseResponse)
async def create_license(
    body: LicenseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("owner")),
):
    org = (await db.execute(select(Organization).where(Organization.id == body.organization_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    raw_key = f"TX3-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days) if body.expires_days else None

    lic = License(
        organization_id=body.organization_id,
        license_key_hash=hash_token(raw_key),
        plan=body.plan,
        max_devices=body.max_devices,
        expires_at=expires_at,
    )
    db.add(lic)
    await audit_log(db, "license_created", "admin", "info", user_id=user.id,
                    metadata={"org": str(body.organization_id), "plan": body.plan, "max": body.max_devices})
    await db.commit()
    await db.refresh(lic)

    return LicenseResponse(
        id=lic.id, organization_id=lic.organization_id, plan=lic.plan,
        max_devices=lic.max_devices, status=lic.status, expires_at=lic.expires_at,
        created_at=lic.created_at, license_key=raw_key,
    )


@router.get("", response_model=list[LicenseResponse])
async def list_licenses(db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    result = await db.execute(select(License).order_by(License.created_at.desc()))
    return [
        LicenseResponse(
            id=l.id, organization_id=l.organization_id, plan=l.plan,
            max_devices=l.max_devices, status=l.status, expires_at=l.expires_at,
            created_at=l.created_at,
        )
        for l in result.scalars().all()
    ]


@router.post("/validate", response_model=LicenseValidateResponse)
async def validate_license(body: LicenseValidateRequest, db: AsyncSession = Depends(get_db)):
    hashed = hash_token(body.license_key)
    result = await db.execute(
        select(License).where(License.license_key_hash == hashed)
    )
    lic = result.scalar_one_or_none()
    if not lic:
        return LicenseValidateResponse(valid=False)

    if lic.status != "active":
        return LicenseValidateResponse(valid=False)

    if lic.expires_at and lic.expires_at < datetime.now(timezone.utc):
        lic.status = "expired"
        await db.commit()
        return LicenseValidateResponse(valid=False)

    org = (await db.execute(select(Organization).where(Organization.id == lic.organization_id))).scalar_one_or_none()

    return LicenseValidateResponse(
        valid=True, plan=lic.plan, max_devices=lic.max_devices,
        organization_name=org.name if org else None, expires_at=lic.expires_at,
    )


@router.delete("/{license_id}")
async def revoke_license(
    license_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("owner")),
):
    lic = (await db.execute(select(License).where(License.id == license_id))).scalar_one_or_none()
    if not lic:
        raise HTTPException(status_code=404, detail="License not found")
    lic.status = "revoked"
    await audit_log(db, "license_revoked", "admin", "warning", user_id=user.id,
                    metadata={"license_id": str(license_id)})
    await db.commit()
    return {"status": "revoked"}

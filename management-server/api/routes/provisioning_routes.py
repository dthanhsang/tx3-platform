"""TX3 Management Server - Provisioning Routes"""
from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.schemas import HeartbeatRequest, HeartbeatResponse, ProvisionRequest, ProvisionResponse, WgConfig, AgentConfig
from auth import audit_log, hash_token
from database import get_db
from database.models import Device, ProvisioningToken, WgPeer

router = APIRouter()


async def _next_wg_ip(db: AsyncSession) -> str:
    """Allocate the next available WireGuard IP in the subnet."""
    network = ipaddress.ip_network(settings.wg_subnet, strict=False)
    hosts = list(network.hosts())
    # Reserve .1 for server
    used_result = await db.execute(select(WgPeer.assigned_ip))
    used_ips = {str(row[0]).split('/')[0] for row in used_result.all() if row[0]}
    used_ips.add(str(settings.wg_server_ip).split('/')[0])

    for host in hosts[1:]:  # Skip .1 (server)
        ip_str = str(host)
        if ip_str not in used_ips:
            return ip_str

    raise HTTPException(status_code=507, detail="No available WireGuard IPs in subnet")


@router.post("/provision", response_model=ProvisionResponse)
@router.post("/register", response_model=ProvisionResponse)
async def provision_device(body: ProvisionRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Device first-boot provisioning endpoint."""
    # Validate bootstrap token
    token_hash = hash_token(body.bootstrap_token)
    result = await db.execute(
        select(ProvisioningToken).where(
            ProvisioningToken.token_hash == token_hash,
            ProvisioningToken.status == "active",
        )
    )
    prov_token = result.scalar_one_or_none()

    if not prov_token:
        await audit_log(db, "provision_rejected", "device", "warning",
                        ip_address=request.client.host if request.client else None,
                        metadata={"reason": "invalid_token"})
        await db.commit()
        return ProvisionResponse(status="rejected", error="Invalid bootstrap token")

    if prov_token.expires_at and prov_token.expires_at < datetime.now(timezone.utc):
        prov_token.status = "expired"
        await db.commit()
        return ProvisionResponse(status="rejected", error="Bootstrap token expired")

    if prov_token.used_count >= prov_token.max_uses:
        prov_token.status = "exhausted"
        await db.commit()
        return ProvisionResponse(status="rejected", error="Bootstrap token exhausted")

    # Check if device already registered (by hardware fingerprint or MAC)
    existing = None
    if body.hardware_fingerprint:
        result = await db.execute(
            select(Device).where(Device.hardware_fingerprint == body.hardware_fingerprint)
        )
        existing = result.scalar_one_or_none()

    if not existing and body.mac_ethernet:
        result = await db.execute(select(Device).where(Device.mac_ethernet == body.mac_ethernet))
        existing = result.scalar_one_or_none()

    if not existing and body.serial:
        result = await db.execute(select(Device).where(Device.serial == body.serial))
        existing = result.scalar_one_or_none()

    if existing:
        # Re-provisioning existing device
        device = existing
        device.wg_public_key = body.wg_public_key
        device.rom_version = body.rom_version
        device.status = "online"
        device.last_seen = datetime.now(timezone.utc)

        # Update WireGuard peer
        wg_result = await db.execute(select(WgPeer).where(WgPeer.device_id == device.id))
        wg_peer = wg_result.scalar_one_or_none()
        if wg_peer:
            wg_peer.public_key = body.wg_public_key
            wg_peer.status = "active"
            assigned_ip = wg_peer.assigned_ip
        else:
            assigned_ip = await _next_wg_ip(db)
            wg_peer = WgPeer(
                device_id=device.id,
                public_key=body.wg_public_key,
                assigned_ip=assigned_ip,
            )
            db.add(wg_peer)
    else:
        # New device
        device_uuid = f"TX3-{uuid.uuid4().hex[:8].upper()}"
        assigned_ip = await _next_wg_ip(db)

        device = Device(
            device_uuid=device_uuid,
            organization_id=prov_token.organization_id,
            mac_wifi=body.mac_wifi,
            mac_ethernet=body.mac_ethernet,
            serial=body.serial,
            android_id=body.android_id,
            model=body.model,
            soc=body.soc,
            ram_mb=body.ram_mb,
            rom_version=body.rom_version,
            wg_public_key=body.wg_public_key,
            wg_ip=assigned_ip,
            hardware_fingerprint=body.hardware_fingerprint,
            status="online",
            last_seen=datetime.now(timezone.utc),
        )
        db.add(device)
        await db.flush()

        wg_peer = WgPeer(
            device_id=device.id,
            public_key=body.wg_public_key,
            assigned_ip=assigned_ip,
        )
        db.add(wg_peer)

    prov_token.used_count += 1

    await audit_log(db, "device_provisioned", "device", "info",
                    device_id=device.id,
                    ip_address=request.client.host if request.client else None,
                    metadata={"device_uuid": device.device_uuid, "model": body.model})
    await db.commit()

    return ProvisionResponse(
        status="ok",
        device_uuid=device.device_uuid,
        wg_config=WgConfig(
            address=f"{assigned_ip}/32",
            server_public_key=settings.wg_server_public_key,
            server_endpoint=settings.wg_server_endpoint,
            allowed_ips="10.88.0.0/24",
            persistent_keepalive=25,
        ),
        agent_config=AgentConfig(
            heartbeat_interval=settings.heartbeat_interval,
            server_api_url=f"http://{settings.wg_server_ip}:{settings.port}/api/v1",
            server_ws_url=f"ws://{settings.wg_server_ip}:{settings.port}/ws",
        ),
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(body: HeartbeatRequest, db: AsyncSession = Depends(get_db)):
    """Device heartbeat - updates status and telemetry."""
    result = await db.execute(select(Device).where(Device.device_uuid == body.device_uuid))
    device = result.scalar_one_or_none()

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.status == "revoked":
        raise HTTPException(status_code=403, detail="Device has been revoked")

    now = datetime.now(timezone.utc)
    device.status = "online"
    device.last_seen = now
    device.agent_version = body.agent_version
    device.uptime_seconds = body.uptime_seconds
    if body.rom_version:
        device.rom_version = body.rom_version
    if body.wg_ip and body.wg_ip.startswith("10.88.0."):
        device.wg_ip = body.wg_ip

    device.last_heartbeat = {
        "ram_used_mb": body.ram_used_mb,
        "ram_total_mb": body.ram_total_mb,
        "cpu_percent": body.cpu_percent,
        "temperature_c": body.temperature_c,
        "storage_used_mb": body.storage_used_mb,
        "storage_total_mb": body.storage_total_mb,
        "network_state": body.network_state,
    }

    # TODO: Check for pending commands (reboot, update, etc.)
    commands = []

    await db.commit()

    return HeartbeatResponse(
        server_time=int(now.timestamp() * 1000),
        commands=commands,
    )

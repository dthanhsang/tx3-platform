"""TX3 Management Server - API Schemas (Pydantic)"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ── Auth ──
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

class RefreshRequest(BaseModel):
    refresh_token: str


# ── Users ──
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: Optional[str] = None
    password: str = Field(min_length=8)
    display_name: Optional[str] = None
    role: str = "viewer"

class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: Optional[str]
    display_name: Optional[str]
    status: str
    roles: list[str] = []
    last_login: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None


# ── Organizations ──
class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)

class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Licenses ──
class LicenseCreate(BaseModel):
    organization_id: uuid.UUID
    plan: str = "standard"
    max_devices: int = 10
    expires_days: Optional[int] = 365

class LicenseResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    plan: str
    max_devices: int
    status: str
    expires_at: Optional[datetime]
    created_at: datetime
    license_key: Optional[str] = None  # Only returned on creation
    model_config = {"from_attributes": True}

class LicenseValidateRequest(BaseModel):
    license_key: str

class LicenseValidateResponse(BaseModel):
    valid: bool
    plan: Optional[str] = None
    max_devices: Optional[int] = None
    organization_name: Optional[str] = None
    expires_at: Optional[datetime] = None


# ── Devices ──
class DeviceResponse(BaseModel):
    id: uuid.UUID
    device_uuid: str
    device_name: Optional[str]
    mac_wifi: Optional[str]
    mac_ethernet: Optional[str]
    serial: Optional[str]
    model: Optional[str]
    soc: Optional[str]
    ram_mb: Optional[int]
    rom_version: Optional[str]
    agent_version: Optional[str]
    wg_ip: Optional[str]
    status: str
    last_seen: Optional[datetime]
    uptime_seconds: Optional[int]
    location: Optional[DeviceLocationResponse] = None
    tags: list[str] = []
    created_at: datetime
    model_config = {"from_attributes": True}

class DeviceUpdate(BaseModel):
    device_name: Optional[str] = None
    status: Optional[str] = None

class DeviceLocationResponse(BaseModel):
    customer: Optional[str]
    site: Optional[str]
    building: Optional[str]
    floor: Optional[str]
    room: Optional[str]
    note: Optional[str]
    model_config = {"from_attributes": True}

class DeviceLocationUpdate(BaseModel):
    customer: Optional[str] = None
    site: Optional[str] = None
    building: Optional[str] = None
    floor: Optional[str] = None
    room: Optional[str] = None
    address_text: Optional[str] = None
    note: Optional[str] = None

class DeviceSearchRequest(BaseModel):
    query: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[list[str]] = None
    organization_id: Optional[uuid.UUID] = None
    page: int = 1
    page_size: int = 50


# ── Provisioning ──
class ProvisionRequest(BaseModel):
    bootstrap_token: str
    mac_wifi: Optional[str] = None
    mac_ethernet: Optional[str] = None
    serial: Optional[str] = None
    android_id: Optional[str] = None
    model: Optional[str] = None
    soc: Optional[str] = None
    ram_mb: Optional[int] = None
    rom_version: Optional[str] = None
    wg_public_key: str
    hardware_fingerprint: Optional[str] = None

class ProvisionResponse(BaseModel):
    status: str  # ok | rejected | error
    device_uuid: Optional[str] = None
    wg_config: Optional[WgConfig] = None
    agent_config: Optional[AgentConfig] = None
    error: Optional[str] = None

class WgConfig(BaseModel):
    address: str
    server_public_key: str
    server_endpoint: str
    allowed_ips: str = "10.88.0.0/24"
    persistent_keepalive: int = 25

class AgentConfig(BaseModel):
    heartbeat_interval: int = 30
    server_api_url: str
    server_ws_url: str


# ── Heartbeat ──
class HeartbeatRequest(BaseModel):
    device_uuid: str
    agent_version: str
    rom_version: Optional[str] = None
    uptime_seconds: int = 0
    wg_ip: Optional[str] = None
    network_state: str = "connected"
    ram_used_mb: Optional[int] = None
    ram_total_mb: Optional[int] = None
    cpu_percent: Optional[float] = None
    temperature_c: Optional[float] = None
    storage_used_mb: Optional[int] = None
    storage_total_mb: Optional[int] = None

class HeartbeatResponse(BaseModel):
    server_time: int
    commands: list[dict] = []


# ── Remote Sessions ──
class RemoteSessionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    device_id: uuid.UUID
    session_type: str
    started_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: Optional[int]
    result: str
    model_config = {"from_attributes": True}


# ── Transfers ──
class TransferResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    device_id: uuid.UUID
    direction: str
    filename: str
    file_size: int
    transferred: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    model_config = {"from_attributes": True}


# ── Tags ──
class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class TagResponse(BaseModel):
    id: uuid.UUID
    name: str
    model_config = {"from_attributes": True}


# ── Audit ──
class AuditLogResponse(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID]
    device_id: Optional[uuid.UUID]
    action: str
    category: str
    severity: str
    ip_address: Optional[str]
    metadata: dict
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Batch ──
class BatchRequest(BaseModel):
    operation_type: str  # install_apk | send_file | adb_command | reboot
    device_ids: list[uuid.UUID]
    payload: dict = {}

class BatchResponse(BaseModel):
    id: uuid.UUID
    operation_type: str
    total_count: int
    status: str
    model_config = {"from_attributes": True}


# ── Telemetry ──
class TelemetryResponse(BaseModel):
    cpu_percent: Optional[float]
    ram_used_mb: Optional[int]
    ram_total_mb: Optional[int]
    temperature_c: Optional[float]
    storage_used_mb: Optional[int]
    storage_total_mb: Optional[int]
    recorded_at: datetime
    model_config = {"from_attributes": True}


# Forward ref fix
DeviceResponse.model_rebuild()
ProvisionResponse.model_rebuild()

"""TX3 Management Server - WebSocket Routes"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import decode_token
from database import async_session
from database.models import Device, RemoteSession

router = APIRouter()

# Connected devices and managers
connected_devices: dict[str, WebSocket] = {}  # device_uuid -> ws
connected_managers: dict[str, WebSocket] = {}  # user_id -> ws
device_sessions: dict[str, str] = {}  # session_id -> device_uuid


@router.websocket("/device/{device_uuid}")
async def device_ws(websocket: WebSocket, device_uuid: str):
    """WebSocket endpoint for Android box agents."""
    await websocket.accept()
    connected_devices[device_uuid] = websocket

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "")

            if msg_type == "agent.heartbeat":
                # Process heartbeat via WS
                async with async_session() as db:
                    result = await db.execute(select(Device).where(Device.device_uuid == device_uuid))
                    device = result.scalar_one_or_none()
                    if device:
                        device.status = "online"
                        device.last_seen = datetime.now(timezone.utc)
                        device.last_heartbeat = msg.get("payload", {})
                        await db.commit()

                await websocket.send_text(json.dumps({
                    "type": "server.heartbeat_ack",
                    "id": str(uuid.uuid4()),
                    "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "payload": {"server_time": int(datetime.now(timezone.utc).timestamp() * 1000), "commands": []},
                }))

            elif msg_type == "box.remote_ready":
                session_id = msg.get("payload", {}).get("session_id")
                if session_id and session_id in device_sessions:
                    # Forward to the requesting manager
                    for uid, ws in connected_managers.items():
                        try:
                            await ws.send_text(data)
                        except Exception:
                            pass

            elif msg_type == "box.remote_stopped":
                session_id = msg.get("payload", {}).get("session_id")
                device_sessions.pop(session_id, None)
                for uid, ws in connected_managers.items():
                    try:
                        await ws.send_text(data)
                    except Exception:
                        pass

            elif msg_type == "box.resource_report":
                for uid, ws in connected_managers.items():
                    try:
                        await ws.send_text(data)
                    except Exception:
                        pass

            elif msg_type == "box.file_list_result":
                for uid, ws in connected_managers.items():
                    try:
                        await ws.send_text(data)
                    except Exception:
                        pass

            elif msg_type == "box.file_chunk_ack":
                for uid, ws in connected_managers.items():
                    try:
                        await ws.send_text(data)
                    except Exception:
                        pass

            elif msg_type == "box.adb_result":
                for uid, ws in connected_managers.items():
                    try:
                        await ws.send_text(data)
                    except Exception:
                        pass

    except WebSocketDisconnect:
        pass
    finally:
        connected_devices.pop(device_uuid, None)
        # Mark device offline
        async with async_session() as db:
            result = await db.execute(select(Device).where(Device.device_uuid == device_uuid))
            device = result.scalar_one_or_none()
            if device:
                device.status = "offline"
                await db.commit()


@router.websocket("/manager")
async def manager_ws(websocket: WebSocket):
    """WebSocket endpoint for TX3 Manager desktop clients."""
    await websocket.accept()

    # Authenticate
    try:
        auth_msg = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        auth_data = json.loads(auth_msg)
        if auth_data.get("type") != "auth":
            await websocket.close(code=4001, reason="Expected auth message")
            return
        token = auth_data.get("token", "")
        payload = decode_token(token)
        user_id = payload.get("sub", "")
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    connected_managers[user_id] = websocket
    await websocket.send_text(json.dumps({"type": "auth_ok", "user_id": user_id}))

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "")
            payload_data = msg.get("payload", {})

            if msg_type == "client.remote_start":
                # Find device and forward
                session_id = payload_data.get("session_id", str(uuid.uuid4()))
                device_uuid = payload_data.get("device_uuid", "")

                if device_uuid in connected_devices:
                    device_sessions[session_id] = device_uuid
                    # Record session in DB
                    async with async_session() as db:
                        result = await db.execute(select(Device).where(Device.device_uuid == device_uuid))
                        device = result.scalar_one_or_none()
                        if device:
                            session = RemoteSession(
                                user_id=uuid.UUID(user_id),
                                device_id=device.id,
                                session_type="remote",
                            )
                            db.add(session)
                            await db.commit()

                    await connected_devices[device_uuid].send_text(data)
                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "payload": {"code": "E004", "message": "Device offline"},
                    }))

            elif msg_type == "client.remote_stop":
                session_id = payload_data.get("session_id", "")
                device_uuid = device_sessions.get(session_id, "")
                if device_uuid and device_uuid in connected_devices:
                    await connected_devices[device_uuid].send_text(data)
                device_sessions.pop(session_id, None)

            elif msg_type in ("client.input_mouse", "client.input_keyboard", "client.input_android"):
                session_id = payload_data.get("session_id", "")
                device_uuid = device_sessions.get(session_id, "")
                if device_uuid and device_uuid in connected_devices:
                    await connected_devices[device_uuid].send_text(data)

            elif msg_type in ("client.file_list", "client.file_upload_start", "client.file_chunk",
                              "client.file_download_start", "client.file_mkdir", "client.file_rename",
                              "client.file_delete", "client.file_move",
                              "transfer.pause", "transfer.resume", "transfer.cancel"):
                device_uuid = payload_data.get("device_uuid", "")
                if device_uuid and device_uuid in connected_devices:
                    await connected_devices[device_uuid].send_text(data)

            elif msg_type == "client.adb_command":
                device_uuid = payload_data.get("device_uuid", "")
                if device_uuid and device_uuid in connected_devices:
                    await connected_devices[device_uuid].send_text(data)

            elif msg_type == "client.device_reboot":
                device_uuid = payload_data.get("device_uuid", "")
                if device_uuid and device_uuid in connected_devices:
                    await connected_devices[device_uuid].send_text(data)

            elif msg_type == "client.profile_change":
                session_id = payload_data.get("session_id", "")
                device_uuid = device_sessions.get(session_id, "")
                if device_uuid and device_uuid in connected_devices:
                    await connected_devices[device_uuid].send_text(data)

    except WebSocketDisconnect:
        pass
    finally:
        connected_managers.pop(user_id, None)

"""TX3 Remote WebSocket Proxy - Routes WebSocket from container to host remote stream server."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger("tx3.remote_proxy")

router = APIRouter()

# Host remote stream server reachable from container via Docker gateway
REMOTE_HOST = "172.23.0.1"
REMOTE_PORT = 15100


async def _proxy_ws(client_ws: WebSocket, target_url: str):
    """Bidirectional WebSocket proxy."""
    import websockets

    await client_ws.accept()

    try:
        async with websockets.connect(target_url, max_size=2**22, ping_interval=20) as server_ws:

            async def client_to_server():
                try:
                    while True:
                        try:
                            data = await client_ws.receive_bytes()
                            await server_ws.send(data)
                        except Exception:
                            try:
                                data = await client_ws.receive_text()
                                await server_ws.send(data)
                            except Exception:
                                break
                except WebSocketDisconnect:
                    pass

            async def server_to_client():
                try:
                    async for message in server_ws:
                        if isinstance(message, bytes):
                            await client_ws.send_bytes(message)
                        else:
                            await client_ws.send_text(message)
                except Exception:
                    pass

            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_server()), asyncio.create_task(server_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        logger.error(f"Proxy error: {e}")
        try:
            await client_ws.close(code=1011, reason=str(e))
        except Exception:
            pass


@router.websocket("/stream")
async def proxy_stream(websocket: WebSocket, device_ip: str = Query(...), fps: int = Query(8)):
    target_url = f"ws://{REMOTE_HOST}:{REMOTE_PORT}/ws/remote/stream?device_ip={device_ip}&fps={fps}"
    await _proxy_ws(websocket, target_url)


@router.websocket("/input")
async def proxy_input(websocket: WebSocket, device_ip: str = Query(...)):
    target_url = f"ws://{REMOTE_HOST}:{REMOTE_PORT}/ws/remote/input?device_ip={device_ip}"
    await _proxy_ws(websocket, target_url)

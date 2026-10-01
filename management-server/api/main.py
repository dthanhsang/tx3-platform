"""TX3 Management Server - Main Application"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from api.config import settings
from database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Start background heartbeat checker
    task = asyncio.create_task(_heartbeat_monitor())
    yield
    task.cancel()


app = FastAPI(
    title="TX3 Management Server",
    version="1.0.0",
    description="Remote Management API for TX3 Android TV Box fleet",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ──
from api.routes.auth_routes import router as auth_router
from api.routes.device_routes import router as device_router
from api.routes.provisioning_routes import router as provision_router
from api.routes.license_routes import router as license_router
from api.routes.audit_routes import router as audit_router
from api.routes.batch_routes import router as batch_router
from api.routes.ws_routes import router as ws_router
from api.routes.remote_proxy import router as remote_proxy_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(device_router, prefix="/api/v1/devices", tags=["Devices"])
app.include_router(provision_router, prefix="/api/v1/provisioning", tags=["Provisioning"])
app.include_router(license_router, prefix="/api/v1/licenses", tags=["Licenses"])
app.include_router(audit_router, prefix="/api/v1/audit", tags=["Audit"])
app.include_router(batch_router, prefix="/api/v1/batch", tags=["Batch Operations"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket"])
app.include_router(remote_proxy_router, prefix="/ws/remote", tags=["Remote Stream"])

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


async def _heartbeat_monitor():
    """Background task: mark devices offline if heartbeat timeout exceeded."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from database import async_session
    from database.models import Device

    while True:
        try:
            async with async_session() as db:
                threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.offline_threshold)
                await db.execute(
                    update(Device)
                    .where(Device.status == "online", Device.last_seen < threshold)
                    .values(status="offline")
                )
                await db.commit()
        except Exception:
            pass
        await asyncio.sleep(30)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host=settings.host, port=settings.port, reload=settings.debug)

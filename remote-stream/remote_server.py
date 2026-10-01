import asyncio
import io
import logging
import subprocess
from PIL import Image
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remote_stream")

app = FastAPI(title="TX3 Ultra-Fast MJPEG JPEG Realtime Remote Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADB_PATH = "/usr/bin/adb"

def get_adb_target(device_ip: str) -> str:
    if ":" not in device_ip:
        return f"{device_ip}:5555"
    return device_ip

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/remote/stream")
async def stream(websocket: WebSocket, device_ip: str = Query(...)):
    await websocket.accept()
    target = get_adb_target(device_ip)
    logger.info(f"Client connected for JPEG Stream: {target}")

    # Ensure ADB connected
    proc_conn = await asyncio.create_subprocess_exec(
        ADB_PATH, "connect", target,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    await proc_conn.wait()

    try:
        while True:
            # Capture PNG frame directly via ADB
            cap_proc = await asyncio.create_subprocess_exec(
                ADB_PATH, "-s", target, "exec-out", "screencap", "-p",
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            raw_png, _ = await cap_proc.communicate()

            if raw_png:
                try:
                    # Convert PNG to lightweight 480p JPEG image (approx 15-20KB)
                    img = Image.open(io.BytesIO(raw_png))
                    img = img.convert('RGB')
                    img.thumbnail((854, 480))
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG', quality=50)
                    jpeg_bytes = buf.getvalue()
                    
                    # Send binary JPEG frame over WebSocket
                    await websocket.send_bytes(jpeg_bytes)
                except Exception as ex:
                    logger.error(f"Frame processing error: {ex}")

            # Send ~2-3 frames per second for smooth web interaction without lag
            await asyncio.sleep(0.3)
    except (WebSocketDisconnect, asyncio.CancelledError):
        logger.info(f"Stream client disconnected: {target}")
    except Exception as e:
        logger.error(f"Stream handler error: {e}")

@app.websocket("/ws/remote/input")
async def input_control(websocket: WebSocket, device_ip: str = Query(...)):
    await websocket.accept()
    target = get_adb_target(device_ip)
    logger.info(f"Input client connected: {target}")

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "keyevent":
                keycode = data.get("keycode")
                if keycode:
                    cmd = [ADB_PATH, "-s", target, "shell", "input", "keyevent", str(keycode)]
                    asyncio.create_task(_run_cmd(cmd))
                    await websocket.send_json({"status": "ok", "action": "keyevent"})

            elif action == "tap":
                x = data.get("x")
                y = data.get("y")
                if x is not None and y is not None:
                    cmd = [ADB_PATH, "-s", target, "shell", "input", "tap", str(x), str(y)]
                    asyncio.create_task(_run_cmd(cmd))
                    await websocket.send_json({"status": "ok", "action": "tap"})

            elif action == "swipe":
                x1 = data.get("x1")
                y1 = data.get("y1")
                x2 = data.get("x2")
                y2 = data.get("y2")
                dur = data.get("duration", 300)
                if all(v is not None for v in [x1, y1, x2, y2]):
                    cmd = [ADB_PATH, "-s", target, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(dur)]
                    asyncio.create_task(_run_cmd(cmd))
                    await websocket.send_json({"status": "ok", "action": "swipe"})

            elif action == "text":
                text = data.get("text", "")
                if text:
                    safe_text = text.replace(" ", "%s")
                    cmd = [ADB_PATH, "-s", target, "shell", "input", "text", safe_text]
                    asyncio.create_task(_run_cmd(cmd))
                    await websocket.send_json({"status": "ok", "action": "text"})

    except WebSocketDisconnect:
        logger.info(f"Input client disconnected: {target}")
    except Exception as e:
        logger.error(f"Input handler error: {e}")

async def _run_cmd(cmd):
    try:
        p = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await p.wait()
    except Exception as e:
        logger.error(f"ADB exec error: {e}")

if __name__ == "__main__":
    uvicorn.run("remote_server:app", host="0.0.0.0", port=15100, log_level="info")

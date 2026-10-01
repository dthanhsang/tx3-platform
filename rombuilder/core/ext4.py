from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))


def tools_root() -> Path:
    bundled = resource_root() / "tools" / "cygwin"
    if bundled.exists():
        return bundled
    development = Path(__file__).resolve().parents[3] / "work" / "tools" / "cygwin-current"
    if development.exists():
        return development
    raise FileNotFoundError("Không tìm thấy bộ công cụ EXT4/debugfs")


def _environment():
    root = tools_root()
    env = os.environ.copy()
    env["PATH"] = str(root / "usr" / "bin") + os.pathsep + env.get("PATH", "")
    return root, env


def run_debugfs(image, command, write=False):
    root, env = _environment()
    args = [str(root / "usr" / "sbin" / "debugfs.exe")]
    if write: args.append("-w")
    args += ["-R", command, str(image)]
    result = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def list_dir(image, path):
    output = run_debugfs(image, f"ls -p {path}")
    entries = []
    for line in output.splitlines():
        if not line.startswith("/"):
            continue
        parts = line.split("/")
        if len(parts) < 7:
            continue
        name = parts[5]
        if name in (".", ".."):
            continue
        entries.append({"mode": parts[2], "name": name, "size": int(parts[6] or 0)})
    return entries


def list_apks(image, progress=None):
    found = []
    roots = [("/app", "system/app"), ("/priv-app", "system/priv-app"), ("/preinstall", "system/preinstall")]
    for root_index, (root, location) in enumerate(roots):
        queue = [root]
        while queue:
            current = queue.pop(0)
            try:
                entries = list_dir(image, current)
            except RuntimeError:
                continue
            for entry in entries:
                child = current.rstrip("/") + "/" + entry["name"]
                if entry["mode"].startswith("04") and entry["name"] not in ("oat", "lib"):
                    queue.append(child)
                elif entry["mode"].startswith("10") and entry["name"].lower().endswith(".apk"):
                    found.append({"name": entry["name"], "path": child, "location": location, "size": entry["size"]})
        if progress:
            progress(int((root_index + 1) * 100 / len(roots)), f"Đang đọc ứng dụng trong {location}")
    return found


def cygwin_path(path: str | Path) -> str:
    path = Path(path).resolve()
    drive = path.drive.rstrip(":").lower()
    rest = path.as_posix()[2:]
    return f"/cygdrive/{drive}{rest}"


def apply_commands(image, commands):
    root, env = _environment()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as command_file:
        command_file.write("\n".join(commands) + "\n")
        command_path = command_file.name
    try:
        args = [str(root / "usr" / "sbin" / "debugfs.exe"), "-w", "-f", command_path, str(image)]
        result = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout + result.stderr
    finally:
        Path(command_path).unlink(missing_ok=True)


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "App"


def validate_ext4(image):
    root, env = _environment()
    result = subprocess.run([str(root / "usr" / "sbin" / "e2fsck.exe"), "-fn", str(image)], env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode not in (0, 1):
        raise RuntimeError("Kiểm tra EXT4 thất bại:\n" + (result.stdout + result.stderr)[-4000:])
    return result.stdout + result.stderr


def repair_ext4(image):
    """Repair filesystem metadata and return the checker report."""
    root, env = _environment()
    result = subprocess.run([str(root / "usr" / "sbin" / "e2fsck.exe"), "-fy", str(image)], env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode not in (0, 1, 2):
        raise RuntimeError("EXT4 repair failed:\n" + (result.stdout + result.stderr)[-4000:])
    return result.stdout + result.stderr

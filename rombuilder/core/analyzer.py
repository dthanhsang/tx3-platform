from __future__ import annotations

from .detector import detect_firmware
from rombuilder.handlers import amlogic, phoenixsuit


def analyze_firmware(path, progress=None, verify_crc=True):
    kind = detect_firmware(path)
    if kind == "amlogic-v2":
        return amlogic.analyze(path, progress, verify_crc)
    if kind == "allwinner-phoenixsuit":
        return phoenixsuit.analyze(path, progress, verify_crc)
    raise ValueError(f"Chưa có bộ xử lý cho {kind}")


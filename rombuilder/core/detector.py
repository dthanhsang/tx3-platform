from __future__ import annotations

from pathlib import Path


class UnsupportedFirmwareError(ValueError):
    pass


def detect_firmware(path: str | Path) -> str:
    firmware = Path(path)
    if not firmware.is_file():
        raise FileNotFoundError(firmware)
    with firmware.open("rb") as source:
        header = source.read(0x4000)
    if len(header) >= 0x2900:
        # Amlogic package records use fixed 0x240-byte entries and ASCII item types.
        if b"PARTITION\x00" in header and b"VERIFY\x00" in header:
            return "amlogic-v2"
    # Allwinner/PhoenixSuit signatures vary by generation. The handler will perform
    # strict validation before enabling extraction/repack.
    if any(mark in header for mark in (b"IMAGEWTY", b"Allwinner", b"softw311")):
        return "allwinner-phoenixsuit"
    raise UnsupportedFirmwareError("Không nhận diện được định dạng firmware")


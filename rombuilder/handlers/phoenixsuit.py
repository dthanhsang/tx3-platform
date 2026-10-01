from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from rombuilder.core.models import FirmwareInfo, PartitionInfo


@dataclass
class PhoenixItem:
    index: int
    main: str
    sub: str
    filename: str
    data_length: int
    file_length: int
    offset: int


def _text(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("ascii", "replace").strip()


def _hi_lo(data: bytes, at: int) -> int:
    return (struct.unpack_from("<I", data, at)[0] << 32) | struct.unpack_from("<I", data, at + 4)[0]


def read_items(path: str | Path) -> tuple[bytes, list[PhoenixItem]]:
    with Path(path).open("rb") as source:
        header = source.read(0x400)
        if header[:8] != b"IMAGEWTY":
            raise ValueError("Không phải PhoenixSuit IMAGEWTY")
        if struct.unpack_from("<I", header, 12)[0] != 0x60:
            raise ValueError("Phiên bản PhoenixSuit header chưa được hỗ trợ")
        item_size = struct.unpack_from("<I", header, 56)[0]
        count = struct.unpack_from("<I", header, 60)[0]
        table_offset = struct.unpack_from("<I", header, 64)[0]
        if item_size != 0x400 or not 1 <= count <= 256 or table_offset != 0x400:
            raise ValueError("Bảng item PhoenixSuit không hợp lệ")
        items = []
        source.seek(table_offset)
        for index in range(count):
            record = source.read(item_size)
            if len(record) != item_size:
                raise EOFError("Bảng item PhoenixSuit bị thiếu")
            items.append(PhoenixItem(index, _text(record[8:16]), _text(record[16:32]),
                                     _text(record[36:292]), _hi_lo(record, 0x120),
                                     _hi_lo(record, 0x128), _hi_lo(record, 0x130)))
    return header, items


def analyze(path: str | Path, progress=None, verify_crc: bool = True) -> FirmwareInfo:
    firmware = Path(path)
    header, items = read_items(firmware)
    size = firmware.stat().st_size
    # The image header stores length as low/high, while v3 item records store
    # their 64-bit values as high/low.
    declared_size = struct.unpack_from("<I", header, 24)[0] | (struct.unpack_from("<I", header, 28)[0] << 32)
    partitions = []
    verify_by_name = {}
    for item in items:
        if item.offset + item.data_length > size:
            raise ValueError(f"Item nằm ngoài IMG: {item.filename}")
        lower = item.filename.lower()
        name = Path(lower.replace("\\", "/")).stem
        if name.startswith("v") and item.file_length == 4:
            verify_by_name[name[1:]] = item
        if item.main == "RFSFAT16" and not name.startswith("v"):
            fmt = "Android sparse" if name == "system" else "Android boot" if name in ("boot", "recovery") else "Binary"
            partitions.append(PartitionInfo(name, "PARTITION", item.offset, item.file_length, fmt))
        else:
            partitions.append(PartitionInfo(name or item.sub, "ITEM", item.offset, item.file_length, "Binary"))
    system = next((item for item in items if item.filename.lower().replace("\\", "/").endswith("/system.fex")), None)
    checksum_ok = None
    if system and "system" in verify_by_name and verify_crc:
        if progress: progress(20, "Đang kiểm tra checksum system.fex")
        total = 0
        with firmware.open("rb") as source:
            source.seek(system.offset); left = system.file_length
            while left:
                data = source.read(min(left, 16 * 1024 * 1024)); left -= len(data)
                data += b"\0" * (-len(data) % 4)
                total = (total + sum(struct.unpack(f"<{len(data)//4}I", data))) & 0xFFFFFFFF
        with firmware.open("rb") as source:
            source.seek(verify_by_name["system"].offset)
            checksum_ok = struct.unpack("<I", source.read(4))[0] == total
    warnings = []
    if declared_size != size: warnings.append("Kích thước IMAGEWTY khai báo không khớp file")
    if checksum_ok is False: warnings.append("Checksum Vsystem không hợp lệ")
    if progress: progress(100, "Đã phân tích PhoenixSuit/Allwinner")
    return FirmwareInfo(path=str(firmware), platform="Allwinner", package_format="PhoenixSuit IMAGEWTY v3",
                        size=size, valid=declared_size == size and system is not None,
                        checksum_ok=checksum_ok, android_version="7.0", architecture="ARMv7",
                        partitions=partitions, warnings=warnings)

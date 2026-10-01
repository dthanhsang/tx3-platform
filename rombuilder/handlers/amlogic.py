from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Callable

from rombuilder.core.models import FirmwareInfo, PartitionInfo

Progress = Callable[[int, str], None]


def analyze(path: str | Path, progress: Progress | None = None, verify_crc: bool = True) -> FirmwareInfo:
    firmware = Path(path)
    size = firmware.stat().st_size
    if progress:
        progress(2, "Đang đọc header Amlogic")
    with firmware.open("rb") as source:
        header = source.read(0x2900)
        if len(header) != 0x2900:
            raise ValueError("Header firmware bị thiếu")
        stored_crc = struct.unpack_from("<I", header, 0)[0]
        declared_size = struct.unpack_from("<I", header, 0x0C)[0]
        count = struct.unpack_from("<I", header, 0x18)[0]
        if not 1 <= count <= 128:
            raise ValueError(f"Số item không hợp lệ: {count}")
        partitions: list[PartitionInfo] = []
        for index in range(count):
            record = 0x40 + index * 0x240
            offset, item_size = struct.unpack_from("<QQ", header, record + 0x10)
            item_type = header[record + 0x20 : record + 0x120].split(b"\0", 1)[0].decode("ascii", "replace")
            item_name = header[record + 0x120 : record + 0x220].split(b"\0", 1)[0].decode("ascii", "replace")
            if offset + item_size > size:
                raise ValueError(f"Item nằm ngoài firmware: {item_type}/{item_name}")
            fmt = "VERIFY" if item_type == "VERIFY" else "Binary"
            if item_type == "PARTITION":
                source.seek(offset)
                magic = source.read(4)
                if magic == b"\x3a\xff\x26\xed":
                    fmt = "Android sparse"
                elif magic == b"\x53\xef" or magic[2:4] == b"\x53\xef":
                    fmt = "EXT"
            partitions.append(PartitionInfo(item_name, item_type, offset, item_size, fmt))

        checksum_ok = None
        warnings: list[str] = []
        if declared_size != size:
            warnings.append(f"Kích thước khai báo {declared_size:,} khác kích thước file {size:,}")
        if verify_crc:
            if progress:
                progress(10, "Đang xác minh CRC toàn bộ firmware")
            crc = 0
            source.seek(4)
            processed = 4
            while data := source.read(16 * 1024 * 1024):
                crc = zlib.crc32(data, crc)
                processed += len(data)
                if progress:
                    progress(min(95, 10 + int(processed / size * 85)), "Đang xác minh CRC toàn bộ firmware")
            checksum_ok = ((~crc) & 0xFFFFFFFF) == stored_crc
            if not checksum_ok:
                warnings.append("CRC firmware không khớp")
    if progress:
        progress(100, "Phân tích Amlogic hoàn tất")
    return FirmwareInfo(
        path=str(firmware), platform="Amlogic", package_format="USB Burning Image v2",
        size=size, valid=declared_size == size, checksum_ok=checksum_ok,
        partitions=partitions, warnings=warnings,
    )


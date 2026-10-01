from __future__ import annotations

import hashlib
import os
import shutil
import struct
from pathlib import Path

from . import ext4
from .firmware_io import copy_with_progress, raw_to_sparse, sparse_to_raw, zero_ext4_free_blocks
from .pipeline import AmlogicProject
from rombuilder.handlers.phoenixsuit import read_items


class PhoenixProject(AmlogicProject):
    def __init__(self, firmware_path):
        self.firmware = Path(firmware_path).resolve()
        identity = f"phoenix|{self.firmware}|{self.firmware.stat().st_size}|{self.firmware.stat().st_mtime_ns}"
        key = hashlib.sha1(identity.encode()).hexdigest()[:16]
        local = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "UniversalAndroidRomBuilder" / "work"
        self.work = local / key
        self.sparse = self.work / "system.original.sparse.img"
        self.raw = self.work / "system.original.raw.img"
        self.modified = self.work / "system.modified.raw.img"
        self.metadata = self.work / "source.json"

    def _system_item(self):
        _header, items = read_items(self.firmware)
        return next(item for item in items if item.filename.lower().replace("\\", "/").endswith("/system.fex"))

    def prepare(self, progress=None):
        self.work.mkdir(parents=True, exist_ok=True)
        item = self._system_item()
        cached = self.raw.exists() and self.raw.stat().st_mtime_ns >= self.firmware.stat().st_mtime_ns
        if not cached:
            with self.firmware.open("rb") as source, self.sparse.open("wb") as output:
                source.seek(item.offset); left = item.file_length
                while left:
                    data = source.read(min(left, 16 * 1024 * 1024)); output.write(data); left -= len(data)
                    if progress: progress(int((item.file_length-left) * 35 / item.file_length), "Đang trích xuất system.fex")
            sparse_to_raw(self.sparse, self.raw, lambda p,t: progress(35+int(p*.55),t) if progress else None)
        apps = ext4.list_apks(self.raw, lambda p,t: progress(90+int(p*.1),t) if progress else None)
        return apps

    @staticmethod
    def _word_sum(path: Path) -> int:
        total = 0
        with path.open("rb") as source:
            while data := source.read(16 * 1024 * 1024):
                data += b"\0" * (-len(data) % 4)
                total = (total + sum(struct.unpack(f"<{len(data)//4}I", data))) & 0xFFFFFFFF
        return total

    def build(self, destination, progress=None):
        if not self.modified.exists(): raise FileNotFoundError("Chưa áp dụng thay đổi")
        sparse = self.work / "system.modified.sparse.img"
        zero_ext4_free_blocks(self.modified, lambda p,t: progress(int(p*.18),t) if progress else None)
        raw_to_sparse(self.modified, sparse, progress=lambda p,t: progress(18+int(p*.37),t) if progress else None)
        _header, items = read_items(self.firmware)
        system = next(item for item in items if item.filename.lower().replace("\\", "/").endswith("/system.fex"))
        verify = next(item for item in items if item.filename.lower().replace("\\", "/").endswith("/vsystem.fex"))
        new_size = sparse.stat().st_size
        if new_size > system.data_length:
            raise OSError(f"system mới lớn hơn vùng PhoenixSuit {new_size-system.data_length:,} byte")
        destination = Path(destination)
        copy_with_progress(self.firmware, destination, lambda p,t: progress(55+int(p*.25), "Đang sao chép gói PhoenixSuit") if progress else None)
        with destination.open("r+b") as output, sparse.open("rb") as source:
            output.seek(system.offset)
            while data := source.read(16 * 1024 * 1024): output.write(data)
            left = system.data_length - new_size
            zero = b"\0" * min(16 * 1024 * 1024, left)
            while left:
                block = zero[:min(left, len(zero))]; output.write(block); left -= len(block)
            record = 0x400 + system.index * 0x400
            output.seek(record + 0x128); output.write(struct.pack("<II", new_size >> 32, new_size & 0xFFFFFFFF))
            output.seek(verify.offset); output.write(struct.pack("<I", self._word_sum(sparse)))
        if progress: progress(100, "Đã cập nhật Vsystem và xác minh PhoenixSuit")
        return destination

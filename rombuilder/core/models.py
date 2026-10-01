from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PartitionInfo:
    name: str
    item_type: str
    offset: int
    size: int
    format: str = "Chưa xác định"
    verified: bool = False


@dataclass
class FirmwareInfo:
    path: str
    platform: str
    package_format: str
    size: int
    valid: bool
    checksum_ok: bool | None = None
    android_version: str = "Chưa phân tích"
    api_level: str = "Chưa phân tích"
    architecture: str = "Chưa phân tích"
    partitions: list[PartitionInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ApkInfo:
    path: str
    filename: str
    size: int
    package_name: str = ""
    activities: list[str] = field(default_factory=list)
    has_main: bool = False
    has_launcher: bool = False
    has_home: bool = False
    has_default: bool = False
    native_architectures: list[str] = field(default_factory=list)
    min_sdk: str = ""
    target_sdk: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def launcher_status(self) -> str:
        if self.has_main and self.has_home and self.has_default:
            return "Có thể làm Home Launcher"
        if self.has_main and self.has_launcher:
            return "Có Launcher, chưa có HOME"
        return "Không phát hiện Launcher"


@dataclass
class ProjectConfig:
    name: str
    firmware_path: str
    output_path: str = ""
    platform: str = ""
    selected_launcher_package: str = ""
    selected_launcher_activity: str = ""
    keep_fallback_launcher: bool = True
    root_mode: str = "Giữ nguyên"
    root_package_path: str = ""
    apks: list[dict[str, Any]] = field(default_factory=list)

    def save(self, destination: Path) -> None:
        import json

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


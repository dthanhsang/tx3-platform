from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path

from .models import ApkInfo


def _read_len8(data: bytes, at: int) -> tuple[int, int]:
    first = data[at]
    return ((((first & 0x7F) << 8) | data[at + 1]), 2) if first & 0x80 else (first, 1)


def _read_len16(data: bytes, at: int) -> tuple[int, int]:
    first = struct.unpack_from("<H", data, at)[0]
    if first & 0x8000:
        return (((first & 0x7FFF) << 16) | struct.unpack_from("<H", data, at + 2)[0], 4)
    return first, 2


def manifest_strings(data: bytes) -> list[str]:
    pos = 8
    while pos + 8 <= len(data):
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, pos)
        if chunk_size < 8:
            break
        if chunk_type == 1:
            count, _styles, flags, strings_start, _style_start = struct.unpack_from("<IIIII", data, pos + 8)
            offsets = struct.unpack_from(f"<{count}I", data, pos + header_size)
            base = pos + strings_start
            utf8 = bool(flags & 0x100)
            values: list[str] = []
            for offset in offsets:
                at = base + offset
                if utf8:
                    _, used = _read_len8(data, at)
                    at += used
                    size, used = _read_len8(data, at)
                    at += used
                    values.append(data[at : at + size].decode("utf-8", "replace"))
                else:
                    size, used = _read_len16(data, at)
                    at += used
                    values.append(data[at : at + size * 2].decode("utf-16le", "replace"))
            return values
        pos += chunk_size
    raise ValueError("AndroidManifest.xml không phải Binary XML được hỗ trợ")


def parse_manifest(data: bytes) -> dict:
    values = manifest_strings(data)
    result = {"package": "", "activities": [], "min_sdk": "", "target_sdk": ""}
    current_activity = None
    pos = 8

    def string_at(index: int) -> str:
        return values[index] if 0 <= index < len(values) else ""

    def attribute_value(at: int) -> str:
        raw_index = struct.unpack_from("<I", data, at + 8)[0]
        data_type = data[at + 15]
        typed_data = struct.unpack_from("<I", data, at + 16)[0]
        if raw_index != 0xFFFFFFFF:
            return string_at(raw_index)
        if data_type == 0x03:
            return string_at(typed_data)
        return str(typed_data)

    while pos + 8 <= len(data):
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, pos)
        if chunk_size < 8:
            break
        if chunk_type == 0x0102 and pos + 36 <= len(data):
            name_index = struct.unpack_from("<I", data, pos + 20)[0]
            tag = string_at(name_index)
            attribute_start, attribute_size, attribute_count = struct.unpack_from("<HHH", data, pos + 24)
            attrs = {}
            first_attribute = pos + 16 + attribute_start
            for index in range(attribute_count):
                at = first_attribute + index * attribute_size
                if at + 20 > pos + chunk_size:
                    break
                attr_name = string_at(struct.unpack_from("<I", data, at + 4)[0])
                attrs[attr_name] = attribute_value(at)
            if tag == "manifest":
                result["package"] = attrs.get("package", "")
            elif tag == "uses-sdk":
                result["min_sdk"] = attrs.get("minSdkVersion", "")
                result["target_sdk"] = attrs.get("targetSdkVersion", "")
            elif tag in ("activity", "activity-alias"):
                raw_name = attrs.get("name", "")
                package = result["package"]
                if raw_name.startswith("."):
                    full_name = package + raw_name
                elif "." not in raw_name and package:
                    full_name = package + "." + raw_name
                else:
                    full_name = raw_name
                current_activity = {"name": full_name, "main": False, "launcher": False, "home": False, "default": False}
                result["activities"].append(current_activity)
            elif current_activity is not None and tag == "action":
                current_activity["main"] |= attrs.get("name") == "android.intent.action.MAIN"
            elif current_activity is not None and tag == "category":
                category = attrs.get("name")
                current_activity["launcher"] |= category == "android.intent.category.LAUNCHER"
                current_activity["home"] |= category == "android.intent.category.HOME"
                current_activity["default"] |= category == "android.intent.category.DEFAULT"
        elif chunk_type == 0x0103 and pos + 24 <= len(data):
            tag = string_at(struct.unpack_from("<I", data, pos + 20)[0])
            if tag in ("activity", "activity-alias"):
                current_activity = None
        pos += chunk_size
    return result


def analyze_apk(path: str | Path) -> ApkInfo:
    apk_path = Path(path)
    info = ApkInfo(path=str(apk_path), filename=apk_path.name, size=apk_path.stat().st_size)
    try:
        with zipfile.ZipFile(apk_path) as archive:
            names = archive.namelist()
            manifest_data = archive.read("AndroidManifest.xml")
            values = manifest_strings(manifest_data)
            manifest = parse_manifest(manifest_data)
            architectures = sorted({name.split("/")[1] for name in names if name.startswith("lib/") and name.count("/") >= 2})
            info.native_architectures = architectures
    except (OSError, KeyError, zipfile.BadZipFile, ValueError) as exc:
        info.warnings.append(str(exc))
        return info

    value_set = set(values)
    info.has_main = "android.intent.action.MAIN" in value_set
    info.has_launcher = "android.intent.category.LAUNCHER" in value_set
    info.has_home = "android.intent.category.HOME" in value_set
    info.has_default = "android.intent.category.DEFAULT" in value_set

    info.package_name = manifest.get("package", "")
    info.min_sdk = manifest.get("min_sdk", "")
    info.target_sdk = manifest.get("target_sdk", "")
    activities = manifest.get("activities", [])
    # A normal MAIN + LAUNCHER entry cannot be selected as Android Home.
    info.activities = [
        item["name"] for item in activities
        if item["main"] and item["home"] and item["default"]
    ]
    info.has_main = any(item["main"] for item in activities) or info.has_main
    info.has_launcher = any(item["launcher"] for item in activities) or info.has_launcher
    info.has_home = any(item["home"] for item in activities) or info.has_home
    info.has_default = any(item["default"] for item in activities) or info.has_default
    if not info.package_name:
        info.warnings.append("Chưa xác định chắc chắn package name; cần bộ phân tích AAPT ở bản đóng gói.")
    return info

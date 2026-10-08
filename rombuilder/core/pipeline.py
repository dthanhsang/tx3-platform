from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import zipfile
from pathlib import Path

from . import ext4
from .firmware_io import (
    copy_with_progress, extract_partition, raw_to_sparse, repack_last_system,
    sparse_to_raw, verify_package, zero_ext4_free_blocks,
)


class AmlogicProject:
    def __init__(self, firmware_path):
        self.firmware = Path(firmware_path).resolve()
        identity = f"{self.firmware}|{self.firmware.stat().st_size}|{self.firmware.stat().st_mtime_ns}"
        key = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
        local = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "UniversalAndroidRomBuilder" / "work"
        self.work = local / key
        self.sparse = self.work / "system.original.sparse.img"
        self.raw = self.work / "system.original.raw.img"
        self.modified = self.work / "system.modified.raw.img"
        self.metadata = self.work / "source.json"

    def prepare(self, progress=None):
        self.work.mkdir(parents=True, exist_ok=True)
        expected = {"path": str(self.firmware), "size": self.firmware.stat().st_size, "mtime": self.firmware.stat().st_mtime_ns}
        cached = False
        if self.raw.exists() and self.metadata.exists():
            try:
                cached = json.loads(self.metadata.read_text(encoding="utf-8")) == expected
            except (OSError, ValueError):
                cached = False
        if not cached:
            required = self.firmware.stat().st_size + 3 * 1024**3
            if shutil.disk_usage(self.work).free < required:
                raise OSError("Không đủ dung lượng trống. Cần tối thiểu khoảng 4–6 GB để bung ROM.")
            extract_partition(self.firmware, "system", self.sparse,
                              lambda p, t: progress(int(p * .35), t) if progress else None)
            with self.sparse.open("rb") as source:
                magic = source.read(4)
            if magic == b"\x3a\xff\x26\xed":
                sparse_to_raw(self.sparse, self.raw,
                              lambda p, t: progress(35 + int(p * .55), t) if progress else None)
            else:
                copy_with_progress(self.sparse, self.raw,
                                   lambda p, t: progress(35 + int(p * .55), t) if progress else None)
            self.metadata.write_text(json.dumps(expected), encoding="utf-8")
        elif progress:
            progress(90, "Đang dùng system đã bung từ bộ nhớ đệm")
        apps = ext4.list_apks(self.raw, lambda p, t: progress(90 + int(p * .1), t) if progress else None)
        return apps

    @staticmethod
    def free_bytes(image):
        with Path(image).open("rb") as source:
            source.seek(1024)
            superblock = source.read(1024)
        free_blocks = struct.unpack_from("<I", superblock, 12)[0]
        block_size = 1024 << struct.unpack_from("<I", superblock, 24)[0]
        return free_blocks * block_size

    def apply(self, additions, removals, launcher_package="", launcher_activity="",
              root_mode="Giữ nguyên root hiện tại", root_zip="", remote_config=None, progress=None):
        added_size = sum(Path(item["path"]).stat().st_size for item in additions)
        removed_size = sum(int(item.get("size", 0)) for item in removals)
        if added_size > self.free_bytes(self.raw) + removed_size - 32 * 1024 * 1024:
            raise OSError("Phân vùng system không đủ chỗ cho các APK đã chọn.")
        copy_with_progress(self.raw, self.modified,
                           lambda p, t: progress(int(p * .65), t) if progress else None)
        commands = []
        existing_app_dirs = {entry["name"] for entry in ext4.list_dir(self.modified, "/app")
                             if entry["mode"].startswith("04")}
        existing_priv_dirs = {entry["name"] for entry in ext4.list_dir(self.modified, "/priv-app")
                              if entry["mode"].startswith("04")}
        for item in removals:
            commands.append(f"rm {item['path']}")
        for item in additions:
            source = Path(item["path"])
            filename = ext4.safe_name(source.name)
            location = item.get("location", "/system/preinstall")
            if location == "/system/app":
                dirname = ext4.safe_name(source.stem)
                directory = "/app/" + dirname
                target = directory + "/" + filename
                if dirname not in existing_app_dirs:
                    commands += [f"mkdir {directory}", f"ea_set {directory} security.selinux u:object_r:system_file:s0"]
                    existing_app_dirs.add(dirname)
            elif location == "/system/priv-app":
                dirname = ext4.safe_name(source.stem)
                directory = "/priv-app/" + dirname
                target = directory + "/" + filename
                if dirname not in existing_priv_dirs:
                    commands += [f"mkdir {directory}", f"ea_set {directory} security.selinux u:object_r:system_file:s0"]
                    existing_priv_dirs.add(dirname)
            else:
                target = "/preinstall/" + filename
                directory = "/preinstall"
            commands += [
                f"cd {directory}",
                f"rm {filename}",
                f"write \"{ext4.cygwin_path(source)}\" {filename}",
                "cd /",
                f"set_inode_field {target} mode 0100644",
                f"ea_set {target} security.selinux u:object_r:system_file:s0",
            ]
        root_enabled = root_mode == "Tích hợp SuperSU từ ZIP"
        if root_enabled:
            archive_path = Path(root_zip)
            if not archive_path.is_file():
                raise FileNotFoundError("Chưa chọn ZIP SuperSU hợp lệ")
            root_files = self.work / "supersu-files"
            root_files.mkdir(parents=True, exist_ok=True)
            try:
                is_64 = bool(ext4.list_dir(self.modified, "/lib64"))
            except RuntimeError:
                is_64 = False
            arch = "arm64" if is_64 else "armv7"
            required = {f"{arch}/su": "su", f"{arch}/supolicy": "supolicy",
                        f"{arch}/libsupol.so": "libsupol.so",
                        "common/Superuser.apk": "SuperSU.apk",
                        "common/install-recovery.sh": "install-recovery.sh"}
            with zipfile.ZipFile(archive_path) as archive:
                missing = [name for name in required if name not in archive.namelist()]
                if missing:
                    raise ValueError("ZIP SuperSU thiếu thành phần: " + ", ".join(missing))
                for member, filename in required.items():
                    (root_files / filename).write_bytes(archive.read(member))
            if "SuperSU" not in existing_app_dirs:
                commands += ["mkdir /app/SuperSU", "ea_set /app/SuperSU security.selinux u:object_r:system_file:s0"]
                existing_app_dirs.add("SuperSU")
            root_targets = [(root_files / "su", "/xbin/su", "0100755"),
                            (root_files / "su", "/xbin/daemonsu", "0100755"),
                            (root_files / "supolicy", "/xbin/supolicy", "0100755"),
                            (root_files / "libsupol.so", "/lib64/libsupol.so" if is_64 else "/lib/libsupol.so", "0100644"),
                            (root_files / "SuperSU.apk", "/app/SuperSU/SuperSU.apk", "0100644"),
                            (root_files / "install-recovery.sh", "/etc/install-recovery.sh", "0100755")]
            for source, target, mode in root_targets:
                parent, filename = target.rsplit("/", 1)
                commands += [f"cd {parent}", f"rm {filename}", f"write \"{ext4.cygwin_path(source)}\" {filename}",
                             "cd /", f"set_inode_field {target} mode {mode}",
                             f"ea_set {target} security.selinux u:object_r:system_file:s0"]

        if (launcher_package and launcher_activity) or root_enabled:
            script = self.work / "preinstall.rombuilder.sh"
            original = self.work / "preinstall.current.sh"
            try:
                ext4.run_debugfs(self.modified, f"dump -p /bin/preinstall.sh \"{ext4.cygwin_path(original)}\"")
                content = original.read_text(encoding="utf-8", errors="replace") if original.exists() else "#!/system/bin/sh\n"
            except (OSError, RuntimeError):
                content = "#!/system/bin/sh\n"
            content = re.sub(r"\n?# ROMBUILDER CONFIG START.*?# ROMBUILDER CONFIG END\n?", "\n", content, flags=re.S)
            content += "\n# ROMBUILDER CONFIG START\n"
            if root_enabled:
                content += "/system/xbin/daemonsu --auto-daemon &\n"
            if launcher_package and launcher_activity:
                component = launcher_activity if "/" in launcher_activity else f"{launcher_package}/{launcher_activity}"
                content += ("i=0\nwhile [ \"$(getprop sys.boot_completed)\" != \"1\" ] && [ $i -lt 90 ]; do sleep 2; i=$((i+1)); done\n"
                            f"cmd package set-home-activity {component}\n")
            content += "# ROMBUILDER CONFIG END\n"
            script.write_text(content, encoding="utf-8", newline="\n")
            commands += [
                "cd /bin",
                "rm preinstall.sh",
                f"write \"{ext4.cygwin_path(script)}\" preinstall.sh",
                "cd /",
                "set_inode_field /bin/preinstall.sh mode 0100755",
                "ea_set /bin/preinstall.sh security.selinux u:object_r:system_file:s0",
            ]

        # Inject Remote Management & Tailscale if configured
        if remote_config and getattr(remote_config, "enabled", False):
            try:
                import sys
                from pathlib import Path
                rm_path = Path(__file__).resolve().parents[2] / "rom-builder" / "modules" / "remote-management"
                if str(rm_path) not in sys.path:
                    sys.path.insert(0, str(rm_path))
                import importlib.util
                rm_init_path = rm_path / "__init__.py"
                spec = importlib.util.spec_from_file_location("tx3_remote_management_module", rm_init_path)
                rm_module = importlib.util.module_from_spec(spec)
                sys.modules["tx3_remote_management_module"] = rm_module
                spec.loader.exec_module(rm_module)
                
                # Append preinstall additions for remote management
                script_path = self.work / "preinstall.rombuilder.sh"
                if script_path.exists():
                    current_script = script_path.read_text(encoding="utf-8")
                else:
                    original = self.work / "preinstall.current.sh"
                    try:
                        ext4.run_debugfs(self.modified, f"dump -p /bin/preinstall.sh \"{ext4.cygwin_path(original)}\"")
                        current_script = original.read_text(encoding="utf-8", errors="replace") if original.exists() else "#!/system/bin/sh\n"
                    except Exception:
                        current_script = "#!/system/bin/sh\n"

                modified_script = rm_module.modify_preinstall_script(current_script, remote_config)
                script_path.write_text(modified_script, encoding="utf-8", newline="\n")

                # Generate debugfs commands to inject binary and configs
                rm_commands = rm_module.generate_debugfs_commands(remote_config, self.work)
                commands += rm_commands

                # Re-write preinstall.sh command
                commands += [
                    "cd /bin",
                    "rm preinstall.sh",
                    f"write \"{ext4.cygwin_path(script_path)}\" preinstall.sh",
                    "cd /",
                    "set_inode_field /bin/preinstall.sh mode 0100755",
                    "ea_set /bin/preinstall.sh security.selinux u:object_r:system_file:s0",
                ]
            except Exception as rm_err:
                print(f"Warning: Remote Management injection failed: {rm_err}")
        if progress: progress(70, "Đang áp dụng thay đổi vào EXT4")
        output = ext4.apply_commands(self.modified, commands)
        if "File not found" in output and additions:
            # 'rm' of a new target is harmless; other errors remain visible in the project log.
            pass
        if progress: progress(90, "Đang kiểm tra EXT4 sau thay đổi")
        try:
            check = ext4.validate_ext4(self.modified)
        except RuntimeError:
            if progress: progress(94, "Repairing EXT4 metadata")
            check = ext4.repair_ext4(self.modified) + ext4.validate_ext4(self.modified)
        if progress: progress(100, "Đã áp dụng và kiểm tra cấu hình")
        return output + check

    def build(self, destination, progress=None):
        destination = Path(destination)
        if not self.modified.exists():
            raise FileNotFoundError("Chưa áp dụng thay đổi")
        sparse = self.work / "system.modified.sparse.img"
        zero_ext4_free_blocks(self.modified, lambda p, t: progress(int(p * .18), t) if progress else None)
        raw_to_sparse(self.modified, sparse, progress=lambda p, t: progress(18 + int(p * .37), t) if progress else None)
        repack_last_system(self.firmware, sparse, destination,
                           lambda p, t: progress(55 + int(p * .30), t) if progress else None)
        verify_package(destination, lambda p, t: progress(85 + int(p * .15), t) if progress else None)
        return destination

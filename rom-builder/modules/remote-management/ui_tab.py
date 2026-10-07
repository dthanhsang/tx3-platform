"""TX3 ROM Builder - Remote Management UI Tab
Adds Remote Management configuration tab to the ROM Builder main window.

This module provides the UI widgets and integration logic for the
Remote Management checkbox panel in ROM Builder v0.7.0.

Version: 1.0.0
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rombuilder.ui.main_window import RomBuilderApp


class RemoteManagementTab:
    """Remote Management configuration tab for ROM Builder."""

    def __init__(self, parent: ttk.Frame, app: RomBuilderApp):
        self.parent = parent
        self.app = app
        self._build_ui()

    def _build_ui(self) -> None:
        # ── Master Enable ──
        header = ttk.Frame(self.parent)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="REMOTE MANAGEMENT", style="Title.TLabel").pack(side="left")

        self.enabled = tk.BooleanVar(value=True)
        self.enable_check = ttk.Checkbutton(
            header, text="Tích hợp Remote Management", variable=self.enabled,
            command=self._toggle_features
        )
        self.enable_check.pack(side="left", padx=20)

        # ── Features Frame ──
        self.features_frame = ttk.LabelFrame(self.parent, text="Tính năng", padding=12)
        self.features_frame.pack(fill="x", pady=(0, 12))

        self.auto_start = tk.BooleanVar(value=True)
        self.wireguard = tk.BooleanVar(value=True)
        self.live_remote = tk.BooleanVar(value=True)
        self.mouse_keyboard = tk.BooleanVar(value=True)
        self.file_transfer = tk.BooleanVar(value=True)
        self.remote_adb = tk.BooleanVar(value=True)
        self.apk_install = tk.BooleanVar(value=True)
        self.auto_reconnect = tk.BooleanVar(value=True)
        self.resource_guard = tk.BooleanVar(value=True)
        self.watchdog = tk.BooleanVar(value=True)
        self.auto_adb = tk.BooleanVar(value=True)

        features = [
            (self.auto_start, "Auto Start", "Tự động khởi động agent khi boot"),
            (self.wireguard, "WireGuard", "Tích hợp WireGuard VPN quản trị"),
            (self.live_remote, "Live Remote", "Remote màn hình thời gian thực H.264"),
            (self.mouse_keyboard, "Mouse / Keyboard / D-Pad", "Điều khiển chuột, bàn phím, D-Pad từ xa"),
            (self.file_transfer, "File Transfer", "Truyền file hai chiều có resume"),
            (self.remote_adb, "Remote ADB", "Quản trị ADB từ xa qua WireGuard"),
            (self.apk_install, "APK Install", "Cài đặt APK từ xa"),
            (self.auto_reconnect, "Auto Reconnect", "Tự kết nối lại khi mất mạng"),
            (self.resource_guard, "Resource Guard", "Bảo vệ tài nguyên CPU/RAM/nhiệt"),
            (self.watchdog, "Watchdog", "Theo dõi và restart process lỗi"),
            (self.auto_adb, "Auto ADB", "Tự động bật ADB khi flash ROM lần đầu"),
        ]

        left = ttk.Frame(self.features_frame)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(self.features_frame)
        right.pack(side="left", fill="both", expand=True)

        for idx, (var, text, tooltip) in enumerate(features):
            frame = left if idx < 6 else right
            cb = ttk.Checkbutton(frame, text=text, variable=var)
            cb.pack(anchor="w", pady=2)
            # Store tooltip for future use
            cb._tooltip_text = tooltip

        self.feature_widgets = [w for w in left.winfo_children() + right.winfo_children()]

        # ── Server Configuration ──
        self.server_frame = ttk.LabelFrame(self.parent, text="Management Server", padding=12)
        self.server_frame.pack(fill="x", pady=(0, 12))

        server_row = ttk.Frame(self.server_frame)
        server_row.pack(fill="x", pady=(0, 8))
        ttk.Label(server_row, text="Server URL:").pack(side="left")
        self.server_url = tk.StringVar(value="http://10.88.0.1:8400")
        self.server_entry = ttk.Entry(server_row, textvariable=self.server_url, width=50)
        self.server_entry.pack(side="left", padx=(8, 0), fill="x", expand=True)

        token_row = ttk.Frame(self.server_frame)
        token_row.pack(fill="x", pady=(0, 8))
        ttk.Label(token_row, text="Bootstrap Token:").pack(side="left")
        self.bootstrap_token = tk.StringVar(value="iil1pZT-8Oo4lOBHmItC86PLcOeg-wnToucCc2IRNeU")
        self.token_entry = ttk.Entry(token_row, textvariable=self.bootstrap_token, width=50, show="•")
        self.token_entry.pack(side="left", padx=(8, 0), fill="x", expand=True)

        self.show_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            token_row, text="Hiện", variable=self.show_token,
            command=lambda: self.token_entry.configure(show="" if self.show_token.get() else "•")
        ).pack(side="left", padx=4)

        ttk.Label(
            self.server_frame,
            text="⚠ Không hard-code private key WireGuard. ROM chỉ chứa bootstrap token cho provisioning.",
            foreground="#9a6700",
        ).pack(anchor="w")

        # ── Profile Selection ──
        self.profile_frame = ttk.LabelFrame(self.parent, text="Profile tối ưu", padding=12)
        self.profile_frame.pack(fill="x", pady=(0, 12))

        self.profile = tk.StringVar(value="Auto - S905W/2GB optimized")
        profiles = [
            "Auto - S905W/2GB optimized",
            "540p / 20 FPS - Tiết kiệm",
            "720p / 20 FPS - Cân bằng",
            "720p / 25 FPS - Mượt",
            "720p / 30 FPS - Cao (cần benchmark)",
        ]
        for p in profiles:
            ttk.Radiobutton(self.profile_frame, text=p, value=p, variable=self.profile).pack(anchor="w", pady=2)

        ttk.Label(
            self.profile_frame,
            text="1080p không được hỗ trợ mặc định trên S905W/2GB.\n"
                 "Thông số cuối cùng chỉ được chốt sau benchmark trên box thật.",
            foreground="#4b5563",
        ).pack(anchor="w", pady=(8, 0))

        # ── Status ──
        self.status_frame = ttk.LabelFrame(self.parent, text="Trạng thái", padding=12)
        self.status_frame.pack(fill="x")

        self.status_text = tk.StringVar(value="Chưa kích hoạt Remote Management.")
        ttk.Label(self.status_frame, textvariable=self.status_text, justify="left").pack(anchor="w")

        # Initial state
        self._toggle_features()

    def _toggle_features(self) -> None:
        """Enable/disable feature checkboxes based on master toggle."""
        state = "normal" if self.enabled.get() else "disabled"
        for widget in self.feature_widgets:
            widget.configure(state=state)
        self.server_entry.configure(state=state)
        self.token_entry.configure(state=state)
        for widget in self.profile_frame.winfo_children():
            if isinstance(widget, ttk.Radiobutton):
                widget.configure(state=state)

        if self.enabled.get():
            self._update_status()
        else:
            self.status_text.set("Chưa kích hoạt Remote Management.")

    def _update_status(self) -> None:
        """Update status text based on current configuration."""
        features_on = []
        if self.auto_start.get(): features_on.append("Auto Start")
        if self.wireguard.get(): features_on.append("WireGuard")
        if self.live_remote.get(): features_on.append("Live Remote")
        if self.file_transfer.get(): features_on.append("File Transfer")
        if self.remote_adb.get(): features_on.append("Remote ADB")
        if self.watchdog.get(): features_on.append("Watchdog")
        if self.auto_adb.get(): features_on.append("Auto ADB")

        warnings = []
        if not self.server_url.get():
            warnings.append("⚠ Chưa cấu hình Server URL")
        if not self.bootstrap_token.get():
            warnings.append("⚠ Chưa nhập Bootstrap Token")

        status = f"✓ Remote Management: {len(features_on)} tính năng\n"
        status += f"  Bao gồm: {', '.join(features_on)}\n"
        status += f"  Profile: {self.profile.get()}"
        if warnings:
            status += "\n" + "\n".join(warnings)

        self.status_text.set(status)

    def get_config(self) -> dict:
        """Get current Remote Management configuration as dict."""
        from rom_builder_integration import RemoteManagementConfig
        profile_map = {
            "Auto - S905W/2GB optimized": "auto",
            "540p / 20 FPS - Tiết kiệm": "540p20",
            "720p / 20 FPS - Cân bằng": "720p20",
            "720p / 25 FPS - Mượt": "720p25",
            "720p / 30 FPS - Cao (cần benchmark)": "720p30",
        }
        config = RemoteManagementConfig(
            enabled=self.enabled.get(),
            auto_start=self.auto_start.get(),
            wireguard=self.wireguard.get(),
            live_remote=self.live_remote.get(),
            mouse_keyboard_dpad=self.mouse_keyboard.get(),
            file_transfer=self.file_transfer.get(),
            remote_adb=self.remote_adb.get(),
            apk_install=self.apk_install.get(),
            auto_reconnect=self.auto_reconnect.get(),
            resource_guard=self.resource_guard.get(),
            watchdog=self.watchdog.get(),
            auto_adb=self.auto_adb.get(),
            server_url=self.server_url.get(),
            bootstrap_token=self.bootstrap_token.get(),
            profile=profile_map.get(self.profile.get(), "auto"),
        )
        return config.to_dict()

    def set_config(self, data: dict) -> None:
        """Restore configuration from dict (project load)."""
        self.enabled.set(data.get("enabled", False))
        self.auto_start.set(data.get("auto_start", True))
        self.wireguard.set(data.get("wireguard", True))
        self.live_remote.set(data.get("live_remote", True))
        self.mouse_keyboard.set(data.get("mouse_keyboard_dpad", True))
        self.file_transfer.set(data.get("file_transfer", True))
        self.remote_adb.set(data.get("remote_adb", True))
        self.apk_install.set(data.get("apk_install", True))
        self.auto_reconnect.set(data.get("auto_reconnect", True))
        self.resource_guard.set(data.get("resource_guard", True))
        self.watchdog.set(data.get("watchdog", True))
        self.auto_adb.set(data.get("auto_adb", True))
        self.server_url.set(data.get("server_url", ""))
        self.bootstrap_token.set(data.get("bootstrap_token", ""))

        profile_reverse = {
            "auto": "Auto - S905W/2GB optimized",
            "540p20": "540p / 20 FPS - Tiết kiệm",
            "720p20": "720p / 20 FPS - Cân bằng",
            "720p25": "720p / 25 FPS - Mượt",
            "720p30": "720p / 30 FPS - Cao (cần benchmark)",
        }
        self.profile.set(profile_reverse.get(data.get("profile", "auto"), "Auto - S905W/2GB optimized"))
        self._toggle_features()

    def validate(self) -> list[str]:
        """Validate configuration before build. Returns list of errors."""
        if not self.enabled.get():
            return []

        errors = []
        if not self.server_url.get().strip():
            errors.append("Remote Management: Chưa cấu hình Server URL")
        if not self.bootstrap_token.get().strip():
            errors.append("Remote Management: Chưa nhập Bootstrap Token")
        if self.live_remote.get() and not self.watchdog.get():
            errors.append("Remote Management: Live Remote yêu cầu Watchdog để đảm bảo ổn định")
        return errors

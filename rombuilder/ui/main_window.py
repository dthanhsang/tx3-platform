from __future__ import annotations

import queue
import csv
import json
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from rombuilder import __version__
from rombuilder.core.analyzer import analyze_firmware
from rombuilder.core.apk import analyze_apk
from rombuilder.core.pipeline import AmlogicProject
from rombuilder.core.phoenix_pipeline import PhoenixProject
from rombuilder.core.usb_burning import detect_tool, launch_and_import


class RomBuilderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Universal Android ROM Builder {__version__}")
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.option_add("*Font", ("Segoe UI", 10))
        self.events: queue.Queue = queue.Queue()
        self.firmware_info = None
        self.apk_infos = []
        self.apk_locations = {}
        self.rom_apps = []
        self.rom_apps_by_path = {}
        self.removal_paths = set()
        self.project = None
        self.changes_applied = False
        self.system_free_bytes = 0
        self.launcher_candidates = {}
        self.started_at = 0.0
        self.analyzed_rom_path = ""
        self._set_app_icon()
        self._configure_style()
        self._build_ui()
        self.after(100, self._drain_events)

    @staticmethod
    def _resource_path(name: str) -> Path:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        candidate = base / "assets" / name
        if candidate.exists():
            return candidate
        return Path(__file__).resolve().parents[2] / "assets" / name

    def _set_app_icon(self) -> None:
        try:
            self.iconbitmap(default=str(self._resource_path("rom_builder.ico")))
        except tk.TclError:
            try:
                self._icon_image = tk.PhotoImage(file=str(self._resource_path("rom_builder_logo.png")))
                self.iconphoto(True, self._icon_image)
            except tk.TclError:
                pass

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 17))
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("Treeview", rowheight=27)

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Universal Android ROM Builder", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Amlogic • PhoenixSuit • Android TV", foreground="#4b5563").pack(side="left", padx=16)

        source = ttk.LabelFrame(self, text="Firmware nguồn", padding=10)
        source.pack(fill="x", padx=16)
        self.rom_path = tk.StringVar()
        ttk.Entry(source, textvariable=self.rom_path).pack(side="left", fill="x", expand=True)
        ttk.Button(source, text="Chọn ROM…", command=self.choose_rom).pack(side="left", padx=(8, 0))
        ttk.Button(source, text="Mở cấu hình…", command=self.load_project).pack(side="left", padx=(8, 0))
        ttk.Button(source, text="Lưu cấu hình…", command=self.save_project).pack(side="left", padx=(8, 0))
        self.analyze_button = ttk.Button(source, text="Phân tích", command=self.start_analysis)
        self.analyze_button.pack(side="left", padx=(8, 0))

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=12)
        self.overview_tab = ttk.Frame(self.tabs, padding=12)
        self.rom_apps_tab = ttk.Frame(self.tabs, padding=12)
        self.apk_tab = ttk.Frame(self.tabs, padding=12)
        self.launcher_tab = ttk.Frame(self.tabs, padding=12)
        self.root_tab = ttk.Frame(self.tabs, padding=12)
        self.build_tab = ttk.Frame(self.tabs, padding=12)
        self.log_tab = ttk.Frame(self.tabs, padding=8)
        self.about_tab = ttk.Frame(self.tabs, padding=18)
        for tab, title in ((self.overview_tab, "Tổng quan"), (self.rom_apps_tab, "Ứng dụng trong ROM"), (self.apk_tab, "Thêm APK"),
                           (self.launcher_tab, "Launcher"), (self.root_tab, "Root"),
                           (self.build_tab, "Đóng gói"), (self.log_tab, "Nhật ký")):
            self.tabs.add(tab, text=title)
        self.tabs.add(self.about_tab, text="Thông tin")
        self._build_overview()
        self._build_rom_apps_tab()
        self._build_apk_tab()
        self._build_launcher_tab()
        self._build_root_tab()
        self._build_build_tab()
        self._build_log_tab()
        self._build_about_tab()

        status = ttk.Frame(self, padding=(16, 0, 16, 12))
        status.pack(fill="x")
        self.status_text = tk.StringVar(value="Sẵn sàng")
        ttk.Label(status, textvariable=self.status_text).pack(fill="x")
        progress_line = ttk.Frame(status)
        progress_line.pack(fill="x", pady=(5, 0))
        self.progress = ttk.Progressbar(progress_line, maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.percent_text = tk.StringVar(value="0%")
        ttk.Label(progress_line, textvariable=self.percent_text, width=6, anchor="e").pack(side="left")

    def _build_overview(self) -> None:
        cards = ttk.Frame(self.overview_tab)
        cards.pack(fill="x")
        self.summary_vars = {key: tk.StringVar(value="—") for key in
                             ("Nền tảng", "Định dạng", "Dung lượng", "CRC", "Trạng thái")}
        for column, (label, var) in enumerate(self.summary_vars.items()):
            box = ttk.LabelFrame(cards, text=label, padding=10)
            box.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0))
            ttk.Label(box, textvariable=var, style="Section.TLabel").pack()
            cards.columnconfigure(column, weight=1)
        ttk.Label(self.overview_tab, text="Phân vùng", style="Section.TLabel").pack(anchor="w", pady=(16, 6))
        columns = ("type", "name", "format", "offset", "size")
        self.partition_tree = ttk.Treeview(self.overview_tab, columns=columns, show="headings")
        for key, title, width in (("type", "Loại", 120), ("name", "Tên", 180), ("format", "Định dạng", 150),
                                  ("offset", "Offset", 150), ("size", "Dung lượng", 160)):
            self.partition_tree.heading(key, text=title)
            self.partition_tree.column(key, width=width, anchor="w")
        self.partition_tree.pack(fill="both", expand=True)

    def _build_apk_tab(self) -> None:
        actions = ttk.Frame(self.apk_tab)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Thêm APK…", command=self.add_apks).pack(side="left")
        ttk.Button(actions, text="⚡ Thêm RustDesk Remote App", command=self.add_rustdesk_apk).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Xóa khỏi danh sách", command=self.remove_selected_apk).pack(side="left", padx=8)
        ttk.Label(actions, text="Vị trí:").pack(side="left", padx=(18, 5))
        self.new_apk_location = tk.StringVar(value="/system/preinstall")
        self.location_combo = ttk.Combobox(actions, textvariable=self.new_apk_location, state="readonly", width=21,
                                           values=("/system/preinstall", "/system/app", "/system/priv-app"))
        self.location_combo.pack(side="left")
        ttk.Button(actions, text="Áp dụng vị trí cho mục chọn", command=self.set_selected_apk_location).pack(side="left", padx=8)
        columns = ("file", "package", "launcher", "arch", "size", "location")
        self.apk_tree = ttk.Treeview(self.apk_tab, columns=columns, show="headings", selectmode="extended")
        definitions = (("file", "File", 200), ("package", "Package", 220), ("launcher", "Khả năng Launcher", 210),
                       ("arch", "Kiến trúc", 120), ("size", "Dung lượng", 100), ("location", "Vị trí đề xuất", 130))
        for key, title, width in definitions:
            self.apk_tree.heading(key, text=title)
            self.apk_tree.column(key, width=width, anchor="w")
        self.apk_tree.pack(fill="both", expand=True)

    
    def add_rustdesk_apk(self) -> None:
        rustdesk_apk_path = "/tmp/rustdesk.apk"
        if not Path(rustdesk_apk_path).exists():
            messagebox.showerror("Lỗi", "Không tìm thấy file APK RustDesk tại /tmp/rustdesk.apk")
            return
        
        self.status_text.set("Đang phân tích RustDesk APK...")
        threading.Thread(target=self._apk_worker, args=([rustdesk_apk_path], "/system/priv-app"), daemon=True).start()
        messagebox.showinfo("Thành công", "Đã thêm RustDesk Remote App vào danh sách cài đặt /system/priv-app!")

    def _build_rom_apps_tab(self) -> None:
        actions = ttk.Frame(self.rom_apps_tab)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Đánh dấu gỡ", command=self.mark_remove_rom_apps).pack(side="left")
        ttk.Button(actions, text="Giữ lại", command=self.unmark_remove_rom_apps).pack(side="left", padx=8)
        ttk.Button(actions, text="Hoàn tác tất cả", command=self.reset_changes).pack(side="left")
        ttk.Button(actions, text="Gỡ các mục đang lọc", command=self.mark_all_visible_remove).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Xuất danh sách…", command=self.export_rom_apps).pack(side="left", padx=8)
        self.rom_apps_summary = tk.StringVar(value="Phân tích ROM để đọc danh sách ứng dụng.")
        ttk.Label(actions, textvariable=self.rom_apps_summary, foreground="#4b5563").pack(side="left", padx=16)
        filters = ttk.Frame(self.rom_apps_tab)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="Tìm kiếm:").pack(side="left")
        self.rom_app_search = tk.StringVar()
        search_entry = ttk.Entry(filters, textvariable=self.rom_app_search, width=42)
        search_entry.pack(side="left", padx=(6, 14))
        ttk.Label(filters, text="Vị trí:").pack(side="left")
        self.rom_app_location_filter = tk.StringVar(value="Tất cả")
        location_filter = ttk.Combobox(filters, textvariable=self.rom_app_location_filter, state="readonly", width=20,
                                       values=("Tất cả", "system/app", "system/priv-app", "system/preinstall"))
        location_filter.pack(side="left", padx=6)
        ttk.Button(filters, text="Xóa bộ lọc", command=self.clear_rom_app_filters).pack(side="left", padx=8)
        self.rom_app_search.trace_add("write", lambda *_: self._refresh_rom_apps_tree())
        location_filter.bind("<<ComboboxSelected>>", lambda _event: self._refresh_rom_apps_tree())
        columns = ("name", "location", "path", "size", "action")
        self.rom_apps_tree = ttk.Treeview(self.rom_apps_tab, columns=columns, show="headings", selectmode="extended")
        for key, title, width in (("name", "APK", 210), ("location", "Vị trí", 160), ("path", "Đường dẫn trong ROM", 430),
                                  ("size", "Dung lượng", 110), ("action", "Thay đổi", 100)):
            self.rom_apps_tree.heading(key, text=title)
            self.rom_apps_tree.column(key, width=width, anchor="w")
        self.rom_apps_tree.tag_configure("remove", foreground="#b42318")
        self.rom_apps_tree.tag_configure("protected", foreground="#667085")
        self.rom_apps_tree.pack(fill="both", expand=True)

    def _build_launcher_tab(self) -> None:
        ttk.Label(self.launcher_tab, text="Cấu hình Home Launcher", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(self.launcher_tab, text="Package").grid(row=1, column=0, sticky="w", pady=10)
        self.launcher_package = tk.StringVar()
        self.launcher_package_combo = ttk.Combobox(self.launcher_tab, textvariable=self.launcher_package, width=60, state="readonly")
        self.launcher_package_combo.grid(row=1, column=1, sticky="ew")
        self.launcher_package_combo.bind("<<ComboboxSelected>>", self._launcher_package_selected)
        ttk.Label(self.launcher_tab, text="Activity").grid(row=2, column=0, sticky="w", pady=10)
        self.launcher_activity = tk.StringVar()
        self.launcher_activity_combo = ttk.Combobox(self.launcher_tab, textvariable=self.launcher_activity, width=60, state="readonly")
        self.launcher_activity_combo.grid(row=2, column=1, sticky="ew")
        self.keep_fallback = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.launcher_tab, text="Giữ Launcher dự phòng để tránh màn hình đen", variable=self.keep_fallback).grid(row=3, column=1, sticky="w", pady=6)
        self.disable_old = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.launcher_tab, text="Vô hiệu hóa Launcher cũ sau khi Launcher mới hoạt động", variable=self.disable_old).grid(row=4, column=1, sticky="w", pady=6)
        ttk.Label(self.launcher_tab, text="Ứng dụng chỉ được đặt làm Home khi manifest có MAIN + HOME + DEFAULT.", foreground="#9a6700").grid(row=5, column=1, sticky="w", pady=14)
        self.launcher_tab.columnconfigure(1, weight=1)

    def _build_root_tab(self) -> None:
        ttk.Label(self.root_tab, text="Bộ quản lý quyền root", style="Section.TLabel").pack(anchor="w")
        self.root_mode = tk.StringVar(value="Giữ nguyên root hiện tại")
        for value in ("Giữ nguyên root hiện tại", "Không root", "Tích hợp SuperSU từ ZIP"):
            ttk.Radiobutton(self.root_tab, text=value, value=value, variable=self.root_mode).pack(anchor="w", pady=5)
        row = ttk.Frame(self.root_tab)
        row.pack(fill="x", pady=12)
        self.root_zip = tk.StringVar()
        ttk.Entry(row, textvariable=self.root_zip).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Chọn ZIP SuperSU…", command=self.choose_root_zip).pack(side="left", padx=8)
        ttk.Label(self.root_tab, text="Ứng dụng sẽ kiểm tra kiến trúc, phiên bản Android, daemon và ứng dụng quản lý trước khi cho build.", foreground="#4b5563").pack(anchor="w")

    def _build_build_tab(self) -> None:
        ttk.Label(self.build_tab, text="Xuất firmware mới", style="Section.TLabel").pack(anchor="w")
        row = ttk.Frame(self.build_tab)
        row.pack(fill="x", pady=12)
        self.output_path = tk.StringVar()
        ttk.Entry(row, textvariable=self.output_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Chọn nơi lưu…", command=self.choose_output).pack(side="left", padx=8)
        burning = ttk.LabelFrame(self.build_tab, text="Amlogic USB Burning Tool", padding=10)
        burning.pack(fill="x", pady=(0, 12))
        tool_row = ttk.Frame(burning)
        tool_row.pack(fill="x")
        self.burning_tool_path = tk.StringVar(value=detect_tool())
        ttk.Entry(tool_row, textvariable=self.burning_tool_path).pack(side="left", fill="x", expand=True)
        ttk.Button(tool_row, text="Chọn công cụ…", command=self.choose_burning_tool).pack(side="left", padx=8)
        ttk.Button(tool_row, text="Tìm tự động", command=self.auto_detect_burning_tool).pack(side="left")
        self.ask_flash_after_build = tk.BooleanVar(value=True)
        ttk.Checkbutton(burning, text="Sau khi đóng gói, hỏi chuyển ROM sang USB Burning Tool", variable=self.ask_flash_after_build).pack(anchor="w", pady=(8, 0))
        ttk.Label(burning, text="ROM Builder sẽ tự nạp file IMG. Người dùng kiểm tra thiết bị và tự bấm Start để flash.", foreground="#4b5563").pack(anchor="w", pady=(4, 0))
        checklist = ttk.LabelFrame(self.build_tab, text="Kiểm tra bắt buộc", padding=12)
        checklist.pack(fill="x")
        self.build_checks = tk.StringVar(value="Chưa phân tích ROM.")
        ttk.Label(checklist, textvariable=self.build_checks, justify="left").pack(anchor="w")
        buttons = ttk.Frame(self.build_tab)
        buttons.pack(fill="x", pady=16)
        self.apply_button = ttk.Button(buttons, text="Áp dụng thay đổi", command=self.start_apply, state="disabled")
        self.apply_button.pack(side="right")
        self.build_button = ttk.Button(buttons, text="Bắt đầu đóng gói", command=self.start_build, state="disabled")
        self.build_button.pack(side="right", padx=8)
        ttk.Button(buttons, text="Hoàn tác cấu hình", command=self.reset_changes).pack(side="left")

    def _build_log_tab(self) -> None:
        self.log_text = tk.Text(self.log_tab, wrap="none", font=("Consolas", 9), state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def _build_about_tab(self) -> None:
        top = ttk.Frame(self.about_tab)
        top.pack(fill="x")
        try:
            image = tk.PhotoImage(file=str(self._resource_path("rom_builder_logo.png")))
            factor = max(1, image.width() // 128)
            self._about_logo = image.subsample(factor, factor)
            ttk.Label(top, image=self._about_logo).pack(side="left", padx=(0, 18))
        except tk.TclError:
            pass
        text = ttk.Frame(top)
        text.pack(side="left", fill="x", expand=True)
        ttk.Label(text, text="Universal Android ROM Builder", style="Title.TLabel").pack(anchor="w")
        ttk.Label(text, text=f"Phiên bản {__version__}").pack(anchor="w", pady=(4, 10))
        ttk.Label(text, text="Công cụ phân tích, tùy chỉnh và đóng gói firmware Android TV.", wraplength=720).pack(anchor="w")
        details = (
            "Nền tảng mục tiêu: Amlogic USB Burning Image và Allwinner/PhoenixSuit.\n"
            "Chức năng: phân tích phân vùng, kiểm tra APK/Home Launcher, quản lý ứng dụng, root, log và checksum.\n\n"
            "An toàn: ứng dụng không ghi đè ROM gốc và chỉ cho phép xuất ROM sau khi các bước xác minh hoàn tất.\n"
            "Logo ứng dụng được thiết kế riêng cho dự án ROM Builder."
            "\nTích hợp: chuyển ROM đã xác minh sang Amlogic USB Burning Tool và tự điền file IMG."
        )
        ttk.Label(self.about_tab, text=details, justify="left", wraplength=900).pack(anchor="w", pady=(24, 0))

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def choose_rom(self) -> None:
        path = filedialog.askopenfilename(title="Chọn firmware", filetypes=[("Firmware image", "*.img"), ("Tất cả file", "*.*")])
        if path:
            if path != self.rom_path.get():
                self._clear_rom_state()
            self.rom_path.set(path)
            default = str(Path(path).with_name(Path(path).stem + "-modified.img"))
            self.output_path.set(default)

    def start_analysis(self) -> None:
        path = self.rom_path.get().strip()
        if not path:
            messagebox.showwarning("Thiếu firmware", "Hãy chọn file ROM trước.")
            return
        if self.analyzed_rom_path and str(Path(path).resolve()) != self.analyzed_rom_path:
            self._clear_rom_state(keep_rom_path=True)
            self.rom_path.set(path)
        elif self.firmware_info is not None:
            # Re-analyzing the same source also starts a clean configuration.
            self._clear_rom_state(keep_rom_path=True)
            self.rom_path.set(path)
        self.analyze_button.configure(state="disabled")
        self.started_at = time.time()
        self.progress["value"] = 0
        self.log(f"Bắt đầu phân tích: {path}")
        threading.Thread(target=self._analysis_worker, args=(path,), daemon=True).start()

    def _analysis_worker(self, path: str) -> None:
        try:
            info = analyze_firmware(path, lambda percent, text: self.events.put(("progress", int(percent * .45), text)))
            self.events.put(("firmware", info))
            if info.platform == "Amlogic" and info.valid and info.checksum_ok is not False:
                project = AmlogicProject(path)
                apps = project.prepare(lambda percent, text: self.events.put(("progress", 45 + int(percent * .55), text)))
                self.events.put(("system_ready", project, apps))
            elif info.platform == "Allwinner" and info.valid and info.checksum_ok is not False:
                project = PhoenixProject(path)
                apps = project.prepare(lambda percent, text: self.events.put(("progress", 45 + int(percent * .55), text)))
                self.events.put(("system_ready", project, apps))
        except Exception as exc:
            self.events.put(("error", "Không thể phân tích ROM", str(exc)))

    def _show_firmware(self, info) -> None:
        self.firmware_info = info
        self.analyzed_rom_path = str(Path(info.path).resolve())
        self.summary_vars["Nền tảng"].set(info.platform)
        self.summary_vars["Định dạng"].set(info.package_format)
        self.summary_vars["Dung lượng"].set(self._size(info.size))
        self.summary_vars["CRC"].set("Hợp lệ" if info.checksum_ok else "Không hợp lệ" if info.checksum_ok is False else "Chưa kiểm tra")
        self.summary_vars["Trạng thái"].set("Có thể xử lý" if info.valid and info.checksum_ok is not False else "Cần kiểm tra")
        self.partition_tree.delete(*self.partition_tree.get_children())
        for part in info.partitions:
            self.partition_tree.insert("", "end", values=(part.item_type, part.name, part.format, f"0x{part.offset:X}", self._size(part.size)))
        for warning in info.warnings:
            self.log("CẢNH BÁO: " + warning)
        self.build_checks.set(
            f"{'✓' if info.valid else '✗'} Cấu trúc gói firmware\n"
            f"{'✓' if info.checksum_ok else '✗'} CRC firmware\n"
            f"{'✓' if any(p.name == 'system' and p.item_type == 'PARTITION' for p in info.partitions) else '✗'} Phân vùng system\n"
            "○ Đang chuẩn bị phân vùng system và danh sách ứng dụng"
        )
        self.log(f"Phân tích hoàn tất sau {time.time() - self.started_at:.1f} giây: {len(info.partitions)} item")

    def add_apks(self) -> None:
        paths = filedialog.askopenfilenames(title="Chọn APK", filetypes=[("Android APK", "*.apk")])
        if not paths:
            return
        self.progress["value"] = 0
        self.status_text.set("Đang phân tích APK")
        threading.Thread(target=self._apk_worker, args=(list(paths), self.new_apk_location.get()), daemon=True).start()

    def _apk_worker(self, paths: list[str], location="/system/preinstall") -> None:
        total = len(paths)
        for index, path in enumerate(paths, 1):
            self.events.put(("log", f"Phân tích APK: {path}"))
            info = analyze_apk(path)
            item_location = location.get(path, "/system/preinstall") if isinstance(location, dict) else location
            self.events.put(("apk", info, item_location))
            self.events.put(("progress", int(index / total * 100), f"Đã phân tích {index}/{total} APK"))
        self.events.put(("apk_done", total))

    def _show_apk(self, info, location="/system/preinstall") -> None:
        if self.apk_tree.exists(info.path):
            return
        self.apk_infos.append(info)
        self.apk_locations[info.path] = location
        self.apk_tree.insert("", "end", iid=info.path, values=(info.filename, info.package_name or "Chưa xác định", info.launcher_status,
                                                                ", ".join(info.native_architectures) or "Không có lib", self._size(info.size), location))
        if info.package_name and info.activities:
            activities = info.activities
            self.launcher_candidates[info.package_name] = activities
            packages = list(self.launcher_candidates)
            self.launcher_package_combo["values"] = packages
            if not self.launcher_package.get():
                self.launcher_package.set(info.package_name)
                self._fill_activities(info.package_name)
        for warning in info.warnings:
            self.log(f"CẢNH BÁO APK {info.filename}: {warning}")

    def _launcher_package_selected(self, _event=None) -> None:
        self._fill_activities(self.launcher_package.get())

    def _fill_activities(self, package: str) -> None:
        activities = self.launcher_candidates.get(package, [])
        self.launcher_activity_combo["values"] = activities
        self.launcher_activity.set(activities[0] if activities else "")

    def remove_selected_apk(self) -> None:
        for item in self.apk_tree.selection():
            self.apk_infos = [info for info in self.apk_infos if info.path != item]
            self.apk_locations.pop(item, None)
            self.apk_tree.delete(item)
        self._configuration_changed()

    def set_selected_apk_location(self) -> None:
        location = self.new_apk_location.get()
        for item in self.apk_tree.selection():
            self.apk_locations[item] = location
            values = list(self.apk_tree.item(item, "values"))
            values[5] = location
            self.apk_tree.item(item, values=values)
        self._configuration_changed()

    def _show_rom_apps(self, apps) -> None:
        self.rom_apps = apps
        self.rom_apps_by_path = {item["path"]: item for item in apps}
        self._refresh_rom_apps_tree()
        self._update_rom_apps_summary()

    def _refresh_rom_apps_tree(self) -> None:
        if not hasattr(self, "rom_apps_tree"):
            return
        self.rom_apps_tree.delete(*self.rom_apps_tree.get_children())
        query = self.rom_app_search.get().strip().lower() if hasattr(self, "rom_app_search") else ""
        location_filter = self.rom_app_location_filter.get() if hasattr(self, "rom_app_location_filter") else "Tất cả"
        for item in sorted(self.rom_apps, key=lambda value: (value["location"], value["name"].lower())):
            if query and query not in item["name"].lower() and query not in item["path"].lower():
                continue
            if location_filter != "Tất cả" and item["location"] != location_filter:
                continue
            protected = self._protected_rom_app(item["name"])
            removed = item["path"] in self.removal_paths
            action = "Bảo vệ" if protected else "Sẽ gỡ" if removed else "Giữ lại"
            self.rom_apps_tree.insert("", "end", iid=item["path"], values=(item["name"], item["location"], item["path"], self._size(item["size"]), action),
                                      tags=("protected",) if protected else ("remove",) if removed else ())
        if hasattr(self, "rom_apps_summary"):
            self._update_rom_apps_summary()

    def mark_remove_rom_apps(self) -> None:
        skipped = []
        for path in self.rom_apps_tree.selection():
            if self._protected_rom_app(self.rom_apps_by_path[path]["name"]):
                skipped.append(self.rom_apps_by_path[path]["name"]); continue
            self.removal_paths.add(path)
            values = list(self.rom_apps_tree.item(path, "values")); values[4] = "Sẽ gỡ"
            self.rom_apps_tree.item(path, values=values, tags=("remove",))
        self._update_rom_apps_summary(); self._configuration_changed()
        if skipped:
            messagebox.showwarning("Ứng dụng được bảo vệ", "Không thể gỡ thành phần hệ thống quan trọng:\n" + "\n".join(skipped))

    def unmark_remove_rom_apps(self) -> None:
        for path in self.rom_apps_tree.selection():
            self.removal_paths.discard(path)
            protected = self._protected_rom_app(self.rom_apps_by_path[path]["name"])
            values = list(self.rom_apps_tree.item(path, "values")); values[4] = "Bảo vệ" if protected else "Giữ lại"
            self.rom_apps_tree.item(path, values=values, tags=("protected",) if protected else ())
        self._update_rom_apps_summary(); self._configuration_changed()

    def _update_rom_apps_summary(self) -> None:
        free = f" • System trống: {self._size(self.system_free_bytes)}" if self.system_free_bytes else ""
        visible = len(self.rom_apps_tree.get_children()) if hasattr(self, "rom_apps_tree") else 0
        self.rom_apps_summary.set(f"Tổng {len(self.rom_apps)} APK • Đang hiện {visible} • Đánh dấu gỡ: {len(self.removal_paths)}{free}")

    def clear_rom_app_filters(self) -> None:
        self.rom_app_search.set("")
        self.rom_app_location_filter.set("Tất cả")
        self._refresh_rom_apps_tree(); self._update_rom_apps_summary()

    def mark_all_visible_remove(self) -> None:
        candidates = [path for path in self.rom_apps_tree.get_children()
                      if not self._protected_rom_app(self.rom_apps_by_path[path]["name"])]
        if not candidates:
            return
        if not messagebox.askyesno("Xác nhận", f"Đánh dấu gỡ {len(candidates)} ứng dụng đang hiển thị?\nCác thành phần được bảo vệ sẽ được giữ lại."):
            return
        self.removal_paths.update(candidates)
        self._refresh_rom_apps_tree(); self._update_rom_apps_summary(); self._configuration_changed()

    def export_rom_apps(self) -> None:
        if not self.rom_apps:
            messagebox.showwarning("Chưa có dữ liệu", "Hãy phân tích ROM trước."); return
        path = filedialog.asksaveasfilename(title="Xuất danh sách ứng dụng", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with Path(path).open("w", newline="", encoding="utf-8-sig") as output:
            writer = csv.writer(output)
            writer.writerow(("APK", "Vị trí", "Đường dẫn trong ROM", "Dung lượng byte", "Trạng thái"))
            for item in sorted(self.rom_apps, key=lambda value: value["path"]):
                status = "Bảo vệ" if self._protected_rom_app(item["name"]) else "Sẽ gỡ" if item["path"] in self.removal_paths else "Giữ lại"
                writer.writerow((item["name"], item["location"], item["path"], item["size"], status))
        self.log(f"Đã xuất danh sách ứng dụng: {path}")

    @staticmethod
    def _protected_rom_app(name: str) -> bool:
        protected = ("SystemUI", "Settings", "SettingsProvider", "PackageInstaller", "AppInstaller",
                     "PermissionController", "DownloadProvider", "MediaProvider", "DocumentsUI")
        lowered = name.lower()
        return any(value.lower() in lowered for value in protected)

    def reset_changes(self) -> None:
        self.removal_paths.clear()
        for path in self.rom_apps_tree.get_children():
            protected = self._protected_rom_app(self.rom_apps_by_path[path]["name"])
            values = list(self.rom_apps_tree.item(path, "values")); values[4] = "Bảo vệ" if protected else "Giữ lại"
            self.rom_apps_tree.item(path, values=values, tags=("protected",) if protected else ())
        self.changes_applied = False
        self.build_button.configure(state="disabled")
        self._refresh_rom_apps_tree()
        self._update_rom_apps_summary()
        self._update_build_checks()

    def _clear_rom_state(self, keep_rom_path=False) -> None:
        old_path = self.rom_path.get() if keep_rom_path and hasattr(self, "rom_path") else ""
        self.firmware_info = None
        self.analyzed_rom_path = ""
        self.project = None
        self.apk_infos.clear(); self.apk_locations.clear(); self.launcher_candidates.clear()
        self.rom_apps.clear(); self.rom_apps_by_path.clear(); self.removal_paths.clear()
        self.changes_applied = False; self.system_free_bytes = 0
        if hasattr(self, "partition_tree"):
            self.partition_tree.delete(*self.partition_tree.get_children())
        if hasattr(self, "apk_tree"):
            self.apk_tree.delete(*self.apk_tree.get_children())
        if hasattr(self, "rom_apps_tree"):
            self.rom_apps_tree.delete(*self.rom_apps_tree.get_children())
        if hasattr(self, "launcher_package_combo"):
            self.launcher_package_combo["values"] = ()
            self.launcher_activity_combo["values"] = ()
        self.launcher_package.set(""); self.launcher_activity.set("")
        self.keep_fallback.set(True); self.disable_old.set(False)
        self.root_mode.set("Giữ nguyên root hiện tại"); self.root_zip.set("")
        self.new_apk_location.set("/system/preinstall")
        self.rom_app_search.set(""); self.rom_app_location_filter.set("Tất cả")
        for var in self.summary_vars.values(): var.set("—")
        self.build_checks.set("Chưa phân tích ROM.")
        self.rom_apps_summary.set("Phân tích ROM để đọc danh sách ứng dụng.")
        self.progress["value"] = 0; self.percent_text.set("0%")
        self.status_text.set("Sẵn sàng phân tích ROM mới")
        self.apply_button.configure(state="disabled"); self.build_button.configure(state="disabled")
        if keep_rom_path:
            self.rom_path.set(old_path)
            if old_path:
                self.output_path.set(str(Path(old_path).with_name(Path(old_path).stem + "-modified.img")))
        else:
            self.output_path.set("")

    def _configuration_changed(self) -> None:
        self.changes_applied = False
        self.build_button.configure(state="disabled")
        self._update_build_checks()

    def choose_root_zip(self) -> None:
        path = filedialog.askopenfilename(title="Chọn ZIP root", filetypes=[("ZIP", "*.zip")])
        if path:
            self.root_zip.set(path)
            self.root_mode.set("Tích hợp SuperSU từ ZIP")

    def choose_output(self) -> None:
        path = filedialog.asksaveasfilename(title="Lưu firmware mới", defaultextension=".img", filetypes=[("Firmware image", "*.img")])
        if path:
            self.output_path.set(path)

    def choose_burning_tool(self) -> None:
        path = filedialog.askopenfilename(title="Chọn USB Burning Tool", filetypes=[("USB Burning Tool", "USB_Burning_Tool.exe"), ("EXE", "*.exe")])
        if path:
            self.burning_tool_path.set(path)

    def auto_detect_burning_tool(self) -> None:
        path = detect_tool()
        if path:
            self.burning_tool_path.set(path)
            messagebox.showinfo("Đã tìm thấy", path)
        else:
            messagebox.showwarning("Không tìm thấy", "Hãy cài Amlogic USB Burning Tool hoặc chọn file EXE thủ công.")

    def save_project(self) -> None:
        path = filedialog.asksaveasfilename(title="Lưu cấu hình dự án", defaultextension=".arbproject", filetypes=[("ROM Builder Project", "*.arbproject"), ("JSON", "*.json")])
        if not path:
            return
        data = {
            "format": "UniversalAndroidRomBuilderProject",
            "version": 1,
            "firmware_path": self.rom_path.get(),
            "output_path": self.output_path.get(),
            "launcher": {
                "package": self.launcher_package.get(),
                "activity": self.launcher_activity.get(),
                "keep_fallback": self.keep_fallback.get(),
                "disable_old": self.disable_old.get(),
            },
            "root": {"mode": self.root_mode.get(), "zip": self.root_zip.get()},
            "apks": [{"path": item.path, "package": item.package_name, "location": self.apk_locations.get(item.path, "/system/preinstall")} for item in self.apk_infos],
            "remove_paths": sorted(self.removal_paths),
            "usb_burning": {"path": self.burning_tool_path.get(), "ask_after_build": self.ask_flash_after_build.get()},
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"Đã lưu cấu hình: {path}")
        messagebox.showinfo("Đã lưu", "Cấu hình dự án đã được lưu thành công.")

    def load_project(self) -> None:
        path = filedialog.askopenfilename(title="Mở cấu hình dự án", filetypes=[("ROM Builder Project", "*.arbproject *.json"), ("Tất cả file", "*.*")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.rom_path.set(data.get("firmware_path", ""))
            self.output_path.set(data.get("output_path", ""))
            launcher = data.get("launcher", {})
            package = launcher.get("package", "")
            activity = launcher.get("activity", "")
            self.keep_fallback.set(bool(launcher.get("keep_fallback", True)))
            self.disable_old.set(bool(launcher.get("disable_old", False)))
            root = data.get("root", {})
            self.root_mode.set(root.get("mode", "Giữ nguyên root hiện tại"))
            self.root_zip.set(root.get("zip", ""))
            apk_locations = {item.get("path"): item.get("location", "/system/preinstall") for item in data.get("apks", []) if item.get("path")}
            apk_paths = [path for path in apk_locations if Path(path).exists()]
            if apk_paths:
                threading.Thread(target=self._apk_worker, args=(apk_paths, apk_locations), daemon=True).start()
            self.removal_paths = set(data.get("remove_paths", []))
            burning = data.get("usb_burning", {})
            if burning.get("path"):
                self.burning_tool_path.set(burning["path"])
            self.ask_flash_after_build.set(bool(burning.get("ask_after_build", True)))
            self.after(250, lambda: (self.launcher_package.set(package), self.launcher_activity.set(activity)))
            self.log(f"Đã mở cấu hình: {path}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("Không mở được cấu hình", str(exc))

    def _update_build_checks(self) -> None:
        if not self.firmware_info:
            self.build_checks.set("Chưa phân tích ROM."); return
        system_ready = self.project is not None
        self.build_checks.set(
            f"{'✓' if self.firmware_info.valid else '✗'} Cấu trúc gói firmware\n"
            f"{'✓' if self.firmware_info.checksum_ok else '✗'} CRC firmware\n"
            f"{'✓' if system_ready else '○'} Phân vùng system và danh sách APK\n"
            f"{'✓' if self.changes_applied else '○'} Cấu hình thay đổi {'đã' if self.changes_applied else 'chưa'} được áp dụng\n"
            f"Thêm mới: {len(self.apk_infos)} APK • Gỡ: {len(self.removal_paths)} APK"
        )

    def start_apply(self) -> None:
        if not self.project:
            messagebox.showwarning("Chưa sẵn sàng", "Hãy phân tích và chờ đọc xong phân vùng system."); return
        if self.root_mode.get() == "Không root":
            messagebox.showwarning("Root chưa hỗ trợ trong build chung", "Bản này chỉ đóng gói an toàn với lựa chọn Giữ nguyên root hiện tại."); return
        if self.root_mode.get() == "Tích hợp SuperSU từ ZIP" and not Path(self.root_zip.get()).is_file():
            messagebox.showwarning("Chưa có ZIP SuperSU", "Hãy chọn file ZIP SuperSU hợp lệ trước khi áp dụng."); return
        selected_package = self.launcher_package.get()
        if selected_package:
            selected_info = next((item for item in self.apk_infos if item.package_name == selected_package), None)
            if selected_info is not None and self.launcher_activity.get() not in selected_info.activities:
                messagebox.showwarning("Không thể đặt Home", "APK đã chọn chỉ có LAUNCHER nhưng không khai báo HOME + DEFAULT."); return
        self.apply_button.configure(state="disabled"); self.build_button.configure(state="disabled")
        additions = [{"path": info.path, "location": self.apk_locations.get(info.path, "/system/preinstall")} for info in self.apk_infos]
        removals = [self.rom_apps_by_path[path] for path in self.removal_paths if path in self.rom_apps_by_path]
        threading.Thread(target=self._apply_worker, args=(additions, removals, self.launcher_package.get(), self.launcher_activity.get(), self.root_mode.get(), self.root_zip.get()), daemon=True).start()

    def _apply_worker(self, additions, removals, launcher_package, launcher_activity, root_mode, root_zip) -> None:
        try:
            output = self.project.apply(additions, removals, launcher_package, launcher_activity,
                                        root_mode, root_zip,
                                        lambda p, t: self.events.put(("progress", p, t)))
            self.events.put(("applied", output))
        except Exception as exc:
            self.events.put(("error", "Không thể áp dụng thay đổi", str(exc)))

    def start_build(self) -> None:
        output = self.output_path.get().strip()
        if not self.changes_applied:
            messagebox.showwarning("Chưa áp dụng", "Hãy bấm Áp dụng thay đổi trước khi đóng gói."); return
        if not output:
            self.choose_output(); output = self.output_path.get().strip()
        if not output: return
        self.build_button.configure(state="disabled"); self.apply_button.configure(state="disabled")
        threading.Thread(target=self._build_worker, args=(output,), daemon=True).start()

    def _build_worker(self, output) -> None:
        try:
            destination = self.project.build(output, lambda p, t: self.events.put(("progress", p, t)))
            self.events.put(("built", str(destination)))
        except Exception as exc:
            self.events.put(("error", "Không thể đóng gói ROM", str(exc)))

    def _burn_worker(self, tool_path, image_path) -> None:
        try:
            launch_and_import(tool_path, image_path, lambda p, t: self.events.put(("progress", p, t)))
            self.events.put(("burn_launched", image_path))
        except Exception as exc:
            self.events.put(("burn_error", str(exc), image_path))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, percent, text = event
                    self.progress["value"] = percent
                    self.percent_text.set(f"{percent}%")
                    self.status_text.set(text)
                elif event[0] == "firmware":
                    self._show_firmware(event[1])
                    self.analyze_button.configure(state="normal")
                    self.progress["value"] = 100
                    self.percent_text.set("100%")
                    self.status_text.set("Đang bung phân vùng system")
                elif event[0] == "system_ready":
                    _, self.project, apps = event
                    self.system_free_bytes = self.project.free_bytes(self.project.raw)
                    self._show_rom_apps(apps)
                    for path in list(self.removal_paths):
                        if self.rom_apps_tree.exists(path):
                            values = list(self.rom_apps_tree.item(path, "values")); values[4] = "Sẽ gỡ"
                            self.rom_apps_tree.item(path, values=values, tags=("remove",))
                    self.apply_button.configure(state="normal")
                    self.analyze_button.configure(state="normal")
                    self.progress["value"] = 100; self.percent_text.set("100%")
                    self.status_text.set("Phân tích ROM và ứng dụng hoàn tất")
                    self._update_build_checks()
                elif event[0] == "apk":
                    self._show_apk(event[1], event[2])
                elif event[0] == "apk_done":
                    self.status_text.set(f"Đã phân tích {event[1]} APK")
                    self.progress["value"] = 100
                    self.percent_text.set("100%")
                elif event[0] == "log":
                    self.log(event[1])
                elif event[0] == "applied":
                    self.changes_applied = True
                    self.apply_button.configure(state="normal"); self.build_button.configure(state="normal")
                    self.progress["value"] = 100; self.percent_text.set("100%")
                    self.status_text.set("Đã áp dụng thay đổi; có thể đóng gói")
                    self.log("Đã áp dụng cấu hình vào system EXT4")
                    self._update_build_checks()
                elif event[0] == "built":
                    self.apply_button.configure(state="normal"); self.build_button.configure(state="normal")
                    self.progress["value"] = 100; self.percent_text.set("100%")
                    self.status_text.set("Đóng gói và xác minh hoàn tất")
                    self.log(f"ROM đầu ra: {event[1]}")
                    if self.firmware_info and self.firmware_info.platform == "Allwinner":
                        messagebox.showinfo("PhoenixSuit ROM hoàn tất", f"Đã tạo và kiểm tra checksum Vsystem:\n{event[1]}\n\nHãy chọn file này trong PhoenixSuit để flash.")
                    elif self.ask_flash_after_build.get() and messagebox.askyesno("Đóng gói hoàn tất", f"Đã tạo và xác minh ROM:\n{event[1]}\n\nChuyển sang USB Burning Tool để flash ROM?"):
                        tool_path = self.burning_tool_path.get().strip()
                        if not tool_path or not Path(tool_path).is_file():
                            self.auto_detect_burning_tool(); tool_path = self.burning_tool_path.get().strip()
                        if tool_path and Path(tool_path).is_file():
                            threading.Thread(target=self._burn_worker, args=(tool_path, event[1]), daemon=True).start()
                        else:
                            messagebox.showwarning("Thiếu USB Burning Tool", "ROM đã tạo thành công nhưng chưa thể chuyển sang công cụ flash.")
                    else:
                        messagebox.showinfo("Hoàn tất", f"Đã tạo và xác minh ROM:\n{event[1]}")
                elif event[0] == "burn_launched":
                    self.progress["value"] = 100; self.percent_text.set("100%")
                    self.status_text.set("ROM đã được nạp vào USB Burning Tool")
                    self.log(f"Đã chuyển ROM sang USB Burning Tool: {event[1]}")
                    messagebox.showinfo("Sẵn sàng flash", "ROM mới đã được điền vào USB Burning Tool.\nHãy kiểm tra tùy chọn Erase, kết nối đúng box rồi bấm Start.")
                elif event[0] == "burn_error":
                    self.status_text.set("Không thể tự động nạp ROM vào USB Burning Tool")
                    self.log(f"LỖI USB Burning Tool: {event[1]}")
                    messagebox.showwarning("Không tự động nạp được ROM", f"{event[1]}\n\nROM vẫn đã được tạo tại:\n{event[2]}\nHãy dùng File > Import image để chọn thủ công.")
                elif event[0] == "error":
                    _, title, detail = event
                    self.analyze_button.configure(state="normal")
                    if self.project:
                        self.apply_button.configure(state="normal")
                    if self.changes_applied:
                        self.build_button.configure(state="normal")
                    self.status_text.set("Có lỗi")
                    self.log(f"LỖI: {detail}")
                    messagebox.showerror(title, detail)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    @staticmethod
    def _size(value: int) -> str:
        size = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{value} B"


def main() -> None:
    RomBuilderApp().mainloop()

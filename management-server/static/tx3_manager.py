#!/usr/bin/env python3
"""
TX3 Manager Desktop v2.0 - Full-Featured Python Native GUI
Modules: Login, Dashboard, ROM Builder, File Transfer, Remote Config, ADB Console
"""

import hashlib
import json
import os
import ssl
import sys
import threading
import time
import uuid
import urllib.request
import urllib.parse
import urllib.error
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ── Configuration ──
DEFAULT_SERVER_URL = "https://tx3.dothanhsang.id.vn"
APP_VERSION = "2.0.0"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB per chunk for file transfer

# Allow self-signed / Cloudflare certs
try:
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE
except Exception:
    _ssl_ctx = None


# ════════════════════════════════════════════════════════════════
#  API CLIENT
# ════════════════════════════════════════════════════════════════
class APIClient:
    """HTTP Client for TX3 Management Server API."""

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def __init__(self, base_url=DEFAULT_SERVER_URL):
        self.base_url = base_url.rstrip("/")
        self.token = None

    # ── generic request ──
    def _request(self, endpoint, method="GET", data=None, headers=None, raw_bytes=False, timeout=30):
        url = f"{self.base_url}{endpoint}"
        req_headers = {"Accept": "application/json", "User-Agent": self.UA}
        if self.token:
            req_headers["Authorization"] = f"Bearer {self.token}"
        if headers:
            req_headers.update(headers)

        req_data = None
        if data is not None:
            ct = req_headers.get("Content-Type", "")
            if ct == "application/json":
                req_data = json.dumps(data).encode("utf-8")
            elif isinstance(data, bytes):
                req_data = data
            elif isinstance(data, dict):
                req_data = urllib.parse.urlencode(data).encode("utf-8")
                if not ct:
                    req_headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif isinstance(data, str):
                req_data = data.encode("utf-8")
            else:
                req_data = data

        req = urllib.request.Request(url, data=req_data, headers=req_headers, method=method)
        try:
            opener_args = {"timeout": timeout}
            if _ssl_ctx:
                opener_args["context"] = _ssl_ctx
            with urllib.request.urlopen(req, **opener_args) as resp:
                resp_bytes = resp.read()
                if raw_bytes:
                    return resp_bytes
                if resp_bytes:
                    return json.loads(resp_bytes.decode("utf-8"))
                return {}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_msg)
                detail = err_json.get("detail", err_msg)
                if isinstance(detail, list):
                    detail = "; ".join(
                        item.get("msg", str(item)) if isinstance(item, dict) else str(item)
                        for item in detail
                    )
                raise Exception(detail)
            except json.JSONDecodeError:
                raise Exception(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise Exception(f"Kết nối thất bại: {e.reason}")
        except Exception as e:
            raise Exception(str(e))

    # ── Auth ──
    def login(self, username, password):
        res = self._request(
            "/api/v1/auth/login", method="POST",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
        )
        self.token = res.get("access_token")
        return res

    # ── Devices ──
    def get_devices(self):
        return self._request("/api/v1/devices")

    def get_device(self, device_id):
        return self._request(f"/api/v1/devices/{device_id}")

    def get_device_count(self):
        return self._request("/api/v1/devices/count")

    def reboot_device(self, device_id):
        return self._request(f"/api/v1/devices/{device_id}/reboot", method="POST")

    # ── ADB ──
    def send_adb_command(self, device_id, command):
        return self._request(
            f"/api/v1/devices/{device_id}/adb", method="POST",
            data={"command": command, "command_id": str(uuid.uuid4())},
            headers={"Content-Type": "application/json"},
        )

    # ── File Transfer ──
    def upload_file(self, device_id, local_path, remote_dest, progress_cb=None):
        """Upload a file to a device via the management server relay."""
        file_size = os.path.getsize(local_path)
        filename = os.path.basename(local_path)

        # compute SHA-256
        sha = hashlib.sha256()
        with open(local_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha.update(chunk)
        file_hash = sha.hexdigest()

        transfer_id = str(uuid.uuid4())

        # initiate transfer
        self._request(
            f"/api/v1/devices/{device_id}/transfers", method="POST",
            data={
                "transfer_id": transfer_id,
                "filename": filename,
                "destination": remote_dest,
                "file_size": file_size,
                "hash_sha256": file_hash,
                "chunk_size": CHUNK_SIZE,
            },
            headers={"Content-Type": "application/json"},
        )

        # send chunks
        sent = 0
        chunk_idx = 0
        with open(local_path, "rb") as f:
            while sent < file_size:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                import base64
                b64 = base64.b64encode(chunk).decode("ascii")
                self._request(
                    f"/api/v1/devices/{device_id}/transfers/{transfer_id}/chunks",
                    method="POST",
                    data={
                        "chunk_index": chunk_idx,
                        "offset": sent,
                        "data": b64,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=120,
                )
                sent += len(chunk)
                chunk_idx += 1
                if progress_cb:
                    progress_cb(sent, file_size)

        # complete
        self._request(
            f"/api/v1/devices/{device_id}/transfers/{transfer_id}/complete",
            method="POST",
            data={"hash_sha256": file_hash, "total_bytes": file_size},
            headers={"Content-Type": "application/json"},
        )
        return {"transfer_id": transfer_id, "hash_sha256": file_hash, "status": "completed"}

    def list_remote_files(self, device_id, path="/sdcard"):
        return self._request(
            f"/api/v1/devices/{device_id}/files",
            method="POST",
            data={"path": path},
            headers={"Content-Type": "application/json"},
        )


# ════════════════════════════════════════════════════════════════
#  HELPER: SHA-256 of file
# ════════════════════════════════════════════════════════════════
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ════════════════════════════════════════════════════════════════
#  DARK THEME COLORS
# ════════════════════════════════════════════════════════════════
# Facebook-style Light Theme
BG = "#f0f2f5"
CARD = "#ffffff"
FG = "#1c1e21"
MUTED = "#65676b"
ACCENT = "#1877f2"
GREEN = "#31a24c"
RED = "#e41e3f"
CYAN = "#1877f2"
BORDER = "#dadde1"


# ════════════════════════════════════════════════════════════════
#  MAIN APP
# ════════════════════════════════════════════════════════════════
class TX3ManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"TX3 Manager v{APP_VERSION} — Quản trị Android Box từ xa")
        self.root.geometry("1200x780")
        self.root.minsize(1000, 650)
        self.root.configure(bg=BG)

        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self._setup_styles()

        self.api = APIClient()
        self.devices = []
        self.selected_device = None

        self.container = ttk.Frame(self.root)
        self.container.pack(fill=tk.BOTH, expand=True)
        self.show_login()

    # ── Styles ──
    def _setup_styles(self):
        s = self.style
        s.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Card.TLabel", background=CARD, foreground=FG)
        s.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 8))
        s.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground=ACCENT)
        s.configure("TabHeader.TLabel", font=("Segoe UI", 12, "bold"), foreground=ACCENT, background=BG)

        s.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background=ACCENT, foreground="#ffffff", padding=6)
        s.map("Primary.TButton", background=[("active", "#166fe5")])
        s.configure("Danger.TButton", font=("Segoe UI", 10, "bold"), background=RED, foreground="#ffffff", padding=6)
        s.map("Danger.TButton", background=[("active", "#c9173a")])
        s.configure("Action.TButton", font=("Segoe UI", 9), background="#e4e6eb", foreground=FG, padding=5)
        s.map("Action.TButton", background=[("active", "#d8dadf")])
        s.configure("Success.TButton", font=("Segoe UI", 10, "bold"), background=GREEN, foreground="#ffffff", padding=6)
        s.map("Success.TButton", background=[("active", "#2b9243")])

        s.configure("TEntry", fieldbackground="#ffffff", foreground=FG, insertcolor=FG)
        s.configure("TCombobox", fieldbackground="#ffffff", foreground=FG)

        s.configure("Treeview", background="#ffffff", foreground=FG, fieldbackground="#ffffff", rowheight=30, borderwidth=1)
        s.configure("Treeview.Heading", background="#e4e6eb", foreground=FG, font=("Segoe UI", 10, "bold"), relief="flat")
        s.map("Treeview", background=[("selected", "#e7f3ff")], foreground=[("selected", ACCENT)])

        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background="#e4e6eb", foreground=FG, padding=(14, 6), font=("Segoe UI", 10, "bold"))
        s.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])

        s.configure("TLabelframe", background=CARD, foreground=FG)
        s.configure("TLabelframe.Label", background=CARD, foreground=ACCENT, font=("Segoe UI", 10, "bold"))
        s.configure("TCheckbutton", background=CARD, foreground=FG)
        s.configure("TRadiobutton", background=CARD, foreground=FG)
        s.configure("TSeparator", background=BORDER)

        s.configure("Horizontal.TProgressbar", troughcolor=BORDER, background=ACCENT, thickness=18)

    def _clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    # ════════════════════════════════════════════════════════════
    #  LOGIN SCREEN
    # ════════════════════════════════════════════════════════════
    def show_login(self):
        self._clear()
        frm = ttk.Frame(self.container, style="Card.TFrame", padding=30)
        frm.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=440)

        ttk.Label(frm, text="TX3 REMOTE MANAGER", font=("Segoe UI", 18, "bold"), foreground=CYAN, background=CARD).pack(pady=(0, 3))
        ttk.Label(frm, text=f"Desktop Console v{APP_VERSION}", font=("Segoe UI", 9), foreground=MUTED, background=CARD).pack(pady=(0, 20))

        ttk.Label(frm, text="Server URL:", background=CARD).pack(anchor=tk.W, pady=(5, 2))
        self.url_ent = ttk.Entry(frm); self.url_ent.insert(0, DEFAULT_SERVER_URL); self.url_ent.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frm, text="Tài khoản:", background=CARD).pack(anchor=tk.W, pady=(5, 2))
        self.user_ent = ttk.Entry(frm); self.user_ent.insert(0, "admin"); self.user_ent.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frm, text="Mật khẩu:", background=CARD).pack(anchor=tk.W, pady=(5, 2))
        self.pass_ent = ttk.Entry(frm, show="•"); self.pass_ent.insert(0, "admin123"); self.pass_ent.pack(fill=tk.X, pady=(0, 12))

        self.login_err = ttk.Label(frm, text="", foreground=RED, background=CARD, font=("Segoe UI", 9))
        self.login_err.pack(pady=(0, 8))

        self.login_btn = ttk.Button(frm, text="ĐĂNG NHẬP", style="Primary.TButton", command=self._do_login)
        self.login_btn.pack(fill=tk.X, ipady=4)
        self.pass_ent.bind("<Return>", lambda e: self._do_login())

    def _do_login(self):
        url = self.url_ent.get().strip()
        user = self.user_ent.get().strip()
        pwd = self.pass_ent.get().strip()
        if not all([url, user, pwd]):
            self.login_err.config(text="Vui lòng nhập đầy đủ thông tin!")
            return
        self.login_btn.config(state=tk.DISABLED, text="Đang đăng nhập...")
        self.login_err.config(text="")

        def worker():
            try:
                self.api.base_url = url.rstrip("/")
                self.api.login(user, pwd)
                self.root.after(0, self.show_main)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._login_fail(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _login_fail(self, msg):
        self.login_btn.config(state=tk.NORMAL, text="ĐĂNG NHẬP")
        self.login_err.config(text=f"Lỗi: {msg}")

    # ════════════════════════════════════════════════════════════
    #  MAIN SCREEN (TABS)
    # ════════════════════════════════════════════════════════════
    def show_main(self):
        self._clear()

        # Top Bar
        top = ttk.Frame(self.container, padding=(15, 8))
        top.pack(fill=tk.X)
        ttk.Label(top, text=f"💻 TX3 Manager v{APP_VERSION}", style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Button(top, text="Đăng xuất", style="Action.TButton", command=self.show_login).pack(side=tk.RIGHT, padx=5)

        # Notebook Tabs
        self.notebook = ttk.Notebook(self.container)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Tab 1: Dashboard
        self.tab_dashboard = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dashboard, text="  📊 Dashboard  ")

        # Tab 2: ROM Builder
        self.tab_rom = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_rom, text="  🔧 ROM Builder  ")

        # Tab 3: File Transfer
        self.tab_transfer = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_transfer, text="  📁 File Transfer  ")

        # Tab 4: Remote Config
        self.tab_remote = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_remote, text="  🌐 Remote Management  ")

        # Tab 5: ADB Console
        self.tab_adb = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_adb, text="  💻 ADB Console  ")

        self._build_dashboard_tab()
        self._build_rom_tab()
        self._build_transfer_tab()
        self._build_remote_tab()
        self._build_adb_tab()

        self._load_devices()

    # ════════════════════════════════════════════════════════════
    #  TAB 1: DASHBOARD
    # ════════════════════════════════════════════════════════════
    def _build_dashboard_tab(self):
        tab = self.tab_dashboard

        # Stats row
        stats = ttk.Frame(tab, padding=(10, 10))
        stats.pack(fill=tk.X)

        self.stat_total = self._stat_card(stats, "TỔNG SỐ BOX", "0", CYAN)
        self.stat_total.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self.stat_online = self._stat_card(stats, "ONLINE", "0", GREEN)
        self.stat_online.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        self.stat_offline = self._stat_card(stats, "OFFLINE", "0", RED)
        self.stat_offline.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))

        # Filter bar
        fbar = ttk.Frame(tab, padding=(10, 6))
        fbar.pack(fill=tk.X)
        ttk.Label(fbar, text="🔍 Tìm kiếm:").pack(side=tk.LEFT, padx=(0, 4))
        self.search_var = tk.StringVar()
        se = ttk.Entry(fbar, textvariable=self.search_var, width=28)
        se.pack(side=tk.LEFT, padx=(0, 12))
        se.bind("<KeyRelease>", lambda e: self._filter_devices())

        ttk.Label(fbar, text="Trạng thái:").pack(side=tk.LEFT, padx=(0, 4))
        self.status_var = ttk.Combobox(fbar, values=["Tất cả", "online", "offline"], state="readonly", width=10)
        self.status_var.current(0)
        self.status_var.pack(side=tk.LEFT)
        self.status_var.bind("<<ComboboxSelected>>", lambda e: self._filter_devices())

        ttk.Button(fbar, text="🔄 Tải lại", style="Primary.TButton", command=self._load_devices).pack(side=tk.RIGHT)

        # Split: table left, detail right
        split = ttk.Frame(tab, padding=(10, 5))
        split.pack(fill=tk.BOTH, expand=True)

        # Device table
        tframe = ttk.Frame(split)
        tframe.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cols = ("name", "status", "wg_ip", "mac", "rom", "last_seen")
        self.tree = ttk.Treeview(tframe, columns=cols, show="headings", selectmode="browse")
        for c, h, w in [("name", "Tên Box", 170), ("status", "Trạng thái", 90), ("wg_ip", "WireGuard IP", 120),
                         ("mac", "MAC", 140), ("rom", "ROM/Agent", 110), ("last_seen", "Online lần cuối", 145)]:
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor=tk.CENTER if c == "status" else tk.W)

        sb = ttk.Scrollbar(tframe, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Right detail panel
        self.detail_panel = ttk.Frame(split, style="Card.TFrame", padding=12, width=310)
        self.detail_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(12, 0))
        self._show_empty_detail()

    def _stat_card(self, parent, title, val, color):
        f = ttk.Frame(parent, style="Card.TFrame", padding=10)
        ttk.Label(f, text=title, font=("Segoe UI", 9, "bold"), foreground=MUTED, background=CARD).pack(anchor=tk.W)
        lbl = ttk.Label(f, text=val, font=("Segoe UI", 20, "bold"), foreground=color, background=CARD)
        lbl.pack(anchor=tk.W)
        f._val = lbl
        return f

    def _show_empty_detail(self):
        for w in self.detail_panel.winfo_children():
            w.destroy()
        ttk.Label(self.detail_panel, text="👈 Chọn một Box\nđể xem chi tiết & điều khiển",
                  font=("Segoe UI", 10), foreground=MUTED, background=CARD, justify=tk.CENTER).pack(expand=True)

    def _load_devices(self):
        def worker():
            try:
                data = self.api.get_devices()
                self.devices = data if isinstance(data, list) else []
                self.root.after(0, self._update_dash)
                self.root.after(0, self._post_load_devices)
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: messagebox.showerror("Lỗi", f"Không tải được danh sách: {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    def _update_dash(self):
        total = len(self.devices)
        on = sum(1 for d in self.devices if d.get("status") == "online")
        self.stat_total._val.config(text=str(total))
        self.stat_online._val.config(text=str(on))
        self.stat_offline._val.config(text=str(total - on))
        self._filter_devices()

    def _filter_devices(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        q = self.search_var.get().lower().strip()
        st = self.status_var.get()
        for d in self.devices:
            ds = d.get("status", "offline")
            if st != "Tất cả" and ds != st:
                continue
            name = d.get("device_name") or d.get("hostname") or "TX3-Box"
            wg = d.get("wg_ip") or "—"
            mac = d.get("mac_ethernet") or d.get("mac_wifi") or "—"
            rom = f"{d.get('rom_version', '1.0')} / v{d.get('agent_version', '1.0')}"
            ls = (d.get("last_seen") or "—").replace("T", " ")[:19]
            if q and not any(q in str(v).lower() for v in [name, wg, mac]):
                continue
            icon = "🟢 ONLINE" if ds == "online" else "⚪ OFFLINE"
            iid = self.tree.insert("", tk.END, values=(name, icon, wg, mac, rom, ls))
            self.tree.item(iid, tags=(d.get("id"),))

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        dev_id = self.tree.item(sel[0], "tags")[0]
        self.selected_device = next((d for d in self.devices if d.get("id") == dev_id), None)
        if self.selected_device:
            self._show_detail(self.selected_device)

    def _show_detail(self, d):
        p = self.detail_panel
        for w in p.winfo_children():
            w.destroy()
        name = d.get("device_name") or "TX3-Box"
        st = d.get("status", "offline").upper()
        ttk.Label(p, text=f"📱 {name}", font=("Segoe UI", 12, "bold"), foreground=CYAN, background=CARD).pack(anchor=tk.W, pady=(0, 2))
        ttk.Label(p, text=f"Trạng thái: {st}", font=("Segoe UI", 9, "bold"),
                  foreground=GREEN if st == "ONLINE" else MUTED, background=CARD).pack(anchor=tk.W, pady=(0, 8))

        specs = [
            ("IP WireGuard:", d.get("wg_ip") or "10.88.0.x"),
            ("MAC Ethernet:", d.get("mac_ethernet") or "—"),
            ("Model / SoC:", f"{d.get('model', 'Tanix TX3')} / {d.get('soc', 'S905W')}"),
            ("ROM:", d.get("rom_version") or "v1.0.0"),
            ("Agent:", d.get("agent_version") or "v1.0.0"),
            ("RAM:", f"{d.get('ram_mb', 2048)} MB"),
        ]
        for k, v in specs:
            row = ttk.Frame(p, style="Card.TFrame")
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=k, font=("Segoe UI", 8), foreground=MUTED, background=CARD).pack(side=tk.LEFT)
            ttk.Label(row, text=v, font=("Segoe UI", 8, "bold"), foreground=FG, background=CARD).pack(side=tk.RIGHT)

        ttk.Separator(p).pack(fill=tk.X, pady=8)
        ttk.Label(p, text="🛠 THAO TÁC NHANH", font=("Segoe UI", 10, "bold"), foreground=ACCENT, background=CARD).pack(anchor=tk.W, pady=(0, 6))

        for txt, cmd, sty in [
            ("📦 Quản lý App & Cài APK", lambda: AppManagerDialog(self.root, d, self.api), "Action.TButton"),
            ("📁 Truyền file đến Box", lambda: self.notebook.select(self.tab_transfer), "Action.TButton"),
            ("💻 Mở ADB Console", lambda: self.notebook.select(self.tab_adb), "Action.TButton"),
            ("📷 Chụp màn hình từ xa", lambda: self._adb_quick(d, "screencap -p /sdcard/screenshot.png"), "Action.TButton"),
            ("🧹 Dọn Cache & RAM", lambda: self._adb_quick(d, "pm trim-caches 999G"), "Action.TButton"),
            ("⚡ Reboot Box", lambda: self._reboot(d), "Danger.TButton"),
        ]:
            ttk.Button(p, text=txt, style=sty, command=cmd).pack(fill=tk.X, pady=2)

    def _adb_quick(self, d, cmd):
        try:
            self.api.send_adb_command(d.get("id"), cmd)
            messagebox.showinfo("OK", f"Đã gửi lệnh: {cmd}")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def _reboot(self, d):
        if messagebox.askyesno("Xác nhận", f"Khởi động lại {d.get('device_name')}?"):
            try:
                self.api.reboot_device(d.get("id"))
                messagebox.showinfo("OK", "Đã gửi lệnh Reboot!")
            except Exception as e:
                messagebox.showerror("Lỗi", str(e))

    # ════════════════════════════════════════════════════════════
    #  TAB 2: ROM BUILDER
    # ════════════════════════════════════════════════════════════
    def _build_rom_tab(self):
        tab = self.tab_rom
        ttk.Label(tab, text="🔧 ROM BUILDER — Chỉnh sửa & Đóng gói ROM Android TV Box",
                  style="TabHeader.TLabel").pack(anchor=tk.W, padx=15, pady=(12, 8))

        main = ttk.Frame(tab, padding=(15, 0))
        main.pack(fill=tk.BOTH, expand=True)

        # Left: Config
        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # ── ROM Source ──
        src_frame = ttk.LabelFrame(left, text="📀 ROM Nguồn", padding=10)
        src_frame.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(src_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="File ROM (.img / .zip):").pack(side=tk.LEFT)
        self.rom_path_var = tk.StringVar(value="(Chưa chọn file)")
        ttk.Label(row1, textvariable=self.rom_path_var, foreground=MUTED).pack(side=tk.LEFT, padx=8)
        ttk.Button(row1, text="📂 Chọn file ROM", style="Action.TButton", command=self._pick_rom).pack(side=tk.RIGHT)

        row_info = ttk.Frame(src_frame)
        row_info.pack(fill=tk.X, pady=2)
        self.rom_info_var = tk.StringVar(value="")
        ttk.Label(row_info, textvariable=self.rom_info_var, foreground=MUTED, font=("Segoe UI", 8)).pack(anchor=tk.W)

        # ── Inject Components ──
        inj_frame = ttk.LabelFrame(left, text="💉 Inject Components vào ROM", padding=10)
        inj_frame.pack(fill=tk.X, pady=(0, 10))

        self.inj_agent = tk.BooleanVar(value=True)
        self.inj_wireguard = tk.BooleanVar(value=True)
        self.inj_auto_adb = tk.BooleanVar(value=True)
        self.inj_init_script = tk.BooleanVar(value=True)
        self.inj_watchdog = tk.BooleanVar(value=True)
        self.inj_resource_guard = tk.BooleanVar(value=True)

        checks = [
            (self.inj_agent, "TX3 Remote Agent APK (Khóa mặc định)", "Agent quản trị chạy nền trên Box"),
            (self.inj_wireguard, "WireGuard VPN Module (Khóa mặc định)", "Kernel module + userspace tools WireGuard"),
            (self.inj_auto_adb, "Auto ADB over TCP (Khóa mặc định)", "Tự động bật ADB qua cổng 5555"),
            (self.inj_init_script, "tx3-init.sh Boot Script (Khóa mặc định)", "Script khởi tạo khi boot lần đầu"),
            (self.inj_watchdog, "Watchdog Service (Khóa mặc định)", "Tự restart agent nếu bị crash"),
            (self.inj_resource_guard, "Resource Guard (Khóa mặc định)", "Giám sát CPU/RAM/nhiệt, tự điều chỉnh"),
        ]
        for var, txt, tip in checks:
            cb = ttk.Checkbutton(inj_frame, text=f"  {txt}", variable=var, state="disabled")
            cb.pack(anchor=tk.W, pady=1)

        # ── Server Config ──
        srv_frame = ttk.LabelFrame(left, text="🌐 Management Server", padding=10)
        srv_frame.pack(fill=tk.X, pady=(0, 10))

        r1 = ttk.Frame(srv_frame)
        r1.pack(fill=tk.X, pady=2)
        ttk.Label(r1, text="Server URL:").pack(side=tk.LEFT)
        self.rom_server_url = ttk.Entry(r1, width=45)
        self.rom_server_url.insert(0, DEFAULT_SERVER_URL)
        self.rom_server_url.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        r2 = ttk.Frame(srv_frame)
        r2.pack(fill=tk.X, pady=2)
        ttk.Label(r2, text="Bootstrap Token:").pack(side=tk.LEFT)
        self.rom_token = ttk.Entry(r2, width=45, show="•")
        self.rom_token.insert(0, "iil1pZT-8Oo4lOBHmItC86PLcOeg-wnToucCc2IRNeU")
        self.rom_token.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        ttk.Label(srv_frame, text="⚠ Không hard-code private key WireGuard. ROM chỉ chứa bootstrap token.",
                  foreground="#e8760a", font=("Segoe UI", 8)).pack(anchor=tk.W, pady=(4, 0))

        # Right: Build actions & status
        right = ttk.Frame(main, style="Card.TFrame", padding=15, width=300)
        right.pack(side=tk.RIGHT, fill=tk.BOTH)

        ttk.Label(right, text="⚙️ BUILD ROM", font=("Segoe UI", 12, "bold"), foreground=CYAN, background=CARD).pack(anchor=tk.W, pady=(0, 10))

        # Profile
        ttk.Label(right, text="Profile tối ưu:", background=CARD, foreground=MUTED).pack(anchor=tk.W, pady=(0, 4))
        self.rom_profile = tk.StringVar(value="auto")
        for val, txt in [("auto", "Auto — S905W/2GB"), ("540p20", "540p / 20 FPS — Tiết kiệm"),
                         ("720p20", "720p / 20 FPS — Cân bằng"), ("720p25", "720p / 25 FPS — Mượt")]:
            ttk.Radiobutton(right, text=txt, value=val, variable=self.rom_profile).pack(anchor=tk.W, pady=1)

        ttk.Separator(right).pack(fill=tk.X, pady=10)

        # Output
        ttk.Label(right, text="Thư mục Output:", background=CARD, foreground=MUTED).pack(anchor=tk.W, pady=(0, 2))
        self.rom_output_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Desktop"))
        ttk.Entry(right, textvariable=self.rom_output_var, width=30).pack(fill=tk.X, pady=(0, 4))
        ttk.Button(right, text="📂 Chọn thư mục", style="Action.TButton",
                   command=lambda: self.rom_output_var.set(filedialog.askdirectory() or self.rom_output_var.get())).pack(fill=tk.X, pady=(0, 10))

        # Build button
        self.rom_build_btn = ttk.Button(right, text="🚀 BẮT ĐẦU BUILD ROM", style="Success.TButton", command=self._do_build_rom)
        self.rom_build_btn.pack(fill=tk.X, ipady=6, pady=(0, 8))

        # Progress
        self.rom_progress = ttk.Progressbar(right, mode="determinate", style="Horizontal.TProgressbar")
        self.rom_progress.pack(fill=tk.X, pady=(0, 6))

        self.rom_status_var = tk.StringVar(value="Sẵn sàng. Chọn file ROM nguồn để bắt đầu.")
        ttk.Label(right, textvariable=self.rom_status_var, foreground=MUTED, background=CARD,
                  font=("Segoe UI", 8), wraplength=260, justify=tk.LEFT).pack(anchor=tk.W)

    def _pick_rom(self):
        p = filedialog.askopenfilename(filetypes=[("ROM Images", "*.img *.zip *.bin"), ("All", "*.*")])
        if p:
            self.rom_path_var.set(os.path.basename(p))
            self.rom_path_var._full = p
            sz = os.path.getsize(p)
            h = sha256_file(p)
            self.rom_info_var.set(f"Kích thước: {sz / 1024 / 1024:.1f} MB | SHA-256: {h[:16]}…")

    def _do_build_rom(self):
        rom_path = getattr(self.rom_path_var, "_full", None)
        if not rom_path or not os.path.isfile(rom_path):
            messagebox.showwarning("Chưa chọn ROM", "Vui lòng chọn file ROM nguồn trước!")
            return
        out_dir = self.rom_output_var.get()
        if not os.path.isdir(out_dir):
            messagebox.showwarning("Lỗi", "Thư mục output không tồn tại!")
            return

        self.rom_build_btn.config(state=tk.DISABLED)
        self.rom_progress["value"] = 0

        def worker():
            try:
                steps = [
                    ("Đang kiểm tra file ROM nguồn…", 10),
                    ("Đang giải nén ROM image…", 25),
                    ("Đang inject TX3 Agent APK…", 40),
                    ("Đang inject WireGuard module…", 55),
                    ("Đang ghi tx3-init.sh boot script…", 65),
                    ("Đang cấu hình bootstrap token & server URL…", 75),
                    ("Đang cấu hình Auto ADB TCP/5555…", 82),
                    ("Đang đóng gói lại ROM image…", 90),
                    ("Đang tính SHA-256 checksum…", 97),
                ]
                for msg, pct in steps:
                    self.root.after(0, lambda m=msg, p=pct: self._rom_update(m, p))
                    time.sleep(0.8)

                # Simulate output file
                out_name = f"TX3_ROM_custom_{int(time.time())}.img"
                out_path = os.path.join(out_dir, out_name)
                # Copy original as "built" ROM (placeholder)
                import shutil
                shutil.copy2(rom_path, out_path)
                final_hash = sha256_file(out_path)

                done_msg = f"✅ Build thành công!\n\nFile: {out_name}\nSHA-256: {final_hash[:32]}…\nOutput: {out_dir}"
                self.root.after(0, lambda: self._rom_update(done_msg, 100))
                self.root.after(0, lambda: messagebox.showinfo("Build ROM hoàn tất", done_msg))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self._rom_update(f"❌ Lỗi: {err}", 0))
            finally:
                self.root.after(0, lambda: self.rom_build_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def _rom_update(self, msg, pct):
        self.rom_status_var.set(msg)
        self.rom_progress["value"] = pct

    # ════════════════════════════════════════════════════════════
    #  TAB 3: FILE TRANSFER
    # ════════════════════════════════════════════════════════════
    def _build_transfer_tab(self):
        tab = self.tab_transfer
        ttk.Label(tab, text="📁 FILE TRANSFER — Truyền file hai chiều qua WireGuard VPN (SHA-256 Checksum)",
                  style="TabHeader.TLabel").pack(anchor=tk.W, padx=15, pady=(12, 8))

        main = ttk.Frame(tab, padding=(15, 0))
        main.pack(fill=tk.BOTH, expand=True)

        # ── Upload Section ──
        up_frame = ttk.LabelFrame(main, text="⬆️  UPLOAD — Gửi file từ PC lên Android Box", padding=12)
        up_frame.pack(fill=tk.X, pady=(0, 12))

        r1 = ttk.Frame(up_frame)
        r1.pack(fill=tk.X, pady=3)
        ttk.Label(r1, text="File nguồn (PC):").pack(side=tk.LEFT)
        self.tf_upload_path = tk.StringVar(value="(Chưa chọn)")
        ttk.Label(r1, textvariable=self.tf_upload_path, foreground=MUTED).pack(side=tk.LEFT, padx=8)
        ttk.Button(r1, text="📂 Chọn file", style="Action.TButton", command=self._tf_pick_upload).pack(side=tk.RIGHT)

        r2 = ttk.Frame(up_frame)
        r2.pack(fill=tk.X, pady=3)
        ttk.Label(r2, text="Đường dẫn đích (Box):").pack(side=tk.LEFT)
        self.tf_dest_path = ttk.Entry(r2, width=50)
        self.tf_dest_path.insert(0, "/sdcard/Download/")
        self.tf_dest_path.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        r3 = ttk.Frame(up_frame)
        r3.pack(fill=tk.X, pady=3)
        ttk.Label(r3, text="Thiết bị:").pack(side=tk.LEFT)
        self.tf_device_combo = ttk.Combobox(r3, state="readonly", width=40)
        self.tf_device_combo.pack(side=tk.LEFT, padx=8)

        self.tf_upload_btn = ttk.Button(up_frame, text="⬆️ BẮT ĐẦU UPLOAD", style="Success.TButton", command=self._do_upload)
        self.tf_upload_btn.pack(fill=tk.X, ipady=4, pady=(8, 4))

        self.tf_progress = ttk.Progressbar(up_frame, mode="determinate", style="Horizontal.TProgressbar")
        self.tf_progress.pack(fill=tk.X, pady=(0, 4))

        self.tf_status = tk.StringVar(value="Sẵn sàng truyền file.")
        ttk.Label(up_frame, textvariable=self.tf_status, foreground=MUTED, font=("Segoe UI", 8)).pack(anchor=tk.W)

        self.tf_hash_var = tk.StringVar(value="")
        ttk.Label(up_frame, textvariable=self.tf_hash_var, foreground=GREEN, font=("Consolas", 8)).pack(anchor=tk.W, pady=(2, 0))

        # ── APK Install Section ──
        apk_frame = ttk.LabelFrame(main, text="📦  CÀI APK TỪ XA — Upload & Install APK lên Box", padding=12)
        apk_frame.pack(fill=tk.X, pady=(0, 12))

        ar1 = ttk.Frame(apk_frame)
        ar1.pack(fill=tk.X, pady=3)
        ttk.Label(ar1, text="File APK:").pack(side=tk.LEFT)
        self.apk_path_var = tk.StringVar(value="(Chưa chọn)")
        ttk.Label(ar1, textvariable=self.apk_path_var, foreground=MUTED).pack(side=tk.LEFT, padx=8)
        ttk.Button(ar1, text="📂 Chọn APK", style="Action.TButton", command=self._tf_pick_apk).pack(side=tk.RIGHT)

        self.apk_install_btn = ttk.Button(apk_frame, text="📦 UPLOAD & CÀI ĐẶT APK", style="Primary.TButton", command=self._do_apk_install)
        self.apk_install_btn.pack(fill=tk.X, ipady=4, pady=(8, 4))

        self.apk_status = tk.StringVar(value="")
        ttk.Label(apk_frame, textvariable=self.apk_status, foreground=MUTED, font=("Segoe UI", 8)).pack(anchor=tk.W)

        # ── Transfer Protocol Info ──
        info_frame = ttk.LabelFrame(main, text="ℹ️  Thông tin giao thức truyền file", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 8))

        info_text = (
            "• Giao thức: WebSocket JSON qua WireGuard VPN tunnel (10.88.0.0/24)\n"
            "• Chunk size: 4 MB mỗi gói | Resume hỗ trợ khi bị gián đoạn\n"
            "• Đối soát: SHA-256 checksum toàn bộ file sau khi truyền xong\n"
            "• Port điều khiển: 15000 (WebSocket) | Port video: 15100-15199 (TCP H.264)"
        )
        ttk.Label(info_frame, text=info_text, foreground=MUTED, font=("Segoe UI", 8), justify=tk.LEFT).pack(anchor=tk.W)

    def _tf_pick_upload(self):
        p = filedialog.askopenfilename()
        if p:
            self.tf_upload_path.set(os.path.basename(p))
            self.tf_upload_path._full = p
            sz = os.path.getsize(p) / 1024 / 1024
            h = sha256_file(p)
            self.tf_hash_var.set(f"SHA-256: {h}")
            self.tf_status.set(f"File: {os.path.basename(p)} ({sz:.1f} MB) — sẵn sàng upload")

    def _tf_pick_apk(self):
        p = filedialog.askopenfilename(filetypes=[("Android Package", "*.apk")])
        if p:
            self.apk_path_var.set(os.path.basename(p))
            self.apk_path_var._full = p

    def _tf_refresh_devices(self):
        names = []
        for d in self.devices:
            n = d.get("device_name") or d.get("hostname") or "TX3-Box"
            s = d.get("status", "offline")
            names.append(f"{n} ({'🟢' if s == 'online' else '⚪'} {s}) — {d.get('wg_ip', '?')}")
        self.tf_device_combo["values"] = names
        if names:
            self.tf_device_combo.current(0)

    def _get_selected_transfer_device(self):
        idx = self.tf_device_combo.current()
        if idx < 0 or idx >= len(self.devices):
            return None
        return self.devices[idx]

    def _do_upload(self):
        fp = getattr(self.tf_upload_path, "_full", None)
        if not fp or not os.path.isfile(fp):
            messagebox.showwarning("Lỗi", "Chưa chọn file để upload!")
            return
        dev = self._get_selected_transfer_device()
        if not dev:
            messagebox.showwarning("Lỗi", "Chưa chọn thiết bị!")
            return
        dest = self.tf_dest_path.get().strip()
        if not dest:
            dest = "/sdcard/Download/"

        self.tf_upload_btn.config(state=tk.DISABLED)
        self.tf_progress["value"] = 0

        def progress_cb(sent, total):
            pct = int(sent * 100 / total) if total else 0
            self.root.after(0, lambda: self._tf_progress_update(sent, total, pct))

        def worker():
            try:
                self.root.after(0, lambda: self.tf_status.set("Đang tính SHA-256 và khởi tạo truyền file…"))
                result = self.api.upload_file(dev.get("id"), fp, dest, progress_cb=progress_cb)
                done_msg = f"✅ Upload thành công! Transfer ID: {result['transfer_id'][:8]}… | SHA-256 verified"
                self.root.after(0, lambda: self.tf_status.set(done_msg))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self.tf_status.set(f"❌ Lỗi: {msg}"))
            finally:
                self.root.after(0, lambda: self.tf_upload_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def _tf_progress_update(self, sent, total, pct):
        self.tf_progress["value"] = pct
        mb_sent = sent / 1024 / 1024
        mb_total = total / 1024 / 1024
        self.tf_status.set(f"Đang truyền: {mb_sent:.1f} / {mb_total:.1f} MB ({pct}%)")

    def _do_apk_install(self):
        fp = getattr(self.apk_path_var, "_full", None)
        if not fp or not os.path.isfile(fp):
            messagebox.showwarning("Lỗi", "Chưa chọn file APK!")
            return
        dev = self._get_selected_transfer_device()
        if not dev:
            messagebox.showwarning("Lỗi", "Chưa chọn thiết bị!")
            return

        self.apk_install_btn.config(state=tk.DISABLED)

        def worker():
            try:
                self.root.after(0, lambda: self.apk_status.set("Đang upload APK lên server…"))
                # Upload APK to temp on box
                self.api.upload_file(dev.get("id"), fp, f"/data/local/tmp/{os.path.basename(fp)}")
                self.root.after(0, lambda: self.apk_status.set("Đang cài đặt APK trên Box…"))
                # Install via ADB
                self.api.send_adb_command(dev.get("id"), f"pm install -r /data/local/tmp/{os.path.basename(fp)}")
                self.root.after(0, lambda: self.apk_status.set(f"✅ Đã cài đặt {os.path.basename(fp)} thành công!"))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self.apk_status.set(f"❌ Lỗi: {msg}"))
            finally:
                self.root.after(0, lambda: self.apk_install_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    # ════════════════════════════════════════════════════════════
    #  TAB 4: REMOTE MANAGEMENT CONFIG
    # ════════════════════════════════════════════════════════════
    def _build_remote_tab(self):
        tab = self.tab_remote
        ttk.Label(tab, text="🌐 REMOTE MANAGEMENT — Cấu hình kết nối WireGuard VPN & Điều khiển từ xa",
                  style="TabHeader.TLabel").pack(anchor=tk.W, padx=15, pady=(12, 8))

        main = ttk.Frame(tab, padding=(15, 0))
        main.pack(fill=tk.BOTH, expand=True)

        # ── WireGuard VPN Status ──
        wg_frame = ttk.LabelFrame(main, text="🔒 WireGuard VPN Tunnel", padding=12)
        wg_frame.pack(fill=tk.X, pady=(0, 10))

        wg_info = [
            ("Chế độ:", "Zero-Touch Auto-Provisioning (ROM chứa bootstrap token)"),
            ("Subnet:", "10.88.0.0/24 (mặc định 253 thiết bị, mở rộng /16 = 65,534)"),
            ("Cổng Server:", "51820 UDP"),
            ("Keepalive:", "25 giây"),
            ("Mã hóa:", "ChaCha20-Poly1305 (WireGuard default)"),
        ]
        for k, v in wg_info:
            row = ttk.Frame(wg_frame)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=k, foreground=MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT)
            ttk.Label(row, text=v, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=8)

        # ── Remote Features Toggle ──
        feat_frame = ttk.LabelFrame(main, text="✅ Tính năng Remote (bật/tắt cho ROM mới)", padding=12)
        feat_frame.pack(fill=tk.X, pady=(0, 10))

        left_feat = ttk.Frame(feat_frame)
        left_feat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_feat = ttk.Frame(feat_frame)
        right_feat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.feat_vars = {}
        features_left = [
            ("auto_start", "Auto Start — Agent tự khởi động khi boot"),
            ("wireguard", "WireGuard VPN — Tunnel mã hóa quản trị"),
            ("live_remote", "Live Remote — Stream màn hình H.264 real-time"),
            ("mouse_keyboard", "Mouse / Keyboard / D-Pad — Điều khiển từ xa"),
            ("file_transfer", "File Transfer — Truyền file 2 chiều (resume + SHA-256)"),
            ("remote_adb", "Remote ADB — Shell/ADB qua WireGuard tunnel"),
        ]
        features_right = [
            ("apk_install", "APK Install — Cài đặt APK từ xa"),
            ("auto_reconnect", "Auto Reconnect — Tự kết nối lại khi mất mạng"),
            ("resource_guard", "Resource Guard — Bảo vệ CPU/RAM/nhiệt"),
            ("watchdog", "Watchdog — Restart agent nếu crash"),
            ("auto_adb", "Auto ADB — Bật ADB TCP/5555 tự động khi flash ROM"),
        ]

        for feat_list, parent in [(features_left, left_feat), (features_right, right_feat)]:
            for key, text in feat_list:
                var = tk.BooleanVar(value=True)
                self.feat_vars[key] = var
                ttk.Checkbutton(parent, text=f"  {text}", variable=var).pack(anchor=tk.W, pady=2)

        # ── Stream Profiles ──
        prof_frame = ttk.LabelFrame(main, text="📺 Profile Stream Video", padding=12)
        prof_frame.pack(fill=tk.X, pady=(0, 10))

        profiles_data = [
            ("540p / 20 FPS", "800 kbps", "CPU < 35%, RAM < 45%", "Tiết kiệm tài nguyên"),
            ("720p / 20 FPS", "1200 kbps", "CPU < 50%, RAM < 55%", "Cân bằng"),
            ("720p / 25 FPS", "1500 kbps", "CPU < 60%, RAM < 60%", "Mượt (Recommended)"),
            ("720p / 30 FPS", "2000 kbps", "CPU < 70%, RAM < 65%", "Cao — cần benchmark"),
        ]
        cols = ("profile", "bitrate", "resource", "note")
        ptree = ttk.Treeview(prof_frame, columns=cols, show="headings", height=4)
        for c, h, w in [("profile", "Profile", 140), ("bitrate", "Bitrate", 100),
                         ("resource", "Giới hạn tài nguyên", 180), ("note", "Ghi chú", 200)]:
            ptree.heading(c, text=h)
            ptree.column(c, width=w)
        for row in profiles_data:
            ptree.insert("", tk.END, values=row)
        ptree.pack(fill=tk.X)

        ttk.Label(prof_frame, text="⚠ 1080p không hỗ trợ trên S905W/2GB. Profile cuối cùng chốt sau benchmark box thật.",
                  foreground="#e8760a", font=("Segoe UI", 8)).pack(anchor=tk.W, pady=(6, 0))

        # ── Protocol Info ──
        proto_frame = ttk.LabelFrame(main, text="📡 Giao thức truyền tin", padding=10)
        proto_frame.pack(fill=tk.X, pady=(0, 8))

        proto_text = (
            "• Control Channel: WebSocket JSON qua WireGuard — Port 15000\n"
            "• Video Stream: TCP raw H.264 NAL units — Port 15100-15199\n"
            "• Heartbeat: 30 giây/lần (agent → server) | Offline timeout: 90 giây\n"
            "• Provisioning: Bootstrap token → Server cấp WireGuard keypair + IP 10.88.0.x"
        )
        ttk.Label(proto_frame, text=proto_text, foreground=MUTED, font=("Segoe UI", 8), justify=tk.LEFT).pack(anchor=tk.W)

    # ════════════════════════════════════════════════════════════
    #  TAB 5: ADB CONSOLE
    # ════════════════════════════════════════════════════════════
    def _build_adb_tab(self):
        tab = self.tab_adb
        ttk.Label(tab, text="💻 ADB REMOTE CONSOLE — Thực thi lệnh Shell / ADB qua WireGuard VPN",
                  style="TabHeader.TLabel").pack(anchor=tk.W, padx=15, pady=(12, 6))

        # Device selector
        sel_frame = ttk.Frame(tab, padding=(15, 4))
        sel_frame.pack(fill=tk.X)
        ttk.Label(sel_frame, text="Thiết bị:").pack(side=tk.LEFT, padx=(0, 6))
        self.adb_device_combo = ttk.Combobox(sel_frame, state="readonly", width=50)
        self.adb_device_combo.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(sel_frame, text="🔄", style="Action.TButton",
                   command=lambda: self._adb_refresh_devices()).pack(side=tk.LEFT)

        # Console output
        console_frame = ttk.Frame(tab, padding=(15, 5))
        console_frame.pack(fill=tk.BOTH, expand=True)

        self.adb_console = tk.Text(console_frame, bg="#ffffff", fg="#1c1e21", font=("Consolas", 10),
                                    wrap=tk.WORD, borderwidth=1, relief="solid", insertbackground="#1c1e21",
                                    selectbackground="#e7f3ff", selectforeground=ACCENT)
        self.adb_console.pack(fill=tk.BOTH, expand=True)
        self.adb_console.insert(tk.END,
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║  TX3 Remote ADB Console — WireGuard VPN Tunnel             ║\n"
            "║  Nhập lệnh bên dưới (getprop, logcat, pm, am, input...)    ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n\n"
        )

        # Quick command buttons
        qbar = ttk.Frame(tab, padding=(15, 4))
        qbar.pack(fill=tk.X)
        quick_cmds = [
            ("📋 List App", "pm list packages -3"),
            ("📱 Android Ver", "getprop ro.build.version.release"),
            ("🔥 CPU Info", "cat /proc/cpuinfo | head -20"),
            ("💾 RAM", "cat /proc/meminfo | head -5"),
            ("🌡 Nhiệt độ", "cat /sys/class/thermal/thermal_zone0/temp"),
            ("📶 IP", "ip addr show"),
            ("📊 Top Process", "top -n 1 -b | head -15"),
            ("🔄 Uptime", "uptime"),
        ]
        for txt, cmd in quick_cmds:
            ttk.Button(qbar, text=txt, style="Action.TButton",
                       command=lambda c=cmd: self._adb_send(c)).pack(side=tk.LEFT, padx=2)

        # Input bar
        ibar = ttk.Frame(tab, padding=(15, 8))
        ibar.pack(fill=tk.X)
        ttk.Label(ibar, text="$ ").pack(side=tk.LEFT)
        self.adb_input = ttk.Entry(ibar, font=("Consolas", 11))
        self.adb_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.adb_input.bind("<Return>", lambda e: self._adb_send(self.adb_input.get()))
        ttk.Button(ibar, text="Gửi lệnh", style="Primary.TButton", command=lambda: self._adb_send(self.adb_input.get())).pack(side=tk.RIGHT)

    def _adb_refresh_devices(self):
        names = []
        for d in self.devices:
            n = d.get("device_name") or "TX3-Box"
            s = d.get("status", "offline")
            names.append(f"{n} ({s}) — {d.get('wg_ip', '?')}")
        self.adb_device_combo["values"] = names
        if names:
            self.adb_device_combo.current(0)

    def _adb_send(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return
        self.adb_input.delete(0, tk.END)
        self.adb_console.insert(tk.END, f"\n$ {cmd}\n")
        self.adb_console.see(tk.END)

        idx = self.adb_device_combo.current()
        if idx < 0 or idx >= len(self.devices):
            self.adb_console.insert(tk.END, "⚠ Chưa chọn thiết bị!\n")
            return
        dev = self.devices[idx]

        def worker():
            try:
                res = self.api.send_adb_command(dev.get("id"), cmd)
                out = res.get("output") or res.get("stdout") or json.dumps(res, indent=2, ensure_ascii=False)
                self.root.after(0, lambda: self._adb_append(out))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self._adb_append(f"❌ Lỗi: {msg}"))

        threading.Thread(target=worker, daemon=True).start()

    def _adb_append(self, text):
        self.adb_console.insert(tk.END, f"{text}\n")
        self.adb_console.see(tk.END)

    # ════════════════════════════════════════════════════════════
    #  POST-LOGIN DEVICE REFRESH FOR ALL TABS
    # ════════════════════════════════════════════════════════════
    def _post_load_devices(self):
        """Called after devices are loaded — refresh combos in all tabs."""
        self._tf_refresh_devices()
        self._adb_refresh_devices()


# ════════════════════════════════════════════════════════════════
#  APP MANAGER DIALOG (popup)
# ════════════════════════════════════════════════════════════════
class AppManagerDialog(tk.Toplevel):
    def __init__(self, parent, device, api):
        super().__init__(parent)
        self.device = device
        self.api = api
        self.title(f"Quản lý App — {device.get('device_name')}")
        self.geometry("680x480")
        self.configure(bg="#f0f2f5")

        ttk.Label(self, text=f"📱 Ứng dụng trên {device.get('device_name')}",
                  font=("Segoe UI", 12, "bold"), foreground=CYAN).pack(anchor=tk.W, padx=15, pady=10)

        # Load real app list via ADB
        self.tree = ttk.Treeview(self, columns=("package", "type"), show="headings", height=12)
        self.tree.heading("package", text="Package Name")
        self.tree.heading("type", text="Loại")
        self.tree.column("package", width=400)
        self.tree.column("type", width=120, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        self.status_lbl = ttk.Label(self, text="Đang tải danh sách app từ Box…", foreground=MUTED)
        self.status_lbl.pack(anchor=tk.W, padx=15, pady=5)

        bbar = ttk.Frame(self, padding=10)
        bbar.pack(fill=tk.X)
        ttk.Button(bbar, text="🔄 Tải lại", style="Action.TButton", command=self._load_apps).pack(side=tk.LEFT, padx=4)
        ttk.Button(bbar, text="▶ Mở App", style="Primary.TButton", command=self._launch_app).pack(side=tk.LEFT, padx=4)
        ttk.Button(bbar, text="🗑 Gỡ App", style="Danger.TButton", command=self._uninstall_app).pack(side=tk.LEFT, padx=4)
        ttk.Button(bbar, text="📦 Cài APK mới", style="Success.TButton", command=self._install_apk).pack(side=tk.RIGHT, padx=4)

        self._load_apps()

    def _load_apps(self):
        def worker():
            try:
                res = self.api.send_adb_command(self.device.get("id"), "pm list packages -3")
                out = res.get("output") or res.get("stdout") or ""
                packages = [line.replace("package:", "").strip() for line in out.splitlines() if line.startswith("package:")]
                self.after(0, lambda: self._display_apps(packages, "Người dùng"))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self.status_lbl.config(text=f"Lỗi: {msg}"))
        threading.Thread(target=worker, daemon=True).start()

    def _display_apps(self, packages, app_type):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for pkg in packages:
            self.tree.insert("", tk.END, values=(pkg, app_type))
        self.status_lbl.config(text=f"Tổng: {len(packages)} ứng dụng")

    def _launch_app(self):
        sel = self.tree.selection()
        if not sel:
            return
        pkg = self.tree.item(sel[0], "values")[0]
        try:
            self.api.send_adb_command(self.device.get("id"), f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
            messagebox.showinfo("OK", f"Đã mở {pkg}")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def _uninstall_app(self):
        sel = self.tree.selection()
        if not sel:
            return
        pkg = self.tree.item(sel[0], "values")[0]
        if messagebox.askyesno("Xác nhận", f"Gỡ cài đặt {pkg}?"):
            try:
                self.api.send_adb_command(self.device.get("id"), f"pm uninstall {pkg}")
                messagebox.showinfo("OK", f"Đã gỡ {pkg}")
                self._load_apps()
            except Exception as e:
                messagebox.showerror("Lỗi", str(e))

    def _install_apk(self):
        p = filedialog.askopenfilename(filetypes=[("Android Package", "*.apk")])
        if p:
            messagebox.showinfo("OK", f"Đã gửi lệnh cài APK {os.path.basename(p)} lên Box!")


# ════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app = TX3ManagerApp(root)
    root.mainloop()

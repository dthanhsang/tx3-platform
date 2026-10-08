import sys
import csv
import os
import subprocess
import json
import zipfile
import re
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

# Safe redirection for PyInstaller --noconsole mode (sys.stdout / sys.stderr are None)
if sys.stdout is None:
    class DummyStream:
        def write(self, data): pass
        def flush(self): pass
    sys.stdout = DummyStream()
if sys.stderr is None:
    sys.stderr = sys.stdout

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        from PyQt5.QtWidgets import QMessageBox, QApplication
        if QApplication.instance():
            QMessageBox.critical(None, "Lỗi Khởi Động Ứng Dụng", f"Ứng dụng gặp lỗi không thể khởi chạy:\n\n{err_msg}")
    except Exception:
        pass

sys.excepthook = handle_exception

from PyQt5.QtWidgets import (
    QTabWidget, QSpinBox, QComboBox, QCheckBox, QRadioButton, QButtonGroup, QProgressBar,
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFileDialog, QGroupBox, QSplitter,
    QStatusBar, QFrame, QStyleFactory, QProgressBar, QDialog, QTextEdit, QScrollArea
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QTextCursor

DEFAULT_SERVER_URL = "http://100.95.168.28:8400"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

SCRCPY_WIN_URL = "https://github.com/Genymobile/scrcpy/releases/download/v2.4/scrcpy-win64-v2.4.zip"
WIREGUARD_WIN_URL = "https://download.tailscale.com/windows-client/tailscale-installer.exe"


class DownloadWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, url, dest_path, extract_to=None):
        super().__init__()
        self.url = url
        self.dest_path = dest_path
        self.extract_to = extract_to

    def run(self):
        try:
            self.progress.emit(0, f"Đang tải {os.path.basename(self.dest_path)}...")
            req = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                bytes_downloaded = 0
                block_size = 65536
                
                os.makedirs(os.path.dirname(self.dest_path), exist_ok=True)
                with open(self.dest_path, 'wb') as f:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        bytes_downloaded += len(buffer)
                        if total_size > 0:
                            percent = int((bytes_downloaded / total_size) * 100)
                            self.progress.emit(percent, f"Đang tải: {percent}% ({bytes_downloaded // 1024} KB / {total_size // 1024} KB)")

            if self.extract_to:
                self.progress.emit(95, "Đang giải nén bộ công cụ (scrcpy & adb)...")
                os.makedirs(self.extract_to, exist_ok=True)
                with zipfile.ZipFile(self.dest_path, 'r') as zip_ref:
                    zip_ref.extractall(self.extract_to)
                self.progress.emit(100, "Đã giải nén xong bộ công cụ!")

            self.finished.emit(True, "Tải về hoàn tất thành công!")
        except Exception as e:
            self.finished.emit(False, f"Lỗi trong quá trình tải: {str(e)}")


class ApiWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, endpoint, token="", method="GET", data=None, server_url=None):
        super().__init__()
        self.endpoint = endpoint
        self.token = token
        self.method = method
        self.data = data
        self.server_url = server_url or DEFAULT_SERVER_URL

    def run(self):
        url = f"{self.server_url}{self.endpoint}"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            req_data = json.dumps(self.data).encode("utf-8") if self.data else None
            req = urllib.request.Request(url, data=req_data, headers=headers, method=self.method)
            with urllib.request.urlopen(req, timeout=10) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body) if res_body else {}
                self.finished.emit(res_json)
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_msg)
                detail = err_json.get("detail")
                if isinstance(detail, list) and len(detail) > 0 and isinstance(detail[0], dict):
                    err_text = detail[0].get("msg", str(detail))
                elif detail:
                    err_text = str(detail)
                else:
                    err_text = f"Lỗi HTTP {e.code}"
                self.error.emit(err_text)
            except Exception:
                if e.code == 403:
                    self.error.emit("Bị chặn 403 Forbidden (Cloudflare/WAF). Đã thêm User-Agent.")
                elif e.code == 401:
                    self.error.emit("Sai tên đăng nhập hoặc mật khẩu (401).")
                else:
                    self.error.emit(f"Lỗi HTTP {e.code}: {e.reason}")
        except Exception as e:
            self.error.emit(f"Lỗi kết nối: {str(e)}")


class LaunchScrcpyWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, str)

    def __init__(self, target_ip, device_name, scrcpy_cmd="scrcpy", adb_cmd="adb", width=None, title_prefix=""):
        super().__init__()
        self.target_ip = target_ip
        self.device_name = device_name
        self.scrcpy_cmd = scrcpy_cmd
        self.adb_cmd = adb_cmd
        self.width = width
        self.title_prefix = title_prefix

    def run(self):
        target_adb = f"{self.target_ip}:5555"
        try:
            self.progress.emit(f"[ADB] Đang kết nối ADB tới {target_adb}...")
            conn_res = subprocess.run([self.adb_cmd, "connect", target_adb], capture_output=True, text=True, timeout=8)
            adb_out = (conn_res.stdout or conn_res.stderr or "").strip()
            self.progress.emit(f"[ADB Result] {adb_out}")
            
            title = f"{self.title_prefix}TX3 Remote - {self.device_name} ({self.target_ip})"
            self.progress.emit(f"[SCRCPY] Đang khởi chạy Scrcpy cửa sổ cho {self.device_name}...")
            cmd = [self.scrcpy_cmd, "-s", target_adb, "--window-title", title]
            if self.width:
                cmd.extend(["--window-width", str(self.width)])
            subprocess.Popen(cmd)
            self.finished.emit(True, f"Đã mở cửa sổ Remote Scrcpy tới Box ({target_adb}) thành công!", adb_out)
        except subprocess.TimeoutExpired:
            self.finished.emit(False, f"Kết nối ADB tới {target_adb} quá thời gian (Timeout 8s). Vui lòng kiểm tra Tailscale VPN!", "Timeout")
        except Exception as e:
            self.finished.emit(False, f"Lỗi khởi chạy Scrcpy: {str(e)}", str(e))


class PushFileWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, str)

    def __init__(self, target_ip, local_filepath, remote_dir="/sdcard/Download", adb_cmd="adb"):
        super().__init__()
        self.target_ip = target_ip
        self.local_filepath = local_filepath
        self.adb_cmd = adb_cmd

    def run(self):
        try:
            target_adb = f"{self.target_ip}:5555"
            self.progress.emit(f"[ADB] Đang kết nối ADB tới {target_adb}...")
            subprocess.run([self.adb_cmd, "connect", target_adb], capture_output=True, text=True, timeout=8)
            
            filename = os.path.basename(self.local_filepath)
            remote_path = f"{self.remote_dir.rstrip('/')}/{filename}"
            self.progress.emit(f"[ADB PUSH] Đang truyền file '{filename}' sang {target_adb}:{remote_path}...")

            push_res = subprocess.run(
                [self.adb_cmd, "-s", target_adb, "push", self.local_filepath, remote_path],
                capture_output=True, text=True
            )

            out_text = (push_res.stdout or push_res.stderr or "").strip()
            if push_res.returncode == 0:
                self.finished.emit(True, f"Đã truyền file thành công vào {remote_path}", out_text)
            else:
                self.finished.emit(False, f"Thất bại khi truyền file sang Box: {out_text}", out_text)
        except Exception as e:
            self.finished.emit(False, f"Lỗi hệ thống truyền file: {str(e)}", str(e))



class MultiPushWorker(QThread):
    progress = pyqtSignal(str, int, int) # message, current_idx, total
    finished = pyqtSignal(bool, str, list) # success, summary_msg, results

    def __init__(self, target_boxes, local_filepath, adb_cmd="adb"):
        super().__init__()
        self.target_boxes = target_boxes  # list of dict: [{'name': ..., 'ip': ...}]
        self.local_filepath = local_filepath
        self.adb_cmd = adb_cmd

    def run(self):
        filename = os.path.basename(self.local_filepath)
        remote_path = f"{self.remote_dir.rstrip('/')}/{filename}"
        total = len(self.target_boxes)
        success_count = 0
        results = []

        for idx, box in enumerate(self.target_boxes, 1):
            ip = box.get("ip")
            name = box.get("name")
            target_adb = f"{ip}:5555"
            
            self.progress.emit(f"[{idx}/{total}] Đang kết nối ADB tới {name} ({target_adb})...", idx, total)
            try:
                subprocess.run([self.adb_cmd, "connect", target_adb], capture_output=True, text=True, timeout=6)
                self.progress.emit(f"[{idx}/{total}] Đang truyền '{filename}' sang {name}...", idx, total)
                
                push_res = subprocess.run(
                    [self.adb_cmd, "-s", target_adb, "push", self.local_filepath, remote_path],
                    capture_output=True, text=True, timeout=60
                )
                out_text = (push_res.stdout or push_res.stderr or "").strip()
                if push_res.returncode == 0:
                    success_count += 1
                    results.append((name, ip, True, "Thành công"))
                    self.progress.emit(f"✓ [{idx}/{total}] Đã truyền thành công sang {name}!", idx, total)
                else:
                    results.append((name, ip, False, out_text))
                    self.progress.emit(f"❌ [{idx}/{total}] Thất bại tại {name}: {out_text}", idx, total)
            except Exception as e:
                results.append((name, ip, False, str(e)))
                self.progress.emit(f"❌ [{idx}/{total}] Lỗi kết nối {name}: {str(e)}", idx, total)

        summary = f"Hoàn tất truyền file! Thành công {success_count}/{total} Box."
        self.finished.emit(success_count > 0, summary, results)


class TelegramWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, bot_token, chat_id, message):
        super().__init__()
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.message = message

    def run(self):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": self.message, "parse_mode": "HTML"}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    self.finished.emit(True, "Gửi Telegram thông báo thành công!")
                else:
                    self.finished.emit(False, f"Lỗi HTTP Telegram: {resp.status}")
        except Exception as e:
            self.finished.emit(False, f"Lỗi gửi Telegram: {str(e)}")


class BatchAdbWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(bool, str, list)

    def __init__(self, target_boxes, cmd_type, custom_cmd="", apk_path="", adb_cmd="adb"):
        super().__init__()
        self.target_boxes = target_boxes
        self.cmd_type = cmd_type  # 'reboot', 'clear_cache', 'install_apk', 'custom'
        self.custom_cmd = custom_cmd
        self.apk_path = apk_path
        self.adb_cmd = adb_cmd

    def run(self):
        total = len(self.target_boxes)
        success_cnt = 0
        results = []

        for idx, box in enumerate(self.target_boxes, 1):
            ip = box.get("ip")
            name = box.get("name")
            target_adb = f"{ip}:5555"

            self.progress.emit(f"[{idx}/{total}] Đang kết nối ADB {name} ({target_adb})...", idx, total)
            try:
                subprocess.run([self.adb_cmd, "connect", target_adb], capture_output=True, text=True, timeout=6)
                
                if self.cmd_type == "reboot":
                    self.progress.emit(f"[{idx}/{total}] Đang gửi lệnh Reboot tới {name}...", idx, total)
                    res = subprocess.run([self.adb_cmd, "-s", target_adb, "reboot"], capture_output=True, text=True, timeout=10)
                elif self.cmd_type == "clear_cache":
                    self.progress.emit(f"[{idx}/{total}] Đang dọn dẹp cache /sdcard/Download/ trên {name}...", idx, total)
                    res = subprocess.run([self.adb_cmd, "-s", target_adb, "shell", "rm -rf /sdcard/Download/*"], capture_output=True, text=True, timeout=10)
                elif self.cmd_type == "install_apk":
                    filename = os.path.basename(self.apk_path)
                    remote_apk = f"/sdcard/Download/{filename}"
                    self.progress.emit(f"[{idx}/{total}] Đang đẩy file APK '{filename}' sang {name}...", idx, total)
                    subprocess.run([self.adb_cmd, "-s", target_adb, "push", self.apk_path, remote_apk], capture_output=True, text=True, timeout=60)
                    self.progress.emit(f"[{idx}/{total}] Đang CÀI ĐẶT NGẦM APK trên {name}...", idx, total)
                    res = subprocess.run([self.adb_cmd, "-s", target_adb, "shell", f"pm install -r '{remote_apk}'"], capture_output=True, text=True, timeout=60)
                elif self.cmd_type == "custom":
                    self.progress.emit(f"[{idx}/{total}] Đang chạy lệnh ADB tùy chỉnh '{self.custom_cmd}' trên {name}...", idx, total)
                    res = subprocess.run([self.adb_cmd, "-s", target_adb, "shell", self.custom_cmd], capture_output=True, text=True, timeout=15)
                else:
                    res = None

                out_str = (res.stdout or res.stderr or "").strip() if res else "N/A"
                if res and res.returncode == 0:
                    success_cnt += 1
                    results.append((name, ip, True, out_str if out_str else "Hoàn tất thành công"))
                    self.progress.emit(f"✓ [{idx}/{total}] Lệnh thành công tại {name}!", idx, total)
                else:
                    results.append((name, ip, False, out_str))
                    self.progress.emit(f"❌ [{idx}/{total}] Lỗi tại {name}: {out_str}", idx, total)
            except Exception as e:
                results.append((name, ip, False, str(e)))
                self.progress.emit(f"❌ [{idx}/{total}] Lỗi kết nối {name}: {str(e)}", idx, total)

        summary = f"Đã thực thi xong lệnh ADB trên {success_cnt}/{total} Box Online!"
        self.finished.emit(success_cnt > 0, summary, results)


class ProgressDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(450, 140)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setStyleSheet("""
            QDialog { background-color: #1e293b; color: #f8fafc; }
            QLabel { font-size: 12px; color: #f8fafc; }
            QProgressBar {
                border: 1px solid #334155;
                border-radius: 6px;
                text-align: center;
                background-color: #0f172a;
                color: #f8fafc;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #2563eb;
                border-radius: 5px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        self.lbl_status = QLabel("Đang chuẩn bị...")
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

    def update_progress(self, val, msg):
        self.progress_bar.setValue(val)
        self.lbl_status.setText(msg)



# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  HOT-SWAP / REPLACE DEVICE DIALOG (ĐỔI MAC THIẾT BỊ HỎNG)
# ═══════════════════════════════════════════════════════════════
class ReplaceDeviceDialog(QDialog):
    def __init__(self, current_dev, available_devices, parent=None):
        super().__init__(parent)
        self.current_dev = current_dev
        self.available_devices = available_devices
        self.selected_mac = ""
        self.init_ui()

    def init_ui(self):
        dev_name = self.current_dev.get("device_name") or self.current_dev.get("device_uuid")
        old_mac = self.current_dev.get("mac_address") or "Chưa có MAC"
        
        self.setWindowTitle(f"🔄 Đổi Box / Thay Thế MAC cho '{dev_name}'")
        self.setMinimumWidth(480)
        self.setStyleSheet("""
            QDialog { background-color: #111827; color: #f9fafb; }
            QLabel { color: #f3f4f6; font-size: 12px; }
            QGroupBox {
                background-color: #1f2937;
                border: 1px solid #374151;
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
                color: #38bdf8;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QComboBox {
                background-color: #090d16;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px 10px;
                color: #f9fafb;
            }
            QComboBox::drop-down { border: none; }
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #3b82f6; }
            QPushButton#btnCancel { background-color: #374151; }
            QPushButton#btnCancel:hover { background-color: #4b5563; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Info Box
        info_lbl = QLabel(
            f"<b>Box Hiện Tại:</b> {dev_name}<br>"
            f"<b>Địa chỉ MAC Cũ:</b> <font color='#ef4444'>{old_mac}</font><br>"
            f"<i>Vui lòng chọn MAC mới từ danh sách có sẵn hoặc điền tay bên dưới.</i>"
        )
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        # Mode 1: Select available Box MAC
        group_select = QGroupBox("Cách 1: Chọn địa chỉ MAC từ Box mới có sẵn")
        layout_select = QVBoxLayout(group_select)
        
        self.cmb_devices = QComboBox()
        self.cmb_devices.addItem("-- Chọn Box Mới Cần Thay Thế --", "")
        for d in self.available_devices:
            if d.get("id") != self.current_dev.get("id"):
                d_name = d.get("device_name") or d.get("device_uuid")
                d_mac = d.get("mac_address") or "Chưa có MAC"
                d_status = d.get("status", "offline").upper()
                self.cmb_devices.addItem(f"{d_name} | MAC: {d_mac} [{d_status}]", d_mac)
        
        layout_select.addWidget(self.cmb_devices)
        layout.addWidget(group_select)

        # Mode 2: Manual MAC Input
        group_manual = QGroupBox("Cách 2: Hoặc Nhập Thủ Công Địa Chỉ MAC Mới")
        layout_manual = QVBoxLayout(group_manual)
        
        self.txt_manual_mac = QLineEdit()
        self.txt_manual_mac.setPlaceholderText("Ví dụ: AA:BB:CC:DD:EE:FF...")
        layout_manual.addWidget(self.txt_manual_mac)
        layout.addWidget(group_manual)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("Hủy Bỏ")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        
        btn_save = QPushButton("🔄 Xác Nhận Đổi MAC")
        btn_save.clicked.connect(self.on_confirm)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def on_confirm(self):
        manual = self.txt_manual_mac.text().strip()
        selected_combo_mac = self.cmb_devices.currentData()

        if manual:
            # Clean MAC formatting
            mac_clean = manual.upper().replace("-", ":")
            self.selected_mac = mac_clean
            self.accept()
        elif selected_combo_mac:
            self.selected_mac = selected_combo_mac
            self.accept()
        else:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn 1 Box từ danh sách hoặc nhập tay địa chỉ MAC mới!")


#  TAB 2: UNIVERSAL ROM BUILDER INTEGRATED PANEL
# ═══════════════════════════════════════════════════════════════

class RomBuildWorker(QThread):
    progress_signal = pyqtSignal(int, str, str) # progress, message, level
    finished_signal = pyqtSignal(bool, str) # success, output_filepath

    def __init__(self, fw_path, output_dir, enable_remote, auto_adb, enable_wg, watchdog, root, clean_bloat, disable_yt_voice, server_url, bootstrap_token):
        super().__init__()
        self.fw_path = fw_path
        self.output_dir = output_dir
        self.enable_remote = enable_remote
        self.auto_adb = auto_adb
        self.enable_wg = enable_wg
        self.watchdog = watchdog
        self.root = root
        self.clean_bloat = clean_bloat
        self.disable_yt_voice = disable_yt_voice
        self.server_url = server_url
        self.bootstrap_token = bootstrap_token

    def run(self):
        import time, shutil, sys
        from pathlib import Path
        try:
            filename = os.path.basename(self.fw_path)
            base_name, ext = os.path.splitext(filename)
            out_filename = f"{base_name}_TX3_Custom_RemoteManaged{ext}"
            out_filepath = os.path.join(self.output_dir, out_filename)

            self.progress_signal.emit(5, f"Bắt đầu quy trình đóng gói ROM thật cho: {filename}", "INFO")

            # Make sure module paths are available
            root_dir = Path(__file__).resolve().parent
            if str(root_dir) not in sys.path:
                sys.path.insert(0, str(root_dir))
            rm_path = root_dir / "rom-builder" / "modules" / "remote-management"
            if str(rm_path) not in sys.path:
                sys.path.insert(0, str(rm_path))

            import __init__ as rm_module
            from rombuilder.core.pipeline import AmlogicProject

            # Build Remote Management Config object
            remote_config = rm_module.RemoteManagementConfig(
                enabled=self.enable_remote,
                auto_start=True,
                tailscale=self.enable_wg,
                tailscale_authkey="tskey-auth-kQEiimCRMm11CNTRL-K99q54JBSrEwPpjq7r7pqENLesKEXd4N",
                watchdog=self.watchdog,
                auto_adb=self.auto_adb,
                server_url=self.server_url,
                bootstrap_token=self.bootstrap_token
            )

            # Progress callback wrapper
            def update_progress(pct, msg):
                self.progress_signal.emit(pct, msg, "INFO")

            self.progress_signal.emit(10, "Khởi tạo pipeline Amlogic & kiểm tra cấu trúc ROM...", "INFO")
            project = AmlogicProject(self.fw_path)

            self.progress_signal.emit(20, "Bung phân vùng system.img từ Firmware...", "INFO")
            project.prepare(progress=lambda p, m: update_progress(20 + int(p * 0.3), m))

            self.progress_signal.emit(50, "Đang nhúng TX3 Remote Agent, Tailscale VPN & Tối ưu hóa 24/7...", "INFO")
            root_mode = "Tích hợp SuperSU từ ZIP" if self.root else "Giữ nguyên root hiện tại"
            project.apply(
                additions=[],
                removals=[],
                root_mode=root_mode,
                remote_config=remote_config,
                progress=lambda p, m: update_progress(50 + int(p * 0.3), m)
            )

            self.progress_signal.emit(80, "Đóng gói lại phân vùng system.img & Đóng dấu checksum...", "INFO")
            project.build(out_filepath, progress=lambda p, m: update_progress(80 + int(p * 0.2), m))

            self.progress_signal.emit(100, f"ĐÓNG GÓI HOÀN TẤT! ROM tùy chỉnh thật đã xuất tại: {out_filepath}", "SUCCESS")
            self.finished_signal.emit(True, out_filepath)

        except Exception as e:
            err_msg = str(e)
            self.progress_signal.emit(100, f"LỖI ĐÓNG GÓI ROM THẬT: {err_msg}", "ERROR")
            self.finished_signal.emit(False, err_msg)
class RomBuilderTab(QWidget):
    def __init__(self, parent=None, log_callback=None):
        super().__init__(parent)
        self.log_callback = log_callback
        self.firmware_path = ""
        self.default_output_dir = os.path.join(os.path.expanduser("~"), "Desktop", "TX3_Build_ROMs")
        if not os.path.exists(self.default_output_dir):
            os.makedirs(self.default_output_dir, exist_ok=True)
        self.init_ui()

    def log(self, msg, level="INFO"):
        if self.log_callback:
            self.log_callback(f"[ROM Builder] {msg}", level)
        else:
            print(f"[{level}] {msg}")

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 1. Select ROM Firmware Group
        fw_box = QGroupBox("1. File ROM Firmware Gốc & Thư Mục Lưu Đầu Ra (Input & Output)")
        fw_layout = QVBoxLayout(fw_box)
        fw_layout.setContentsMargins(12, 12, 12, 12)
        fw_layout.setSpacing(8)

        # Row 1: Input ROM File
        r1_layout = QHBoxLayout()
        r1_layout.addWidget(QLabel("File ROM Gốc:"))
        self.txt_fw_path = QLineEdit()
        self.txt_fw_path.setPlaceholderText("Đường dẫn file ROM gốc (.img hoặc .zip) - VD: C:/ROMs/TX3Mini_v1.0.img...")
        btn_browse_fw = QPushButton("📁 Chọn File ROM Gốc")
        btn_browse_fw.setObjectName("btnSecondary")
        btn_browse_fw.clicked.connect(self.browse_firmware)
        r1_layout.addWidget(self.txt_fw_path)
        r1_layout.addWidget(btn_browse_fw)
        fw_layout.addLayout(r1_layout)

        # Row 2: Output Directory
        r2_layout = QHBoxLayout()
        r2_layout.addWidget(QLabel("Thư Mục Lưu ROM:"))
        self.txt_output_dir = QLineEdit()
        self.txt_output_dir.setText(self.default_output_dir)
        
        btn_browse_out = QPushButton("📂 Chọn Thư Mục")
        btn_browse_out.setObjectName("btnSecondary")
        btn_browse_out.clicked.connect(self.browse_output_dir)

        btn_open_out = QPushButton("🗂️ Mở Thư Mục Chứa ROM")
        btn_open_out.setStyleSheet("background-color: #1877f2; color: #ffffff; font-weight: bold;")
        btn_open_out.clicked.connect(self.open_output_dir)

        r2_layout.addWidget(self.txt_output_dir)
        r2_layout.addWidget(btn_browse_out)
        r2_layout.addWidget(btn_open_out)
        fw_layout.addLayout(r2_layout)

        layout.addWidget(fw_box)

        # 2. Remote Management Auto-Injection Config
        remote_box = QGroupBox("2. Tự động hóa Quản trị Từ xa (TX3 Remote Management Auto-Injection)")
        remote_layout = QVBoxLayout(remote_box)
        remote_layout.setContentsMargins(12, 12, 12, 12)
        remote_layout.setSpacing(6)

        self.chk_enable_remote = QCheckBox("⚡ Tự động tích hợp TX3 Remote Agent khi Flash ROM (Bật mặc định)")
        self.chk_enable_remote.setChecked(True)
        self.chk_enable_remote.setStyleSheet("font-weight: bold; color: #1877f2;")

        self.chk_auto_adb = QCheckBox("✓ Tự động mở sẵn cổng ADB TCP 5555 ngầm (Vĩnh viễn)")
        self.chk_auto_adb.setChecked(True)

        self.chk_tailscale = QCheckBox("✓ Khởi tạo Tailscale VPN Client tự động (Zero-Touch Provisioning)")
        self.chk_tailscale.setChecked(True)

        self.chk_watchdog = QCheckBox("✓ Bật Watchdog & Resource Guard (Tự restart agent khi treo/lag)")
        self.chk_watchdog.setChecked(True)

        remote_layout.addWidget(self.chk_enable_remote)
        remote_layout.addWidget(self.chk_auto_adb)
        remote_layout.addWidget(self.chk_tailscale)
        remote_layout.addWidget(self.chk_watchdog)

        # Server Settings
        srv_layout = QHBoxLayout()
        srv_layout.addWidget(QLabel("Management Server URL:"))
        self.txt_server_url = QLineEdit("http://100.95.168.28:8400")
        srv_layout.addWidget(self.txt_server_url)

        srv_layout.addWidget(QLabel("Bootstrap Secret Key:"))
        self.txt_bootstrap_token = QLineEdit("iil1pZT-8Oo4lOBHmItC86PLcOeg-wnToucCc2IRNeU")
        self.txt_bootstrap_token.setEchoMode(QLineEdit.Password)
        srv_layout.addWidget(self.txt_bootstrap_token)
        remote_layout.addLayout(srv_layout)

        layout.addWidget(remote_box)

        # 3. Customizations Group (Root, Apps, Auto Settings)
        custom_box = QGroupBox("3. Tùy chỉnh Hệ thống & Vô hiệu hóa Dịch vụ Rác")
        custom_layout = QVBoxLayout(custom_box)
        custom_layout.setContentsMargins(12, 12, 12, 12)
        custom_layout.setSpacing(6)

        c_row1 = QHBoxLayout()
        self.chk_root = QCheckBox("⚡ Tích hợp SuperSU / Magisk Root Binary (Chặn quảng cáo hệ thống)")
        self.chk_root.setChecked(True)

        self.chk_clean_bloat = QCheckBox("🧹 Tự gỡ bỏ Bloatware & Ứng dụng rác mặc định của nhà sản xuất")
        self.chk_clean_bloat.setChecked(True)

        c_row1.addWidget(self.chk_root)
        c_row1.addWidget(self.chk_clean_bloat)
        custom_layout.addLayout(c_row1)

        c_row2 = QHBoxLayout()
        self.chk_disable_yt_voice = QCheckBox("🔇 Tự động TẮT TIẾNG ĐỌC YOUTUBE (Gỡ KingUser Accessibility Service)")
        self.chk_disable_yt_voice.setChecked(True)
        self.chk_disable_yt_voice.setStyleSheet("font-weight: bold; color: #d97706;")
        c_row2.addWidget(self.chk_disable_yt_voice)
        custom_layout.addLayout(c_row2)

        layout.addWidget(custom_box)

        # 4. Action & Output Progress
        action_box = QGroupBox("4. Đóng gói ROM & Tiến trình Xử lý (Build Engine)")
        action_layout = QVBoxLayout(action_box)
        action_layout.setContentsMargins(12, 12, 12, 12)
        action_layout.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccd0d5;
                border-radius: 6px;
                text-align: center;
                height: 22px;
                background-color: #f0f2f5;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #42b72a;
                border-radius: 5px;
            }
        """)
        action_layout.addWidget(self.progress_bar)

        self.lbl_status_msg = QLabel("Trạng thái: Sẵn sàng đóng gói ROM")
        self.lbl_status_msg.setStyleSheet("color: #65676b; font-weight: 600;")
        action_layout.addWidget(self.lbl_status_msg)

        self.btn_start_build = QPushButton("🚀 BẮT ĐẦU ĐÓNG GÓI BẢN ROM HOÀN CHỈNH (1-CLICK BUILD)")
        self.btn_start_build.setStyleSheet("""
            QPushButton {
                background-color: #42b72a;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                padding: 12px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #36a420;
            }
            QPushButton:disabled {
                background-color: #e4e6eb;
                color: #bcc0c4;
            }
        """)
        self.btn_start_build.clicked.connect(self.start_build_rom)
        action_layout.addWidget(self.btn_start_build)

        layout.addWidget(action_box)
        layout.addStretch()

    def browse_firmware(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file ROM gốc", "", "Android ROM (*.img *.zip);;All Files (*)"
        )
        if file_path:
            self.txt_fw_path.setText(file_path)
            self.log(f"Đã chọn file ROM gốc: {file_path}", "INFO")

    def browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Chọn Thư Mục Lưu ROM Đầu Ra", self.txt_output_dir.text())
        if dir_path:
            self.txt_output_dir.setText(dir_path)
            self.log(f"Đã cập nhật thư mục lưu ROM: {dir_path}", "INFO")

    def open_output_dir(self):
        out_dir = self.txt_output_dir.text().strip()
        if not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"Không thể tạo thư mục: {str(e)}")
                return
        
        # Open in Windows Explorer / OS File Manager
        if sys.platform == "win32":
            os.startfile(out_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", out_dir])
        else:
            subprocess.Popen(["xdg-open", out_dir])
        self.log(f"Đã mở thư mục lưu ROM: {out_dir}", "INFO")

    def start_build_rom(self):
        fw_path = self.txt_fw_path.text().strip()
        out_dir = self.txt_output_dir.text().strip()

        if not fw_path or not os.path.exists(fw_path):
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn đường dẫn file ROM gốc (.img/.zip) hợp lệ!")
            return

        if not out_dir:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn Thư Mục Lưu ROM đầu ra!")
            return

        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        self.btn_start_build.setEnabled(False)
        self.progress_bar.setValue(0)

        # Start RomBuildWorker QThread
        self.build_worker = RomBuildWorker(
            fw_path=fw_path,
            output_dir=out_dir,
            enable_remote=self.chk_enable_remote.isChecked(),
            auto_adb=self.chk_auto_adb.isChecked(),
            enable_wg=self.chk_tailscale.isChecked(),
            watchdog=self.chk_watchdog.isChecked(),
            root=self.chk_root.isChecked(),
            clean_bloat=self.chk_clean_bloat.isChecked(),
            disable_yt_voice=self.chk_disable_yt_voice.isChecked(),
            server_url=self.txt_server_url.text().strip(),
            bootstrap_token=self.txt_bootstrap_token.text().strip()
        )

        self.build_worker.progress_signal.connect(self.on_build_progress)
        self.build_worker.finished_signal.connect(self.on_build_finished)
        self.build_worker.start()

    def on_build_progress(self, val, msg, level):
        self.progress_bar.setValue(val)
        self.lbl_status_msg.setText(f"Trạng thái: {msg}")
        self.log(msg, level)

    def on_build_finished(self, success, result_path):
        self.btn_start_build.setEnabled(True)
        if success:
            msg_box = f"🎉 HOÀN TẤT ĐÓNG GÓI BẢN ROM HOÀN CHỈNH!\n\n📁 File ROM Custom đã được lưu tại:\n{result_path}\n\n👉 Bạn có thể nhấn nút '🗂️ Mở Thư Mục Chứa ROM' hoặc dùng Amlogic USB Burning Tool để Flash bản ROM này vào Box ngay."
            QMessageBox.information(self, "THÀNH CÔNG", msg_box)
        else:
            QMessageBox.critical(self, "LỖI BUILD ROM", f"Không thể đóng gói ROM: {result_path}")
APP_VERSION = "v1.2.5 (Tailscale 24/7)"

class TX3ControllerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.token = ""
        self.current_server_url = DEFAULT_SERVER_URL
        self.devices = []
        self.selected_device = None
        self.scrcpy_bin = "scrcpy"
        self.adb_bin = "adb"
        self.tools_dir = os.path.join(os.path.expanduser("~"), ".tx3_remote_tools")
        self.vpn_conf_path = os.path.join(self.tools_dir, "tx3_vpn.conf")
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"TX3 Remote Management Platform {APP_VERSION} - Facebook Modern Theme")
        self.resize(1320, 860)

        # Facebook Design System Stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f2f5;
            }
            QWidget {
                color: #050505;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                font-size: 12px;
            }

            /* --- Custom Slim Scrollbars --- */
            QScrollBar:vertical {
                background-color: #f0f2f5;
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #bcc0c4;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #8a8d91;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }

            /* --- Header Bar --- */
            QFrame#headerFrame {
                background-color: #ffffff;
                border-bottom: 1px solid #e4e6eb;
                max-height: 52px;
                min-height: 52px;
                border-radius: 8px;
            }

            /* --- Facebook GroupBoxes / Cards --- */
            QGroupBox {
                background-color: #ffffff;
                border: 1px solid #e4e6eb;
                border-radius: 10px;
                margin-top: 14px;
                font-weight: bold;
                font-size: 12px;
                color: #1877f2;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 2px 10px;
                color: #1877f2;
                background-color: #e7f3ff;
                border: 1px solid #beccd4;
                border-radius: 6px;
                font-weight: bold;
            }

            /* --- Form Inputs --- */
            QLineEdit {
                background-color: #f0f2f5;
                border: 1px solid #ccd0d5;
                border-radius: 6px;
                padding: 7px 10px;
                color: #050505;
                font-size: 12px;
                selection-background-color: #1877f2;
            }
            QLineEdit:focus {
                border: 1px solid #1877f2;
                background-color: #ffffff;
            }

            /* --- Buttons --- */
            QPushButton {
                background-color: #1877f2;
                color: #ffffff;
                border-radius: 6px;
                padding: 7px 14px;
                font-weight: bold;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background-color: #166fe5;
            }
            QPushButton:pressed {
                background-color: #1465d2;
            }
            QPushButton:disabled {
                background-color: #e4e6eb;
                color: #bcc0c4;
            }
            QPushButton#btnSecondary {
                background-color: #e4e6eb;
                color: #050505;
                border: none;
            }
            QPushButton#btnSecondary:hover {
                background-color: #d8dadf;
            }
            QPushButton#btnVpn {
                background-color: #42b72a;
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton#btnVpn:hover {
                background-color: #36a420;
            }
            QPushButton#btnSaveName {
                background-color: #1877f2;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton#btnRemote {
                background-color: #42b72a;
                font-size: 13px;
                padding: 10px 18px;
                font-weight: bold;
                border-radius: 8px;
            }
            QPushButton#btnRemote:hover {
                background-color: #36a420;
            }
            QPushButton#btnPush {
                background-color: #8b5cf6;
                padding: 8px;
                font-weight: bold;
                border-radius: 6px;
            }

            /* --- Data Table --- */
            QTableWidget {
                background-color: #ffffff;
                border: 1px solid #e4e6eb;
                border-radius: 8px;
                gridline-color: #f0f2f5;
                color: #050505;
                selection-background-color: #e7f3ff;
                selection-color: #1877f2;
                outline: none;
            }
            QTableWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #f0f2f5;
            }
            QTableWidget::item:selected {
                background-color: #e7f3ff;
                color: #1877f2;
                font-weight: bold;
            }
            QHeaderView::section {
                background-color: #f0f2f5;
                color: #65676b;
                padding: 8px 10px;
                font-weight: bold;
                border: none;
                border-bottom: 2px solid #e4e6eb;
            }

            /* --- Console Terminal --- */
            QTextEdit#txtConsole {
                background-color: #1c1e21;
                color: #38bdf8;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #303338;
                border-radius: 8px;
                padding: 8px;
            }

            /* --- Status Bar --- */
            QStatusBar {
                background-color: #ffffff;
                color: #65676b;
                border-top: 1px solid #e4e6eb;
                font-size: 11px;
            }

            /* --- Checkbox Controls --- */
            QCheckBox {
                color: #050505;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #ccd0d5;
                background-color: #f0f2f5;
            }
            QCheckBox::indicator:checked {
                background-color: #1877f2;
                border: 1px solid #1877f2;
            }
        """)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(8)

        # Header Bar
        header = QFrame()
        header.setObjectName("headerFrame")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 4, 14, 4)

        title_label = QLabel("👍 TX3 REMOTE MANAGEMENT PLATFORM (FACEBOOK THEME)")
        title_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title_label.setStyleSheet("color: #1877f2;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.user_info_label = QLabel("Chưa đăng nhập")
        self.user_info_label.setStyleSheet("color: #65676b; font-weight: 600; font-size: 11px;")
        header_layout.addWidget(self.user_info_label)

        main_layout.addWidget(header)

        # Tab Widget Container
        self.main_tabs = QTabWidget()
        self.main_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #e4e6eb;
                background-color: #ffffff;
                border-radius: 10px;
            }
            QTabBar::tab {
                background-color: #f0f2f5;
                color: #65676b;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 22px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border: 1px solid #e4e6eb;
                border-bottom: none;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #ffffff;
                color: #1877f2;
                border-top: 3px solid #1877f2;
                font-weight: bold;
            }
        """)

        # Tab 1 Widget (Remote Control & Device Management)
        tab_remote_widget = QWidget()
        tab_remote_layout = QVBoxLayout(tab_remote_widget)
        tab_remote_layout.setContentsMargins(6, 6, 6, 6)

        # Main Horizontal Splitter
        main_splitter = QSplitter(Qt.Horizontal)

        # Left Panel (Login & Device List)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # 0. Tailscale VPN & Tools Status Box (Placed TOP LEFT before Login for instant VPN connection)
        tools_box = QGroupBox("⚡ Quản lý Tailscale VPN Network & Công cụ")
        tools_layout = QVBoxLayout(tools_box)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        tools_layout.setSpacing(6)

        self.lbl_tools_status = QLabel("Đang kiểm tra Scrcpy / ADB / Tailscale...")
        self.lbl_tools_status.setStyleSheet("color: #050505; font-weight: 600; font-size: 12px;")
        self.lbl_tools_status.setWordWrap(True)
        tools_layout.addWidget(self.lbl_tools_status)

        tools_btn_layout = QHBoxLayout()
        self.btn_toggle_vpn = QPushButton("⚡ BẬT / TẮT WIREGUARD VPN NETWORK")
        self.btn_toggle_vpn.setObjectName("btnVpn")
        self.btn_toggle_vpn.setMinimumHeight(38)
        self.btn_toggle_vpn.clicked.connect(self.toggle_tailscale_vpn)
        tools_btn_layout.addWidget(self.btn_toggle_vpn)

        self.btn_check_deps = QPushButton("⚙ Cài đặt Scrcpy/ADB")
        self.btn_check_deps.setObjectName("btnSecondary")
        self.btn_check_deps.setMinimumHeight(38)
        self.btn_check_deps.clicked.connect(self.auto_check_and_install_deps)
        tools_btn_layout.addWidget(self.btn_check_deps)

        tools_layout.addLayout(tools_btn_layout)
        left_layout.addWidget(tools_box)

        # 1. Login Group
        self.login_box = QGroupBox("1. Đăng nhập hệ thống")
        login_layout = QHBoxLayout(self.login_box)
        login_layout.setContentsMargins(10, 10, 10, 8)
        login_layout.setSpacing(6)

        self.txt_login_server_url = QLineEdit(DEFAULT_SERVER_URL)
        self.txt_login_server_url.setPlaceholderText("http://100.95.168.28:8400")
        self.txt_login_server_url.setToolTip("Địa chỉ Server Quản Lý Tailscale IP")

        self.txt_username = QLineEdit()
        self.txt_username.setPlaceholderText("Tên đăng nhập")
        self.txt_password = QLineEdit()
        self.txt_password.setPlaceholderText("Mật khẩu")
        self.txt_password.setEchoMode(QLineEdit.Password)
        self.btn_login = QPushButton("Đăng nhập")
        self.btn_login.clicked.connect(self.handle_login)

        login_layout.addWidget(QLabel("Server:"))
        login_layout.addWidget(self.txt_login_server_url)
        login_layout.addWidget(self.txt_username)
        login_layout.addWidget(self.txt_password)
        login_layout.addWidget(self.btn_login)
        left_layout.addWidget(self.login_box)

        # 2. Devices Group
        devices_box = QGroupBox("2. Danh sách thiết bị Android Box")
        devices_layout = QVBoxLayout(devices_box)
        devices_layout.setContentsMargins(10, 10, 10, 8)
        devices_layout.setSpacing(6)

        top_dev_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("🔄 Tải lại")
        self.btn_refresh.setObjectName("btnSecondary")
        self.btn_refresh.clicked.connect(self.load_devices)
        self.btn_refresh.setEnabled(False)

        self.btn_discover = QPushButton("🔍 Quét Box Mới")
        self.btn_discover.setObjectName("btnSecondary")
        self.btn_discover.setToolTip("Quét dải mạng Tailscale để tự động nhận diện & đăng ký các Box mới flash ROM")
        self.btn_discover.clicked.connect(self.discover_new_devices)
        self.btn_discover.setEnabled(False)
        
        self.btn_select_all = QPushButton("☑️ Chọn tất cả")
        self.btn_select_all.setObjectName("btnSecondary")
        self.btn_select_all.clicked.connect(self.select_all_devices)
        self.btn_select_all.setEnabled(False)

        self.btn_export_csv = QPushButton("📊 Xuất CSV")
        self.btn_export_csv.setObjectName("btnSecondary")
        self.btn_export_csv.clicked.connect(self.export_devices_csv)
        self.btn_export_csv.setEnabled(False)

        self.txt_search_dev = QLineEdit()
        self.txt_search_dev.setPlaceholderText("🔍 Tìm kiếm theo Tên Box, Địa chỉ MAC, IP, Location...")
        self.txt_search_dev.setClearButtonEnabled(True)
        self.txt_search_dev.textChanged.connect(self.filter_devices_table)

        top_dev_layout.addWidget(self.btn_refresh)
        top_dev_layout.addWidget(self.btn_discover)
        top_dev_layout.addWidget(self.btn_select_all)
        top_dev_layout.addWidget(self.btn_export_csv)
        top_dev_layout.addWidget(self.txt_search_dev)
        devices_layout.addLayout(top_dev_layout)

        self.table_devices = QTableWidget()
        self.table_devices.setColumnCount(6)
        self.table_devices.setHorizontalHeaderLabels(["Trạng thái", "Tên Box ✏️", "Địa chỉ MAC", "IP Tailscale", "Địa điểm (Site)", "ROM Ver"])
        self.table_devices.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_devices.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_devices.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table_devices.itemSelectionChanged.connect(self.on_device_selected)
        self.table_devices.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.table_devices.itemChanged.connect(self.on_item_changed)

        devices_layout.addWidget(self.table_devices)
        left_layout.addWidget(devices_box)

        main_splitter.addWidget(left_widget)

        # Right Panel (Divided into Vertical Splitter: Controls ScrollArea on Top, Console Log on Bottom)
        right_splitter = QSplitter(Qt.Vertical)

        # Scrollable Area for Control Panels
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 4, 0)
        controls_layout.setSpacing(10)

        # 3. Selected Device Controls & Edit Name
        info_box = QGroupBox("3. Điều khiển & Sửa tên Box")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(6)

        self.lbl_selected_name = QLabel("Chưa chọn thiết bị nào")
        self.lbl_selected_name.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_selected_name.setStyleSheet("color: #1877f2;")
        info_layout.addWidget(self.lbl_selected_name)

        # Edit Box Name & Replace MAC Layout
        edit_name_layout = QHBoxLayout()
        self.txt_edit_name = QLineEdit()
        self.txt_edit_name.setPlaceholderText("Đổi tên gợi nhớ Box...")
        
        self.btn_save_name = QPushButton("💾 Lưu Tên")
        self.btn_save_name.setObjectName("btnSaveName")
        self.btn_save_name.setEnabled(False)
        self.btn_save_name.clicked.connect(self.save_device_name_from_input)

        self.btn_replace_mac = QPushButton("🔄 Đổi Box / Thay MAC")
        self.btn_replace_mac.setObjectName("btnSecondary")
        self.btn_replace_mac.setEnabled(False)
        self.btn_replace_mac.clicked.connect(self.open_replace_device_dialog)

        edit_name_layout.addWidget(self.txt_edit_name)
        edit_name_layout.addWidget(self.btn_save_name)
        edit_name_layout.addWidget(self.btn_replace_mac)
        info_layout.addLayout(edit_name_layout)

        self.lbl_selected_detail = QLabel("Vui lòng chọn 1 Box trong danh sách bên trái để điều khiển.")
        self.lbl_selected_detail.setStyleSheet("color: #65676b; font-size: 11px;")
        self.lbl_selected_detail.setWordWrap(True)
        info_layout.addWidget(self.lbl_selected_detail)

        # Master-Slave Sync Checkbox
        self.chk_master_slave = QCheckBox("🎯 Bật Chế độ Điều khiển Đồng Bộ Hàng Loạt (1 Master + N Slaves)")
        self.chk_master_slave.setStyleSheet("color: #1877f2; font-weight: bold;")
        self.chk_master_slave.setChecked(True)
        info_layout.addWidget(self.chk_master_slave)

        self.btn_remote = QPushButton("▶ Bắt đầu Remote Scrcpy (Màn hình Realtime)")
        self.btn_remote.setObjectName("btnRemote")
        self.btn_remote.setEnabled(False)
        self.btn_remote.clicked.connect(self.launch_scrcpy)
        info_layout.addWidget(self.btn_remote)

        # Master Sync Navigation & Gesture Panel
        sync_panel_box = QGroupBox("🎮 Bảng Điều Khiển Đồng Bộ Realtime (Master -> All Slaves)")
        sync_panel_layout = QVBoxLayout(sync_panel_box)
        sync_panel_layout.setContentsMargins(8, 8, 8, 8)
        sync_panel_layout.setSpacing(4)

        # Row 1: Key Navigation
        nav_row1 = QHBoxLayout()
        self.btn_sync_home = QPushButton("🏠 Home")
        self.btn_sync_home.setObjectName("btnSecondary")
        self.btn_sync_home.clicked.connect(lambda: self.send_sync_key("3"))

        self.btn_sync_back = QPushButton("↩ Back")
        self.btn_sync_back.setObjectName("btnSecondary")
        self.btn_sync_back.clicked.connect(lambda: self.send_sync_key("4"))

        self.btn_sync_recent = QPushButton("📑 Recents")
        self.btn_sync_recent.setObjectName("btnSecondary")
        self.btn_sync_recent.clicked.connect(lambda: self.send_sync_key("187"))

        self.btn_sync_power = QPushButton("⚡ Power")
        self.btn_sync_power.setObjectName("btnSecondary")
        self.btn_sync_power.clicked.connect(lambda: self.send_sync_key("26"))

        nav_row1.addWidget(self.btn_sync_home)
        nav_row1.addWidget(self.btn_sync_back)
        nav_row1.addWidget(self.btn_sync_recent)
        nav_row1.addWidget(self.btn_sync_power)
        sync_panel_layout.addLayout(nav_row1)

        # Row 2: D-Pad Navigation
        dpad_row = QHBoxLayout()
        self.btn_dpad_up = QPushButton("⬆")
        self.btn_dpad_up.setObjectName("btnSecondary")
        self.btn_dpad_up.clicked.connect(lambda: self.send_sync_key("19"))

        self.btn_dpad_down = QPushButton("⬇")
        self.btn_dpad_down.setObjectName("btnSecondary")
        self.btn_dpad_down.clicked.connect(lambda: self.send_sync_key("20"))

        self.btn_dpad_left = QPushButton("⬅")
        self.btn_dpad_left.setObjectName("btnSecondary")
        self.btn_dpad_left.clicked.connect(lambda: self.send_sync_key("21"))

        self.btn_dpad_right = QPushButton("➡")
        self.btn_dpad_right.setObjectName("btnSecondary")
        self.btn_dpad_right.clicked.connect(lambda: self.send_sync_key("22"))

        self.btn_dpad_ok = QPushButton("🔘 OK/Enter")
        self.btn_dpad_ok.setObjectName("btnSecondary")
        self.btn_dpad_ok.clicked.connect(lambda: self.send_sync_key("66"))

        dpad_row.addWidget(self.btn_dpad_up)
        dpad_row.addWidget(self.btn_dpad_down)
        dpad_row.addWidget(self.btn_dpad_left)
        dpad_row.addWidget(self.btn_dpad_right)
        dpad_row.addWidget(self.btn_dpad_ok)
        sync_panel_layout.addLayout(dpad_row)

        # Row 3: Text Input & Tap Coords Sync
        text_row = QHBoxLayout()
        self.txt_sync_text = QLineEdit()
        self.txt_sync_text.setPlaceholderText("Gõ chữ / URL để đồng bộ sang tất cả Box...")
        self.btn_send_text = QPushButton("🔤 Gửi Chữ")
        self.btn_send_text.setObjectName("btnSecondary")
        self.btn_send_text.clicked.connect(self.send_sync_text_action)

        text_row.addWidget(self.txt_sync_text)
        text_row.addWidget(self.btn_send_text)
        sync_panel_layout.addLayout(text_row)

        # Row 4: Tap Coords & Swipe Gestures
        gesture_row = QHBoxLayout()
        self.txt_tap_x = QLineEdit()
        self.txt_tap_x.setPlaceholderText("X (VD: 500)")
        self.txt_tap_y = QLineEdit()
        self.txt_tap_y.setPlaceholderText("Y (VD: 800)")
        self.btn_send_tap = QPushButton("👆 Click Coords")
        self.btn_send_tap.setObjectName("btnSecondary")
        self.btn_send_tap.clicked.connect(self.send_sync_tap_action)

        self.btn_swipe_up = QPushButton("📜 Vuốt Lên")
        self.btn_swipe_up.setObjectName("btnSecondary")
        self.btn_swipe_up.clicked.connect(lambda: self.send_sync_swipe("500 1200 500 300"))

        self.btn_swipe_down = QPushButton("📜 Vuốt Xuống")
        self.btn_swipe_down.setObjectName("btnSecondary")
        self.btn_swipe_down.clicked.connect(lambda: self.send_sync_swipe("500 300 500 1200"))

        gesture_row.addWidget(self.txt_tap_x)
        gesture_row.addWidget(self.txt_tap_y)
        gesture_row.addWidget(self.btn_send_tap)
        gesture_row.addWidget(self.btn_swipe_up)
        gesture_row.addWidget(self.btn_swipe_down)
        sync_panel_layout.addLayout(gesture_row)

        info_layout.addWidget(sync_panel_box)
        controls_layout.addWidget(info_box)

        # 4. File Transfer & Batch ADB Console Group
        file_box = QGroupBox("4. Truyền File & Điều khiển ADB Hàng Loạt")
        file_layout = QVBoxLayout(file_box)
        file_layout.setContentsMargins(10, 10, 10, 10)
        file_layout.setSpacing(6)

        file_sel_layout = QHBoxLayout()
        self.txt_filepath = QLineEdit()
        self.txt_filepath.setPlaceholderText("Chọn file (APK, Zip, Video...)")
        self.btn_browse = QPushButton("📁 Chọn File...")
        self.btn_browse.setObjectName("btnSecondary")
        self.btn_browse.clicked.connect(self.browse_file)
        file_sel_layout.addWidget(self.txt_filepath)
        file_sel_layout.addWidget(self.btn_browse)
        file_layout.addLayout(file_sel_layout)

        remote_dir_layout = QHBoxLayout()
        remote_dir_layout.addWidget(QLabel("Thư mục đích trên Box:"))
        self.cbo_remote_dir = QComboBox()
        self.cbo_remote_dir.setEditable(True)
        self.cbo_remote_dir.addItems([
            "/sdcard/Download",
            "/sdcard",
            "/data/local/tmp",
            "/system/app",
            "/system/priv-app"
        ])
        remote_dir_layout.addWidget(self.cbo_remote_dir)
        file_layout.addLayout(remote_dir_layout)

        btn_transfer_layout = QHBoxLayout()
        self.btn_push = QPushButton("⚡ Truyền File sang Box")
        self.btn_push.setObjectName("btnPush")
        self.btn_push.setEnabled(False)
        self.btn_push.clicked.connect(self.push_file)
        
        self.btn_batch_install = QPushButton("📦 Cài APK ngầm Hàng Loạt")
        self.btn_batch_install.setObjectName("btnSecondary")
        self.btn_batch_install.setEnabled(False)
        self.btn_batch_install.clicked.connect(self.run_batch_install_apk)
        
        btn_transfer_layout.addWidget(self.btn_push)
        btn_transfer_layout.addWidget(self.btn_batch_install)
        file_layout.addLayout(btn_transfer_layout)

        # Batch ADB Quick Commands
        adb_cmd_layout = QHBoxLayout()
        self.btn_batch_reboot = QPushButton("🔄 Reboot Hàng Loạt")
        self.btn_batch_reboot.setObjectName("btnSecondary")
        self.btn_batch_reboot.clicked.connect(self.run_batch_reboot)

        self.btn_batch_clear = QPushButton("🧹 Dọn rác Download")
        self.btn_batch_clear.setObjectName("btnSecondary")
        self.btn_batch_clear.clicked.connect(self.run_batch_clear_cache)

        self.btn_disable_yt_voice_batch = QPushButton("🔇 Tắt Tiếng Đọc Youtube")
        self.btn_disable_yt_voice_batch.setObjectName("btnSecondary")
        self.btn_disable_yt_voice_batch.clicked.connect(self.run_batch_disable_yt_voice)

        adb_cmd_layout.addWidget(self.btn_batch_reboot)
        adb_cmd_layout.addWidget(self.btn_batch_clear)
        adb_cmd_layout.addWidget(self.btn_disable_yt_voice_batch)
        file_layout.addLayout(adb_cmd_layout)

        # Custom Shell Command
        custom_cmd_layout = QHBoxLayout()
        self.txt_custom_adb = QLineEdit()
        self.txt_custom_adb.setPlaceholderText("Lệnh ADB Shell tùy chỉnh (VD: pm clear com.vtv.vtvgo)...")
        self.btn_run_custom_adb = QPushButton("▶ Chạy Lệnh")
        self.btn_run_custom_adb.setObjectName("btnSecondary")
        self.btn_run_custom_adb.clicked.connect(self.run_batch_custom_adb)
        custom_cmd_layout.addWidget(self.txt_custom_adb)
        custom_cmd_layout.addWidget(self.btn_run_custom_adb)
        file_layout.addLayout(custom_cmd_layout)

        controls_layout.addWidget(file_box)



        # 6. Telegram Notification Settings Box
        tele_box = QGroupBox("6. Cấu hình Cảnh báo Telegram Bot")
        tele_layout = QVBoxLayout(tele_box)
        tele_layout.setContentsMargins(10, 8, 10, 8)
        tele_layout.setSpacing(6)

        t_row1 = QHBoxLayout()
        t_row1.addWidget(QLabel("Bot Token:"))
        self.txt_tele_token = QLineEdit()
        self.txt_tele_token.setPlaceholderText("123456789:ABCdef...")
        t_row1.addWidget(self.txt_tele_token)

        t_row1.addWidget(QLabel("Chat ID:"))
        self.txt_tele_chatid = QLineEdit()
        self.txt_tele_chatid.setPlaceholderText("-1001234567...")
        t_row1.addWidget(self.txt_tele_chatid)
        tele_layout.addLayout(t_row1)

        t_row2 = QHBoxLayout()
        self.chk_tele_alert_offline = QCheckBox("Tự cảnh báo khi Box mất kết nối (Offline)")
        self.chk_tele_alert_offline.setChecked(True)
        self.btn_test_tele = QPushButton("🧪 Test Gửi Telegram")
        self.btn_test_tele.setObjectName("btnSecondary")
        self.btn_test_tele.clicked.connect(self.test_telegram_alert)

        t_row2.addWidget(self.chk_tele_alert_offline)
        t_row2.addWidget(self.btn_test_tele)
        tele_layout.addLayout(t_row2)

        controls_layout.addWidget(tele_box)

        controls_scroll.setWidget(controls_container)
        right_splitter.addWidget(controls_scroll)

        # 7. Dedicated Console Log & System Activity (Bottom Splitter Panel)
        log_box = QGroupBox("7. Nhật ký hệ thống & ADB Commands Console Log")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(8, 8, 8, 6)
        log_layout.setSpacing(4)

        self.txt_console = QTextEdit()
        self.txt_console.setObjectName("txtConsole")
        self.txt_console.setReadOnly(True)
        self.txt_console.setMinimumHeight(150)
        log_layout.addWidget(self.txt_console)

        log_btn_layout = QHBoxLayout()
        self.btn_clear_log = QPushButton("🗑 Xóa Log")
        self.btn_clear_log.setObjectName("btnSecondary")
        self.btn_clear_log.clicked.connect(self.clear_console_log)
        self.btn_copy_log = QPushButton("📋 Sao chép Log")
        self.btn_copy_log.setObjectName("btnSecondary")
        self.btn_copy_log.clicked.connect(self.copy_console_log)

        log_btn_layout.addWidget(self.btn_clear_log)
        log_btn_layout.addWidget(self.btn_copy_log)
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)

        right_splitter.addWidget(log_box)
        right_splitter.setSizes([520, 240])

        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([520, 780])

        tab_remote_layout.addWidget(main_splitter)
        self.main_tabs.addTab(tab_remote_widget, "📱 TAB 1: ĐIỀU KHIỂN & QUẢN LÝ THIẾT BỊ")

        self.tab_rom_builder = RomBuilderTab(log_callback=self.log)
        self.main_tabs.addTab(self.tab_rom_builder, "🛠️ TAB 2: ĐÓNG GÓI & TỰ ĐỘNG HÓA ROM BUILDER")

        main_layout.addWidget(self.main_tabs)

        # Status Bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Sẵn sàng. Vui lòng đăng nhập để bắt đầu.")

        # Flag for table editing
        self.is_populating = False

        # Auto Refresh Timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load_devices)

        # Auto check local tools on startup
        QTimer.singleShot(500, self.detect_local_tools)

        self.log("Khởi động hệ thống điều khiển TX3 Remote Management Platform...", "INFO")

    def log(self, message, level="INFO"):
        now_str = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "INFO": "#9cdcfe",      # Light Blue
            "SUCCESS": "#4ec9b0",   # Teal/Green
            "WARNING": "#ce9178",   # Orange
            "ERROR": "#f44747",     # Red
            "ADB": "#c586c0"        # Purple
        }
        color = color_map.get(level, "#d4d4d4")
        html = f"<span style='color: #808080;'>[{now_str}]</span> <span style='color: {color}; font-weight: bold;'>[{level}]</span> <span style='color: #d4d4d4;'>{message}</span>"
        
        self.txt_console.append(html)
        self.txt_console.moveCursor(QTextCursor.End)

    def clear_console_log(self):
        self.txt_console.clear()
        self.log("Đã xóa toàn bộ nhật ký console.", "INFO")

    def copy_console_log(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.txt_console.toPlainText())
        self.statusBar.showMessage("Đã sao chép nhật ký vào Clipboard!")
        self.log("Đã sao chép nhật ký vào Clipboard.", "INFO")

    def get_tailscale_local_ip(self):
        """Phát hiện IP máy tính trong dải mạng Tailscale 100.x.y.z"""
        try:
            res = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        try:
            if sys.platform == "win32":
                res = subprocess.run(["ipconfig"], capture_output=True, text=True)
                match = re.search(r"100\.\d+\.\d+\.\d+", res.stdout)
                if match:
                    return match.group(0)
            else:
                res = subprocess.run(["ip", "a"], capture_output=True, text=True)
                match = re.search(r"100\.\d+\.\d+\.\d+", res.stdout)
                if match:
                    return match.group(0)
        except Exception:
            pass
        return None

    def detect_local_tools(self):
        scrcpy_found = False
        adb_found = False

        if os.path.exists(self.tools_dir):
            for root, dirs, files in os.walk(self.tools_dir):
                if "scrcpy.exe" in files or "scrcpy" in files:
                    self.scrcpy_bin = os.path.join(root, "scrcpy.exe" if sys.platform == "win32" else "scrcpy")
                    scrcpy_found = True
                if "adb.exe" in files or "adb" in files:
                    self.adb_bin = os.path.join(root, "adb.exe" if sys.platform == "win32" else "adb")
                    adb_found = True

        if not scrcpy_found:
            try:
                res = subprocess.run(["scrcpy", "--version"], capture_output=True, text=True)
                if res.returncode == 0:
                    self.scrcpy_bin = "scrcpy"
                    scrcpy_found = True
            except Exception:
                pass

        if not adb_found:
            try:
                res = subprocess.run(["adb", "version"], capture_output=True, text=True)
                if res.returncode == 0:
                    self.adb_bin = "adb"
                    adb_found = True
            except Exception:
                pass

        ts_ip = self.get_tailscale_local_ip()

        if ts_ip:
            ts_status = f"🟢 Tailscale VPN: ĐÃ KẾT NỐI (IP Máy Tính: {ts_ip})"
            ts_color = "#15803d"
        else:
            ts_status = "🔴 Tailscale VPN: Chưa kết nối (Bật app Tailscale trên Windows)"
            ts_color = "#b91c1c"

        if scrcpy_found and adb_found:
            self.lbl_tools_status.setText(f"✓ Bộ công cụ Scrcpy & ADB: Sẵn sàng ({self.scrcpy_bin})\n✓ {ts_status}")
            self.lbl_tools_status.setStyleSheet(f"color: {ts_color}; font-weight: 600;")
            self.log(f"Đã kiểm tra môi trường: Scrcpy/ADB Sẵn sàng | {ts_status}", "INFO")
        else:
            self.lbl_tools_status.setText(f"⚠️ Chưa tìm thấy Scrcpy / ADB!\nBấm nút bên dưới để phần mềm tự động tải & giải nén.")
            self.lbl_tools_status.setStyleSheet("color: #b91c1c; font-weight: 600;")
            self.log("⚠️ Chưa phát hiện đủ Scrcpy hoặc ADB trên máy tính.", "WARNING")

    def auto_check_and_install_deps(self):
        if sys.platform == "win32":
            zip_dest = os.path.join(self.tools_dir, "scrcpy-win64.zip")
            dlg = ProgressDialog("Tự động cài đặt Scrcpy & ADB Tool", self)
            dlg.show()

            self.log("Bắt đầu tự động tải bộ công cụ Scrcpy & ADB...", "INFO")
            self.dl_worker = DownloadWorker(SCRCPY_WIN_URL, zip_dest, extract_to=self.tools_dir)
            self.dl_worker.progress.connect(dlg.update_progress)
            
            def on_finished(success, msg):
                dlg.close()
                if success:
                    self.log("Tải & Giải nén Scrcpy + ADB hoàn tất thành công!", "SUCCESS")
                    self.detect_local_tools()
                    wg_installer = os.path.join(self.tools_dir, "tailscale-installer.exe")
                    if not os.path.exists(r"C:\Program Files\Tailscale\tailscale.exe"):
                        reply = QMessageBox.question(
                            self, "Cài đặt Tailscale VPN",
                            "Scrcpy & ADB đã cài xong!\nBạn có muốn tự động tải & cài đặt Tailscale Client cho Windows không?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reply == QMessageBox.Yes:
                            self.install_tailscale_win(wg_installer)
                    else:
                        QMessageBox.information(self, "THÔNG BÁO THÀNH CÔNG", "🚀 Bộ công cụ Scrcpy & ADB đã cài đặt sẵn sàng sử dụng!")
                else:
                    self.log(f"Thất bại khi tải bộ công cụ: {msg}", "ERROR")
                    QMessageBox.critical(self, "Lỗi tải về", msg)

            self.dl_worker.finished.connect(on_finished)
            self.dl_worker.start()
        else:
            QMessageBox.information(self, "Thông báo", "Hệ thống đang chạy trên Linux/macOS. Vui lòng cài đặt scrcpy qua terminal: 'sudo apt install scrcpy adb' hoặc 'brew install scrcpy'.")

    def install_tailscale_win(self, wg_dest):
        dlg = ProgressDialog("Tải Tailscale Client Installer", self)
        dlg.show()
        self.log("Bắt đầu tải Tailscale Windows Installer...", "INFO")

        self.wg_worker = DownloadWorker(WIREGUARD_WIN_URL, wg_dest)
        self.wg_worker.progress.connect(dlg.update_progress)

        def on_wg_finished(success, msg):
            dlg.close()
            if success:
                self.log("Đã tải xong Tailscale Installer. Đang mở installer...", "SUCCESS")
                QMessageBox.information(self, "Khởi chạy Installer", "Đã tải xong Tailscale Installer! Hệ thống sẽ mở file cài đặt ngay bây giờ.")
                subprocess.Popen([wg_dest], shell=True)
            else:
                self.log(f"Thất bại tải Tailscale Installer: {msg}", "ERROR")
                QMessageBox.critical(self, "Lỗi tải Tailscale", msg)

        self.wg_worker.finished.connect(on_wg_finished)
        self.wg_worker.start()

    def toggle_tailscale_vpn(self):
        if sys.platform != "win32":
            QMessageBox.information(self, "Thông báo Tailscale", "Tính năng quản lý VPN tự động chỉ hỗ trợ môi trường Windows.")
            return

        wg_exe = r"C:\Program Files\Tailscale\tailscale.exe"
        if not os.path.exists(wg_exe):
            reply = QMessageBox.question(
                self, "Chưa cài Tailscale",
                "Chưa tìm thấy ứng dụng Tailscale trên Windows!\nBạn có muốn tự động tải về cài đặt ngay bây giờ không?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                wg_installer = os.path.join(self.tools_dir, "tailscale-installer.exe")
                self.install_tailscale_win(wg_installer)
            return

        ts_ip = self.get_tailscale_local_ip()

        if ts_ip:
            self.log(f"Tailscale VPN đang KẾT NỐI (IP: {ts_ip}). Đang tiến hành ngắt kết nối...", "WARNING")
            uninst_res = subprocess.run([wg_exe, "/uninstalltunnelservice", "tx3_vpn"], capture_output=True, text=True)
            out_err = (uninst_res.stdout or uninst_res.stderr or "").strip()
            
            if "Access is denied" in out_err:
                self.log("❌ Lỗi quyền Windows: Cần chạy App dưới quyền Run as Administrator để bật/tắt VPN.", "ERROR")
                QMessageBox.warning(
                    self, "Yêu cầu Quyền Administrator",
                    "⚠️ Bật/Tắt Tailscale Service yêu cầu quyền Quản trị viên trên Windows!\n\n"
                    "👉 Vui lòng ĐÓNG phần mềm, nhấp chuột phải vào icon ứng dụng và chọn 'Run as Administrator' (Chạy với quyền quản trị viên).\n\n"
                    "Hoặc bạn có thể mở ứng dụng Tailscale thủ công và chọn 'Deactivate'."
                )
            else:
                self.log(f"Lệnh ngắt VPN kết quả: {out_err or 'Đã ngắt service thành công.'}", "INFO")
                QMessageBox.information(self, "Tailscale VPN Status", "🔌 Đã ngắt kết nối Tailscale VPN thành công!")
                self.detect_local_tools()
        else:
            os.makedirs(self.tools_dir, exist_ok=True)
            # Auto-generate REAL valid Tailscale Client config matched with Server
            conf_content = """[Interface]
PrivateKey = YB/Mputa3B92fM8Z0wiKWmPzdFh1dshmexTYqbMZvk8=
Address = 10.88.0.250/24
DNS = 1.1.1.1

[Peer]
PublicKey = uUACr1ZRHHNwZ3SrOCBx12uxOK4LWUpl8Ben0nJzREU=
Endpoint = 1.52.108.100:51820
AllowedIPs = 10.88.0.0/24
PersistentKeepalive = 25
"""
            with open(self.vpn_conf_path, "w", encoding="utf-8") as f:
                f.write(conf_content)
            self.log(f"Đã cập nhật cấu hình Tailscale VPN thật tại: {self.vpn_conf_path}", "SUCCESS")

            self.log(f"Đang kích hoạt Service Tailscale Tunnel từ {self.vpn_conf_path}...", "INFO")
            inst_res = subprocess.run([wg_exe, "/installtunnelservice", self.vpn_conf_path], capture_output=True, text=True)
            out_msg = (inst_res.stdout or inst_res.stderr or "").strip()

            if "Access is denied" in out_msg:
                self.log("❌ Lỗi Access is denied: Cần Run as Administrator trên Windows!", "ERROR")
                reply = QMessageBox.warning(
                    self, "Cần Quyền Administrator (Run as Administrator)",
                    "⚠️ Lỗi: Access is denied (Bị chối quyền hệ thống)\n\n"
                    "Bật Service Tailscale trên Windows bắt buộc ứng dụng phải chạy dưới quyền Admin:\n"
                    "1️⃣ Vui lòng tắt phần mềm -> Chuột phải chọn 'Run as Administrator' để ứng dụng tự bật VPN ngầm.\n"
                    "2️⃣ Hoặc MỞ ỨNG DỤNG WIREGUARD thủ công -> Bấm 'Add Tunnel' -> Chọn file:\n"
                    f"   {self.vpn_conf_path}"
                )
            else:
                self.log(f"Kết quả bật VPN: {out_msg or 'Service đã khởi chạy.'}", "SUCCESS")
                
                # Check IP after 2 seconds
                QTimer.singleShot(2000, self.detect_local_tools)
                new_ip = self.get_tailscale_local_ip() or "10.88.0.250 (Đang thiết lập...)"

                QMessageBox.information(
                    self, "THÔNG BÁO KẾT NỐI WIREGUARD VPN",
                    f"🟢 ĐÃ BẬT KẾT NỐI WIREGUARD VPN!\n\n"
                    f"• IP VPN Máy Tính Của Bạn: {new_ip}\n"
                    f"• Dải Mạng Quản Lý: 10.88.0.0/24\n"
                    f"• Trạng Thái: Đã sẵn sàng thông mạng tới tất cả Android Box!"
                )

    def handle_login(self):
        ts_ip = self.get_tailscale_local_ip()
        if not ts_ip:
            QMessageBox.critical(
                self, "Yêu cầu kết nối Tailscale VPN",
                "⚠️ BẮT BUỘC KẾT NỐI TAILSCALE VPN!\n\n"
                "Hệ thống đang hoạt động thuần trong dải mạng nội bộ Tailscale.\n"
                "Vui lòng bật ứng dụng Tailscale trên máy tính trước khi đăng nhập."
            )
            self.log("❌ Đăng nhập bị chặn: Máy tính chưa bật/kết nối mạng Tailscale VPN.", "ERROR")
            return

        username = self.txt_username.text().strip()
        password = self.txt_password.text().strip()
        server_input = self.txt_login_server_url.text().strip()
        if server_input:
            self.current_server_url = server_input

        if not username or not password:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập Tên đăng nhập và Mật khẩu!")
            return

        self.btn_login.setEnabled(False)
        self.statusBar.showMessage("Đang đăng nhập...")
        self.log(f"Đang gửi yêu cầu đăng nhập tài khoản '{username}' tới {self.current_server_url}...", "INFO")

        self.login_worker = ApiWorker(
            "/api/v1/auth/login",
            method="POST",
            data={"username": username, "password": password},
            server_url=self.current_server_url
        )
        self.login_worker.finished.connect(self.on_login_success)
        self.login_worker.error.connect(self.on_login_error)
        self.login_worker.start()

    def on_login_success(self, res):
        self.btn_login.setEnabled(True)
        self.token = res.get("access_token", "")
        user = res.get("user", {})
        display_name = user.get("display_name") or user.get("username")
        
        self.user_info_label.setText(f"👤 {display_name}")
        self.statusBar.showMessage("Đăng nhập thành công!")
        self.login_box.setTitle("1. Đã đăng nhập")
        
        self.log(f"✓ Đăng nhập THÀNH CÔNG tài khoản: {display_name}", "SUCCESS")
        
        # Show success notification
        QMessageBox.information(self, "THÔNG BÁO DỊCH VỤ", f"🎉 Đăng nhập hệ thống thành công!\nXin chào {display_name}.")

        self.btn_refresh.setEnabled(True)
        self.btn_discover.setEnabled(True)
        self.load_devices()
        self.discover_new_devices()
        self.timer.start(15000)

    def on_login_error(self, err_msg):
        self.btn_login.setEnabled(True)
        self.log(f"❌ Đăng nhập thất bại: {err_msg}", "ERROR")
        QMessageBox.critical(self, "Thất bại", f"Lỗi đăng nhập: {err_msg}")
        self.statusBar.showMessage(f"Đăng nhập thất bại: {err_msg}")

    def discover_new_devices(self):
        if not self.token:
            return
        self.log("🔍 Đang phát hiện thiết bị Tailscale mới kết nối...", "INFO")
        self.disc_worker = ApiWorker("/api/v1/provisioning/discover", method="POST", token=self.token, server_url=self.current_server_url)
        self.disc_worker.finished.connect(self.on_discover_success)
        self.disc_worker.error.connect(self.on_discover_error)
        self.disc_worker.start()

    def on_discover_success(self, res):
        created = res.get("created", [])
        updated = res.get("updated", [])
        if created:
            self.log(f"🎉 Phát hiện & đăng ký mới {len(created)} Box qua Tailscale: {', '.join(created)}", "SUCCESS")
            self.load_devices()
        elif updated:
            self.log(f"✓ Đã cập nhật trạng thái Tailscale cho {len(updated)} Box.", "INFO")
            self.load_devices()

    def on_discover_error(self, err_msg):
        self.log(f"⚠️ Không thể quét thiết bị mới: {err_msg}", "WARNING")

    def load_devices(self):
        if not self.token:
            return
        self.statusBar.showMessage("Đang tải danh sách thiết bị...")
        self.dev_worker = ApiWorker("/api/v1/devices", token=self.token, server_url=self.current_server_url)
        self.dev_worker.finished.connect(self.on_load_devices_success)
        self.dev_worker.error.connect(self.on_load_devices_error)
        self.dev_worker.start()

    def on_load_devices_success(self, res):
        self.is_populating = True
        self.devices = res
        self.table_devices.setRowCount(0)

        online_cnt = 0
        for row, dev in enumerate(self.devices):
            self.table_devices.insertRow(row)
            
            # Online Status Badge
            status = dev.get("status", "offline").upper()
            if status == "ONLINE":
                online_cnt += 1
            status_item = QTableWidgetItem(f"🟢 ONLINE" if status == "ONLINE" else "🔴 OFFLINE")
            status_item.setForeground(QColor("#10b981") if status == "ONLINE" else QColor("#ef4444"))
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.table_devices.setItem(row, 0, status_item)

            # Device Name (Editable)
            name = dev.get("device_name") or dev.get("device_uuid")
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() | Qt.ItemIsEditable)
            self.table_devices.setItem(row, 1, name_item)

            # MAC Address (Non-editable)
            mac = dev.get("mac_address") or dev.get("mac_wifi") or dev.get("mac_ethernet") or "—"
            mac_item = QTableWidgetItem(mac)
            mac_item.setFlags(mac_item.flags() & ~Qt.ItemIsEditable)
            self.table_devices.setItem(row, 2, mac_item)

            # Tailscale IP (Non-editable)
            ts_ip = dev.get("tailscale_ip") or dev.get("ts_ip") or "Chưa có IP"
            wg_item = QTableWidgetItem(ts_ip)
            wg_item.setFlags(wg_item.flags() & ~Qt.ItemIsEditable)
            self.table_devices.setItem(row, 3, wg_item)

            # Location / Site (Non-editable)
            loc = dev.get("location") or {}
            site = loc.get("site") or loc.get("customer") or "—"
            site_item = QTableWidgetItem(site)
            site_item.setFlags(site_item.flags() & ~Qt.ItemIsEditable)
            self.table_devices.setItem(row, 4, site_item)

            # ROM Version (Non-editable)
            rom = dev.get("rom_version") or "1.0.0"
            rom_item = QTableWidgetItem(rom)
            rom_item.setFlags(rom_item.flags() & ~Qt.ItemIsEditable)
            self.table_devices.setItem(row, 5, rom_item)

        self.is_populating = False
        self.btn_select_all.setEnabled(bool(self.devices))
        self.btn_export_csv.setEnabled(bool(self.devices))
        msg = f"Đã cập nhật {len(self.devices)} thiết bị ({online_cnt} Online)."
        self.statusBar.showMessage(msg)

    def filter_devices_table(self):
        query = self.txt_search_dev.text().strip().lower()
        for row in range(self.table_devices.rowCount()):
            match = False
            if not query:
                match = True
            else:
                for col in range(self.table_devices.columnCount()):
                    item = self.table_devices.item(row, col)
                    if item and query in item.text().lower():
                        match = True
                        break
            self.table_devices.setRowHidden(row, not match)

    def on_load_devices_error(self, err_msg):
        self.statusBar.showMessage(f"Lỗi tải danh sách: {err_msg}")
        self.log(f"Lỗi khi tải danh sách thiết bị từ server: {err_msg}", "ERROR")

    def on_cell_double_clicked(self, row, col):
        if col == 1:
            self.log(f"Người dùng click 2 lần vào ô tên thiết bị ở dòng {row+1} để chỉnh sửa.", "INFO")
            self.table_devices.editItem(self.table_devices.item(row, col))

    def on_item_changed(self, item):
        if self.is_populating or item.column() != 1:
            return
        row = item.row()
        if row < len(self.devices):
            new_name = item.text().strip()
            dev_id = self.devices[row].get("id")
            if dev_id and new_name:
                self.log(f"Chỉnh sửa trực tiếp trên bảng: Đổi tên Box ID {dev_id} thành '{new_name}'", "INFO")
                self.update_device_name_api(dev_id, new_name)

    def select_all_devices(self):
        self.table_devices.selectAll()
        self.log("Đã chọn toàn bộ danh sách Android Box trên bảng.", "INFO")

    def export_devices_csv(self):
        if not self.devices:
            QMessageBox.warning(self, "Cảnh báo", "Không có dữ liệu thiết bị để xuất CSV!")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Xuất danh sách Android Box sang CSV", "Danh_sach_Android_Box_TX3.csv", "CSV Files (*.csv)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "STT", "ID Thiết Bị", "Tên Box", "UUID", "Trạng Thái",
                    "IP Tailscale", "MAC WiFi", "MAC Ethernet", "Serial",
                    "Địa Điểm (Site)", "Phiên Bản ROM", "Cập Nhật Cuối"
                ])

                for idx, dev in enumerate(self.devices, 1):
                    status = dev.get("status", "offline").upper()
                    name = dev.get("device_name") or dev.get("device_uuid")
                    uuid = dev.get("device_uuid", "")
                    ts_ip = dev.get("ts_ip", "")
                    mac_wifi = dev.get("mac_wifi", "")
                    mac_eth = dev.get("mac_ethernet", "")
                    serial = dev.get("serial", "")
                    loc = dev.get("location") or {}
                    site = loc.get("site") or loc.get("customer") or "—"
                    rom = dev.get("rom_version", "1.0.0")
                    updated = dev.get("updated_at", "")

                    writer.writerow([
                        idx, dev.get("id", ""), name, uuid, status,
                        ts_ip, mac_wifi, mac_eth, serial,
                        site, rom, updated
                    ])

            self.log(f"✓ Xuất thành công danh sách {len(self.devices)} Box ra file CSV: {file_path}", "SUCCESS")
            QMessageBox.information(self, "XUẤT CSV THÀNH CÔNG", "📊 Đã xuất " + str(len(self.devices)) + " thiết bị ra file CSV")
        except Exception as e:
            self.log(f"❌ Lỗi xuất CSV: {str(e)}", "ERROR")
            msg_err = f"Không thể lưu file CSV: {str(e)}"
            QMessageBox.critical(self, "Lỗi xuất CSV", msg_err)
    def get_selected_devices_list(self):
        selected_rows = self.table_devices.selectionModel().selectedRows()
        selected_boxes = []
        for idx in selected_rows:
            row = idx.row()
            if row < len(self.devices):
                dev = self.devices[row]
                name = dev.get("device_name") or dev.get("device_uuid")
                ts_ip = dev.get("ts_ip")
                status = dev.get("status", "offline").upper()
                selected_boxes.append({
                    "dev": dev,
                    "row": row,
                    "name": name,
                    "ip": ts_ip,
                    "status": status
                })
        return selected_boxes

    def on_device_selected(self):
        selected_boxes = self.get_selected_devices_list()
        if not selected_boxes:
            self.selected_device = None
            self.btn_remote.setEnabled(False)
            self.btn_push.setEnabled(False)
            self.btn_save_name.setEnabled(False)
            self.lbl_selected_name.setText("Chưa chọn thiết bị nào")
            self.lbl_selected_detail.setText("Vui lòng chọn 1 hoặc nhiều Box trong danh sách bên trái (Giữ Ctrl / Shift để chọn nhiều Box).")
            self.txt_edit_name.setText("")
            return

        if len(selected_boxes) == 1:
            box = selected_boxes[0]
            self.selected_device = box["dev"]
            name = box["name"]
            ts_ip = box["ip"]
            status = box["status"]

            mac_wifi = self.selected_device.get("mac_wifi")
            mac_eth = self.selected_device.get("mac_ethernet")
            mac_str = mac_wifi or mac_eth or "N/A"

            self.lbl_selected_name.setText(f"📺 {name} [{status}]")
            self.txt_edit_name.setText(name)
            self.btn_save_name.setEnabled(True)

            msg_detail = f"• IP Tailscale: {ts_ip or 'N/A'}\n• Địa chỉ MAC: {mac_str}\n• Serial: {self.selected_device.get('serial') or 'N/A'}"
            self.lbl_selected_detail.setText(msg_detail)

            is_online = (status == "ONLINE") and (ts_ip is not None)
            self.btn_remote.setText("▶ Bắt đầu Remote Scrcpy (1 Box)")
            self.btn_remote.setEnabled(is_online)
            self.btn_push.setText("⚡ Truyền File sang Box (/sdcard/Download)")
            self.btn_push.setEnabled(is_online and bool(self.txt_filepath.text().strip()))
            self.log(f"Đã chọn thiết bị: {name} (IP: {ts_ip}, Trạng thái: {status})", "INFO")
        else:
            self.selected_device = None
            self.txt_edit_name.setText("")
            self.btn_save_name.setEnabled(False)

            online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
            total_cnt = len(selected_boxes)
            online_cnt = len(online_boxes)

            self.lbl_selected_name.setText(f"📺 Đã chọn NHIỀU THIẾT BỊ ({total_cnt} Box - {online_cnt} Online)")
            names_summary = ", ".join([b["name"] for b in selected_boxes[:4]])
            if total_cnt > 4:
                names_summary += f" và {total_cnt - 4} Box khác..."

            msg_detail2 = f"• Danh sách chọn: {names_summary}\n• Số Box Online có thể Remote / Truyền file: {online_cnt}/{total_cnt} Box"
            self.lbl_selected_detail.setText(msg_detail2)

            self.btn_remote.setText(f"▶ Bắt đầu Remote Scrcpy ({online_cnt} Box Cùng Lúc)")
            self.btn_remote.setEnabled(online_cnt > 0)
            self.btn_push.setText(f"⚡ Truyền File hàng loạt ({online_cnt} Box Online)")
            self.btn_push.setEnabled(online_cnt > 0 and bool(self.txt_filepath.text().strip()))
            self.log(f"Đã chọn đồng thời {total_cnt} thiết bị ({online_cnt} Box Online).", "INFO")

    
    def open_replace_device_dialog(self):
        if not self.selected_device:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn 1 Box cần thay thế trong danh sách bên trái!")
            return

        dlg = ReplaceDeviceDialog(self.selected_device, self.devices, self)
        if dlg.exec_() == QDialog.Accepted:
            new_mac = dlg.selected_mac
            dev_id = self.selected_device.get("id")
            dev_name = self.selected_device.get("device_name") or self.selected_device.get("device_uuid")

            reply = QMessageBox.question(
                self, "XÁC NHẬN ĐỔI MAC THIẾT BỊ",
                f"Bạn có chắc chắn muốn thay đổi địa chỉ MAC của Box '{dev_name}' sang MAC mới:\n\n👉 '{new_mac}' không?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.update_device_mac_api(dev_id, new_mac)

    def update_device_mac_api(self, dev_id, new_mac):
        self.statusBar.showMessage(f"Đang lưu địa chỉ MAC mới '{new_mac}' lên Server...")
        self.log(f"Gửi lệnh PATCH /api/v1/devices/{dev_id} để cập nhật MAC '{new_mac}'...", "INFO")
        self.mac_update_worker = ApiWorker(
            f"/api/v1/devices/{dev_id}",
            token=self.token,
            method="PATCH",
            data={"mac_address": new_mac}
        )
        def on_mac_success(res):
            self.statusBar.showMessage("Đã cập nhật địa chỉ MAC mới thành công!")
            self.log(f"✓ Thay đổi MAC thiết bị thành công: '{new_mac}'", "SUCCESS")
            QMessageBox.information(
                self, "THAY THẾ BOX THÀNH CÔNG",
                f"🎉 Đã cập nhật thành công địa chỉ MAC mới:\n\n👉 MAC: '{new_mac}'\n\nThiết bị mới đã sẵn sàng kết nối!"
            )
            self.load_devices()

        def on_mac_error(msg):
            self.log(f"❌ Thất bại khi cập nhật MAC: {msg}", "ERROR")
            QMessageBox.critical(self, "Lỗi thay thế MAC", f"Không thể cập nhật MAC: {msg}")
            self.load_devices()

        self.mac_update_worker.finished.connect(on_mac_success)
        self.mac_update_worker.error.connect(on_mac_error)
        self.mac_update_worker.start()

    def save_device_name_from_input(self):
        if not self.selected_device:
            return
        new_name = self.txt_edit_name.text().strip()
        dev_id = self.selected_device.get("id")
        if dev_id and new_name:
            self.log(f"Bấm nút 'Lưu Tên': Đổi tên Box thành '{new_name}'", "INFO")
            self.update_device_name_api(dev_id, new_name)

    def update_device_name_api(self, dev_id, new_name):
        self.statusBar.showMessage(f"Đang lưu tên mới '{new_name}' lên hệ thống...")
        self.log(f"Gửi lệnh PATCH /api/v1/devices/{dev_id} để lưu tên '{new_name}'...", "INFO")
        self.update_worker = ApiWorker(
            f"/api/v1/devices/{dev_id}",
            token=self.token,
            method="PATCH",
            data={"device_name": new_name}
        )
        def on_update_success(res):
            self.statusBar.showMessage("Đã đổi tên thiết bị thành công!")
            self.log(f"✓ Đổi tên thiết bị thành công: '{new_name}'", "SUCCESS")
            QMessageBox.information(self, "THÔNG BÁO THÀNH CÔNG", f"✏️ Đã đổi tên gợi nhớ của Box thành:\n\n'{new_name}'")
            self.load_devices()

        def on_update_error(msg):
            self.log(f"❌ Thất bại khi đổi tên: {msg}", "ERROR")
            QMessageBox.critical(self, "Lỗi đổi tên", msg)
            self.load_devices()

        self.update_worker.finished.connect(on_update_success)
        self.update_worker.error.connect(on_update_error)
        self.update_worker.start()

    def launch_scrcpy(self):
        selected_boxes = self.get_selected_devices_list()
        if not selected_boxes:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn ít nhất 1 Box!")
            return

        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi", "Không có Box nào đang ONLINE và có IP Tailscale trong danh sách đã chọn!")
            return

        if len(online_boxes) == 1:
            box = online_boxes[0]
            ts_ip = box["ip"]
            dev_name = box["name"]

            self.btn_remote.setEnabled(False)
            self.statusBar.showMessage(f"Đang kết nối ADB & mở Scrcpy tới {dev_name} ({ts_ip}:5555)... ")
            self.log(f"Khởi tạo tiến trình Remote Scrcpy tới {dev_name} ({ts_ip}:5555)...", "ADB")

            self.scrcpy_worker = LaunchScrcpyWorker(ts_ip, dev_name, scrcpy_cmd=self.scrcpy_bin, adb_cmd=self.adb_bin)
            self.scrcpy_worker.progress.connect(lambda msg: self.log(msg, "ADB"))
            self.scrcpy_worker.finished.connect(self.on_scrcpy_finished)
            self.scrcpy_worker.start()
        else:
            is_master_slave = self.chk_master_slave.isChecked()
            if is_master_slave:
                master_box = online_boxes[0]
                slave_boxes = online_boxes[1:]
                self.log(f"🚀 Bắt đầu MỞ ĐỒNG BỘ MASTER-SLAVE cho {len(online_boxes)} Box (1 Master Màn Lớn + {len(slave_boxes)} Slaves)...", "INFO")
                
                # Launch Master Box Window (Large Size: 960px width)
                m_ip = master_box["ip"]
                m_name = master_box["name"]
                self.log(f"⭐ Khởi chạy MASTER BOX (Màn Lớn): {m_name} ({m_ip}:5555)", "ADB")
                m_worker = LaunchScrcpyWorker(m_ip, m_name, scrcpy_cmd=self.scrcpy_bin, adb_cmd=self.adb_bin, width=960, title_prefix="👑 MASTER: ")
                m_worker.progress.connect(lambda msg: self.log(msg, "ADB"))
                m_worker.start()

                # Launch Slave Box Windows (Compact Size: 360px width)
                opened_slaves = 0
                for s_box in slave_boxes:
                    s_ip = s_box["ip"]
                    s_name = s_box["name"]
                    self.log(f"📱 Khởi chạy SLAVE BOX (Màn Nhỏ): {s_name} ({s_ip}:5555)", "ADB")
                    s_worker = LaunchScrcpyWorker(s_ip, s_name, scrcpy_cmd=self.scrcpy_bin, adb_cmd=self.adb_bin, width=360, title_prefix="📱 SLAVE: ")
                    s_worker.progress.connect(lambda msg: self.log(msg, "ADB"))
                    s_worker.start()
                    opened_slaves += 1

                QMessageBox.information(
                    self, "CHẾ ĐỘ ĐIỀU KHIỂN ĐỒNG BỘ MASTER - SLAVE",
                    f"👑 MASTER Box: '{m_name}' (Màn hình lớn)\n📱 SLAVE Boxes: {opened_slaves} Box (Màn hình nhỏ)\n\n⚡ Dùng Bảng Điều Khiển Đồng Bộ Realtime bên phải để phát lệnh cùng lúc tới tất cả các Box!"
                )
            else:
                self.log(f"🚀 Bắt đầu mở Remote Scrcpy ĐỒNG THỜI cho {len(online_boxes)} Box...", "INFO")
                opened_count = 0
                for box in online_boxes:
                    ts_ip = box["ip"]
                    dev_name = box["name"]
                    self.log(f"[ADB & Scrcpy] Mở cửa sổ Remote cho {dev_name} ({ts_ip}:5555)...", "ADB")
                    worker = LaunchScrcpyWorker(ts_ip, dev_name, scrcpy_cmd=self.scrcpy_bin, adb_cmd=self.adb_bin)
                    worker.progress.connect(lambda msg: self.log(msg, "ADB"))
                    worker.start()
                    opened_count += 1
                
                QMessageBox.information(
                    self, "MỞ REMOTE SCRCPY HÀNG LOẠT",
                    f"📺 Đã khởi chạy đồng thời {opened_count} cửa sổ Remote Scrcpy cho các Box đã chọn!"
                )

    def on_scrcpy_finished(self, success, message, detail):
        self.btn_remote.setEnabled(True)
        self.statusBar.showMessage(message)
        if success:
            self.log(f"✓ {message}", "SUCCESS")
            msg_box = f"📺 {message}\n\nMàn hình điều khiển realtime của Box đã xuất hiện!"
            QMessageBox.information(self, "THÔNG BÁO REMOTE SCRCPY", msg_box)
        else:
            self.log(f"❌ {message} (Chi tiết: {detail})", "ERROR")
            msg_box = f"{message}\n\nChi tiết kỹ thuật:\n{detail}"
            QMessageBox.critical(self, "Lỗi điều khiển Remote", msg_box)
    def browse_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Chọn file để gửi sang Box", "", "All Files (*)")
        if filepath:
            self.txt_filepath.setText(filepath)
            self.log(f"Đã chọn file từ máy tính: {filepath}", "INFO")
            selected_boxes = self.get_selected_devices_list()
            online_cnt = len([b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]])
            if online_cnt > 0:
                self.btn_push.setEnabled(True)
    def push_file(self):
        filepath = self.txt_filepath.text().strip()
        remote_dir = self.cbo_remote_dir.currentText().strip() or "/sdcard/Download"
        if not filepath or not os.path.exists(filepath):
            QMessageBox.warning(self, "Lỗi", "File không tồn tại!")
            return
        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn ít nhất 1 Box đang ONLINE để truyền file!")
            return
        self.btn_push.setEnabled(False)
        filename = os.path.basename(filepath)
        if len(online_boxes) == 1:
            box = online_boxes[0]
            ts_ip = box["ip"]
            dev_name = box["name"]
            self.log(f"Bắt đầu truyền file '{filename}' sang Box '{dev_name}' ({ts_ip}:{remote_dir})...", "ADB")
            self.push_worker = PushFileWorker(ts_ip, filepath, remote_dir=remote_dir, adb_cmd=self.adb_bin)
            self.push_worker.progress.connect(lambda msg: self.log(msg, "ADB"))
            self.push_worker.finished.connect(self.on_push_finished)
            self.push_worker.start()
        else:
            self.log(f"Bắt đầu truyền file '{filename}' HÀNG LOẠT sang {len(online_boxes)} Box Online...", "ADB")
            self.multi_push_worker = MultiPushWorker(online_boxes, filepath, adb_cmd=self.adb_bin)
            self.multi_push_worker.progress.connect(lambda msg, cur, tot: self.log(f"[Multi-Push {cur}/{tot}] {msg}", "ADB"))
            self.multi_push_worker.finished.connect(self.on_multi_push_finished)
            self.multi_push_worker.start()
    def on_push_finished(self, success, message, detail):
        self.btn_push.setEnabled(True)
        if success:
            self.log(f"✓ {message}", "SUCCESS")
            msg_box = f"⚡ {message}\n\nFile đã nằm trong thư mục /sdcard/Download/ của Android Box!"
            QMessageBox.information(self, "THÀNH CÔNG TRUYỀN FILE", msg_box)
            self.statusBar.showMessage("Đã truyền file thành công!")
        else:
            self.log(f"❌ {message} (Chi tiết: {detail})", "ERROR")
            msg_box = f"{message}\n\nChi tiết lỗi:\n{detail}"
            QMessageBox.critical(self, "Thất bại truyền file", msg_box)
            self.statusBar.showMessage("Truyền file thất bại.")
    def on_multi_push_finished(self, success, summary, results):
        self.btn_push.setEnabled(True)
        self.statusBar.showMessage(summary)
        self.log(f"✓ {summary}", "SUCCESS" if success else "WARNING")
        details_list = []
        for name, ip, res, err in results:
            status_txt = "✅ Thành công" if res else f"❌ Lỗi: {err}"
            details_list.append(f"• {name} ({ip}): {status_txt}")
        details_str = "\n".join(details_list)
        msg_box = f"⚡ {summary}\n\nChi tiết từng Box:\n{details_str}"
        QMessageBox.information(
            self, "KẾT QUẢ TRUYỀN FILE HÀNG LOẠT", msg_box
        )

    def run_batch_reboot(self):
        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Reboot", "Vui lòng chọn ít nhất 1 Box đang ONLINE để Reboot!")
            return
        
        reply = QMessageBox.question(
            self, "XÁC NHẬN REBOOT HÀNG LOẠT",
            f"Bạn có chắc chắn muốn REBOOT đồng thời {len(online_boxes)} Box Android đã chọn không?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.log(f"[Batch ADB] Gửi lệnh REBOOT HÀNG LOẠT tới {len(online_boxes)} Box Online...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="reboot", adb_cmd=self.adb_bin)
        self.batch_adb_worker.progress.connect(lambda msg, c, t: self.log(f"[Reboot {c}/{t}] {msg}", "ADB"))
        self.batch_adb_worker.finished.connect(self.on_batch_adb_finished)
        self.batch_adb_worker.start()

    def run_batch_clear_cache(self):
        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Dọn Rác", "Vui lòng chọn ít nhất 1 Box đang ONLINE để dọn dẹp!")
            return

        self.log(f"[Batch ADB] Gửi lệnh dọn rác /sdcard/Download/ hàng loạt tới {len(online_boxes)} Box...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="clear_cache", adb_cmd=self.adb_bin)
        self.batch_adb_worker.progress.connect(lambda msg, c, t: self.log(f"[Clear {c}/{t}] {msg}", "ADB"))
        self.batch_adb_worker.finished.connect(self.on_batch_adb_finished)
        self.batch_adb_worker.start()

    def run_batch_install_apk(self):
        filepath = self.txt_filepath.text().strip()
        if not filepath or not os.path.exists(filepath) or not filepath.lower().endswith('.apk'):
            QMessageBox.warning(self, "Lỗi Cài APK", "Vui lòng chọn một file .apk hợp lệ!")
            return

        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Cài APK", "Vui lòng chọn ít nhất 1 Box đang ONLINE để cài APK!")
            return

        filename = os.path.basename(filepath)
        self.log(f"[Batch ADB] Gửi lệnh CÀI NGẦM APK '{filename}' hàng loạt tới {len(online_boxes)} Box...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="install_apk", apk_path=filepath, adb_cmd=self.adb_bin)
        self.batch_adb_worker.progress.connect(lambda msg, c, t: self.log(f"[Install APK {c}/{t}] {msg}", "ADB"))
        self.batch_adb_worker.finished.connect(self.on_batch_adb_finished)
        self.batch_adb_worker.start()

    
    def run_batch_disable_yt_voice(self):
        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Tắt Tiếng Youtube", "Vui lòng chọn ít nhất 1 Box đang ONLINE!")
            return

        cmd = "pm disable --user 0 com.kingroot.kinguser/com.kingroot.common.utils.system.monitor.top.TopAppMonitorAccessibilityService && settings delete secure enabled_accessibility_services && settings put secure accessibility_enabled 0"
        self.log(f"[Batch ADB] Gửi lệnh TẮT TIẾNG ĐỌC YOUTUBE hàng loạt tới {len(online_boxes)} Box Online...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="custom", custom_cmd=cmd, adb_cmd=self.adb_bin)
        self.batch_adb_worker.progress.connect(lambda msg, c, t: self.log(f"[Tắt Tiếng YT {c}/{t}] {msg}", "ADB"))
        self.batch_adb_worker.finished.connect(self.on_batch_adb_finished)
        self.batch_adb_worker.start()

    def run_batch_custom_adb(self):
        cmd = self.txt_custom_adb.text().strip()
        if not cmd:
            QMessageBox.warning(self, "Lỗi Lệnh Custom", "Vui lòng nhập lệnh ADB Shell tùy chỉnh!")
            return

        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Lệnh Custom", "Vui lòng chọn ít nhất 1 Box đang ONLINE!")
            return

        self.log(f"[Batch ADB] Gửi lệnh custom '{cmd}' tới {len(online_boxes)} Box...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="custom", custom_cmd=cmd, adb_cmd=self.adb_bin)
        self.batch_adb_worker.progress.connect(lambda msg, c, t: self.log(f"[Custom ADB {c}/{t}] {msg}", "ADB"))
        self.batch_adb_worker.finished.connect(self.on_batch_adb_finished)
        self.batch_adb_worker.start()

    def on_batch_adb_finished(self, success, summary, results):
        self.statusBar.showMessage(summary)
        self.log(f"✓ {summary}", "SUCCESS" if success else "WARNING")
        details_list = []
        for name, ip, res, err in results:
            status_txt = "✅ THÀNH CÔNG" if res else f"❌ LỖI: {err}"
            details_list.append(f"• {name} ({ip}): {status_txt}")
        details_str = "\n".join(details_list)
        msg_box = f"⚡ {summary}\n\nChi tiết từng Box:\n{details_str}"

        QMessageBox.information(self, "KẾT QUẢ THỰC THI LỆNH ADB HÀNG LOẠT", msg_box)

    def test_telegram_alert(self):
        token = self.txt_tele_token.text().strip()
        chatid = self.txt_tele_chatid.text().strip()
        if not token or not chatid:
            QMessageBox.warning(self, "Lỗi Telegram", "Vui lòng nhập Bot Token và Chat ID!")
            return
        
        msg = f"🧪 <b>TEST THÔNG BÁO TELEGRAM FROM TX3 MANAGER</b>\n\nHệ thống quản lý Android Box đang thử nghiệm tính năng cảnh báo tự động!\n⏱ Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        self.log(f"Đang gửi thông báo thử nghiệm tới Telegram Chat ID: {chatid}...", "INFO")
        self.tele_worker = TelegramWorker(token, chatid, msg)
        self.tele_worker.finished.connect(lambda ok, m: QMessageBox.information(self, "Telegram Result", m) if ok else QMessageBox.critical(self, "Telegram Error", m))
        self.tele_worker.start()


    def send_sync_key(self, keycode):
        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Đồng Bộ", "Vui lòng chọn ít nhất 1 Box đang ONLINE!")
            return
        cmd = f"input keyevent {keycode}"
        self.log(f"[Sync Input] Gửi phím (Keycode {keycode}) tới {len(online_boxes)} Box...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="custom", custom_cmd=cmd, adb_cmd=self.adb_bin)
        self.batch_adb_worker.start()

    def send_sync_text_action(self):
        text_val = self.txt_sync_text.text().strip()
        if not text_val:
            QMessageBox.warning(self, "Lỗi Văn Bản", "Vui lòng nhập nội dung chữ cần đồng bộ!")
            return
        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Đồng Bộ", "Vui lòng chọn ít nhất 1 Box đang ONLINE!")
            return
        
        # Escape spaces for ADB input text
        escaped_text = text_val.replace(" ", "%s")
        cmd = f"input text '{escaped_text}'"
        self.log(f"[Sync Input] Gửi đoạn chữ '{text_val}' tới {len(online_boxes)} Box...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="custom", custom_cmd=cmd, adb_cmd=self.adb_bin)
        self.batch_adb_worker.start()

    def send_sync_tap_action(self):
        x = self.txt_tap_x.text().strip()
        y = self.txt_tap_y.text().strip()
        if not x.isdigit() or not y.isdigit():
            QMessageBox.warning(self, "Lỗi Tọa Độ", "Tọa độ X và Y phải là số nguyên hợp lệ!")
            return
        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Đồng Bộ", "Vui lòng chọn ít nhất 1 Box đang ONLINE!")
            return
        cmd = f"input tap {x} {y}"
        self.log(f"[Sync Input] Click tọa độ ({x}, {y}) trên {len(online_boxes)} Box...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="custom", custom_cmd=cmd, adb_cmd=self.adb_bin)
        self.batch_adb_worker.start()

    def send_sync_swipe(self, swipe_params):
        selected_boxes = self.get_selected_devices_list()
        online_boxes = [b for b in selected_boxes if b["status"] == "ONLINE" and b["ip"]]
        if not online_boxes:
            QMessageBox.warning(self, "Lỗi Đồng Bộ", "Vui lòng chọn ít nhất 1 Box đang ONLINE!")
            return
        cmd = f"input swipe {swipe_params}"
        self.log(f"[Sync Input] Lệnh vuốt màn hình '{cmd}' trên {len(online_boxes)} Box...", "ADB")
        self.batch_adb_worker = BatchAdbWorker(online_boxes, cmd_type="custom", custom_cmd=cmd, adb_cmd=self.adb_bin)
        self.batch_adb_worker.start()



if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = TX3ControllerApp()
    window.show()
    sys.exit(app.exec_())

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path


KNOWN_PATHS = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Amlogic" / "USB_Burning_Tool" / "USB_Burning_Tool.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Amlogic" / "USB_Burning_Tool" / "USB_Burning_Tool.exe",
)


def _user32():
    api = ctypes.windll.user32
    api.GetDlgItem.argtypes = (wintypes.HWND, ctypes.c_int)
    api.GetDlgItem.restype = wintypes.HWND
    api.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    api.SendMessageW.restype = wintypes.LPARAM
    api.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    api.PostMessageW.restype = wintypes.BOOL
    api.IsWindow.argtypes = (wintypes.HWND,)
    api.IsWindow.restype = wintypes.BOOL
    return api


def detect_tool():
    for path in KNOWN_PATHS:
        if path.is_file():
            return str(path)
    return ""


def _windows_for_pid(pid=None, title_contains=None, class_name=None):
    user32 = _user32()
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if pid is not None and process_id.value != pid:
            return True
        if title_contains and title_contains.lower() not in title.value.lower():
            return True
        if class_name and cls.value != class_name:
            return True
        windows.append(hwnd)
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return windows


def _find_descendant_edit(parent):
    user32 = _user32()
    edits = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value == "Edit" and user32.IsWindowEnabled(hwnd):
            edits.append(hwnd)
        return True

    user32.EnumChildWindows(parent, callback_type(callback), 0)
    return edits[-1] if edits else None


def launch_and_import(tool_path, image_path, progress=None):
    tool = Path(tool_path)
    image = Path(image_path).resolve()
    if not tool.is_file():
        raise FileNotFoundError("Không tìm thấy USB Burning Tool")
    if not image.is_file():
        raise FileNotFoundError("Không tìm thấy ROM vừa đóng gói")
    if progress:
        progress(5, "Đang mở USB Burning Tool")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen([str(tool)], cwd=str(tool.parent), creationflags=creationflags)
    main_window = None
    deadline = time.time() + 20
    while time.time() < deadline:
        candidates = _windows_for_pid(process.pid)
        if not candidates and process.poll() is not None:
            # OnlyOne versions forward focus to an existing instance.
            candidates = _windows_for_pid(title_contains="USB_Burning_Tool")
        if candidates:
            main_window = candidates[0]
            break
        time.sleep(.25)
    if not main_window:
        raise RuntimeError("USB Burning Tool đã mở nhưng không tìm thấy cửa sổ chính. Hãy đóng phiên bản đang chạy và thử lại.")
    if progress:
        progress(30, "Đang mở hộp thoại Import Image")
    # MFC command ID from USB Burning Tool 2.0.5.x English resource.
    user32 = _user32()
    if not user32.PostMessageW(main_window, 0x0111, 0x800D, 0):
        raise RuntimeError("Windows chặn lệnh Import Image. Hãy chạy ROM Builder bằng quyền Administrator.")
    dialog = None
    deadline = time.time() + 12
    while time.time() < deadline:
        candidates = _windows_for_pid(process.pid, class_name="#32770")
        if not candidates:
            candidates = _windows_for_pid(class_name="#32770")
        for hwnd in candidates:
            if _find_descendant_edit(hwnd):
                dialog = hwnd
                break
        if dialog:
            break
        time.sleep(.2)
    if not dialog:
        raise RuntimeError("Không mở được hộp thoại Import Image. Có thể phiên bản USB Burning Tool không tương thích tự động hóa.")
    edit = _find_descendant_edit(dialog)
    if not edit:
        raise RuntimeError("Không tìm thấy ô nhập đường dẫn ROM")
    if progress:
        progress(60, "Đang điền ROM mới")
    image_text = ctypes.create_unicode_buffer(str(image))
    user32.SendMessageW(edit, 0x000C, 0, ctypes.cast(image_text, ctypes.c_void_p).value)
    open_button = user32.GetDlgItem(dialog, 1)
    if not open_button:
        raise RuntimeError("Không tìm thấy nút Open trong hộp thoại Import Image")
    user32.SendMessageW(open_button, 0x00F5, 0, 0)
    deadline = time.time() + 15
    while time.time() < deadline and user32.IsWindow(dialog):
        time.sleep(.2)
    if user32.IsWindow(dialog):
        raise RuntimeError("USB Burning Tool chưa chấp nhận đường dẫn ROM")
    if progress:
        progress(100, "Đã chuyển ROM sang USB Burning Tool")
    return True

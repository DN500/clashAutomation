r"""
Herta Capture v5.3 - hotkey screenshot + text detection (OCR) + image auto-clicker
Purple theme inspired by The Herta (Honkai: Star Rail).

New in v5.3:
  * LOADING SCREEN: your picture + fake little Python log (bottom-left) + "Loading" bar.
    Put loading_bg.png (or .jpg/.webp) next to the app to change its picture.
    Settings for it (size, time, position, log text) are at the top of class SplashScreen.

New in v5.2:
  * Each click point has its OWN repeat count (the number next to it in the sequence)
  * DISCORD WEBHOOK: when a round (the whole sequence) finishes, a screenshot of the loot
    screen + round info is sent to your Discord channel

New in v5.1:
  * CLICK POINT steps: "◎ Add click point" lets you click one exact spot on the screen
    (or inside the target window). It becomes a block in the Auto Click sequence, just
    like an image step. A crosshair + live coordinates follow the mouse while picking,
    and click a point's row (or "Show points") to flash a marker on the real screen.

From v5:
  * Auto click SEQUENCE: add several click images, they are clicked in order
    (loop / delay after click / skip a step after X seconds)
  * "Always scroll down" toggle for auto click (optionally only while the image isn't found)
  * Real glass UI: panels are see-through (Settings > Panel transparency) and the whole
    software can fade too (Whole window transparency). Black corners are gone.
  * Default theme: Settings > "Save current look as default" -> everyone who downloads the
    app starts with YOUR picture + position + transparency
  * Collapsible sections (hotkey, capture mode, target, auto click ...) + Collapse all
  * Capture / Play buttons and the status line are always visible at the top

Install (only needed when running the .py directly):
    py -3.12 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install customtkinter keyboard mss pillow numpy opencv-python-headless rapidocr-onnxruntime pytesseract

Run:
    .\.venv\Scripts\python.exe hreg.py
"""
import atexit
import copy
import ctypes
import json
import os
import shutil
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk
import keyboard
import mss
import numpy as np
import tkinter as tk
from PIL import Image, ImageDraw, ImageEnhance, ImageTk

# Make Windows report real pixel sizes (fixes blurry UI + wrong crop on scaled displays)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# ---------- Win32 helpers (window listing + capture) ----------
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

SKIP_TITLES = {"Program Manager", "Windows Input Experience"}

# --- embedding (SetParent) helpers ---
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.SetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]

# --- mouse helpers (auto click) ---
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD] * 4 + [ctypes.c_size_t]

_GetLong = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_SetLong = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_GetLong.argtypes = [wintypes.HWND, ctypes.c_int]
_GetLong.restype = ctypes.c_ssize_t
_SetLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_SetLong.restype = ctypes.c_ssize_t

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_VISIBLE, WS_CLIPSIBLINGS = 0x40000000, 0x10000000, 0x04000000
# popup | caption | thickframe | sysmenu | minimize | maximize
WS_STRIP = 0x80000000 | 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000
# dlgmodalframe | windowedge | clientedge | staticedge | appwindow
EX_STRIP = 0x00000001 | 0x00000100 | 0x00000200 | 0x00020000 | 0x00040000

_EMBEDDED = {}  # hwnd -> original style info (so we can always put windows back)


def get_style(hwnd, idx):
    return _GetLong(hwnd, idx) & 0xFFFFFFFF


def set_style(hwnd, idx, value):
    _SetLong(hwnd, idx, value & 0xFFFFFFFF)


def restore_window(hwnd, info):
    """Give an embedded window back to the desktop with its original look/position."""
    try:
        if user32.IsWindow(hwnd):
            user32.SetParent(hwnd, None)
            set_style(hwnd, GWL_STYLE, info["style"])
            set_style(hwnd, GWL_EXSTYLE, info["ex"])
            x, y, w, h = info["rect"]
            user32.SetWindowPos(hwnd, None, x, y, w, h, 0x0004 | 0x0020 | 0x0040)
    except Exception:
        pass
    finally:
        _EMBEDDED.pop(hwnd, None)


@atexit.register
def _release_all_embedded():
    # If the app exits normally, never leave a window stuck inside a dead parent.
    for h, info in list(_EMBEDDED.items()):
        restore_window(h, info)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def exe_of_pid(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


def list_windows(exclude_pid=0):
    """Visible, titled top-level windows with the exe that owns them."""
    out = []

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            ex = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            if (ex & 0x80) and not (ex & 0x40000):  # tool window without app-window flag
                return True
            cloaked = wintypes.DWORD(0)
            dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)  # DWMWA_CLOAKED
            if cloaked.value:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == exclude_pid:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            if title in SKIP_TITLES:
                return True
            exe = exe_of_pid(pid.value)
            if not exe:
                return True
            rc = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rc))
            area = max(rc.right, 0) * max(rc.bottom, 0)
            out.append({"hwnd": hwnd, "title": title, "exe": exe, "area": area})
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def _printwindow(hwnd, w, h):
    """Capture a window's client area even if other windows cover it."""
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    try:
        old = gdi32.SelectObject(mem, bmp)
        ok = user32.PrintWindow(hwnd, mem, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
        gdi32.SelectObject(mem, old)  # bitmap must be deselected before GetDIBits
        if not ok:
            return None
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(hdc, bmp, 0, h, buf, ctypes.byref(bmi), 0):
            return None
        return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)


def grab_window(hwnd):
    """Client-area screenshot of a window. None if closed/minimized."""
    if not hwnd or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w < 2 or h < 2:
        return None
    img = None
    try:
        img = _printwindow(hwnd, w, h)
    except Exception:
        img = None
    if img is None or img.getbbox() is None:  # failed or all black -> fall back to screen rect
        try:
            pt = wintypes.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            with mss.mss() as s:
                shot = s.grab({"left": pt.x, "top": pt.y, "width": w, "height": h})
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception:
            return None
    return img


def client_origin(hwnd):
    """Screen position of a window's client-area top-left corner."""
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def top_hwnd(widget):
    """The real top-level Win32 window of a Tk window."""
    return user32.GetAncestor(widget.winfo_id(), 2)  # GA_ROOT


def mouse_click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    time.sleep(0.03)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up


def mouse_scroll_down(x, y, notches):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    for _ in range(max(int(notches), 1)):
        user32.mouse_event(0x0800, 0, 0, (-120) & 0xFFFFFFFF, 0)  # wheel down
        time.sleep(0.03)


def point_hits_window(x, y, hwnd):
    """True if the pixel at (x, y) really belongs to hwnd's window (not covered by another)."""
    try:
        top = user32.GetAncestor(hwnd, 2)  # GA_ROOT
        under = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        return bool(under) and user32.GetAncestor(under, 2) == top
    except Exception:
        return True


def send_webhook(url, text, img=None):
    """Post a message (+ optional screenshot) to a Discord webhook. Raises on failure."""
    import io
    import urllib.request
    import uuid
    payload = json.dumps({"content": text, "username": "Herta Capture"})
    headers = {"User-Agent": "HertaCapture/5.2"}  # Discord rejects the default Python agent
    if img is None:
        body = payload.encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=90)
        boundary = uuid.uuid4().hex
        body = b"".join([
            (f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
             f'Content-Type: application/json\r\n\r\n{payload}\r\n').encode("utf-8"),
            (f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; '
             f'filename="loot.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode("utf-8"),
            buf.getvalue(),
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ])
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=20).read()


def webhook_ok(url):
    return url.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                           "https://canary.discord.com/api/webhooks/", "https://ptb.discord.com/api/webhooks/"))


# ---------- Paths (work both as .py and as a built .exe) ----------
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)          # settings/screenshots live next to the exe
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)             # files bundled inside the exe

SAVE_DIR = os.path.join(APP_DIR, "screenshots")
TEMPLATE_DIR = os.path.join(APP_DIR, "click_images")
CFG_PATH = os.path.join(APP_DIR, "settings.json")
THEME_FILE = "default_theme.json"
BG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
os.makedirs(SAVE_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)


def find_default_bg():
    """The picture that ships with the app (default_bg.png/.jpg/...)."""
    for base in (APP_DIR, RES_DIR):
        for ext in BG_EXTS:
            p = os.path.join(base, "default_bg" + ext)
            if os.path.exists(p):
                return p
    return ""


def find_splash_bg():
    """loading_bg.png/.jpg next to the exe wins. Swap it any time. Falls back to the default picture."""
    for base in (APP_DIR, RES_DIR):
        for ext in BG_EXTS:
            p = os.path.join(base, "loading_bg" + ext)
            if os.path.exists(p):
                return p
    return find_default_bg()


def apply_icon(win):
    """Window/taskbar icon: icon.ico next to the exe wins (edit it any time, no rebuild)."""
    def go():
        for base in (APP_DIR, RES_DIR):
            p = os.path.join(base, "icon.ico")
            if os.path.exists(p):
                try:
                    win.iconbitmap(p)
                    return
                except Exception:
                    pass
    win.after(300, go)  # CTk sets its own icon first, so we go after it


# ---------- Theme ----------
BG = "#140B24"
PANEL = "#1F1236"
PANEL_RGB = (0x1F, 0x12, 0x36)
PANEL_2 = "#2A1A4A"
ACCENT = "#9B5DE5"
ACCENT_HOVER = "#B983FF"
LILAC = "#D8B4FE"
TEXT = "#EDE3FF"
MUTED = "#9C8AB8"
DANGER = "#8E2F66"
GOOD = "#3F7D5A"
KEY = "#010101"  # "see-through" colour: anything painted in it becomes a window hole

TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

DEFAULTS = {
    "always_on_top": False,
    "opacity": 1.0,             # whole window (1 = solid)
    "panel_transparency": 0.30, # glass panels (0 = solid panels, 1 = invisible panels)
    "glass": True,              # see-through UI (restart after changing)
    "bg_path": "",              # "" = default picture, "none" = no picture, else a file path
    "dim": 0.55,
    "bg_x": 0.5,                # background character position (0 = left, 1 = right)
    "bg_y": 0.5,                # (0 = top, 1 = bottom)
    "bg_zoom": 1.0,             # 1 = fit, bigger = zoom in
    "autosave": True,
    "autocopy": True,
    "text_collapsed": False,
    "hotkey": "f8",
    "mode": "Region",
    "engine": "RapidOCR",
    "target_exe": "",
    "window_region": False,     # Window mode: drag a region inside the window -> click image
    "template": "",             # selected click image (file name without .png)
    "sequence": [],             # ordered steps: image names (str) or click points (dict)
    "loop_sequence": True,
    "click_delay": 0.5,         # seconds to wait after a click before the next step
    "webhook_on": False,        # send the loot to Discord when a round finishes
    "webhook_url": "",          # Discord webhook URL (keep private - it's in settings.json)
    "webhook_delay": 1.5,       # seconds to wait after the last click before the loot screenshot
    "step_timeout": 0.0,        # skip a step if not found after X sec (0 = never)
    "always_scroll": False,     # scroll down while auto-clicking
    "scroll_only_missing": False,
    "scroll_amount": 3,
    "click_hotkey": "f9",       # play / pause auto click
    "click_interval": 1.0,      # seconds between searches
    "click_threshold": 0.85,    # match accuracy needed to click
    "collapsed": {},            # which left-panel sections are folded
}
THEME_KEYS = ["dim", "bg_x", "bg_y", "bg_zoom", "opacity", "panel_transparency"]
MODES = ["Screen", "Region", "Window"]
NONE_LABEL = "— none —"


def load_cfg():
    cfg = copy.deepcopy(DEFAULTS)
    # shipped default look (made with Settings > Save current look as default)
    for base in (RES_DIR, APP_DIR):
        try:
            with open(os.path.join(base, THEME_FILE), "r", encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if k in THEME_KEYS:
                        cfg[k] = v
        except Exception:
            pass
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    if cfg["mode"] not in MODES:
        cfg["mode"] = "Region"
    cfg["bg_zoom"] = max(float(cfg["bg_zoom"]), 1.0)
    if not isinstance(cfg.get("collapsed"), dict):
        cfg["collapsed"] = {}
    if not isinstance(cfg.get("sequence"), list):
        cfg["sequence"] = []
    # keep image names (str) and click points (dict); drop anything else
    cfg["sequence"] = [s for s in cfg["sequence"]
                       if isinstance(s, str) or (isinstance(s, dict) and s.get("type") == "point")]
    return cfg


def cover(img, size, dim=0.0, fx=0.5, fy=0.5, zoom=1.0):
    """Scale + crop img to fill size. fx/fy pick which part stays visible, zoom enlarges."""
    w, h = max(int(size[0]), 1), max(int(size[1]), 1)
    r = max(w / img.width, h / img.height) * max(zoom, 1.0)
    nw, nh = int(img.width * r) + 1, int(img.height * r) + 1
    im = img.resize((nw, nh), Image.BICUBIC)
    left = int((nw - w) * min(max(fx, 0.0), 1.0))
    top = int((nh - h) * min(max(fy, 0.0), 1.0))
    im = im.crop((left, top, left + w, top + h)).convert("RGB")
    if dim > 0:
        im = Image.blend(im, Image.new("RGB", (w, h), BG), min(dim, 0.95))
    return im


def rounded_mask(w, h, radius, alpha):
    """Anti-aliased rounded-rectangle mask, scaled by alpha (0..1)."""
    s = 3
    m = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=255)
    m = m.resize((w, h), Image.LANCZOS)
    if alpha < 1.0:
        m = m.point(lambda v: int(v * alpha))
    return m


def make_cimg(widget, pil_img):
    try:
        scale = widget._get_widget_scaling()
    except Exception:
        scale = 1.0
    size = (max(int(pil_img.width / scale), 1), max(int(pil_img.height / scale), 1))
    return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)


def clean_name(s):
    s = "".join(c for c in s.strip() if c.isalnum() or c in " -_").strip()
    return s[:40]


# ---------- OCR engines (switchable on the spot) ----------
class OCRManager:
    def __init__(self):
        self._rapid = None

    def run(self, img: Image.Image, engine: str) -> str:
        if engine == "RapidOCR":
            return self._rapidocr(img)
        return self._tesseract(img)

    def _rapidocr(self, img):
        if self._rapid is None:
            from rapidocr_onnxruntime import RapidOCR
            self._rapid = RapidOCR()
        result, _ = self._rapid(np.array(img.convert("RGB")))
        if not result:
            return ""
        return "\n".join(item[1] for item in result)

    def _tesseract(self, img):
        import pytesseract
        for p in TESSERACT_PATHS:
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break
        return pytesseract.image_to_string(img).strip()


# ---------- Loading screen ----------
class SplashScreen(tk.Toplevel):
    W, H = 720, 400          # size of the loading window
    SECONDS = 3.2            # how long the loading screen lasts at least
    FX, FY, ZOOM = 0.5, 0.5, 1.0   # picture position (0..1) and zoom, like in Settings
    DIM = 0.35               # darken the picture
    TITLE = "✦ Herta Capture"
    SUB = "Kuru kuru~  capture, read & click"
    LINES = [
        ">>> import customtkinter as ctk",
        ">>> import keyboard, mss, numpy as np",
        "ctypes.windll.shcore.SetProcessDpiAwareness(1)",
        "loading settings.json ........ ok",
        "cv2.matchTemplate  ........... ready",
        "rapidocr_onnxruntime: warming up engine",
        "scanning click_images/ ....... ok",
        "keyboard.add_hotkey('f8')",
        "keyboard.add_hotkey('f9')",
        "building glass backdrop ...",
        "compositing panels ........... done",
        "starting live_loop thread",
        "mainloop() -> kuru kuru~",
    ]

    def __init__(self, master):
        super().__init__(master)
        W, H = self.W, self.H
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=BG)
        x = (self.winfo_screenwidth() - W) // 2
        y = (self.winfo_screenheight() - H) // 2
        self.geometry(f"{W}x{H}+{x}+{y}")

        c = self.canvas = tk.Canvas(self, width=W, height=H, highlightthickness=0, bg=BG)
        c.pack()
        self.photo = self.make_bg()
        if self.photo:
            c.create_image(0, 0, anchor="nw", image=self.photo)
        c.create_rectangle(0, 0, W - 1, H - 1, outline=ACCENT, width=2)
        c.create_text(24, 24, anchor="nw", text=self.TITLE, fill=LILAC, font=("Segoe UI", 24, "bold"))
        c.create_text(26, 64, anchor="nw", text=self.SUB, fill=TEXT, font=("Segoe UI", 11))

        # fake python log (bottom-left, little text)
        self.log = c.create_text(20, H - 44, anchor="sw", text="", fill=LILAC,
                                 font=("Consolas", 9), justify="left")
        # progress bar + "Loading"
        c.create_rectangle(20, H - 36, W - 20, H - 31, fill=PANEL_2, outline="")
        self.fill = c.create_rectangle(20, H - 36, 20, H - 31, fill=ACCENT_HOVER, outline="")
        self.load_txt = c.create_text(20, H - 16, anchor="w", text="Loading", fill=TEXT,
                                      font=("Segoe UI", 11, "bold"))
        self.pct_txt = c.create_text(W - 20, H - 16, anchor="e", text="0%", fill=TEXT,
                                     font=("Segoe UI", 11, "bold"))
        self.t0 = time.time()
        self._cb = None
        self.pump()

    def make_bg(self):
        W, H = self.W, self.H
        try:
            path = find_splash_bg()
            if path:
                im = cover(Image.open(path).convert("RGB"), (W, H), self.DIM, self.FX, self.FY, self.ZOOM)
            else:
                im = Image.new("RGB", (W, H), PANEL_RGB)
            # darker toward the bottom so the little text stays readable
            mask = Image.linear_gradient("L").resize((W, H)).point(lambda v: int(v * 0.9))
            return ImageTk.PhotoImage(Image.composite(Image.new("RGB", (W, H), BG), im, mask))
        except Exception:
            return None

    def progress(self):
        return min((time.time() - self.t0) / self.SECONDS, 1.0)

    def pump(self, full=True):
        """Redraw the log/bar. Call it between slow start-up steps."""
        try:
            if not self.winfo_exists():
                return
            p = self.progress()
            n = min(len(self.LINES), int(p * len(self.LINES)) + 1)
            self.canvas.itemconfigure(self.log, text="\n".join(self.LINES[max(0, n - 6):n]))
            self.canvas.coords(self.fill, 20, self.H - 36, 20 + (self.W - 40) * p, self.H - 31)
            dots = "." * (int((time.time() - self.t0) * 3) % 4)
            self.canvas.itemconfigure(self.load_txt, text="Loading" + dots)
            self.canvas.itemconfigure(self.pct_txt, text=f"{int(p * 100)}%")
            if full:
                self.update()
            else:
                self.update_idletasks()
        except Exception:
            pass

    def finish(self, callback):
        """Keep animating until the time is up, fade out, then call callback (shows the app)."""
        self._cb = callback
        self._tick()

    def _tick(self):
        if not self.winfo_exists():
            self._cb()
            return
        self.pump(full=False)
        if self.progress() < 1.0:
            self.after(30, self._tick)
        else:
            self.after(250, self._fade, 1.0)

    def _fade(self, a):
        a -= 0.1
        if a <= 0:
            self.destroy()
            self._cb()
            return
        try:
            self.attributes("-alpha", a)
        except Exception:
            pass
        self.after(20, self._fade, a)


# ---------- Region picker ----------
class RegionPicker(tk.Toplevel):
    def __init__(self, master, full_img, origin, on_done,
                 hint="Drag to select an area  •  Esc to cancel"):
        super().__init__(master)
        self.full_img = full_img
        self.on_done = on_done
        self.start = None
        self.rect = None

        w, h = full_img.size
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{w}x{h}{origin[0]:+d}{origin[1]:+d}")

        dim = ImageEnhance.Brightness(full_img).enhance(0.55)
        self.tk_img = ImageTk.PhotoImage(dim)
        self.canvas = tk.Canvas(self, width=w, height=h, highlightthickness=0, cursor="crosshair")
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        self.canvas.create_text(
            w // 2, 40, text=hint, fill=LILAC, font=("Segoe UI", 16, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", lambda e: self.cancel())
        self.focus_force()

    def on_press(self, e):
        self.start = (e.x, e.y)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline=ACCENT_HOVER, width=2)

    def on_drag(self, e):
        if self.rect:
            self.canvas.coords(self.rect, self.start[0], self.start[1], e.x, e.y)

    def on_release(self, e):
        if not self.start:
            return
        x1, y1 = self.start
        x2, y2 = e.x, e.y
        box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        self.destroy()
        if box[2] - box[0] < 5 or box[3] - box[1] < 5:
            self.on_done(None)
        else:
            self.on_done(self.full_img.crop(box))

    def cancel(self):
        self.destroy()
        self.on_done(None)


# ---------- Point picker (click one exact spot) ----------
class PointPicker(tk.Toplevel):
    def __init__(self, master, full_img, origin, on_done, marks=()):
        super().__init__(master)
        self.full_img, self.on_done = full_img, on_done
        w, h = full_img.size
        self.w, self.h = w, h
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{w}x{h}{origin[0]:+d}{origin[1]:+d}")
        self.tk_img = ImageTk.PhotoImage(ImageEnhance.Brightness(full_img).enhance(0.55))
        self.canvas = tk.Canvas(self, width=w, height=h, highlightthickness=0, cursor="crosshair")
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        self.canvas.create_text(w // 2, 40, text="Click the exact spot to auto-click  •  Esc to cancel",
                                fill=LILAC, font=("Segoe UI", 16, "bold"))
        for mx, my, num in marks:  # points that already exist
            x, y = mx - origin[0], my - origin[1]
            if 0 <= x < w and 0 <= y < h:
                self.canvas.create_oval(x - 14, y - 14, x + 14, y + 14, outline=LILAC, width=2)
                self.canvas.create_text(x, y, text=str(num), fill=LILAC, font=("Segoe UI", 11, "bold"))
        self.hl = self.canvas.create_line(0, 0, 0, 0, fill=ACCENT_HOVER)
        self.vl = self.canvas.create_line(0, 0, 0, 0, fill=ACCENT_HOVER)
        self.tag = self.canvas.create_text(0, 0, text="", fill=TEXT, anchor="w",
                                           font=("Consolas", 12, "bold"))
        self.canvas.bind("<Motion>", self.on_move)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.bind("<Escape>", lambda e: self.cancel())
        self.focus_force()

    def on_move(self, e):
        self.canvas.coords(self.hl, 0, e.y, self.w, e.y)
        self.canvas.coords(self.vl, e.x, 0, e.x, self.h)
        self.canvas.coords(self.tag, e.x + 14, e.y - 14)
        self.canvas.itemconfigure(self.tag, text=f"{e.x}, {e.y}")

    def on_press(self, e):
        self.destroy()
        self.on_done((e.x, e.y))

    def cancel(self):
        self.destroy()
        self.on_done(None)


# ---------- On-screen marker (click-through ring showing a point) ----------
class PointMarker(tk.Toplevel):
    S = 56

    def __init__(self, master, sx, sy, number, ms=3000):
        super().__init__(master)
        S = self.S
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=KEY)
        self.geometry(f"{S}x{S}+{int(sx) - S // 2}+{int(sy) - S // 2}")
        c = tk.Canvas(self, width=S, height=S, bg=KEY, highlightthickness=0)
        c.pack()
        c.create_oval(6, 6, S - 6, S - 6, outline=ACCENT_HOVER, width=3)
        c.create_line(S // 2, 0, S // 2, S, fill=LILAC)
        c.create_line(0, S // 2, S, S // 2, fill=LILAC)
        c.create_oval(S // 2 - 3, S // 2 - 3, S // 2 + 3, S // 2 + 3, fill=ACCENT_HOVER, outline="")
        c.create_oval(S - 20, 0, S, 20, fill=ACCENT, outline="")
        c.create_text(S - 10, 10, text=str(number), fill="white", font=("Segoe UI", 9, "bold"))
        self.attributes("-transparentcolor", KEY)
        self.update_idletasks()
        try:  # click-through + no taskbar button + never takes focus
            hw = top_hwnd(self)
            set_style(hw, GWL_EXSTYLE, get_style(hw, GWL_EXSTYLE) | 0x20 | 0x80 | 0x08000000)
        except Exception:
            pass
        self.after(ms, self.destroy)


# ---------- Name pop-up (rename the picked image) ----------
class NameDialog(ctk.CTkToplevel):
    def __init__(self, app, img, default, on_done, title="Name this click image"):
        super().__init__(app)
        self.on_done = on_done
        self._finished = False
        self.title("Herta Capture - Name")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        apply_icon(self)

        card = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=18)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(card, text=title, font=("Segoe UI", 16, "bold"),
                     text_color=LILAC).pack(anchor="w", padx=18, pady=(16, 8))

        t = img.copy()
        t.thumbnail((320, 150), Image.BILINEAR)
        self.cimg = make_cimg(self, t)
        ctk.CTkLabel(card, text="", image=self.cimg, fg_color=PANEL_2, corner_radius=10
                     ).pack(padx=18, pady=(0, 10), fill="x")

        self.entry = ctk.CTkEntry(card, height=36, fg_color=PANEL_2, border_color=ACCENT,
                                  text_color=TEXT, corner_radius=10, font=("Segoe UI", 13))
        self.entry.pack(fill="x", padx=18)
        self.entry.insert(0, default)

        self.err = ctk.CTkLabel(card, text="", text_color="#FF8FB8", font=("Segoe UI", 11))
        self.err.pack(anchor="w", padx=20, pady=(2, 0))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(6, 16))
        row.grid_columnconfigure((0, 1), weight=1, uniform="b")
        ctk.CTkButton(row, text="Save", height=36, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.save
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(row, text="Cancel", height=36, corner_radius=10, fg_color=PANEL_2,
                      hover_color="#3A2766", text_color=TEXT, command=self.cancel
                      ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        w, h = 380, 410
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.after(200, self.focus_entry)

    def focus_entry(self):
        try:
            self.lift()
            self.focus_force()
            self.entry.focus_set()
            self.entry.select_range(0, "end")
        except Exception:
            pass

    def save(self):
        name = clean_name(self.entry.get())
        if not name:
            self.err.configure(text="Please type a name (letters, numbers, space, - _)")
            return
        self.finish(name)

    def cancel(self):
        self.finish(None)

    def finish(self, name):
        if self._finished:
            return
        self._finished = True
        self.destroy()
        self.on_done(name)


# ---------- Collapsible section (left panel) ----------
class Section(ctk.CTkFrame):
    def __init__(self, app, parent, title, key):
        super().__init__(parent, fg_color="transparent")
        self.app, self.key, self.title_text = app, key, title
        self.open = not app.cfg["collapsed"].get(key, False)
        self.btn = ctk.CTkButton(self, text="", anchor="w", height=26, corner_radius=8,
                                 fg_color="transparent", hover_color=PANEL_2, text_color=MUTED,
                                 font=("Segoe UI", 11, "bold"), command=self.toggle)
        self.btn.pack(fill="x", padx=8, pady=(8, 2))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        if self.open:
            self.body.pack(fill="x")
        self.refresh()

    def refresh(self):
        self.btn.configure(text=("▾  " if self.open else "▸  ") + self.title_text)

    def set_open(self, value, save=True):
        if value == self.open:
            return
        self.open = value
        if value:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()
        self.refresh()
        self.app.cfg["collapsed"][self.key] = not value
        if save:
            self.app.schedule_save()

    def toggle(self):
        self.set_open(not self.open)


# ---------- Settings window ----------
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Herta Capture - Settings")
        self.geometry("430x800")
        self.resizable(False, True)
        self.configure(fg_color=BG)
        self.attributes("-topmost", True)
        apply_icon(self)

        card = ctk.CTkScrollableFrame(self, fg_color=PANEL, corner_radius=18,
                                      scrollbar_button_color=PANEL_2,
                                      scrollbar_button_hover_color=ACCENT)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(card, text="⚙ Settings", font=("Segoe UI", 20, "bold"),
                     text_color=LILAC).pack(anchor="w", padx=20, pady=(10, 6))

        pct = lambda v: f"{int(round(v * 100))}%"

        # --- Theme ---
        self.heading(card, "THEME")
        self.top_sw = ctk.CTkSwitch(card, text="Always on top", progress_color=ACCENT,
                                    text_color=TEXT, command=self.on_top)
        if app.cfg["always_on_top"]:
            self.top_sw.select()
        self.top_sw.pack(anchor="w", padx=20, pady=(0, 10))

        self.lslider(card, "Whole window transparency", 0.0, 0.75, 1.0 - app.cfg["opacity"],
                     lambda v: app.set_opacity(1.0 - v), pct)
        self.lslider(card, "Panel transparency (glass)", 0.0, 1.0, app.cfg["panel_transparency"],
                     app.set_panel_transparency, pct)
        self.glass_sw = ctk.CTkSwitch(card, text="Glass UI (restart app to apply)", progress_color=ACCENT,
                                      text_color=TEXT, command=lambda: self.on_flag("glass", self.glass_sw))
        if app.cfg["glass"]:
            self.glass_sw.select()
        self.glass_sw.pack(anchor="w", padx=20, pady=(0, 6))

        # --- Background ---
        self.heading(card, "BACKGROUND PICTURE")
        self.bg_name = ctk.CTkLabel(card, text=self.bg_text(), text_color=MUTED,
                                    font=("Segoe UI", 12), wraplength=330, justify="left")
        self.bg_name.pack(anchor="w", padx=20, pady=(0, 6))
        ctk.CTkButton(card, text="Choose image…", height=34, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.on_pick
                      ).pack(fill="x", padx=20, pady=(0, 6))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 10))
        row.grid_columnconfigure((0, 1), weight=1, uniform="bg")
        ctk.CTkButton(row, text="Use default picture", height=30, corner_radius=10, fg_color=PANEL_2,
                      hover_color="#3A2766", text_color=TEXT, command=self.on_default
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(row, text="No picture", height=30, corner_radius=10, fg_color=PANEL_2,
                      hover_color="#3A2766", text_color=TEXT, command=self.on_none
                      ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.lslider(card, "Darken picture", 0.0, 0.9, app.cfg["dim"], app.set_dim, pct)

        # --- Character position ---
        self.heading(card, "CHARACTER POSITION")
        self.pos_setters = []
        for key, label, lo, hi in (("bg_x", "Left  ↔  Right", 0.0, 1.0),
                                   ("bg_y", "Up  ↔  Down", 0.0, 1.0),
                                   ("bg_zoom", "Zoom", 1.0, 3.0)):
            fmt = (lambda v: f"{v:.2f}x") if key == "bg_zoom" else pct
            _, setter = self.lslider(card, label, lo, hi, app.cfg[key],
                                     lambda v, k=key: app.set_bg_param(k, v), fmt)
            self.pos_setters.append((key, setter))
        ctk.CTkLabel(card, text="Tip: zoom in a little first - then you can slide the picture around.",
                     text_color=MUTED, font=("Segoe UI", 11), wraplength=330, justify="left"
                     ).pack(anchor="w", padx=20, pady=(0, 6))
        ctk.CTkButton(card, text="Reset position", height=32, corner_radius=10, fg_color=PANEL_2,
                      hover_color="#3A2766", text_color=TEXT, command=self.on_reset_pos
                      ).pack(fill="x", padx=20, pady=(0, 6))

        # --- Default look ---
        self.heading(card, "DEFAULT LOOK  (for people who download your app)")
        ctk.CTkLabel(card, text="Saves the current picture, position, darkness and transparency as "
                                "the look everyone starts with.",
                     text_color=MUTED, font=("Segoe UI", 11), wraplength=330, justify="left"
                     ).pack(anchor="w", padx=20, pady=(0, 6))
        ctk.CTkButton(card, text="★  Save current look as default", height=36, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.on_save_default
                      ).pack(fill="x", padx=20, pady=(0, 4))
        self.note = ctk.CTkLabel(card, text="", text_color=LILAC, font=("Segoe UI", 11),
                                 wraplength=330, justify="left")
        self.note.pack(anchor="w", padx=20, pady=(0, 6))

        # --- Behaviour ---
        self.heading(card, "BEHAVIOUR")
        self.save_sw = ctk.CTkSwitch(card, text="Save screenshots to disk", progress_color=ACCENT,
                                     text_color=TEXT, command=lambda: self.on_flag("autosave", self.save_sw))
        if app.cfg["autosave"]:
            self.save_sw.select()
        self.save_sw.pack(anchor="w", padx=20, pady=(0, 10))
        self.copy_sw = ctk.CTkSwitch(card, text="Auto-copy detected text", progress_color=ACCENT,
                                     text_color=TEXT, command=lambda: self.on_flag("autocopy", self.copy_sw))
        if app.cfg["autocopy"]:
            self.copy_sw.select()
        self.copy_sw.pack(anchor="w", padx=20, pady=(0, 14))

    def heading(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=("Segoe UI", 11, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=20, pady=(16, 6))

    def slider(self, parent, lo, hi, value, command):
        s = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=100, progress_color=ACCENT,
                          button_color=LILAC, button_hover_color=ACCENT_HOVER, fg_color=PANEL_2,
                          command=command)
        s.set(value)
        s.pack(fill="x", padx=20, pady=(2, 8))
        return s

    def lslider(self, parent, text, lo, hi, value, command, fmt):
        lab = ctk.CTkLabel(parent, text=f"{text}: {fmt(value)}", text_color=TEXT)
        lab.pack(anchor="w", padx=20)

        def cb(v):
            v = float(v)
            lab.configure(text=f"{text}: {fmt(v)}")
            command(v)

        s = self.slider(parent, lo, hi, value, cb)

        def setter(v):
            s.set(v)
            lab.configure(text=f"{text}: {fmt(v)}")

        return s, setter

    def bg_text(self):
        p = self.app.cfg["bg_path"]
        if p == "none":
            return "No picture"
        if p and os.path.exists(p):
            return os.path.basename(p)
        d = find_default_bg()
        return f"Default picture ({os.path.basename(d)})" if d else "No default picture yet - choose one!"

    def on_top(self):
        self.app.set_topmost(bool(self.top_sw.get()))

    def on_pick(self):
        path = filedialog.askopenfilename(
            parent=self, title="Choose a background picture",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
        if path:
            self.app.set_background(path)
            self.bg_name.configure(text=self.bg_text())

    def on_default(self):
        self.app.set_background("")
        self.bg_name.configure(text=self.bg_text())

    def on_none(self):
        self.app.set_background("none")
        self.bg_name.configure(text=self.bg_text())

    def on_reset_pos(self):
        for key, setter in self.pos_setters:
            setter(DEFAULTS[key])
            self.app.cfg[key] = DEFAULTS[key]
        self.app.set_bg_param("bg_zoom", DEFAULTS["bg_zoom"])

    def on_save_default(self):
        self.note.configure(text=self.app.save_default_look())

    def on_flag(self, key, switch):
        self.app.cfg[key] = bool(switch.get())
        self.app.schedule_save()


# ---------- Smooth, throttled wheel scrolling (stops the "ghost trails" on the glass UI) ----------
def _wheel_add(frame, units):
    """Collect wheel movement and apply it at most ~60 times per second."""
    frame._wheel_acc = getattr(frame, "_wheel_acc", 0.0) + units
    if getattr(frame, "_wheel_job", None) is None:
        frame._wheel_job = frame.after(16, lambda: _wheel_flush(frame))


def _wheel_flush(frame):
    frame._wheel_job = None
    try:
        acc = getattr(frame, "_wheel_acc", 0.0)
        step = int(max(-4, min(4, acc)))          # never jump more than 4 units per frame
        if step == 0 and abs(acc) >= 0.5:
            step = 1 if acc > 0 else -1
        if step:
            frame._wheel_acc = acc - step
            canvas = frame._parent_canvas
            canvas.yview_scroll(step, "units")
            canvas.update_idletasks()             # repaint right now so nothing smears
            frame._wheel_job = frame.after(16, lambda: _wheel_flush(frame))
        else:
            frame._wheel_acc = 0.0
    except Exception:
        frame._wheel_acc = 0.0


def _smooth_mouse_wheel(self, event):
    try:
        if not self.check_if_master_is_canvas(event.widget):
            return
        if self._parent_canvas.yview() == (0.0, 1.0):
            return
        _wheel_add(self, -event.delta / 120 * 3)
    except Exception:
        pass


ctk.CTkScrollableFrame._mouse_wheel_all = _smooth_mouse_wheel  # patched before any frame is created


# ---------- Main app ----------
class HertaCapture(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()                      # hide the main window while the loading screen runs
        self.splash = SplashScreen(self)
        ctk.set_appearance_mode("dark")
        self.cfg = load_cfg()
        self.glass = bool(self.cfg["glass"])
        self.card_color = KEY if self.glass else PANEL
        self.title("Herta Capture")
        self.geometry("1080x860")
        self.minsize(940, 680)
        self.configure(fg_color=KEY if self.glass else BG)
        self.attributes("-topmost", bool(self.cfg["always_on_top"]))
        self.attributes("-alpha", float(self.cfg["opacity"]))
        apply_icon(self)

        self.ocr = OCRManager()
        self.hotkey = None
        self.hotkey_handle = None
        self.click_hotkey = None
        self.click_hotkey_handle = None
        self.busy = False
        self.ocr_job = 0

        # auto click
        self.clicking = False
        self.click_gen = 0
        self.click_count = 0
        self.round_no = 0
        self._round_clicks = 0
        self._round_start = time.time()

        # window targeting / live view
        self.mode_name = self.cfg["mode"]
        self.live_on = True
        self.target_exe = self.cfg["target_exe"]
        self.target_hwnd = None
        self.embedded_hwnd = None
        self.embed_info = None
        self.targets = {}
        self.latest = None
        self._last_shown = None
        self._last_resolve = 0.0
        self._warned = False
        self.freeze_until = 0.0

        # state
        self.last_img = None
        self.last_path = None
        self.preview_state = "idle"
        self.bg_src = None
        self.bd_photo = None
        self.bd_label = None
        self.backdrop = None
        self._bd_geom = None
        self._bg_job = None
        self._save_job = None
        self._confirm_clear = False
        self.settings_win = None
        self.sections = []
        self.markers = []

        self.blank = ctk.CTkImage(Image.new("RGBA", (1, 1), (0, 0, 0, 0)), size=(1, 1))

        self.splash.pump()
        self.build_ui()
        self.splash.pump()
        self.load_background(self.effective_bg_path())
        self.apply_text_state()
        self.refresh_targets()
        self.splash.pump()
        self.refresh_templates()
        self.refresh_count()
        self.update_tag()
        self.update_play_ui()
        self.splash.pump()

        if self.glass:
            self.init_glass()
        else:
            self.bd_label = tk.Label(self, bd=0, highlightthickness=0, bg=BG)

        try:
            self.bind_hotkey(self.cfg["hotkey"])
        except Exception:
            self.bind_hotkey("f8")
        try:
            self.bind_click_hotkey(self.cfg["click_hotkey"])
        except Exception:
            self.bind_click_hotkey("f9")
        self.splash.pump()

        self.bind("<Configure>", self.on_root_configure, add="+")
        self.bind("<FocusIn>", lambda e: self.sync_backdrop(), add="+")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=self.live_loop, daemon=True).start()
        self.after(100, self.poll_live)
        self.after(150, self.sync_loop)
        self.after(250, self.refresh_visuals)
        self.splash.finish(self.show_main)   # keep animating, fade out, then show the app

    FADE_MS = 450  # smooth fade-in length after the loading screen

    def set_both_alpha(self, a):
        try:
            self.attributes("-alpha", a)
            if self.backdrop is not None:
                self.backdrop.attributes("-alpha", a)
        except Exception:
            pass

    def show_main(self):
        """Loading screen is done: show the app invisible, lay it out for real, then fade it in."""
        self.set_both_alpha(0.0)
        self.deiconify()
        self.update()                      # let Tk place + size every widget for real
        self.lift()
        if self._bg_job:                   # drop redraws that were made while the window was hidden
            self.after_cancel(self._bg_job)
            self._bg_job = None
        self._bd_geom = None
        self.update_backdrop()             # glass is drawn with the REAL window/panel positions
        self.sync_backdrop()
        self._fade_t0 = time.time()
        self._fade_in()
        self.after(200, lambda: self.on_configure(None, force=True))  # final safety redraw

    def _fade_in(self):
        target = float(self.cfg["opacity"])
        t = min((time.time() - self._fade_t0) * 1000.0 / self.FADE_MS, 1.0)
        eased = 1 - (1 - t) ** 3           # ease-out
        self.set_both_alpha(target * eased)
        self.sync_backdrop()
        if t < 1.0:
            self.after(16, self._fade_in)
        else:
            self.set_both_alpha(target)
            self.refresh_visuals()

    # ----- Config -----
    def schedule_save(self):
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self.save_cfg)

    def save_cfg(self):
        self._save_job = None
        try:
            with open(CFG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
        except Exception:
            pass

    def on_close(self):
        self.clicking = False
        self.click_gen += 1
        self.release_target(quiet=True)  # never close with a program still inside us
        self.save_cfg()
        self.destroy()

    # ----- Glass UI (see-through panels) -----
    def init_glass(self):
        """A picture window sits right behind this one; panels are holes in this window."""
        try:
            self.backdrop = tk.Toplevel(self, bg=BG)
            self.backdrop.withdraw()
            self.backdrop.overrideredirect(True)
            self.bd_label = tk.Label(self.backdrop, bd=0, highlightthickness=0, bg=BG)
            self.bd_label.place(x=0, y=0)
            self.bd_label.bind("<MouseWheel>", self.on_bd_wheel)
            self.backdrop.update_idletasks()
            self.backdrop.attributes("-alpha", float(self.cfg["opacity"]))
            self.backdrop.attributes("-topmost", bool(self.cfg["always_on_top"]))
            hw = top_hwnd(self.backdrop)
            # tool window (no taskbar button) + never steals focus
            set_style(hw, GWL_EXSTYLE, get_style(hw, GWL_EXSTYLE) | 0x08000000 | 0x00000080)
            self.attributes("-transparentcolor", KEY)
        except Exception:
            self.disable_glass()

    def disable_glass(self):
        self.glass = False
        self.cfg["glass"] = False
        try:
            self.attributes("-transparentcolor", "")
        except Exception:
            pass
        try:
            if self.backdrop is not None:
                self.backdrop.destroy()
        except Exception:
            pass
        self.backdrop = None
        self.configure(fg_color=BG)
        for c in (self.left, self.prev_card, self.text_card):
            try:
                c.configure(fg_color=PANEL)
            except Exception:
                pass
        self.bd_label = tk.Label(self, bd=0, highlightthickness=0, bg=BG)
        self.set_status("Glass UI couldn't start - using solid panels")

    def sync_backdrop(self):
        """Keep the picture window exactly behind this window."""
        if not self.glass or self.backdrop is None:
            return
        try:
            if self.state() in ("iconic", "withdrawn"):
                if self.backdrop.state() != "withdrawn":
                    self.backdrop.withdraw()
                return
            w, h = self.winfo_width(), self.winfo_height()
            if w < 50 or h < 50:
                return
            if self.backdrop.state() == "withdrawn":
                self.backdrop.deiconify()
                self._bd_geom = None
            geom = f"{w}x{h}{self.winfo_rootx():+d}{self.winfo_rooty():+d}"
            if geom != self._bd_geom:
                self._bd_geom = geom
                self.backdrop.geometry(geom)
            # NOSIZE | NOMOVE | NOACTIVATE : slot it directly under the main window
            user32.SetWindowPos(top_hwnd(self.backdrop), top_hwnd(self), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        except Exception:
            pass

    def sync_loop(self):
        self.sync_backdrop()
        self.after(150, self.sync_loop)

    def on_root_configure(self, e):
        if e.widget is self:
            self.sync_backdrop()
            self.on_configure(e)

    def on_bd_wheel(self, e):
        """Mouse wheel over a see-through spot of the left panel still scrolls it."""
        try:
            x0 = self.left_card.winfo_rootx()
            if x0 <= e.x_root <= x0 + self.left_card.winfo_width():
                _wheel_add(self.left, -e.delta / 120 * 3)
        except Exception:
            pass

    def hide_for_capture(self):
        self.withdraw()
        if self.backdrop is not None:
            try:
                self.backdrop.withdraw()
            except Exception:
                pass

    # ----- UI -----
    def build_ui(self):
        cc = self.card_color
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=2)

        # ===== Left: controls =====
        left = ctk.CTkScrollableFrame(
            self, fg_color=cc, corner_radius=18, width=270,
            scrollbar_button_color=PANEL_2, scrollbar_button_hover_color=ACCENT)
        left.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(24, 12), pady=24)
        self.left = left
        self.left_card = getattr(left, "_parent_frame", left)

        ctk.CTkLabel(left, text="✦ Herta Capture", font=("Segoe UI", 22, "bold"),
                     text_color=LILAC).pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(left, text="Kuru kuru~  capture, read & click", font=("Segoe UI", 12),
                     text_color=MUTED).pack(anchor="w", padx=14, pady=(0, 6))

        # always visible: capture + play/pause + status
        qrow = ctk.CTkFrame(left, fg_color="transparent")
        qrow.pack(fill="x", padx=12, pady=(0, 4))
        qrow.grid_columnconfigure((0, 1), weight=1, uniform="q")
        self.capture_btn = ctk.CTkButton(qrow, text="Capture now", height=40, corner_radius=12,
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                         font=("Segoe UI", 13, "bold"), command=self.capture)
        self.capture_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.play_btn = ctk.CTkButton(qrow, text="▶  Play", height=40, corner_radius=12,
                                      fg_color=GOOD, hover_color="#4E9A70",
                                      font=("Segoe UI", 13, "bold"), command=self.toggle_autoclick)
        self.play_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.status = ctk.CTkLabel(left, text="Ready", text_color=MUTED, font=("Segoe UI", 12),
                                   wraplength=235, justify="left")
        self.status.pack(anchor="w", padx=14, pady=(2, 2))

        self.compact_btn = ctk.CTkButton(left, text="⇕  Collapse all", height=28, corner_radius=8,
                                         fg_color=PANEL_2, hover_color="#3A2766", text_color=TEXT,
                                         font=("Segoe UI", 12), command=self.toggle_all_sections)
        self.compact_btn.pack(fill="x", padx=12, pady=(4, 0))

        # ----- Hotkey -----
        body = self.add_section(left, "HOTKEY  (capture)", "hotkey")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 6))
        self.key_label = ctk.CTkLabel(row, text="F8", width=90, height=36, fg_color=PANEL_2,
                                      corner_radius=10, font=("Consolas", 15, "bold"), text_color=TEXT)
        self.key_label.pack(side="left")
        self.bind_btn = ctk.CTkButton(row, text="Change bind", height=36, corner_radius=10,
                                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                      command=lambda: self.start_rebind("capture"))
        self.bind_btn.pack(side="left", padx=(8, 0), fill="x", expand=True)

        # ----- Capture mode -----
        body = self.add_section(left, "CAPTURE MODE", "mode")
        self.mode = ctk.CTkSegmentedButton(
            body, values=MODES, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            unselected_color=PANEL_2, unselected_hover_color="#3A2766", text_color=TEXT,
            command=self.on_mode)
        self.mode.set(self.mode_name)
        self.mode.pack(fill="x", padx=12, pady=(0, 6))

        # ----- Target window -----
        body = self.add_section(left, "TARGET WINDOW  (Window mode)", "target")
        trow = ctk.CTkFrame(body, fg_color="transparent")
        trow.pack(fill="x", padx=12, pady=(0, 6))
        self.target_menu = ctk.CTkOptionMenu(
            trow, values=[NONE_LABEL], width=190, dynamic_resizing=False, fg_color=PANEL_2,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, dropdown_fg_color=PANEL_2,
            dropdown_hover_color=ACCENT, text_color=TEXT, command=self.on_target)
        self.target_menu.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(trow, text="⟳", width=38, height=28, corner_radius=8, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.refresh_targets).pack(side="left", padx=(6, 0))
        self.live_switch = ctk.CTkSwitch(body, text="Live view inside app", progress_color=ACCENT,
                                         text_color=TEXT, command=self.on_live)
        self.live_switch.select()
        self.live_switch.pack(anchor="w", padx=14, pady=(2, 8))
        self.embed_btn = ctk.CTkButton(body, text="Embed in app", height=34, corner_radius=10,
                                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                       command=self.toggle_embed)
        self.embed_btn.pack(fill="x", padx=12, pady=(0, 2))
        ctk.CTkLabel(body, text="Embedded apps are fully clickable. Hotkey captures the whole window.",
                     text_color=MUTED, font=("Segoe UI", 11), wraplength=235, justify="left"
                     ).pack(anchor="w", padx=14, pady=(0, 6))
        self.region_sw = ctk.CTkSwitch(body, text="Pick region inside window", progress_color=ACCENT,
                                       text_color=TEXT, command=self.on_region_sw)
        if self.cfg["window_region"]:
            self.region_sw.select()
        self.region_sw.pack(anchor="w", padx=14, pady=(2, 2))
        ctk.CTkLabel(body, text="ON: hotkey → drag a box in the window → name it → it becomes a "
                                "click image for Auto Click.",
                     text_color=MUTED, font=("Segoe UI", 11), wraplength=235, justify="left"
                     ).pack(anchor="w", padx=14, pady=(0, 6))

        # ----- Auto click -----
        body = self.add_section(left, "AUTO CLICK  (image / point → mouse)", "autoclick")
        ctk.CTkLabel(body, text="Click images", text_color=MUTED, font=("Segoe UI", 11)
                     ).pack(anchor="w", padx=14)
        self.tpl_menu = ctk.CTkOptionMenu(
            body, values=[NONE_LABEL], dynamic_resizing=False, fg_color=PANEL_2,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, dropdown_fg_color=PANEL_2,
            dropdown_hover_color=ACCENT, text_color=TEXT, command=self.on_template)
        self.tpl_menu.pack(fill="x", padx=12, pady=(2, 6))
        self.tpl_thumb = ctk.CTkLabel(body, text="", image=self.blank)
        self.tpl_thumb.pack(padx=12, pady=(0, 6))

        arow = ctk.CTkFrame(body, fg_color="transparent")
        arow.pack(fill="x", padx=12, pady=(0, 8))
        arow.grid_columnconfigure((0, 1), weight=1, uniform="a")
        ctk.CTkButton(arow, text="Rename", height=30, corner_radius=10, fg_color=PANEL_2,
                      hover_color="#3A2766", text_color=TEXT, command=self.rename_template
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(arow, text="Delete", height=30, corner_radius=10, fg_color=PANEL_2,
                      hover_color=DANGER, text_color=TEXT, command=self.delete_template
                      ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ctk.CTkLabel(body, text="SEQUENCE  (clicked top → bottom)", text_color=MUTED,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(4, 2))
        self.seq_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.seq_frame.pack(fill="x", padx=12)
        srow = ctk.CTkFrame(body, fg_color="transparent")
        srow.pack(fill="x", padx=12, pady=(4, 6))
        srow.grid_columnconfigure((0, 1), weight=1, uniform="s")
        ctk.CTkButton(srow, text="＋ Add selected", height=30, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.seq_add
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(srow, text="Clear", height=30, corner_radius=10, fg_color=PANEL_2,
                      hover_color=DANGER, text_color=TEXT, command=self.seq_clear
                      ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        prow = ctk.CTkFrame(body, fg_color="transparent")
        prow.pack(fill="x", padx=12, pady=(0, 6))
        prow.grid_columnconfigure((0, 1), weight=1, uniform="p")
        ctk.CTkButton(prow, text="◎ Add click point", height=30, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.add_point
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(prow, text="Show points", height=30, corner_radius=10, fg_color=PANEL_2,
                      hover_color="#3A2766", text_color=TEXT, command=self.show_points
                      ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ctk.CTkLabel(body, text="Click point = click one exact spot (no image needed). Click a "
                                "point's row to flash where it is. The number after × on a point = how many times "
                                "it is clicked.\n"
                                "Empty sequence = Play just keeps clicking the selected image.",
                     text_color=MUTED, font=("Segoe UI", 11), wraplength=235, justify="left"
                     ).pack(anchor="w", padx=14, pady=(0, 4))

        self.cfg_switch(body, "loop_sequence", "Loop sequence")
        self.cfg_slider(body, "click_delay", "Delay after a click", 0.0, 3.0, lambda v: f"{v:.1f}s")
        self.cfg_slider(body, "step_timeout", "Skip step if not found", 0.0, 30.0,
                        lambda v: "never" if v < 0.5 else f"{v:.0f}s", steps=30)
        self.cfg_switch(body, "always_scroll", "Always scroll down")
        self.cfg_switch(body, "scroll_only_missing", "…only while image isn't found")
        self.cfg_slider(body, "scroll_amount", "Scroll amount", 1, 10,
                        lambda v: f"{int(round(v))} notch{'es' if round(v) != 1 else ''}", steps=9)

        crow = ctk.CTkFrame(body, fg_color="transparent")
        crow.pack(fill="x", padx=12, pady=(4, 6))
        self.click_key_label = ctk.CTkLabel(crow, text="F9", width=90, height=34, fg_color=PANEL_2,
                                            corner_radius=10, font=("Consolas", 15, "bold"),
                                            text_color=TEXT)
        self.click_key_label.pack(side="left")
        self.click_bind_btn = ctk.CTkButton(crow, text="Bind play/pause", height=34, corner_radius=10,
                                            fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                            command=lambda: self.start_rebind("click"))
        self.click_bind_btn.pack(side="left", padx=(8, 0), fill="x", expand=True)

        self.cfg_slider(body, "click_threshold", "Match accuracy", 0.5, 1.0,
                        lambda v: f"{int(round(v * 100))}%")
        self.cfg_slider(body, "click_interval", "Search every", 0.1, 5.0, lambda v: f"{v:.1f}s")
        ctk.CTkLabel(body, text="Clicks use your real mouse, so keep the target window visible "
                                "(embedded in this app is easiest).",
                     text_color=MUTED, font=("Segoe UI", 11), wraplength=235, justify="left"
                     ).pack(anchor="w", padx=14, pady=(0, 4))

        # ----- Discord webhook -----
        body = self.add_section(left, "DISCORD WEBHOOK  (loot)", "webhook")
        self.cfg_switch(body, "webhook_on", "Send loot when a round finishes")
        self.webhook_entry = ctk.CTkEntry(body, height=32, corner_radius=10, fg_color=PANEL_2,
                                          border_color=ACCENT, text_color=TEXT, show="•",
                                          placeholder_text="Paste Discord webhook URL")
        self.webhook_entry.pack(fill="x", padx=12, pady=(2, 6))
        if self.cfg["webhook_url"]:
            self.webhook_entry.insert(0, self.cfg["webhook_url"])
        self.webhook_entry.bind("<KeyRelease>", lambda e: self.on_webhook_url())
        self.cfg_slider(body, "webhook_delay", "Wait before loot screenshot", 0.0, 10.0,
                        lambda v: f"{v:.1f}s")
        ctk.CTkButton(body, text="Send test message", height=30, corner_radius=10, fg_color=PANEL_2,
                      hover_color="#3A2766", text_color=TEXT, command=self.test_webhook
                      ).pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(body, text="A round = the whole sequence finished (last step clicked). Then it "
                                "waits, screenshots the target window (or screen) and posts it. "
                                "Discord: channel settings → Integrations → Webhooks.",
                     text_color=MUTED, font=("Segoe UI", 11), wraplength=235, justify="left"
                     ).pack(anchor="w", padx=14, pady=(0, 4))

        # ----- OCR -----
        body = self.add_section(left, "RECOGNITION ENGINE", "ocr")
        self.engine = ctk.CTkOptionMenu(
            body, values=["RapidOCR", "Tesseract"], fg_color=PANEL_2, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, dropdown_fg_color=PANEL_2, dropdown_hover_color=ACCENT,
            text_color=TEXT, command=self.on_engine)
        self.engine.set(self.cfg["engine"])
        self.engine.pack(fill="x", padx=12, pady=(0, 6))

        # ----- Files -----
        body = self.add_section(left, "SCREENSHOT FILES", "files")
        drow = ctk.CTkFrame(body, fg_color="transparent")
        drow.pack(fill="x", padx=12, pady=(0, 8))
        drow.grid_columnconfigure((0, 1), weight=1, uniform="d")
        ctk.CTkButton(drow, text="Discard last", height=34, corner_radius=10, fg_color=PANEL_2,
                      hover_color="#3A2766", text_color=TEXT, command=self.discard_last
                      ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.clear_btn = ctk.CTkButton(drow, text="Clear all old", height=34, corner_radius=10,
                                       fg_color=PANEL_2, hover_color=DANGER, text_color=TEXT,
                                       command=self.clear_all)
        self.clear_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ctk.CTkButton(body, text="Open screenshots folder", height=32, corner_radius=10,
                      fg_color=PANEL_2, hover_color="#3A2766", text_color=TEXT,
                      command=lambda: os.startfile(SAVE_DIR)).pack(fill="x", padx=12, pady=(0, 4))
        self.count_label = ctk.CTkLabel(body, text="", text_color=MUTED, font=("Segoe UI", 11))
        self.count_label.pack(anchor="w", padx=14)

        ctk.CTkButton(left, text="⚙  Settings / Theme", height=36, corner_radius=10, fg_color=PANEL_2,
                      hover_color=ACCENT, text_color=TEXT, command=self.open_settings
                      ).pack(fill="x", padx=12, pady=(12, 10))

        # ===== Right top: preview card =====
        prev_card = ctk.CTkFrame(self, fg_color=cc, corner_radius=18)
        prev_card.grid(row=0, column=1, sticky="nsew", padx=(12, 24), pady=(24, 12))
        prev_card.grid_propagate(False)
        prev_card.grid_rowconfigure(1, weight=1)
        prev_card.grid_columnconfigure(0, weight=1)
        self.prev_card = prev_card

        phead = ctk.CTkFrame(prev_card, fg_color="transparent")
        phead.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        ctk.CTkLabel(phead, text="PREVIEW", font=("Segoe UI", 11, "bold"),
                     text_color=MUTED).pack(side="left")
        self.preview_tag = ctk.CTkLabel(phead, text="", font=("Segoe UI", 11, "bold"),
                                        text_color=LILAC)
        self.preview_tag.pack(side="right")

        self.preview = ctk.CTkLabel(prev_card, text="No capture yet", text_color=MUTED,
                                    image=self.blank, compound="center")
        self.preview.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        # Real Win32 child-window host: the targeted program is parented into this frame.
        self.host = tk.Frame(prev_card, bg="#000000", bd=0, highlightthickness=0)
        self.host.bind("<Configure>", self.on_host_resize)

        # ===== Right bottom: collapsible text card =====
        text_card = ctk.CTkFrame(self, fg_color=cc, corner_radius=18)
        text_card.grid(row=1, column=1, sticky="nsew", padx=(12, 24), pady=(0, 24))
        text_card.grid_columnconfigure(0, weight=1)
        text_card.grid_rowconfigure(1, weight=1)
        self.text_card = text_card

        thead = ctk.CTkFrame(text_card, fg_color="transparent")
        thead.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        self.text_toggle = ctk.CTkButton(
            thead, text="▾  DETECTED TEXT", width=0, height=28, fg_color="transparent",
            hover_color=PANEL_2, text_color=MUTED, font=("Segoe UI", 11, "bold"), anchor="w",
            command=self.toggle_text)
        self.text_toggle.pack(side="left")
        self.text_hint = ctk.CTkLabel(thead, text="", text_color=LILAC, font=("Segoe UI", 11))
        self.text_hint.pack(side="left", padx=6)
        ctk.CTkButton(thead, text="Copy", width=70, height=26, corner_radius=8, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.copy_text).pack(side="right")
        self.thumb = ctk.CTkLabel(thead, text="", image=self.blank)
        self.thumb.pack(side="right", padx=(0, 10))

        self.textbox = ctk.CTkTextbox(text_card, height=150, fg_color=PANEL_2, text_color=TEXT,
                                      corner_radius=12, font=("Consolas", 13), border_width=0)
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        # when a card changes size, redraw the glass behind it
        for card in (self.left_card, prev_card, text_card):
            try:
                card.bind("<Configure>", lambda e: self.on_configure(None, force=True), add="+")
            except Exception:
                pass

    # ----- small UI helpers -----
    def add_section(self, parent, title, key):
        s = Section(self, parent, title, key)
        s.pack(fill="x")
        self.sections.append(s)
        return s.body

    def toggle_all_sections(self):
        any_open = any(s.open for s in self.sections)
        for s in self.sections:
            s.set_open(not any_open, save=False)
        self.schedule_save()
        self.compact_btn.configure(text="⇕  Expand all" if any_open else "⇕  Collapse all")

    def cfg_slider(self, parent, key, text, lo, hi, fmt, steps=90):
        lab = ctk.CTkLabel(parent, text="", text_color=TEXT, font=("Segoe UI", 12))
        lab.pack(anchor="w", padx=14)

        def cb(v, save=True):
            v = float(v)
            self.cfg[key] = round(v, 2)
            lab.configure(text=f"{text}: {fmt(v)}")
            if save:
                self.schedule_save()

        s = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps, progress_color=ACCENT,
                          button_color=LILAC, button_hover_color=ACCENT_HOVER, fg_color=PANEL_2,
                          command=cb)
        s.set(self.cfg[key])
        s.pack(fill="x", padx=14, pady=(2, 8))
        cb(self.cfg[key], save=False)
        return s

    def cfg_switch(self, parent, key, text):
        sw = ctk.CTkSwitch(parent, text=text, progress_color=ACCENT, text_color=TEXT,
                           command=lambda: self.on_cfg_switch(key, sw))
        if self.cfg[key]:
            sw.select()
        sw.pack(anchor="w", padx=14, pady=(2, 6))
        return sw

    def on_cfg_switch(self, key, sw):
        self.cfg[key] = bool(sw.get())
        self.schedule_save()

    # ----- Collapsible text -----
    def toggle_text(self):
        self.cfg["text_collapsed"] = not self.cfg["text_collapsed"]
        self.apply_text_state()
        self.schedule_save()

    def apply_text_state(self):
        if self.cfg["text_collapsed"]:
            self.textbox.grid_remove()
            self.text_toggle.configure(text="▸  DETECTED TEXT")
            self.grid_rowconfigure(1, weight=0)
        else:
            self.textbox.grid()
            self.text_toggle.configure(text="▾  DETECTED TEXT")
            self.grid_rowconfigure(1, weight=2)
        self.after(50, self.refresh_visuals)

    # ----- Settings actions -----
    def open_settings(self):
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus_force()
            return
        self.settings_win = SettingsWindow(self)

    def set_topmost(self, value):
        self.cfg["always_on_top"] = value
        self.attributes("-topmost", value)
        if self.backdrop is not None:
            try:
                self.backdrop.attributes("-topmost", value)
            except Exception:
                pass
        self.schedule_save()

    def set_opacity(self, value):
        value = min(max(value, 0.25), 1.0)
        self.cfg["opacity"] = round(value, 2)
        self.attributes("-alpha", value)
        if self.backdrop is not None:
            try:
                self.backdrop.attributes("-alpha", value)
            except Exception:
                pass
        self.schedule_save()

    def set_panel_transparency(self, value):
        self.cfg["panel_transparency"] = round(float(value), 2)
        self.schedule_save()
        self.on_configure(None, force=True)

    def set_dim(self, value):
        self.cfg["dim"] = round(value, 2)
        self.schedule_save()
        self.on_configure(None, force=True)

    def set_bg_param(self, key, value):
        self.cfg[key] = round(float(value), 3)
        self.schedule_save()
        self.on_configure(None, force=True)

    def effective_bg_path(self):
        p = self.cfg["bg_path"]
        if p == "none":
            return ""
        if p and os.path.exists(p):
            return p
        return find_default_bg()

    def set_background(self, path):
        self.cfg["bg_path"] = path
        self.load_background(self.effective_bg_path())
        self.refresh_visuals()
        self.schedule_save()

    def load_background(self, path):
        self.bg_src = None
        if path and os.path.exists(path):
            try:
                im = Image.open(path).convert("RGB")
                im.thumbnail((2400, 2400))
                self.bg_src = im
            except Exception as e:
                self.set_status(f"Couldn't open picture: {e}")

    def save_default_look(self):
        """Make the current picture + look the one everyone starts with."""
        try:
            src = self.effective_bg_path()
            for ext in BG_EXTS:
                old = os.path.join(APP_DIR, "default_bg" + ext)
                if os.path.exists(old) and (not src or os.path.abspath(old) != os.path.abspath(src)):
                    os.remove(old)
            if src:
                dst = os.path.join(APP_DIR, "default_bg" + (os.path.splitext(src)[1].lower() or ".png"))
                if os.path.abspath(src) != os.path.abspath(dst):
                    shutil.copyfile(src, dst)
            with open(os.path.join(APP_DIR, THEME_FILE), "w", encoding="utf-8") as f:
                json.dump({k: self.cfg[k] for k in THEME_KEYS}, f, indent=2)
            self.cfg["bg_path"] = ""  # now it simply uses the default picture
            self.schedule_save()
            return ("Saved! Everyone who gets this folder starts with this look. "
                    "(Share the whole app folder, without settings.json.)")
        except Exception as e:
            return f"Couldn't save default look: {e}"

    def bg_cover(self, size, dim):
        return cover(self.bg_src, size, dim, self.cfg["bg_x"], self.cfg["bg_y"], self.cfg["bg_zoom"])

    # ----- Backdrop / glass drawing -----
    def on_configure(self, e, force=False):
        if not force and (e is None or e.widget != self):
            return
        if self._bg_job:
            self.after_cancel(self._bg_job)
        self._bg_job = self.after(120, self.refresh_visuals)

    def refresh_visuals(self):
        self._bg_job = None
        self.update_backdrop()
        if self.preview_state == "idle":
            self.show_idle()

    def compose_backdrop(self, w, h):
        base = self.bg_cover((w, h), self.cfg["dim"]) if self.bg_src is not None \
            else Image.new("RGB", (w, h), BG)
        opacity = 1.0 - float(self.cfg["panel_transparency"])
        if opacity > 0.01:
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            try:
                scale = self._get_window_scaling()
            except Exception:
                scale = 1.0
            radius = max(int(18 * scale), 4)
            for card in (self.left_card, self.prev_card, self.text_card):
                if not card.winfo_ismapped():
                    continue
                cw, ch = card.winfo_width(), card.winfo_height()
                if cw < 8 or ch < 8:
                    continue
                x0, y0 = card.winfo_rootx() - rx, card.winfo_rooty() - ry
                base.paste(Image.new("RGB", (cw, ch), PANEL_RGB), (x0, y0),
                           rounded_mask(cw, ch, radius, opacity))
        return base

    def update_backdrop(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50 or h < 50 or self.bd_label is None:
            return
        if self.glass:
            im = self.compose_backdrop(w, h)
        else:
            if self.bg_src is None:
                self.bd_label.place_forget()
                return
            im = self.bg_cover((w, h), self.cfg["dim"])
        self.bd_photo = ImageTk.PhotoImage(im)
        self.bd_label.configure(image=self.bd_photo)
        if self.glass:
            self.bd_label.place(x=0, y=0)
        else:
            self.bd_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.bd_label.lower()
        self.sync_backdrop()

    def preview_box(self):
        return max(self.preview.winfo_width() - 16, 120), max(self.preview.winfo_height() - 16, 100)

    def set_preview_image(self, pil_img):
        cimg = make_cimg(self.preview, pil_img)
        self.preview.configure(image=cimg, text="")
        self.preview.image = cimg

    def show_idle(self):
        self.preview_state = "idle"
        self.preview.configure(image=self.blank, text="No capture yet")
        self.preview.image = self.blank

    def show_preview(self, img):
        self.preview_state = "frame"
        w, h = self.preview_box()
        thumb = img.copy()
        thumb.thumbnail((w, h), Image.BILINEAR)
        self.set_preview_image(thumb)

    # ----- Hotkeys -----
    def bind_hotkey(self, key):
        if self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
            except Exception:
                pass
        self.hotkey_handle = keyboard.add_hotkey(key, lambda: self.after(0, self.capture))
        self.hotkey = key
        self.cfg["hotkey"] = key
        self.key_label.configure(text=key.upper())
        self.schedule_save()

    def bind_click_hotkey(self, key):
        if self.click_hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.click_hotkey_handle)
            except Exception:
                pass
        self.click_hotkey_handle = keyboard.add_hotkey(key, lambda: self.after(0, self.toggle_autoclick))
        self.click_hotkey = key
        self.cfg["click_hotkey"] = key
        self.click_key_label.configure(text=key.upper())
        self.schedule_save()

    def start_rebind(self, which):
        btn = self.bind_btn if which == "capture" else self.click_bind_btn
        btn.configure(text="Press a key…", state="disabled")
        self.set_status("Press the new key combo")

        def worker():
            try:
                combo = keyboard.read_hotkey(suppress=False)
                self.after(0, lambda: self.finish_rebind(which, combo))
            except Exception as e:
                self.after(0, lambda: self.finish_rebind(which, None, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def finish_rebind(self, which, combo, err=None):
        if which == "capture":
            self.bind_btn.configure(text="Change bind", state="normal")
            other = self.click_hotkey
        else:
            self.click_bind_btn.configure(text="Bind play/pause", state="normal")
            other = self.hotkey
        if not combo:
            self.set_status(f"Bind failed: {err}")
            return
        if other and combo.lower() == other.lower():
            self.set_status(f"{combo.upper()} is already used by the other action")
            return
        try:
            if which == "capture":
                self.bind_hotkey(combo)
            else:
                self.bind_click_hotkey(combo)
            self.set_status(f"Bound to {combo.upper()}")
        except Exception as e:
            self.set_status(f"Bind failed: {e}")

    # ----- Mode / target / live view -----
    def set_status(self, msg):
        self.status.configure(text=msg)

    def post_status(self, msg):
        try:
            self.after(0, lambda: self.set_status(msg))
        except Exception:
            pass

    def on_mode(self, value):
        self.mode_name = value
        self.cfg["mode"] = value
        self.schedule_save()
        self._warned = False
        self._last_shown = None
        if value == "Window":
            if not self.target_exe:
                self.set_status("Pick a target window below")
        else:
            if self.embedded_hwnd:
                pass  # keep the embedded program visible
            elif self.last_img is not None:
                self.show_preview(self.last_img)
            else:
                self.show_idle()
        self.update_tag()

    def on_region_sw(self):
        self.cfg["window_region"] = bool(self.region_sw.get())
        self.schedule_save()
        if self.cfg["window_region"]:
            self.set_status("Window region ON - press the capture hotkey to cut a click image")

    def on_target(self, choice):
        new_exe = self.targets.get(choice, "")
        if self.embedded_hwnd and new_exe.lower() != self.target_exe.lower():
            self.release_target(quiet=True)
        self.target_exe = new_exe
        self.target_hwnd = None
        self.latest = None
        self._last_shown = None
        self._warned = False
        self._last_resolve = 0.0
        self.cfg["target_exe"] = self.target_exe
        self.schedule_save()
        if self.target_exe:
            self.set_status(f"Targeting {self.target_exe}")
            if self.mode_name != "Window":
                self.mode.set("Window")
                self.on_mode("Window")
        self.update_tag()

    def on_live(self):
        self.live_on = bool(self.live_switch.get())
        self.set_status("Live view on" if self.live_on else "Live view paused")
        self.update_tag()

    def on_engine(self, value):
        self.cfg["engine"] = value
        self.schedule_save()

    def update_tag(self):
        if self.embedded_hwnd:
            self.preview_tag.configure(text=f"● EMBEDDED   {self.target_exe}")
        elif self.mode_name == "Window" and self.target_exe:
            dot = "● LIVE" if self.live_on else "❚❚ PAUSED"
            self.preview_tag.configure(text=f"{dot}   {self.target_exe}")
        else:
            self.preview_tag.configure(text="")

    def refresh_targets(self):
        best = {}
        for w in list_windows(os.getpid()):
            k = w["exe"].lower()
            if k not in best or w["area"] > best[k]["area"]:
                best[k] = w
        self.targets = {NONE_LABEL: ""}
        labels = [NONE_LABEL]
        for k in sorted(best):
            w = best[k]
            label = f"{w['exe']} — {w['title'][:26]}"
            self.targets[label] = w["exe"]
            labels.append(label)
        cur = self.target_exe
        if cur and cur.lower() not in best:
            label = f"{cur} (embedded)" if self.embedded_hwnd else f"{cur} (not running)"
            self.targets[label] = cur
            labels.insert(1, label)
        self.target_menu.configure(values=labels)
        sel = None
        if cur:
            sel = next((l for l, e in self.targets.items() if e and e.lower() == cur.lower()), None)
        self.target_menu.set(sel or NONE_LABEL)

    def resolve_hwnd(self, force=False):
        exe = self.target_exe
        if not exe:
            return None
        if self.embedded_hwnd and user32.IsWindow(self.embedded_hwnd):
            return self.embedded_hwnd
        h = self.target_hwnd
        if h and user32.IsWindow(h) and user32.IsWindowVisible(h):
            return h
        now = time.time()
        if not force and now - self._last_resolve < 1.0:
            return None
        self._last_resolve = now
        best = None
        for w in list_windows(os.getpid()):
            if w["exe"].lower() == exe.lower() and (best is None or w["area"] > best["area"]):
                best = w
        self.target_hwnd = best["hwnd"] if best else None
        return self.target_hwnd

    def live_loop(self):
        while True:
            try:
                if (self.live_on and self.mode_name == "Window" and self.target_exe
                        and not self.embedded_hwnd):
                    hwnd = self.resolve_hwnd()
                    self.latest = grab_window(hwnd) if hwnd else None
            except Exception:
                self.latest = None
            time.sleep(0.08)

    def poll_live(self):
        try:
            if self.embedded_hwnd:
                if not user32.IsWindow(self.embedded_hwnd):
                    self.release_target(quiet=True)
                    self.set_status("The embedded program was closed")
            elif self.mode_name == "Window" and self.live_on and self.target_exe:
                frame = self.latest
                if frame is not None:
                    self._warned = False
                    if time.time() > self.freeze_until and frame is not self._last_shown:
                        self._last_shown = frame
                        self.show_preview(frame)
                elif not self._warned:
                    self._warned = True
                    self.set_status(f"Can't see {self.target_exe} (closed or minimized?)")
        except Exception:
            pass
        finally:
            self.after(100, self.poll_live)

    # ----- Embedding the target window inside the app -----
    def show_host(self, on):
        if on:
            self.preview.grid_remove()
            self.host.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        else:
            self.host.grid_remove()
            self.preview.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def on_host_resize(self, e):
        h = self.embedded_hwnd
        if h and user32.IsWindow(h):
            user32.SetWindowPos(h, None, 0, 0, e.width, e.height, 0x0004 | 0x0010)

    def toggle_embed(self):
        if self.embedded_hwnd:
            self.release_target()
        else:
            self.embed_target()

    def update_embed_ui(self):
        if self.embedded_hwnd:
            self.embed_btn.configure(text="Release window", fg_color=PANEL_2, hover_color=DANGER)
        else:
            self.embed_btn.configure(text="Embed in app", fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.update_tag()

    def embed_target(self):
        if not self.target_exe:
            self.set_status("Pick a target window first")
            return
        hwnd = self.resolve_hwnd(force=True)
        if not hwnd:
            self.set_status(f"{self.target_exe} isn't running")
            return
        if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(0.15)

        rc = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        info = {
            "style": get_style(hwnd, GWL_STYLE),
            "ex": get_style(hwnd, GWL_EXSTYLE),
            "rect": (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top),
        }

        self.latest = None
        self.show_host(True)
        self.update_idletasks()
        host_id = self.host.winfo_id()
        w, h = max(self.host.winfo_width(), 50), max(self.host.winfo_height(), 50)

        # Per Win32 docs: switch POPUP -> CHILD *before* SetParent.
        set_style(hwnd, GWL_STYLE, (info["style"] & ~WS_STRIP) | WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS)
        set_style(hwnd, GWL_EXSTYLE, info["ex"] & ~EX_STRIP)
        user32.SetParent(hwnd, host_id)

        if (user32.GetParent(hwnd) or 0) != host_id:
            restore_window(hwnd, info)
            self.show_host(False)
            self.set_status(f"Windows refused to embed {self.target_exe}. Try running Herta "
                            "Capture as administrator (or the app is a Store/UWP app).")
            return

        user32.SetWindowPos(hwnd, None, 0, 0, w, h, 0x0004 | 0x0010 | 0x0020 | 0x0040)
        self.embedded_hwnd = hwnd
        self.embed_info = info
        _EMBEDDED[hwnd] = info
        if self.mode_name != "Window":
            self.mode.set("Window")
            self.on_mode("Window")
        self.update_embed_ui()
        self.set_status(f"{self.target_exe} is inside the app - click it like normal")

    def release_target(self, quiet=False):
        hwnd, info = self.embedded_hwnd, self.embed_info
        self.embedded_hwnd = None
        self.embed_info = None
        if hwnd and info:
            restore_window(hwnd, info)
        self.show_host(False)
        self._last_shown = None
        self._warned = False
        if self.last_img is not None:
            self.show_preview(self.last_img)
        else:
            self.show_idle()
        self.update_embed_ui()
        if not quiet:
            self.set_status("Window released back to the desktop")

    def set_thumb(self, img):
        if img is None:
            self.thumb.configure(image=self.blank)
            self.thumb.image = self.blank
            return
        t = img.copy()
        t.thumbnail((120, 68), Image.BILINEAR)
        c = make_cimg(self.thumb, t)
        self.thumb.configure(image=c)
        self.thumb.image = c

    # ----- Click images (templates) -----
    def template_path(self, name):
        return os.path.join(TEMPLATE_DIR, f"{name}.png")

    def template_names(self):
        try:
            return sorted(os.path.splitext(f)[0] for f in os.listdir(TEMPLATE_DIR)
                          if f.lower().endswith(".png"))
        except OSError:
            return []

    def unique_name(self, name, ignore=None):
        base, n, cand = name, 2, name
        while cand.lower() != (ignore or "").lower() and os.path.exists(self.template_path(cand)):
            cand = f"{base}_{n}"
            n += 1
        return cand

    def refresh_templates(self):
        names = self.template_names()
        cur = self.cfg["template"]
        if cur not in names:
            cur = names[0] if names else ""
            self.cfg["template"] = cur
        # keep click points (dict) and image steps whose file still exists
        self.cfg["sequence"] = [s for s in self.cfg["sequence"] if isinstance(s, dict) or s in names]
        self.tpl_menu.configure(values=names or [NONE_LABEL])
        self.tpl_menu.set(cur or NONE_LABEL)
        self.update_tpl_thumb()
        self.refresh_sequence()

    def update_tpl_thumb(self):
        name = self.cfg["template"]
        p = self.template_path(name) if name else ""
        if p and os.path.exists(p):
            try:
                with Image.open(p) as im:
                    t = im.convert("RGB")
                t.thumbnail((200, 90), Image.BILINEAR)
                c = make_cimg(self.tpl_thumb, t)
                self.tpl_thumb.configure(image=c)
                self.tpl_thumb.image = c
                return
            except Exception:
                pass
        self.tpl_thumb.configure(image=self.blank)
        self.tpl_thumb.image = self.blank

    def on_template(self, choice):
        self.cfg["template"] = "" if choice == NONE_LABEL else choice
        self.update_tpl_thumb()
        self.schedule_save()
        if self.clicking and not self.cfg["sequence"]:
            self.stop_autoclick("Click image changed - press Play again")

    def next_default_name(self):
        return self.unique_name("click_1")

    def after_window_region(self, crop):
        if crop is None:
            self.busy = False
            self.set_status("Cancelled")
            return
        NameDialog(self, crop, self.next_default_name(),
                   lambda name, c=crop: self.finish_template(c, name))

    def finish_template(self, crop, name):
        self.busy = False
        if not name:
            self.set_status("Cancelled - nothing saved")
            return
        name = self.unique_name(name)
        try:
            crop.save(self.template_path(name))
        except Exception as e:
            self.set_status(f"Couldn't save click image: {e}")
            return
        self.cfg["template"] = name
        self.refresh_templates()
        self.schedule_save()
        self.set_status(f"Saved click image '{name}' - use ＋ Add selected to put it in the sequence")

    def rename_template(self):
        cur = self.cfg["template"]
        p = self.template_path(cur) if cur else ""
        if not p or not os.path.exists(p):
            self.set_status("No click image selected")
            return
        try:
            with Image.open(p) as im:
                img = im.convert("RGB")
        except Exception as e:
            self.set_status(f"Couldn't open it: {e}")
            return
        NameDialog(self, img, cur, lambda n, c=cur: self.finish_rename(c, n), title="Rename click image")

    def finish_rename(self, old, new):
        if not new or new == old:
            return
        new = self.unique_name(new, ignore=old)
        try:
            os.replace(self.template_path(old), self.template_path(new))
        except OSError as e:
            self.set_status(f"Rename failed: {e}")
            return
        self.cfg["template"] = new
        self.cfg["sequence"] = [new if n == old else n for n in self.cfg["sequence"]]
        self.refresh_templates()
        self.schedule_save()
        self.set_status(f"Renamed to '{new}'")

    def delete_template(self):
        cur = self.cfg["template"]
        p = self.template_path(cur) if cur else ""
        if not p or not os.path.exists(p):
            self.set_status("No click image selected")
            return
        if self.clicking:
            self.stop_autoclick()
        try:
            os.remove(p)
        except OSError as e:
            self.set_status(f"Couldn't delete: {e}")
            return
        self.cfg["template"] = ""
        self.cfg["sequence"] = [n for n in self.cfg["sequence"] if n != cur]
        self.refresh_templates()
        self.schedule_save()
        self.set_status(f"Deleted '{cur}'")

    # ----- Sequence -----
    def refresh_sequence(self):
        for w in self.seq_frame.winfo_children():
            w.destroy()
        seq = self.cfg["sequence"]
        if not seq:
            ctk.CTkLabel(self.seq_frame, text="(empty)", text_color=MUTED,
                         font=("Segoe UI", 11)).pack(anchor="w", padx=4)
            return
        for i, item in enumerate(seq):
            row = ctk.CTkFrame(self.seq_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            if isinstance(item, dict):  # click point block (click the row to flash it on screen)
                mark = "◈" if item.get("rel") else "◎"  # ◈ = inside the target window, ◎ = on the screen
                ctk.CTkButton(row, text=f"{i + 1}. {mark} {item.get('label', 'Point')}", anchor="w",
                              height=24, corner_radius=6, fg_color="transparent", hover_color=PANEL_2,
                              text_color=LILAC, font=("Segoe UI", 12),
                              command=lambda i=i: self.show_point(i)
                              ).pack(side="left", fill="x", expand=True)
            else:
                short = item if len(item) <= 16 else item[:15] + "…"
                ctk.CTkLabel(row, text=f"{i + 1}. {short}", text_color=TEXT, anchor="w",
                             font=("Segoe UI", 12)).pack(side="left", fill="x", expand=True, padx=(4, 0))
            for txt, cmd, hov in (("✕", lambda i=i: self.seq_remove(i), DANGER),
                                  ("▼", lambda i=i: self.seq_move(i, 1), ACCENT),
                                  ("▲", lambda i=i: self.seq_move(i, -1), ACCENT)):
                ctk.CTkButton(row, text=txt, width=26, height=24, corner_radius=6, fg_color=PANEL_2,
                              hover_color=hov, text_color=TEXT, command=cmd
                              ).pack(side="right", padx=(2, 0))
            if isinstance(item, dict):  # repeat count for this point
                ent = ctk.CTkEntry(row, width=34, height=24, corner_radius=6, border_width=0,
                                   fg_color=PANEL_2, text_color=TEXT, justify="center",
                                   font=("Segoe UI", 12))
                ent.pack(side="right", padx=(2, 0))
                ent.insert(0, str(max(int(item.get("repeat", 1) or 1), 1)))
                ent.bind("<Return>", lambda e, i=i, ent=ent: self.set_point_repeat(i, ent))
                ent.bind("<FocusOut>", lambda e, i=i, ent=ent: self.set_point_repeat(i, ent))
                ctk.CTkLabel(row, text="×", width=10, text_color=MUTED).pack(side="right")

    def set_point_repeat(self, i, ent):
        """Save the number typed next to a point (1-99)."""
        try:
            seq = self.cfg["sequence"]
            if not (0 <= i < len(seq)) or not isinstance(seq[i], dict):
                return
            txt = "".join(c for c in ent.get() if c.isdigit())
            v = min(max(int(txt), 1), 99) if txt else 1
            ent.delete(0, "end")
            ent.insert(0, str(v))
            if seq[i].get("repeat", 1) != v:
                seq[i]["repeat"] = v
                self.schedule_save()
                if self.clicking:
                    self.set_status("Repeat changed - press Pause, then Play to apply")
        except Exception:
            pass

    def seq_changed(self):
        self.schedule_save()
        self.refresh_sequence()
        if self.clicking:
            self.stop_autoclick("Sequence changed - press Play again")

    def seq_add(self):
        name = self.cfg["template"]
        if not name:
            self.set_status("Pick or capture a click image first")
            return
        self.cfg["sequence"].append(name)
        self.seq_changed()
        self.set_status(f"Added '{name}' as step {len(self.cfg['sequence'])}")

    def seq_remove(self, i):
        if 0 <= i < len(self.cfg["sequence"]):
            del self.cfg["sequence"][i]
            self.seq_changed()

    def seq_move(self, i, d):
        seq = self.cfg["sequence"]
        j = i + d
        if 0 <= i < len(seq) and 0 <= j < len(seq):
            seq[i], seq[j] = seq[j], seq[i]
            self.seq_changed()

    def seq_clear(self):
        self.cfg["sequence"] = []
        self.seq_changed()

    # ----- Click points -----
    def point_screen_pos(self, s):
        """Where a saved point is on the real screen right now (None if its window isn't visible)."""
        try:
            if s.get("rel"):
                hwnd = self.resolve_hwnd()
                if not hwnd or user32.IsIconic(hwnd):
                    return None
                ox, oy = client_origin(hwnd)
                return ox + int(s["x"]), oy + int(s["y"])
            return int(s["x"]), int(s["y"])
        except Exception:
            return None

    def mark_list(self):
        out = []
        for i, s in enumerate(self.cfg["sequence"]):
            if isinstance(s, dict):
                p = self.point_screen_pos(s)
                if p:
                    out.append((p[0], p[1], i + 1))
        return out

    def show_points(self, only=None):
        for m in self.markers:
            try:
                m.destroy()
            except Exception:
                pass
        self.markers = []
        if not isinstance(only, int):  # the "Show points" button passes nothing
            only = None
        for sx, sy, num in self.mark_list():
            if only is None or num - 1 == only:
                self.markers.append(PointMarker(self, sx, sy, num, 4000))
        if not self.markers:
            self.set_status("No click points to show (window points need their window visible)")

    def show_point(self, i):
        self.show_points(only=i)

    def add_point(self):
        if self.busy:
            return
        if self.mode_name == "Window" and self.target_exe:
            hwnd = self.embedded_hwnd or self.resolve_hwnd(force=True)
            img = grab_window(hwnd) if hwnd else None
            if img is None:
                self.set_status(f"Can't see {self.target_exe} (closed or minimized?)")
                return
            origin, rel = client_origin(hwnd), True
        else:
            self.busy = True
            self.hide_for_capture()
            self.update()
            time.sleep(0.25)  # let the window disappear
            try:
                img, origin = self.grab_screen()
            except Exception as e:
                self.deiconify()
                self.sync_backdrop()
                self.busy = False
                self.set_status(f"Capture failed: {e}")
                return
            rel = False
        self.busy = True
        PointPicker(self, img, origin,
                    lambda p, o=origin, r=rel: self.after_point(p, r, o), self.mark_list())

    def after_point(self, pt, rel, origin):
        if self.state() == "withdrawn":
            self.deiconify()
            self.sync_backdrop()
        self.busy = False
        if pt is None:
            self.set_status("Cancelled")
            return
        # window points are stored relative to the window, screen points as absolute positions
        x, y = pt if rel else (origin[0] + pt[0], origin[1] + pt[1])
        n = sum(1 for s in self.cfg["sequence"] if isinstance(s, dict)) + 1
        self.cfg["sequence"].append({"type": "point", "label": f"Point {n}",
                                     "x": int(x), "y": int(y), "rel": bool(rel), "repeat": 1})
        self.seq_changed()
        self.show_point(len(self.cfg["sequence"]) - 1)
        self.set_status(f"Added click point as step {len(self.cfg['sequence'])}")

    # ----- Auto click -----
    def update_play_ui(self):
        if self.clicking:
            self.play_btn.configure(text="⏸  Pause", fg_color=DANGER, hover_color="#A8407B")
        else:
            self.play_btn.configure(text="▶  Play", fg_color=GOOD, hover_color="#4E9A70")

    def toggle_autoclick(self):
        if self.clicking:
            self.stop_autoclick()
        else:
            self.start_autoclick()

    def start_autoclick(self):
        try:
            import cv2
        except Exception:
            self.set_status("OpenCV is missing - run: pip install opencv-python-headless")
            return
        seq = [s for s in self.cfg["sequence"]
               if isinstance(s, dict) or os.path.exists(self.template_path(s))]
        single = not seq
        if single:
            cur = self.cfg["template"]
            if not cur or not os.path.exists(self.template_path(cur)):
                self.set_status("Pick or capture a click image first")
                return
            seq = [cur]
        steps = []
        try:
            for s in seq:
                if isinstance(s, dict):
                    steps.append(("point", s.get("label", "Point"),
                                  (int(s["x"]), int(s["y"]), bool(s.get("rel")),
                                   max(int(s.get("repeat", 1) or 1), 1))))
                else:
                    with Image.open(self.template_path(s)) as im:
                        gray = cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2GRAY)
                    steps.append(("img", s, gray))
        except Exception as e:
            self.set_status(f"Couldn't open click image: {e}")
            return
        self.click_gen += 1
        self.clicking = True
        self.click_count = 0
        self.round_no = 0
        self._round_clicks = 0
        self._round_start = time.time()
        self.update_play_ui()
        what = f"{len(steps)}-step sequence" if not single else f"'{seq[0]}'"
        self.set_status(f"▶ Auto-click running: {what}")
        threading.Thread(target=self.click_loop, args=(self.click_gen, steps, single), daemon=True).start()

    def stop_autoclick(self, msg="⏸ Auto-click paused"):
        self.clicking = False
        self.click_gen += 1
        self.update_play_ui()
        self.set_status(msg)

    def click_times(self, x, y, total, alive):
        """Click (x, y) 'total' times (this point's own repeat). Returns how many clicks happened."""
        done = 0
        for k in range(max(int(total), 1)):
            if not alive():
                break
            mouse_click(x, y)
            done += 1
            if k < total - 1:
                time.sleep(0.12)  # short gap between repeated clicks
        return done

    # ----- Discord webhook (loot) -----
    def on_webhook_url(self):
        self.cfg["webhook_url"] = self.webhook_entry.get().strip()
        self.schedule_save()

    def test_webhook(self):
        url = self.cfg["webhook_url"].strip()
        if not webhook_ok(url):
            self.set_status("Paste a Discord webhook URL first (https://discord.com/api/webhooks/...)")
            return
        self.set_status("Sending test message…")
        threading.Thread(target=self._send_webhook, args=(url, "✦ Herta Capture webhook test - it works!",
                                                          None), daemon=True).start()

    def _send_webhook(self, url, text, img):
        try:
            send_webhook(url, text, img)
            self.post_status("✔ Sent to Discord")
        except Exception as e:
            self.post_status(f"Discord webhook failed: {e}")

    def round_done(self, alive):
        """Called from the click thread when the last step of the sequence was clicked."""
        self.round_no += 1
        clicks = self.click_count - self._round_clicks
        took = int(time.time() - self._round_start)
        url = self.cfg["webhook_url"].strip()
        if self.cfg["webhook_on"] and webhook_ok(url):
            end = time.time() + float(self.cfg["webhook_delay"])
            while time.time() < end and alive():  # let the loot screen appear
                time.sleep(0.03)
            if alive():
                shot = None
                try:
                    shot = self.search_image()[0]
                except Exception:
                    pass
                m, s = divmod(took, 60)
                text = f"✦ Round {self.round_no} finished  •  {clicks} clicks  •  {m}m {s:02d}s"
                threading.Thread(target=self._send_webhook, args=(url, text, shot), daemon=True).start()
        self._round_clicks = self.click_count
        self._round_start = time.time()

    def search_image(self):
        """(image, screen origin, hwnd) of the area we look for the click image in."""
        if self.mode_name == "Window" and self.target_exe:
            hwnd = self.resolve_hwnd()
            if not hwnd:
                return None, None, None
            img = grab_window(hwnd)
            if img is None:
                return None, None, None
            return img, client_origin(hwnd), hwnd
        with mss.mss() as s:
            mon = s.monitors[0]
            shot = s.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img, (mon["left"], mon["top"]), None

    def click_loop(self, gen, steps, single):
        import cv2
        n = len(steps)
        idx = 0
        step_started = time.time()
        alive = lambda: self.clicking and gen == self.click_gen
        while alive():
            kind, name, data = steps[idx]
            label = f"Step {idx + 1}/{n} '{name}'" if n > 1 else f"'{name}'"
            found = False
            try:
                if kind == "point":
                    # ---- click point: no searching, just click the saved spot ----
                    px, py, rel, reps = data
                    cx = cy = None
                    hwnd = None
                    if rel:
                        hwnd = self.resolve_hwnd()
                        if hwnd and not user32.IsIconic(hwnd):
                            ox, oy = client_origin(hwnd)
                            cx, cy = ox + px, oy + py
                    else:
                        cx, cy = px, py
                    if cx is None:
                        self.post_status("Auto-click: waiting for the target window…")
                    elif hwnd and not point_hits_window(cx, cy, hwnd):
                        self.post_status("Point is covered by another window - bring it to front")
                    elif alive():
                        done = self.click_times(cx, cy, reps, alive)
                        found = done > 0
                        self.click_count += done
                        self.post_status(f"▶ {label} clicked {done}x  ({self.click_count} total)")
                        self.after(0, lambda x=cx, y=cy, k=idx + 1: PointMarker(self, x, y, k, 400))
                        if (self.cfg["always_scroll"] and not self.cfg["scroll_only_missing"]
                                and alive()):
                            mouse_scroll_down(cx, cy, int(round(self.cfg["scroll_amount"])))
                else:
                    # ---- image step: find the picture on screen, click its centre ----
                    tpl_gray = data
                    th, tw = tpl_gray.shape
                    shot, origin, hwnd = self.search_image()
                    if shot is None:
                        self.post_status("Auto-click: waiting for the target window…")
                    else:
                        hay = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
                        if hay.shape[0] < th or hay.shape[1] < tw:
                            self.post_status("Auto-click: click image is bigger than the search area")
                        else:
                            res = cv2.matchTemplate(hay, tpl_gray, cv2.TM_CCOEFF_NORMED)
                            _, best, _, loc = cv2.minMaxLoc(res)
                            if best != best:  # NaN (flat single-colour image)
                                best = 0.0
                            if best >= self.cfg["click_threshold"]:
                                cx = origin[0] + loc[0] + tw // 2
                                cy = origin[1] + loc[1] + th // 2
                                if hwnd and not point_hits_window(cx, cy, hwnd):
                                    self.post_status("Found it, but the window is covered - bring it to front")
                                elif alive():
                                    mouse_click(cx, cy)
                                    found = True
                                    self.click_count += 1
                                    self.post_status(f"▶ {label} clicked  ({self.click_count} total, "
                                                     f"match {int(best * 100)}%)")
                            else:
                                self.post_status(f"▶ {label}: searching…  best match {int(best * 100)}%")

                        # always scroll down (optionally only while the image isn't found)
                        if (self.cfg["always_scroll"] and alive()
                                and not (self.cfg["scroll_only_missing"] and found)):
                            sx, sy = origin[0] + shot.width // 2, origin[1] + shot.height // 2
                            if not hwnd or point_hits_window(sx, sy, hwnd):
                                mouse_scroll_down(sx, sy, int(round(self.cfg["scroll_amount"])))
            except Exception as e:
                self.after(0, lambda e=e: self.stop_autoclick(f"Auto-click error: {e}"))
                return

            if found:
                idx += 1
                step_started = time.time()
                if idx >= n:
                    if not single:
                        self.round_done(alive)  # webhook: send the loot for this round
                        if not alive():
                            return
                    if self.cfg["loop_sequence"] or single:
                        idx = 0
                    else:
                        self.after(0, lambda: self.stop_autoclick("✔ Sequence finished"))
                        return
                delay = float(self.cfg["click_delay"])
            else:
                timeout = float(self.cfg["step_timeout"])
                if timeout >= 0.5 and n > 1 and time.time() - step_started > timeout:
                    self.post_status(f"{label} not found - skipping")
                    idx += 1
                    step_started = time.time()
                    if idx >= n:
                        if self.cfg["loop_sequence"]:
                            idx = 0
                        else:
                            self.after(0, lambda: self.stop_autoclick("Sequence ended (last step skipped)"))
                            return
                delay = float(self.cfg["click_interval"])

            end = time.time() + max(delay, 0.05)
            while time.time() < end and alive():
                time.sleep(0.03)

    # ----- Capture -----
    def grab_screen(self):
        with mss.mss() as s:
            mon = s.monitors[0]  # all monitors combined
            shot = s.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img, (mon["left"], mon["top"])

    def capture(self):
        if self.busy:
            return

        if self.mode_name == "Window":
            if not self.target_exe:
                self.set_status("Pick a target window first")
                return
            hwnd = self.embedded_hwnd or self.resolve_hwnd(force=True)
            img = grab_window(hwnd) if hwnd else None
            if img is None:
                self.set_status(f"Can't capture {self.target_exe} (closed or minimized?)")
                return
            self.busy = True
            if self.cfg["window_region"]:
                # drag a box inside the window -> name it -> saved as a click image
                RegionPicker(self, img, client_origin(hwnd), self.after_window_region,
                             hint="Drag around the thing to click  •  Esc to cancel")
                return
            self.freeze_until = time.time() + 1.5
            self.after_capture(img)
            return

        self.busy = True
        self.hide_for_capture()
        self.update()
        time.sleep(0.25)  # let the window disappear
        try:
            img, origin = self.grab_screen()
        except Exception as e:
            self.deiconify()
            self.sync_backdrop()
            self.busy = False
            self.set_status(f"Capture failed: {e}")
            return

        if self.mode_name == "Region":
            RegionPicker(self, img, origin, self.after_capture)
        else:
            self.after_capture(img)

    def after_capture(self, img):
        if self.state() == "withdrawn":
            self.deiconify()
            self.sync_backdrop()
        if img is None:
            self.busy = False
            self.set_status("Cancelled")
            return

        path = None
        if self.cfg["autosave"]:
            stamp = f"{datetime.now():%Y%m%d_%H%M%S}_{int(time.time() * 1000) % 1000:03d}"
            path = os.path.join(SAVE_DIR, f"herta_{stamp}.png")
            try:
                img.save(path)
            except Exception as e:
                path = None
                self.set_status(f"Save failed: {e}")

        self.last_img = img
        self.last_path = path
        self.show_preview(img)
        self.set_thumb(img)
        self.refresh_count()
        name = os.path.basename(path) if path else "not saved to disk"
        self.set_status(f"Captured ({name})\nReading text…")
        self.textbox.delete("1.0", "end")
        self.text_hint.configure(text="")

        self.ocr_job += 1
        token = self.ocr_job
        engine = self.engine.get()
        threading.Thread(target=self.run_ocr, args=(img, engine, token), daemon=True).start()

    def run_ocr(self, img, engine, token):
        try:
            text = self.ocr.run(img, engine)
            err = None
        except Exception as e:
            text, err = "", str(e)
        self.after(0, lambda: self.finish_ocr(text, err, engine, token))

    def finish_ocr(self, text, err, engine, token):
        if token != self.ocr_job:  # discarded or superseded
            return
        self.busy = False
        if err:
            self.set_status(f"{engine} error: {err}")
            self.textbox.insert("1.0", f"[{engine} failed]\n{err}")
            self.text_hint.configure(text="error")
            return
        self.textbox.insert("1.0", text if text else "(no text detected)")
        lines = len([l for l in text.splitlines() if l.strip()])
        self.text_hint.configure(text=f"· {lines} line{'s' if lines != 1 else ''}" if text else "· none")
        if text and self.cfg["autocopy"]:
            self.clipboard_clear()
            self.clipboard_append(text)
        self.set_status(f"Done with {engine}" + (" - copied" if text and self.cfg["autocopy"] else ""))

    def copy_text(self):
        text = self.textbox.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.set_status("Copied to clipboard")

    # ----- Discard old screenshots -----
    def saved_files(self):
        try:
            return [os.path.join(SAVE_DIR, f) for f in os.listdir(SAVE_DIR)
                    if f.startswith("herta_") and f.lower().endswith(".png")]
        except OSError:
            return []

    def refresh_count(self):
        files = self.saved_files()
        size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
        self.count_label.configure(text=f"{len(files)} saved  ·  {size / 1_048_576:.1f} MB")

    def reset_after_discard(self):
        self.ocr_job += 1  # ignore any OCR still running
        self.busy = False
        self.last_img = None
        self.last_path = None
        self.set_thumb(None)
        self.textbox.delete("1.0", "end")
        self.text_hint.configure(text="")
        self.freeze_until = 0.0
        self._last_shown = None
        if not (self.mode_name == "Window" and self.live_on and self.target_exe) and not self.embedded_hwnd:
            self.show_idle()
        self.refresh_count()

    def discard_last(self):
        if self.last_img is None and not self.last_path:
            self.set_status("Nothing to discard")
            return
        if self.last_path and os.path.exists(self.last_path):
            try:
                os.remove(self.last_path)
            except OSError as e:
                self.set_status(f"Couldn't delete: {e}")
                return
        self.reset_after_discard()
        self.set_status("Discarded the last capture")

    def clear_all(self):
        if not self._confirm_clear:
            self._confirm_clear = True
            self.clear_btn.configure(text="Sure? Click again", fg_color=DANGER)
            self.after(3000, self.reset_clear_btn)
            return
        removed = 0
        for f in self.saved_files():
            try:
                os.remove(f)
                removed += 1
            except OSError:
                pass
        self.reset_clear_btn()
        self.reset_after_discard()
        self.set_status(f"Deleted {removed} old screenshot{'s' if removed != 1 else ''}")

    def reset_clear_btn(self):
        self._confirm_clear = False
        self.clear_btn.configure(text="Clear all old", fg_color=PANEL_2)


if __name__ == "__main__":
    HertaCapture().mainloop()
"""
iPad → Windows Clipboard Sync
Runs in the system tray; receives clipboard from iOS via WebSocket.
"""

import asyncio
import json
import signal
import sys
import threading
import tkinter as tk
from tkinter import ttk
import winsound
from collections import deque
from pathlib import Path

import pyperclip
import pystray
import aiohttp
from aiohttp import ClientSession, WSMsgType
from PIL import Image, ImageDraw

try:
    from windows_toasts import Toast, WindowsToaster, ToastButton, ToastActivatedEventArgs
    _toaster = WindowsToaster("Clipboard Sync")
    _toasts_available = True
except ImportError:
    _toasts_available = False

CONFIG_PATH = Path(__file__).parent / "config.json"
HISTORY_SIZE = 10

status = {"connected": False, "muted": False}
history = deque(maxlen=HISTORY_SIZE)
_config: dict = {}
_config_lock = threading.Lock()


# ── Config ────────────────────────────────────

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_config(host: str, secret: str):
    CONFIG_PATH.write_text(json.dumps({"host": host, "secret": secret}, indent=2))


def _ws_url() -> str:
    with _config_lock:
        return f"wss://{_config['host']}/ws?room={_config['secret']}"


def _health_url() -> str:
    with _config_lock:
        return f"https://{_config['host']}/"


def _is_configured() -> bool:
    with _config_lock:
        return bool(_config.get("host") and _config.get("secret"))


# ── Config dialog ─────────────────────────────

def show_config_dialog(on_save=None):
    with _config_lock:
        current = dict(_config)

    root = tk.Tk()
    root.title("CpSync — Configure")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=20)
    frame.grid(sticky="nsew")

    ttk.Label(frame, text="Server host").grid(row=0, column=0, sticky="w")
    host_var = tk.StringVar(value=current.get("host", ""))
    host_entry = ttk.Entry(frame, textvariable=host_var, width=42)
    host_entry.grid(row=1, column=0, pady=(4, 2))
    ttk.Label(frame, text="e.g. my-server.example.com", foreground="grey").grid(
        row=2, column=0, sticky="w", pady=(0, 14)
    )

    ttk.Label(frame, text="Room secret").grid(row=3, column=0, sticky="w")
    secret_var = tk.StringVar(value=current.get("secret", ""))
    secret_entry = ttk.Entry(frame, textvariable=secret_var, show="•", width=42)
    secret_entry.grid(row=4, column=0, pady=(4, 20))

    error_var = tk.StringVar()
    ttk.Label(frame, textvariable=error_var, foreground="red").grid(row=5, column=0)

    def _save():
        host = host_var.get().strip().rstrip("/")
        secret = secret_var.get().strip()
        if not host or not secret:
            error_var.set("Both fields are required.")
            return
        with _config_lock:
            _config["host"] = host
            _config["secret"] = secret
        _save_config(host, secret)
        root.destroy()
        if on_save:
            on_save()

    ttk.Button(frame, text="Save & Connect", command=_save).grid(row=6, column=0)
    root.bind("<Return>", lambda _: _save())
    (host_entry if not current.get("host") else secret_entry).focus()
    root.mainloop()


# ── Clipboard & notifications ─────────────────

def content_kind(text: str) -> tuple[str, str]:
    t = text.strip()
    if t.startswith(("http://", "https://", "www.")):
        return "🔗", "Link"
    if "\n" in t:
        return "📄", "Text block"
    return "📋", "Text"


def notify_clipboard(text: str):
    if status["muted"]:
        return
    winsound.MessageBeep(winsound.MB_ICONASTERISK)
    if not _toasts_available:
        return

    emoji, label = content_kind(text)
    preview = text[:120] + ("…" if len(text) > 120 else "")

    toast = Toast()
    toast.text_fields = [f"{emoji} {label} synced", preview]

    def _copy_again(_args: "ToastActivatedEventArgs"):
        pyperclip.copy(text)
        winsound.MessageBeep(winsound.MB_OK)

    try:
        toast.AddAction(ToastButton("Copy again", "copy_again"))
        toast.on_activated = _copy_again
    except Exception:
        pass

    _toaster.show_toast(toast)


# ── Tray ──────────────────────────────────────

def create_icon_image(color="grey"):
    img = Image.new("RGB", (64, 64), color=color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([16, 16, 48, 48], fill="white")
    draw.rectangle([24, 28, 40, 36], fill=color)
    return img


def add_to_history(text: str):
    try:
        history.remove(text)
    except ValueError:
        pass
    history.appendleft(text)
    tray_icon.update_menu()


def _open_config(icon, item):
    threading.Thread(
        target=show_config_dialog,
        kwargs={"on_save": lambda: print("Config updated, reconnecting on next cycle...")},
        daemon=True,
    ).start()


def build_menu(icon):
    def quit_app(icon, item):
        icon.stop()
        sys.exit(0)

    def toggle_mute(icon, item):
        status["muted"] = not status["muted"]
        icon.update_menu()

    def make_recall(value):
        def recall(icon, item):
            pyperclip.copy(value)
            winsound.MessageBeep(winsound.MB_OK)
        return recall

    def history_items():
        if not history:
            yield pystray.MenuItem("(no items yet)", None, enabled=False)
            return
        for entry in history:
            emoji, _ = content_kind(entry)
            label = entry.replace("\n", " ")[:50]
            if len(entry) > 50:
                label += "…"
            yield pystray.MenuItem(f"{emoji} {label}", make_recall(entry))

    return pystray.Menu(
        pystray.MenuItem(
            lambda text: "🟢 Connected" if status["connected"] else "🔴 Disconnected",
            None,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Recent (click to copy)", pystray.Menu(history_items)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Mute notifications",
            toggle_mute,
            checked=lambda item: status["muted"],
        ),
        pystray.MenuItem("Configure…", _open_config),
        pystray.MenuItem("Quit", quit_app),
    )


# ── WebSocket listener ────────────────────────

async def wake_server(session: ClientSession) -> bool:
    try:
        async with session.get(_health_url(), timeout=aiohttp.ClientTimeout(total=60)) as resp:
            print(f"  Health check: {resp.status}")
            return resp.status == 200
    except Exception as e:
        print(f"  Health check error: {e}")
        return False


async def listen():
    while True:
        if not _is_configured():
            await asyncio.sleep(1)
            continue

        try:
            async with ClientSession() as session:
                print("Waking server...")
                if not await wake_server(session):
                    print("Health check failed, retrying in 5s...")
                    await asyncio.sleep(5)
                    continue

                print("Connecting...")
                async with session.ws_connect(_ws_url()) as ws:
                    status["connected"] = True
                    tray_icon.icon = create_icon_image("green")
                    tray_icon.update_menu()
                    print("Connected! Waiting for clipboard content...")

                    async for msg in ws:
                        if msg.type == WSMsgType.TEXT:
                            text = msg.data.strip()
                            if text:
                                pyperclip.copy(text)
                                add_to_history(text)
                                print(f"✅ Clipboard updated: {text[:60]}...")
                                threading.Thread(
                                    target=notify_clipboard, args=(text,), daemon=True
                                ).start()
                        elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                            print("Connection closed.")
                            break

        except Exception as e:
            print(f"Connection lost: {e}. Retrying in 5s...")

        status["connected"] = False
        tray_icon.icon = create_icon_image("red")
        tray_icon.update_menu()
        await asyncio.sleep(5)


def start_ws_loop():
    asyncio.run(listen())


# ── Startup ───────────────────────────────────

with _config_lock:
    _config = _load_config()

if not _is_configured():
    show_config_dialog()

tray_icon = pystray.Icon(
    name="ClipboardSync",
    icon=create_icon_image("grey"),
    title="Clipboard Sync",
)
tray_icon.menu = build_menu(tray_icon)


def _shutdown(signum, frame):
    print("\nShutting down...")
    tray_icon.stop()


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGBREAK, _shutdown)

ws_thread = threading.Thread(target=start_ws_loop, daemon=True)
ws_thread.start()

print("Starting system tray...")
tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
tray_thread.start()

while tray_thread.is_alive():
    try:
        tray_thread.join(0.2)
    except KeyboardInterrupt:
        _shutdown(None, None)
        break

sys.exit(0)

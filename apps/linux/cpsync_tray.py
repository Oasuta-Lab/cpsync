"""
iPad → Linux Clipboard Sync
Lives in the tray (StatusNotifierItem) when the desktop has one, otherwise in a
small window. Receives clipboard from iOS via WebSocket; writes it with wl-copy.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

import aiohttp
from aiohttp import ClientSession, WSMsgType
from dbus_next.aio import MessageBus

# Native Wayland when available, X11 otherwise. Must be set before Qt loads.
os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cpsync"
CONFIG_PATH = CONFIG_DIR / "config.json"
# PyInstaller unpacks bundled data (icon.png, wl-copy — see release-linux.yml)
# next to the executable; fall back to the script dir when running from source.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
HISTORY_SIZE = 10
NOTIF_BUS, NOTIF_PATH = "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
SOUND_DIR = Path("/usr/share/sounds/freedesktop/stereo")

status = {"connected": False, "muted": False}
history = deque(maxlen=HISTORY_SIZE)
_config: dict = {}
_config_lock = threading.Lock()
_active = {"ws": None, "loop": None}  # live WebSocket, so a config change can force a reconnect


# ── Config ────────────────────────────────────

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_config(host: str, secret: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
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


def _reconnect():
    ws, loop = _active["ws"], _active["loop"]
    if ws is not None and loop is not None:
        asyncio.run_coroutine_threadsafe(ws.close(), loop)


# ── Config dialog ─────────────────────────────

def show_config_dialog(parent=None) -> bool:
    with _config_lock:
        current = dict(_config)

    dlg = QDialog(parent)
    dlg.setWindowTitle("CpSync — Configure")
    form = QFormLayout(dlg)

    host = QLineEdit(current.get("host", ""))
    host.setPlaceholderText("my-server.example.com")
    secret = QLineEdit(current.get("secret", ""))
    secret.setEchoMode(QLineEdit.EchoMode.Password)
    error = QLabel()
    error.setStyleSheet("color: red")
    form.addRow("Server host", host)
    form.addRow("Room secret", secret)
    form.addRow(error)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save && Connect")

    def _save():
        h, s = host.text().strip().rstrip("/"), secret.text().strip()
        if not h or not s:
            error.setText("Both fields are required.")
            return
        with _config_lock:
            _config.update(host=h, secret=s)
        _save_config(h, s)
        dlg.accept()

    buttons.accepted.connect(_save)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)
    (host if not current.get("host") else secret).setFocus()
    return dlg.exec() == QDialog.DialogCode.Accepted


# ── Clipboard & notifications ─────────────────

def content_kind(text: str) -> tuple[str, str]:
    t = text.strip()
    if t.startswith(("http://", "https://", "www.")):
        return "🔗", "Link"
    if "\n" in t:
        return "📄", "Text block"
    return "📋", "Text"


def copy_to_clipboard(text: str):
    # Qt's clipboard is ignored on Wayland unless the app has focus; wl-copy
    # (bundled in the AppImage) serves the selection from a background process.
    if os.environ.get("WAYLAND_DISPLAY"):
        bundled = BUNDLE_DIR / "wl-copy"
        cmd = [str(bundled) if bundled.is_file() else "wl-copy"]
    else:
        cmd = ["xclip", "-selection", "clipboard"]
    try:
        subprocess.run(cmd, input=text.encode(), check=True, timeout=5, env=_system_env())
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Clipboard error ({cmd[0]}): {e}")


def _system_env() -> dict:
    # PyInstaller points LD_LIBRARY_PATH at its bundled libs; give host tools their own.
    env = dict(os.environ)
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    return env


def play_sound(name: str = "message-new-instant"):
    """Linux stand-in for winsound.MessageBeep: fire-and-forget, silently skipped if no player."""
    for player in ("pw-play", "paplay", "canberra-gtk-play"):
        args = [player, "-i", name] if player == "canberra-gtk-play" else [player, str(SOUND_DIR / f"{name}.oga")]
        try:
            subprocess.Popen(args, env=_system_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue


class Notifier:
    """org.freedesktop.Notifications with a 'Copy again' action. Lives on the asyncio loop."""

    def __init__(self):
        self._iface = None
        self._pending: dict[int, str] = {}

    async def _interface(self):
        if self._iface is None:
            bus = await MessageBus().connect()
            intro = await bus.introspect(NOTIF_BUS, NOTIF_PATH)
            self._iface = bus.get_proxy_object(NOTIF_BUS, NOTIF_PATH, intro).get_interface(NOTIF_BUS)
            self._iface.on_action_invoked(self._on_action)
            self._iface.on_notification_closed(lambda nid, _reason: self._pending.pop(nid, None))
        return self._iface

    def _on_action(self, nid: int, _key: str):
        text = self._pending.pop(nid, None)
        if text:
            copy_to_clipboard(text)
            play_sound("complete")

    async def notify(self, text: str):
        if status["muted"]:
            return
        play_sound()
        emoji, label = content_kind(text)
        preview = text[:120] + ("…" if len(text) > 120 else "")
        try:
            iface = await self._interface()
            nid = await iface.call_notify(
                "CpSync", 0, "edit-paste", f"{emoji} {label} synced", preview,
                ["copy_again", "Copy again"], {}, 5000,
            )
            self._pending[nid] = text
        except Exception as e:
            print(f"Notification error: {e}")
            self._iface = None


# ── UI (tray + window) ────────────────────────

# Brand mark (phone -> laptop), see assets/logo/build.py `symbol_small`. Rounded rects on a 256 grid;
# with odd-even fill the nested rects become holes and the piece inside the screen is filled again.
MARK_RECTS = ((8, 48, 88, 160, 22), (44, 84, 36, 36, 10),      # phone, hole
              (128, 48, 120, 108, 20), (148, 68, 80, 68, 6),   # laptop screen, cavity
              (164, 84, 36, 36, 10), (120, 176, 128, 32, 16))  # piece, keyboard


def make_icon(color: str) -> QIcon:
    """The mark in the connection-state colour on a transparent 64 px pixmap."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    path = QPainterPath()
    for x, y, w, h, r in MARK_RECTS:
        path.addRoundedRect(x, y, w, h, r, r)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(0.25, 0.25)
    p.fillPath(path, QColor(color))
    p.end()
    return QIcon(pm)


class Bridge(QObject):
    """Cross-thread events: asyncio thread → Qt main thread."""
    connected = Signal(bool)
    received = Signal(str)


bridge = Bridge()


class Window(QWidget):
    hide_on_close = False

    def closeEvent(self, event):
        if self.hide_on_close:
            event.ignore()
            self.hide()
        else:
            QApplication.quit()


class Ui(QObject):
    def __init__(self):
        super().__init__()
        self.mute_action = QAction("Mute notifications", self)
        self.mute_action.setCheckable(True)
        self.mute_action.toggled.connect(lambda v: status.__setitem__("muted", v))

        self.window = Window()
        self.window.setWindowTitle("CpSync")
        self.window.setWindowIcon(QIcon(str(BUNDLE_DIR / "icon.png")))
        self.window.resize(380, 320)
        layout = QVBoxLayout(self.window)
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("Recent (click to copy)"))
        self.list = QListWidget()
        self.list.itemClicked.connect(lambda item: self.recall(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.list)
        mute = QCheckBox("Mute notifications")
        mute.toggled.connect(self.mute_action.setChecked)
        self.mute_action.toggled.connect(mute.setChecked)
        layout.addWidget(mute)
        row = QHBoxLayout()
        configure = QPushButton("Configure…")
        configure.clicked.connect(self.configure)
        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(QApplication.quit)
        row.addWidget(configure)
        row.addWidget(quit_btn)
        layout.addLayout(row)

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_icon("grey"), self)
            self.menu = QMenu()
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()
            self.window.hide_on_close = True
        else:
            print("No system tray found (GNOME needs the AppIndicator extension); using a window.")
            self.window.show()

        bridge.connected.connect(self.set_connected)
        bridge.received.connect(self.add_to_history)
        self.refresh()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.window.setVisible(not self.window.isVisible())

    @staticmethod
    def recall(text: str):
        copy_to_clipboard(text)
        play_sound("complete")

    def configure(self):
        if show_config_dialog(self.window):
            print("Config updated, reconnecting...")
            _reconnect()
            self.refresh()

    def set_connected(self, connected: bool):
        status["connected"] = connected
        self.refresh()

    def add_to_history(self, text: str):
        try:
            history.remove(text)
        except ValueError:
            pass
        history.appendleft(text)
        self.refresh()

    def refresh(self):
        if status["connected"]:
            text, color = "🟢 Connected", "green"
        elif _is_configured():
            text, color = "🔴 Disconnected", "red"
        else:
            text, color = "⚪ Not configured", "grey"
        self.status_label.setText(text)

        self.list.clear()
        for entry in history:
            item = QListWidgetItem(self._label(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)

        if not self.tray:
            return
        self.tray.setIcon(make_icon(color))
        self.tray.setToolTip(f"CpSync — {text}")
        m = self.menu
        m.clear()
        m.addAction(text).setEnabled(False)
        m.addSeparator()
        recent = m.addMenu("Recent (click to copy)")
        if not history:
            recent.addAction("(no items yet)").setEnabled(False)
        for entry in history:
            recent.addAction(self._label(entry), lambda *_, e=entry: self.recall(e))
        m.addSeparator()
        m.addAction(self.mute_action)
        m.addAction("Configure…", self.configure)
        m.addAction("Show window", self.window.show)
        m.addAction("Quit", QApplication.quit)

    @staticmethod
    def _label(entry: str) -> str:
        emoji, _ = content_kind(entry)
        label = entry.replace("\n", " ")[:50]
        return f"{emoji} {label}" + ("…" if len(entry) > 50 else "")


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
    notifier = Notifier()
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
                    _active["ws"], _active["loop"] = ws, asyncio.get_running_loop()
                    bridge.connected.emit(True)
                    print("Connected! Waiting for clipboard content...")

                    async for msg in ws:
                        if msg.type == WSMsgType.TEXT:
                            text = msg.data.strip()
                            if text:
                                copy_to_clipboard(text)
                                bridge.received.emit(text)
                                print(f"✅ Clipboard updated: {text[:60]}...")
                                await notifier.notify(text)
                        elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                            print("Connection closed.")
                            break

        except Exception as e:
            print(f"Connection lost: {e}. Retrying in 5s...")

        bridge.connected.emit(False)
        await asyncio.sleep(5)


# ── Startup ───────────────────────────────────

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setApplicationName("CpSync")
    app.setDesktopFileName("cpsync")
    app.setQuitOnLastWindowClosed(False)

    with _config_lock:
        _config = _load_config()
    if not _is_configured():
        show_config_dialog()

    ui = Ui()
    threading.Thread(target=lambda: asyncio.run(listen()), daemon=True).start()
    sys.exit(app.exec())

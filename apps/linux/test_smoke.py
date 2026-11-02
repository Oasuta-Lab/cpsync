"""Offscreen smoke test — run: python test_smoke.py"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()

import cpsync_tray as app  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)

assert app.content_kind("https://example.com") == ("🔗", "Link")
assert app.content_kind("a\nb") == ("📄", "Text block")
assert app.content_kind("hello") == ("📋", "Text")

app._save_config("h.example.com", "s")
app._config.update(app._load_config())
assert app._is_configured() and app._ws_url() == "wss://h.example.com/ws?room=s"

ui = app.Ui()
server = app.single_instance(ui.show_window)
assert server is not None and app.single_instance(ui.show_window) is None, "second launch must be refused"
assert ui.status_label.text() == "🔴 Disconnected"
for text in ("hello", "hello", "world"):
    app.bridge.received.emit(text)
assert list(app.history) == ["world", "hello"], list(app.history)
assert ui.list.count() == 2 and ui.list.item(0).data(app.Qt.ItemDataRole.UserRole) == "world"
app.bridge.connected.emit(True)
assert ui.status_label.text() == "🟢 Connected"
ui.mute_action.setChecked(True)
assert app.status["muted"] is True
print("ok")

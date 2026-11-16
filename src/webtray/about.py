# Copyright 2026 Dieter Steinwedel
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""About dialog: version, web engine, storage locations and shortcuts."""

import os
import re

import PySide6
from PySide6.QtCore import QStandardPaths, Qt, qVersion
from PySide6.QtWidgets import QMessageBox

from . import APP_TITLE, __version__

AUTHOR = "Dieter Steinwedel"
COPYRIGHT = f"© 2026 {AUTHOR}"
LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0"

SHORTCUTS = [
    ("Ctrl + +", "Zoom in"),
    ("Ctrl + -", "Zoom out"),
    ("Ctrl + 0", "Reset zoom"),
    ("F5 / Ctrl + R", "Reload page"),
    ("Ctrl + W", "Hide window"),
]

MOUSE_ACTIONS = [
    ("Left-click tray icon", "Show / hide the page window"),
    ("Right-click tray icon", "Open the tray menu"),
    ("Hover tray icon", "Show page name, URL and favicon while the pointer is on the icon (tooltip, own hover note on XEmbed trays)"),
    ("Tray menu: Configure URLs…", "Add / edit a page: URL, and optional title and icon"),
]


def _rows(pairs):
    return "".join(
        f"<tr><td><b>{key}</b></td><td>&nbsp;{what}</td></tr>"
        for key, what in pairs
    )


def _engine_line(engine_info):
    m = re.search(r"QtWebEngine/([\d.]+).*Chrome/([\d.]+)", engine_info)
    return f"QtWebEngine {m.group(1)} · Chromium {m.group(2)}" if m else engine_info


def about_html(store, engine_info):
    """Full About dialog text (HTML)."""
    data_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    cache_dir = os.path.join(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation),
        "favicons")
    return (
        f"<h3>{APP_TITLE} {__version__}</h3>"
        "<p>Tray launcher for web applications — one page per tray icon.</p>"
        f"<p><b>Copyright:</b> {COPYRIGHT}<br>"
        f"<b>License:</b> <a href='{LICENSE_URL}'>Apache License 2.0</a></p>"
        "<p><b>Keyboard shortcuts</b></p>"
        f"<table cellpadding='2'>{_rows(SHORTCUTS)}</table>"
        "<p><b>Tray icon</b></p>"
        f"<table cellpadding='2'>{_rows(MOUSE_ACTIONS)}</table>"
        f"<p><b>Web engine:</b> {_engine_line(engine_info)}<br>"
        f"<b>Qt:</b> {qVersion()} (PySide6 {PySide6.__version__})</p>"
        f"<p><b>Settings:</b> {store.path}<br>"
        f"<b>Sessions:</b> {data_dir}<br>"
        f"<b>Favicon cache:</b> {cache_dir}</p>"
        + (f"<p>The settings file was unreadable and is kept as "
           f"<b>{store.path}.corrupt</b>; the configuration started empty.</p>"
           if getattr(store, "corrupt", None) else ""))


def show_about(store, engine_info):
    """Show the About dialog with engine info, storage paths and shortcuts."""
    box = QMessageBox(QMessageBox.Icon.NoIcon, f"About {APP_TITLE}",
                      about_html(store, engine_info))
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    box.exec()

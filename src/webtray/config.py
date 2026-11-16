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

"""Configuration dialog: manage the URL list — add, edit, remove, reorder.

The URL editor is the only place that sets the optional per-URL title and
icon file; the tray menus only open pages. Both are stored per URL in the
JSON settings (store.py), so every per-URL data — icon, title, geometry,
zoom — is one entry that follows the URL on rename and goes when it is
removed.
"""

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

ICON_FILTER = "Images (*.png *.svg *.xpm *.ico *.icns *.jpg *.jpeg *.bmp);;All files (*)"


def normalize(url):
    """Add the https:// scheme when the user only typed a host name."""
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


class UrlEditor(QDialog):
    """One URL entry: the address, plus an optional title and icon.

    Empty title/icon mean "follow the page": the page's own title and the
    site's favicon. apply() stores them for the address in the fields.
    """

    def __init__(self, store, url, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Add URL" if not url else "Edit URL")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("https://example.org")
        self.url_edit.setText(url)
        self.url_edit.setToolTip("Page to open — a host name alone gets https:// in front.")
        form.addRow("URL", self.url_edit)

        self.title_edit = QLineEdit(self)
        self.title_edit.setPlaceholderText("optional — the page's own title when empty")
        self.title_edit.setToolTip(
            "Shown in the tray tooltip and in front of the window title.")
        self.title_edit.setText(self.store.title(url))
        form.addRow("Title", self.title_edit)

        icon_row = QHBoxLayout()
        # the same sunken frame the line edits have, around the thumbnail
        self.icon_preview = QLabel(self)
        self.icon_preview.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setFixedSize(26, 26)      # 24 px thumbnail + 1 px frame
        icon_row.addWidget(self.icon_preview)

        self.icon_edit = QLineEdit(self)
        self.icon_edit.setReadOnly(True)
        self.icon_edit.setPlaceholderText("optional — the site's favicon when empty")
        self.icon_edit.setToolTip("Image for the tray icon (PNG, SVG, ICO, …).")
        self.icon_edit.setText(self.store.icon_path(url))
        self.icon_edit.textChanged.connect(self.show_icon_preview)
        icon_row.addWidget(self.icon_edit, 1)

        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self.pick_icon)
        icon_row.addWidget(browse)
        none_btn = QPushButton("None", self)
        none_btn.setToolTip("Use the site's favicon again")
        none_btn.clicked.connect(self.clear_icon)
        icon_row.addWidget(none_btn)
        form.addRow("Icon", self._wrap(icon_row))

        lay.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        ok = QPushButton("OK", self)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        lay.addLayout(buttons)

        self.show_icon_preview()
        self.url_edit.setFocus()

    @staticmethod
    def _wrap(box_layout):
        """QFormLayout.addRow() takes a widget, so the icon row goes in one."""
        holder = QWidget()
        holder.setLayout(box_layout)
        box_layout.setContentsMargins(0, 0, 0, 0)
        return holder

    def show_icon_preview(self):
        """Thumbnail of the picked icon (the tray shows it at these sizes)."""
        pm = QIcon(self.icon_edit.text()).pixmap(QSize(24, 24))
        if pm.isNull():
            self.icon_preview.clear()
        else:
            self.icon_preview.setPixmap(pm)

    def pick_icon(self):
        start = os.path.dirname(self.icon_edit.text()) or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Tray icon for this page", start, ICON_FILTER)
        if path:
            self.icon_edit.setText(path)

    def clear_icon(self):
        self.icon_edit.setText("")

    def apply(self):
        """Store title and icon for the address in the fields; returns the
        normalized URL ('' = nothing typed). An empty field clears the
        entry, so the page's own title resp. its favicon is used again."""
        url = normalize(self.url_edit.text())
        if not url:
            return ""
        self.store.set_title(url, self.title_edit.text())
        self.store.set_icon(url, self.icon_edit.text())
        return url

    def accept(self):
        """Only accept with a URL — an empty field edits nothing."""
        if not normalize(self.url_edit.text()):
            QMessageBox.warning(self, self.windowTitle(), "Please enter a URL.")
            self.url_edit.setFocus()
            return
        super().accept()


class ConfigDialog(QDialog):
    """Manage the list of URLs shown as tray icons.

    The list shows each entry with its optional title and custom icon, so
    the settings state is visible; Add/Edit open the URL editor.
    """

    def __init__(self, urls, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Configure URLs")
        self.resize(520, 320)
        lay = QVBoxLayout(self)

        self.list = QListWidget(self)
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(lambda _item: self.edit())
        for url in urls:
            self.append_entry(url)
        lay.addWidget(self.list)

        row = QHBoxLayout()
        self.buttons = {}
        for text, slot in [
            ("Add", self.add),
            ("Edit", self.edit),
            ("Remove", self.remove),
            ("Up", lambda: self.move(-1)),
            ("Down", lambda: self.move(+1)),
        ]:
            btn = QPushButton(text, self)
            btn.clicked.connect(slot)
            row.addWidget(btn)
            self.buttons[text] = btn
        row.addStretch()
        done = QPushButton("Close", self)
        done.setDefault(True)
        done.clicked.connect(self.accept)
        row.addWidget(done)
        lay.addLayout(row)
        # the list is full and the buttons exist: only now track the selection
        self.list.itemSelectionChanged.connect(self.refresh_buttons)
        self.refresh_buttons()

    def refresh_buttons(self):
        """Only offer what the current selection supports: Add always,
        Edit/Remove with entries selected, Up/Down within the list."""
        rows = self.list.count()
        row = self.list.currentRow()
        selected = len(self.list.selectedItems())
        self.buttons["Edit"].setEnabled(selected == 1)
        self.buttons["Remove"].setEnabled(selected > 0)
        self.buttons["Up"].setEnabled(rows > 1 and row > 0)
        self.buttons["Down"].setEnabled(rows > 1 and 0 <= row < rows - 1)

    def set_entry(self, item, url):
        """Item = the URL (in UserRole, urls() reads it) shown with its
        optional title in front and its custom icon."""
        item.setData(Qt.ItemDataRole.UserRole, url)
        title = self.store.title(url)
        item.setText(f"{title} — {url}" if title else url)
        icon = self.store.icon_path(url)
        item.setIcon(QIcon(icon) if icon else QIcon())
        item.setToolTip(url)
        return item

    def append_entry(self, url):
        """New row for a URL, made current."""
        self.list.addItem("")
        item = self.list.item(self.list.count() - 1)
        self.set_entry(item, url)
        self.list.setCurrentItem(item)

    def add(self):
        dlg = UrlEditor(self.store, "", self)
        if dlg.exec():
            url = dlg.apply()
            if url:
                self.append_entry(url)
                self.refresh_buttons()

    def edit(self):
        item = self.list.currentItem()
        if not item:
            return
        old = item.data(Qt.ItemDataRole.UserRole)
        dlg = UrlEditor(self.store, old, self)
        if dlg.exec():
            new = dlg.apply()
            if not new:
                return
            if new != old:
                # the editor stored title and icon under the new address;
                # the window data follows, and the old address is gone
                self.store.move_site(old, new)
            self.set_entry(item, new)
            self.list.setCurrentItem(item)
            self.refresh_buttons()

    def remove(self):
        selected = self.list.selectedItems()
        if len(selected) > 1:
            answer = QMessageBox.question(
                self, "Remove URLs", f"Really remove {len(selected)} URLs?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        for item in selected:
            self.store.drop_sites([item.data(Qt.ItemDataRole.UserRole)])
            self.list.takeItem(self.list.row(item))
        self.refresh_buttons()

    def move(self, direction):
        row = self.list.currentRow()
        target = row + direction
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self.refresh_buttons()

    def urls(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole).strip()
                for i in range(self.list.count())
                if self.list.item(i).data(Qt.ItemDataRole.UserRole).strip()]

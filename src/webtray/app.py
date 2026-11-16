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

"""Main application: tray icons, shared browser window and global actions."""

import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

import shiboken6
from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QFileSystemWatcher,
    QPoint,
    QRect,
    QSize,
    QSocketNotifier,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    qVersion,
)
from PySide6.QtGui import (
    QCursor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMenu,
    QSystemTrayIcon,
    QToolTip,
    QVBoxLayout,
)

from . import APP_NAME, APP_TITLE, about, favicons
from . import store as settings_store
from .config import ConfigDialog

ICON_SIZES = (16, 20, 22, 24, 28, 32, 36, 40, 44, 48, 56, 64, 74, 96, 128, 192, 256, 512)
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


def load_app_icon():
    """Branded icon: all sizes, plus 2x sources as real dpr-2 entries.

    Each size n is registered plainly; the 2n px PNG is registered at
    logical size n via addPixmap() with setDevicePixelRatio(2.0) —
    QIcon.addFile(path, QSize) does not set a dpr, it only hints a size.
    n px PNGs additionally become the dpr-2 source of logical size n/2
    when n/2 is not a base size (37 px is what the Cinnamon 2x tray
    requests), so 74 px tray requests get 1:1 pixels. XEmbed tray
    painting on Qt < 6.12 ignores dpr entirely — TrayPixelPainter
    covers that case with native pixels."""
    icon = QIcon()

    def add_dpr2(path):
        pm = QPixmap(path)
        if pm.isNull():
            return
        pm.setDevicePixelRatio(2.0)
        icon.addPixmap(pm, QIcon.Mode.Normal, QIcon.State.On)

    for size in ICON_SIZES:
        path = os.path.join(ICON_DIR, f"{size}x{size}.png")
        if os.path.isfile(path):
            icon.addFile(path)
        double = os.path.join(ICON_DIR, f"{2 * size}x{2 * size}.png")
        if 2 * size in ICON_SIZES and os.path.isfile(double):
            add_dpr2(double)
        half = size // 2
        if size % 2 == 0 and half not in ICON_SIZES and os.path.isfile(path):
            add_dpr2(path)
    if icon.isNull() and os.path.isfile("icon.png"):
        icon = QIcon("icon.png")
    return icon


# Chromium's own watchdog notices: pages that resize the layout from inside
# a ResizeObserver callback get these on every following frame (the loop
# simply continues there — the page keeps working), so the repeated text
# is noise rather than a problem of the app.
BENIGN_CONSOLE_MESSAGES = ("ResizeObserver loop completed with undelivered "
                          "notifications",
                          "ResizeObserver loop limit exceeded")


class Page(QWebEnginePage):
    """Page whose JavaScript console output does not flood the console.

    QtWebEngine's default implementation prints every console.log/warn/error
    of the visited page to the terminal prefixed "js: " — pages with banner
    and tracking scripts bury a tray app's console in that (on heise.de the
    ResizeObserver watchdog alone repeats dozens of times a second). The
    messages come out with WEBTRAY_DEBUG instead, less the watchdog above."""

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith(BENIGN_CONSOLE_MESSAGES):
            return
        if os.environ.get("WEBTRAY_DEBUG"):
            name = getattr(level, "name", str(level))
            name = name.replace("MessageLevel", "").lower()
            print(f"js [{name}] {message} ({source}:{int(line)})",
                  file=sys.stderr, flush=True)


class TrayView(QWebEngineView):
    """Browser window that remembers its geometry and zoom on close.

    Qt.Tool gives normal window decoration (movable, resizable, close
    button) without a separate taskbar entry of its own.
    """

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store
        self.current_url = ""
        self.setWindowFlags(Qt.Tool)

    def closeEvent(self, event):
        # remember window size/position and zoom — globally and per URL
        self._store.save_window(self, self.zoomFactor())
        self._store.save_site_window(self.current_url, self, self.zoomFactor())
        super().closeEvent(event)


def standard_key(name, fallback):
    """QKeySequence.StandardKey member as far as the PySide6 version has it,
    the literal key text otherwise (PySide6 lacks ZoomReset/ZoomOriginal)."""
    key = getattr(QKeySequence.StandardKey, name, None)
    return QKeySequence(key) if key is not None else QKeySequence(fallback)


def setup_shortcuts(view):
    """Zoom and window shortcuts (shown in the About dialog)."""

    def zoom_by(factor):
        view.setZoomFactor(min(max(view.zoomFactor() * factor, 0.25), 5.0))

    shortcuts = [
        (standard_key("ZoomIn", "Ctrl++"), lambda: zoom_by(1.1)),
        (standard_key("ZoomOut", "Ctrl+-"), lambda: zoom_by(1 / 1.1)),
        (standard_key("ZoomReset", "Ctrl+0"), lambda: view.setZoomFactor(1.0)),
        (standard_key("Refresh", "F5"), lambda: view.reload()),
        (QKeySequence("Ctrl+R"), lambda: view.reload()),
        (QKeySequence("Ctrl+W"), view.hide),
        (QKeySequence("Ctrl+F4"), view.hide),
    ]
    for seq, handler in shortcuts:
        sc = QShortcut(seq, view)
        sc.activated.connect(handler)


AUTOSTART_DESKTOP = """\
[Desktop Entry]
Type=Application
Version=1.0
Name=WebTray
GenericName=Web Application Tray Launcher
Comment=Open web applications from the system tray
Exec={exe}
Icon=webtray
Terminal=false
Categories=Network;WebBrowser;Utility;
StartupNotify=false
X-GNOME-Autostart-enabled={flag}
"""


def autostart_path():
    """Per-user XDG autostart entry (~/.config/autostart/webtray.desktop).
    Cinnamon and friends fully manage this location in their autostart GUI."""
    cfg = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.ConfigLocation)
    return os.path.join(cfg, "autostart", "webtray.desktop")


def autostart_enabled():
    path = autostart_path()
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8") as f:
        m = re.search(r"(?im)^\s*X-GNOME-Autostart-enabled\s*=\s*(\w+)", f.read())
    return m.group(1).lower() != "false" if m else True


def set_autostart(enable):
    path = autostart_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exe = shutil.which("webtray") or "webtray"
    with open(path, "w", encoding="utf-8") as f:
        f.write(AUTOSTART_DESKTOP.format(exe=exe, flag="true" if enable else "false"))


def urls_dir():
    """Drop-in URL files directory: ~/.config/webtray/urls (watched)."""
    return os.path.join(settings_store.config_dir(), "urls")


def read_url_file(path):
    """First http(s) URL in a file: plain "https://…" line, or URL= line
    (Windows .url INetShortcut / .desktop Type=Link style)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.lower().startswith("url="):
                    line = line[4:].strip().strip("\"'")
                if line.lower().startswith(("http://", "https://")):
                    return line
    except OSError:
        return None
    return None


def file_url_entries():
    """url -> path of the URL files in urls_dir(); hidden files, backups
    and temp files are ignored."""
    d = urls_dir()
    entries = {}
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return entries
    for name in names:
        if name.startswith(".") or name.endswith((".tmp", ".bak", ".swp", "~")):
            continue
        path = os.path.join(d, name)
        url = read_url_file(path)
        if url:
            entries[url] = path
    return entries


class WebTray:
    """Owns the tray icons, the shared web view and all actions."""

    def __init__(self, app):
        self.app = app
        self.store = settings_store.Store()
        self.engine_info = "Chromium (probed at startup…)"
        self._probe_page = None
        self.url_trays = {}   # url -> QSystemTrayIcon (references are mandatory!)
        self.file_urls = {}   # url -> path of drop-in URL files (urls dir)

        # urls dir: watch for added/removed/changed files (inotify backend)
        os.makedirs(urls_dir(), exist_ok=True)
        self.watcher = QFileSystemWatcher(app)
        self.watcher.directoryChanged.connect(self._on_watch_change)
        self.watcher.fileChanged.connect(self._on_watch_change)
        self._sync_timer = QTimer(app)   # debounce bursts (atomic saves)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(200)
        self._sync_timer.timeout.connect(self._sync_file_urls)

        # autostart: enabled by default — on first start, and self-healing
        # on every start (rewrites the entry if the desktop's autostart GUI
        # disabled it). ~/.config/autostart is honored by Cinnamon, GNOME,
        # KDE, XFCE …; the tray menu entry remains the user's on/off switch.
        autostart = self.store.autostart()
        if autostart is None:
            self.store.set_autostart(True)
            autostart = True
        if autostart:
            set_autostart(True)

        self.base_icon = QIcon.fromTheme(APP_NAME, load_app_icon())
        app.setWindowIcon(self.base_icon)
        self.cache_dir = os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation),
            "favicons")
        self.tray_painter = TrayPixelPainter(app, self.base_icon)

        self.profile = self._make_profile()
        self.view = self._make_view()
        self.nam = QNetworkAccessManager(app)

        urls = self.get_urls()
        self.view.setWindowTitle(urls[0] if urls else APP_TITLE)

        self._probe_engine()
        self._make_main_tray()
        self.rebuild_url_trays()
        self._sync_file_urls()       # drop-in URL files from the urls dir
        self.tray_painter.start()

        # also save geometry and zoom on "Quit" (globally and per URL)
        app.aboutToQuit.connect(self.save_all)

    # ---------- setup ----------

    def _make_profile(self):
        """Persistent WebEngine profile: logins survive restarts."""
        data_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        os.makedirs(data_dir, exist_ok=True)
        profile = QWebEngineProfile(APP_NAME, self.app)
        # Qt 6.5-6.11: set the paths explicitly; Qt 6.12+: the default path
        # (~/.local/share/<app>) is persistent for named profiles anyway —
        # everything lives below QtWebEngineDefault there.
        if hasattr(profile, "setStoragePath"):
            profile.setStoragePath(data_dir)
        elif hasattr(profile, "setPersistentStoragePath"):
            profile.setPersistentStoragePath(data_dir)
            if hasattr(profile, "setPersistentCookiesPath"):
                profile.setPersistentCookiesPath(os.path.join(data_dir, "cookies"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        return profile

    def _make_view(self):
        view = TrayView(self.store)
        page = Page(self.profile, view)
        view.setPage(page)

        # window icon = favicon of the loaded page
        page.iconChanged.connect(lambda ic: view.setWindowIcon(ic) if not ic.isNull() else None)

        # survive renderer crashes: reload the page instead of a white window
        def on_render_terminated(status, _exit_code):
            normal = QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus
            if status != normal:
                view.reload()

        page.renderProcessTerminated.connect(on_render_terminated)

        # restore the last window size/position; first start: centered, one third of the desktop
        if not settings_store.apply_geometry(view, self.store.geometry_for()):
            self.default_geometry(view)

        # window title and the tray tooltip of the current URL = page title
        # (a custom per-URL title goes in front, and the tooltip always
        # ends with the URL, so hovering shows which page opens)
        def on_title(title):
            if not title:
                return
            url = view.current_url
            view.setWindowTitle(self.combined_title(url, title))
            tray = self.url_trays.get(url)
            if tray is not None:
                tray.setToolTip(self.tray_tooltip(url, title))

        view.titleChanged.connect(on_title)

        setup_shortcuts(view)
        return view

    def _probe_engine(self):
        """Read navigator.userAgent from a probe page to learn the
        QtWebEngine/Chromium versions for the About dialog."""
        probe = Page(self.profile)

        def probe_loaded(_ok):
            def store(ua):
                if ua:
                    self.engine_info = ua

            probe.runJavaScript("navigator.userAgent", store)

        probe.loadFinished.connect(probe_loaded)
        probe.load(QUrl("about:blank"))
        self._probe_page = probe   # keep the reference!

    def _make_main_tray(self):
        """The app's own icon, shown only while no URL is configured.

        With no page open there is no window to show, so the menu starts at
        Configure URLs…; a left click still runs toggle_last, which opens the
        configuration dialog for the first page."""
        self.main_tray = QSystemTrayIcon(self.base_icon)
        self.main_tray.setToolTip(APP_TITLE)
        menu = QMenu()
        menu.addAction("Configure URLs...", self.open_config)
        menu.addAction(f"About {APP_TITLE}", self.show_about)
        menu.addSeparator()
        self._autostart_action(menu)
        menu.addAction("Quit", self.app.quit)
        self.main_tray.activated.connect(
            lambda reason, m=menu: self._tray_activated(reason, m, self.toggle_last))
        self.main_tray._menu = menu      # popup style: keep the reference
        self.main_tray.show()
        self.tray_painter.register(self.main_tray)

    @staticmethod
    def _tray_activated(reason, menu, on_trigger):
        """Left click runs the action; right click opens the context menu
        below the panel (popup_menu: correct position on HiDPI, all Qt versions)."""
        act = QSystemTrayIcon.ActivationReason
        if reason == act.Trigger:
            on_trigger()
        elif reason == act.Context:
            popup_menu(menu)

    # ---------- URL list ----------

    def get_urls(self):
        """Configured URLs, in the configured order.
        No default: an empty configuration opens the configuration dialog."""
        return self.store.urls()

    def set_urls(self, urls):
        self.store.set_urls(urls)

    def open_config(self):
        old = self.get_urls()
        dlg = ConfigDialog(old, self.store)
        if dlg.exec():
            new = dlg.urls()
            # title, icon, geometry and zoom of removed URLs (and of the old
            # address of a rename) must go too — the dialog moves the window
            # data of a renamed URL to its new address
            self.store.drop_sites([url for url in old if url not in new])
            self.set_urls(new)
            self.rebuild_url_trays()
            self.refresh_window_title()

    # ---------- window control ----------

    @staticmethod
    def default_geometry(view):
        """Center the window, one third of the desktop width/height."""
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = screen.width() // 3, screen.height() // 3
        view.setGeometry(screen.x() + (screen.width() - w) // 2,
                         screen.y() + (screen.height() - h) // 2, w, h)

    def apply_geometry(self, url):
        """Use saved size/position: per URL first, then global, then centered."""
        if not settings_store.apply_geometry(self.view, self.store.geometry_for(url)):
            self.default_geometry(self.view)

    def apply_zoom(self, url):
        """Use saved zoom factor: per URL first, then global."""
        self.view.setZoomFactor(min(max(self.store.zoom_for(url), 0.25), 5.0))

    def open_url(self, url):
        self.view.current_url = url
        self.apply_geometry(url)
        self.apply_zoom(url)
        self.view.setWindowTitle(self.custom_title(url) or url)  # until the page's own title arrives
        self.view.load(QUrl(url))
        self.view.show()
        self.view.raise_()
        self.view.activateWindow()

    def toggle_url(self, url):
        if self.view.isVisible() and self.view.current_url == url:
            self.view.hide()
        else:
            self.open_url(url)

    def toggle_last(self):
        """Show/hide the window; with no page open, show the first configured
        page — and with an empty configuration, open the configuration dialog."""
        if self.view.isVisible():
            self.view.hide()
        elif self.view.current_url:
            self.open_url(self.view.current_url)
        else:
            urls = self.get_urls()
            if urls:
                self.open_url(urls[0])
            else:
                self.open_config()

    def save_all(self):
        """Save size/position and zoom at shutdown (globally and per URL)."""
        zoom = self.view.zoomFactor()
        self.store.save_window(self.view, zoom)
        self.store.save_site_window(self.view.current_url, self.view, zoom)
        self.tray_painter.close_hint()      # a hover note may be open

    # ---------- about ----------

    def show_about(self):
        about.show_about(self.store, self.engine_info)

    # ---------- autostart ----------

    def _autostart_action(self, menu):
        """Checkable "Start on login" entry; state refreshed when the menu opens."""
        act = menu.addAction("Start on login")
        act.setCheckable(True)
        act.setChecked(autostart_enabled())
        act.triggered.connect(lambda checked: self._set_autostart(checked))
        menu.aboutToShow.connect(lambda: act.setChecked(autostart_enabled()))
        return act

    def _set_autostart(self, enable):
        set_autostart(enable)
        self.store.set_autostart(enable)

    # ---------- one tray icon per URL ----------

    def make_url_tray(self, url):
        tray = QSystemTrayIcon(self.base_icon)
        tray.setToolTip(self.tray_tooltip(url))
        menu = QMenu()
        menu.addAction("Configure URLs...", self.open_config)
        menu.addAction(f"About {APP_TITLE}", self.show_about)
        menu.addSeparator()
        self._autostart_action(menu)
        menu.addAction("Quit", self.app.quit)

        tray.activated.connect(
            lambda reason, m=menu, u=url: self._tray_activated(
                reason, m, lambda: self.toggle_url(u)))
        tray._menu = menu                # popup style: keep the reference
        tray.show()
        self.tray_painter.register(tray)
        self.apply_icon_for(tray, url)   # custom icon file, else favicon
        return tray

    # ---------- custom per-URL icon and title ----------
    #
    # Set in the configuration dialog's URL editor (config.py), stored per URL.

    def custom_icon_path(self, url):
        """Path of the user's icon file for this URL ('' if unset/gone)."""
        return self.store.icon_path(url)

    def apply_tray_icon(self, tray, icon):
        if not icon.isNull():
            tray.setIcon(icon)
            self.tray_painter.set_icon(tray, icon)

    def apply_icon_for(self, tray, url):
        """Tray icon = the custom file if set, else the site's favicon."""
        path = self.custom_icon_path(url)
        if path:
            icon = QIcon(path)
            if not icon.isNull():
                self.apply_tray_icon(tray, icon)
                return
        favicons.fetch(url, self.nam, self.cache_dir,
                       lambda icon, tray=tray: self.apply_tray_icon(tray, icon))

    def custom_title(self, url):
        """User's display title for this URL ('' = the page's own title)."""
        return self.store.title(url)

    def tray_tooltip(self, url, page_title=""):
        """Tooltip of a URL tray: name and URL on one line, so hovering
        over the icon shows which page it opens. Name = the custom title,
        else the page's own title once it is known."""
        name = self.custom_title(url) or page_title
        return f"{name} — {url}" if name else url

    def combined_title(self, url, page_title):
        """Window title: the custom title first, the page's title appended."""
        custom = self.custom_title(url)
        if custom:
            return f"{custom} — {page_title}" if page_title else custom
        return page_title or url

    def refresh_window_title(self):
        """Window title after a configuration change: the current page's
        custom title (if any) in front of the page's own title."""
        url = self.view.current_url
        if url:
            self.view.setWindowTitle(self.combined_title(url, self.view.title()))

    def all_urls(self):
        """Configured URLs + drop-in URL files (configured wins on duplicates;
        the configuration dialog only ever lists the configured URLs)."""
        configured = self.get_urls()
        files = file_url_entries()
        self.file_urls = {u: p for u, p in files.items() if u not in configured}
        return configured + list(self.file_urls)

    def rebuild_url_trays(self):
        for tray in self.url_trays.values():
            tray.hide()
            tray.deleteLater()
        self.url_trays.clear()
        for url in self.all_urls():
            self.url_trays[url] = self.make_url_tray(url)
        self.sync_main_tray()

    def sync_main_tray(self):
        """Show the generic app icon only while no URL is configured.

        Showing it makes the panel embed a fresh X window, so the native-pixel
        overlay has to be re-applied — without that repaint the panel shows
        Qt's upscaled raster (the small icon)."""
        if self.url_trays:
            self.main_tray.hide()
        else:
            self.main_tray.show()
        self.tray_painter.schedule()

    # ---------- drop-in URL files (urls dir, inotify) ----------

    def _on_watch_change(self, _path):
        self._sync_timer.start()

    def _sync_file_urls(self):
        """Rescan the urls dir: add trays for new URLs, drop trays of
        removed files (their window closes too), refresh the watches."""
        os.makedirs(urls_dir(), exist_ok=True)
        urls = self.all_urls()
        for url in list(self.url_trays):
            if url not in urls:
                tray = self.url_trays.pop(url)
                tray.hide()
                tray.deleteLater()
                if self.view.current_url == url:
                    self.view.hide()
        for url in urls:
            if url not in self.url_trays:
                self.url_trays[url] = self.make_url_tray(url)
        self.sync_main_tray()
        self._register_watches()

    def _register_watches(self):
        d = urls_dir()
        if d not in self.watcher.directories():
            self.watcher.addPath(d)
        desired = set(self.file_urls.values())
        current = set(self.watcher.files())
        if current - desired:
            self.watcher.removePaths(sorted(current - desired))
        if desired - current:
            self.watcher.addPaths(sorted(desired - current))


def available_area(screen):
    """availableGeometry() of the screen in logical pixels on every Qt
    version. Qt before 6.12 reports the struts (the Cinnamon panel) in
    physical pixels on HiDPI (2x: 74 px -> 74 logical), so the area starts
    twice the panel height below the screen edge; the insets are scaled
    back here."""
    area = screen.availableGeometry()
    dpr = screen.devicePixelRatio()
    qt_version = tuple(int(v) for v in qVersion().split(".")[:2])
    if qt_version >= (6, 12) or dpr <= 1:
        return area
    # the reported area also reaches past the screen's far edge (6.10.2,
    # 2x: y 74 + height 1011 on a 1080 screen) — no negative insets
    full = screen.geometry()
    left = max(0, int((area.left() - full.left()) / dpr))
    top = max(0, int((area.top() - full.top()) / dpr))
    right = max(0, int((full.right() - area.right()) / dpr))
    bottom = max(0, int((full.bottom() - area.bottom()) / dpr))
    return full.adjusted(left, top, -right, -bottom)


def popup_menu(menu):
    """Show a tray context menu below the panel (at the icon's bottom edge),
    placed identically on every Qt version.

    Qt 6.10 reports the screen's top strut (Cinnamon panel) in physical
    pixels (2x: 74 px -> 74 logical) and clamps popup menus to it, so the
    menu lands at twice the panel height. popup() at the panel edge is
    clamped there, move() is not: pop up, then move to the same target —
    which is a no-op on correct Qt versions.
    """
    pos = QCursor.pos()
    strut = available_area(QApplication.primaryScreen()).y()   # panel edge
    target = QPoint(pos.x(), max(pos.y(), strut))
    menu.popup(target)
    menu.move(target)


class HoverHint(QFrame):
    """Hover note of an XEmbed tray icon: a frameless tooltip window with
    page name and URL next to the icon (the favicon is the tray icon
    itself, so the note does not repeat it). A plain window rather
    than a desktop notification — the notification server would list
    every hover in its history (notification applet, tray of the panel)."""

    MARGIN = 6      # logical px between icon and note

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFrameShape(QFrame.Shape.Box)
        # the desktop's tooltip colours, like the tooltip on SNI trays
        self.setPalette(QToolTip.palette())
        self.setAutoFillBackground(True)
        self.title = QLabel()
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.url = QLabel()
        for label in (self.title, self.url):
            label.setTextFormat(Qt.TextFormat.PlainText)
        text = QVBoxLayout(self)
        text.setContentsMargins(8, 6, 8, 6)
        text.setSpacing(2)
        text.addWidget(self.title)
        text.addWidget(self.url)

    def show_for(self, title, url, anchor):
        """Show the note beside `anchor` (the tray icon in logical
        coordinates): below it on a top panel, above it otherwise,
        clamped to the screen's available area (available_area: Qt 6.10
    reports the panel strut in physical pixels)."""
        self.title.setText(title)
        self.url.setText(url)
        self.adjustSize()
        screen = (QGuiApplication.screenAt(anchor.center())
                  or QGuiApplication.primaryScreen())
        area = available_area(screen)
        size = self.sizeHint()
        x = anchor.center().x() - size.width() // 2
        if anchor.center().y() < screen.geometry().center().y():
            y = anchor.bottom() + 1 + self.MARGIN
        else:
            y = anchor.top() - self.MARGIN - size.height()
        x = max(area.left(), min(x, area.right() + 1 - size.width()))
        y = max(area.top(), min(y, area.bottom() + 1 - size.height()))
        self.move(x, y)
        self.show()
        self.raise_()


class TrayPixelPainter(QAbstractNativeEventFilter):
    """Paint tray icon pixels 1:1 into the tray's X window (X11/HiDPI).

    On XEmbed panels (measured on Cinnamon 2x with Qt 6.10.2 and 6.12)
    the tray content Qt draws is a 37 px raster upscaled to the 74 px
    window, so the logo's thin strokes read as a pixelated fringe. The
    compositor (muffin) uses the window pixmap for the panel icon, so
    writing the native-resolution icon pixels directly into the window
    yields 1:1 edges: the window's own icon size (74 px on Cinnamon 2x,
    22 px elsewhere) is requested from the QIcon and blitted as
    premultiplied BGRA via Xlib put_image.

    Qt repaints the upscaled raster on every Expose, so the overlay is
    re-applied after each Expose of a tray window (native event filter),
    after every resize the panel makes, and after icon changes. Non-X11
    sessions and missing python-xlib are detected and disable the overlay
    silently.
    """

    def __init__(self, app, base_icon):
        super().__init__()
        self.app = app
        self.base_icon = base_icon
        self.icons = {}          # id(tray) -> QIcon (favicon overrides)
        self.trays = []          # QSystemTrayIcon instances to map by toolTip
        self._display = None
        self._wins = {}          # X window id -> (toolTip, w, h, depth, x, y)
        self._sys_widgets = {}   # X window id -> QSystemTrayIconSys widget
        self._pending = False
        self.enabled = True
        # hover tooltips: Cinnamon's legacy tray shows none for XEmbed icons,
        # so the forwarded XEMBED activate/deactivate messages drive a
        # hover note (HoverHint) with the URL instead
        self._xembed = None      # XEMBED atom id, -1 when it cannot be read
        self._hint = None        # HoverHint, created on the first hover
        self._hover = None       # (name, title, url, wid) until shown
        self._hover_wid = None   # window being hovered, None = none
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(700)
        self._hover_timer.timeout.connect(self._show_hover)
        # Cinnamon forwards neither XEMBED messages nor pointer crossings
        # to Qt, so the pointer position is polled against the icon
        # rectangles as the one path that every panel guarantees; the
        # short interval is what hides a hint right after leaving
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(150)
        self._poll_timer.timeout.connect(self._poll_hover)

    # ---------- public ----------

    def start(self):
        self.app.installNativeEventFilter(self)
        # paint as soon as the panel has embedded the tray windows, then catch
        # the slow embeds: an early pass is what keeps the icon from visibly
        # switching from Qt's upscaled raster to the 1:1 pixels
        for delay in (0, 300, 1500):
            QTimer.singleShot(delay, self._repaint)
        self._poll_timer.start()

    def register(self, tray):
        self.trays.append(tray)
        self.schedule()

    def set_icon(self, tray, icon):
        self.icons[id(tray)] = icon
        self.schedule()

    def schedule(self):
        if self.enabled and not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._run)

    # ---------- X11 plumbing ----------

    def _open_display(self):
        if self._display is None:
            from Xlib import display
            self._display = display.Display()
        return self._display

    def _find_windows(self):
        """Tray X windows of this process: Qt backs every XEmbed tray icon
        with a top-level QSystemTrayIconSys widget whose winId() is the
        embedded X window and whose toolTip() mirrors the tray's. The
        X window name is empty, so it cannot identify the tray."""
        d = self._open_display()
        found = {}
        widgets = {}
        for widget in self.app.topLevelWidgets():
            if widget.metaObject().className() != "QSystemTrayIconSys":
                continue
            wid = int(widget.winId())
            try:
                win = d.create_resource_object("window", wid)
                g = win.get_geometry()
            except Exception:
                continue
            if 8 <= g.width <= 256 and g.width == g.height:
                # the window's root origin for the hover polling: the
                # reply maps root's origin into window coordinates, so
                # the origin in root coordinates is its negative
                try:
                    r = win.translate_coords(d.screen().root, 0, 0)
                    x, y = -r.x, -r.y
                except Exception:
                    x, y = 0, 0
                found[wid] = (widget.toolTip(), g.width, g.height, g.depth,
                              x, y)
                widgets[wid] = widget
        self._wins = found
        self._sys_widgets = widgets
        return found

    def _live_trays(self):
        """Registered trays whose C++ object still exists (rebuilt URL
        trays are deleteLater()'d)."""
        self.trays = [t for t in self.trays if shiboken6.isValid(t)]
        return self.trays

    def _icon_for(self, name, taken):
        """Icon of the first not yet painted tray with this tooltip
        (two pages may share a title)."""
        for tray in self._live_trays():
            if id(tray) not in taken and tray.toolTip() == name:
                taken.add(id(tray))
                return self.icons.get(id(tray), self.base_icon)
        return self.base_icon

    def _run(self):
        self._pending = False
        self._repaint()

    def _repaint(self):
        if not self.enabled:
            return
        dbg = os.environ.get("WEBTRAY_DEBUG")
        try:
            from Xlib import X
            wins = self._find_windows()
            d = self._display
        except Exception:
            self.enabled = False     # no X11 (Wayland) / no python-xlib
            return
        if dbg:
            print("tray overlay: windows", {hex(k): v for k, v in wins.items()},
                  file=sys.stderr, flush=True)
        taken = set()
        for wid, (name, w, h, depth, _x, _y) in wins.items():
            try:
                # w x h are device pixels: dpr 1.0, else Qt 6 multiplies
                # by the app's dpr (148 px at 2x) and the size check skips
                pm = self._icon_for(name, taken).pixmap(QSize(w, h), 1.0)
                if dbg:
                    print(f"tray overlay: {hex(wid)} req {w}x{h} "
                          f"pm {pm.width()}x{pm.height()}@{pm.devicePixelRatio()} "
                          f"null {pm.isNull()}", file=sys.stderr, flush=True)
                if pm.isNull() or pm.width() != w:
                    continue
                img = pm.toImage().convertToFormat(
                    QImage.Format.Format_ARGB32_Premultiplied)
                data = bytes(img.constBits())
                bpl = img.bytesPerLine()
                if bpl != w * 4:
                    data = b"".join(data[i * bpl:i * bpl + w * 4]
                                    for i in range(h))
                # resource object of the high-level Display — a bare
                # drawable.Drawable(d, …) lacks allocate_resource_id, so
                # create_gc() raised and the overlay never painted
                win = d.create_resource_object("window", wid)
                win.put_image(win.create_gc(), 0, 0, w, h, X.ZPixmap,
                              depth, 0, data)
                if dbg:
                    print(f"tray overlay: painted {hex(wid)} {w}x{h} "
                          f"depth {depth} name {name!r}",
                          file=sys.stderr, flush=True)
            except Exception as e:
                if dbg:
                    print(f"tray overlay: {hex(wid)} failed: {e!r}",
                          file=sys.stderr, flush=True)
        try:
            d.flush()
        except Exception:
            self.enabled = False

    # ---------- Qt hooks ----------

    def nativeEventFilter(self, event_type, message):
        """Re-apply the overlay when the panel resizes a tray window
        (ConfigureNotify) or Qt repaints it (Expose).

        The panel first embeds the window at the panel's base size (44 px on
        Cinnamon 2x) and only a moment later grows it to the real icon size
        (74 px); that resize is a ConfigureNotify. Without a repaint at the
        new size the panel scales the old pixels, i.e. the icon stays in the
        small resolution.

        X protocol events are 32 bytes; the code is the first byte and the
        window id sits at bytes 4..8. `message` is a void pointer — PySide6
        hands it over as shiboken's VoidPtr, whose int() is the address.
        """
        if self.enabled and b"xcb" in bytes(event_type):
            try:
                import ctypes
                addr = int(message)
                if not addr:
                    return (False, 0)
                b = bytes((ctypes.c_ubyte * 16).from_address(addr))
                code = b[0] & 0x7F
                if code in (12, 22):            # 12 = Expose, 22 = ConfigureNotify
                    if int.from_bytes(b[4:8], "little") in self._wins:
                        self.schedule()
                elif code in (9, 10):           # 9 = EnterNotify, 10 = LeaveNotify
                    # Cinnamon's tray actor forwards the real pointer
                    # enter/leave of the icon to the embedded window; Qt
                    # ignores the crossings, the window id is at 12..16
                    wid = int.from_bytes(b[12:16], "little")
                    if wid in self._wins:
                        if code == 9:
                            self._arm_hover(self._wins[wid][0], wid)
                        else:
                            self._cancel_hover()
                elif code == 33:                # ClientMessage (XEMBED hover)
                    self._xembed_message(
                        bytes((ctypes.c_ubyte * 32).from_address(addr)))
            except Exception:
                pass
        return (False, 0)

    # ---------- hover tooltips ----------

    def _xembed_atom(self):
        """Id of the _XEMBED atom (the XEmbed protocol messages carry it)."""
        if self._xembed is None:
            try:
                self._xembed = int(self._open_display().intern_atom("_XEMBED", False))
            except Exception:
                self._xembed = -1
        return self._xembed

    def _xembed_message(self, b):
        """Panels implementing XEMBED's "notify on click" (GNOME family)
        send WINDOW_ACTIVATE = 2 / WINDOW_DEACTIVATE = 1 messages;
        Cinnamon forwards pointer crossings instead (nativeEventFilter).
        Qt ignores both and Cinnamon shows no tooltip for XEmbed icons,
        so a short delay after enter ends in a hover note with the name
        and the URL of the page; leaving cancels it.

        xcb_client_message_event_t: format at byte 1, window 4..8, type
        atom 8..12, data32[1] (the XEMBED opcode) 16..20."""
        atom = self._xembed_atom()
        if atom < 0 or b[1] != 32:
            return
        if int.from_bytes(b[8:12], "little") != atom:
            return
        wid = int.from_bytes(b[4:8], "little")
        entry = self._wins.get(wid)
        if entry is None:
            return
        opcode = int.from_bytes(b[16:20], "little")
        if opcode == 2:
            self._arm_hover(entry[0], wid)
        elif opcode == 1:
            self._cancel_hover()

    def _current_tooltip(self, wid, cached):
        """Tooltip of the tray window as of now: the cached one in _wins
        dates from the last repaint, and the page title arriving later
        changes it (on_title) without a repaint, so the note would show
        the bare URL instead of the page name."""
        widget = self._sys_widgets.get(wid)
        if widget is not None and shiboken6.isValid(widget):
            return widget.toolTip()
        return cached

    def _arm_hover(self, name, wid):
        """Arm the hover note of the hovered icon; the app's own icon
        has no URL, so an armed note is cancelled."""
        name = self._current_tooltip(wid, name)
        if name == APP_TITLE:
            self._cancel_hover()
            return
        title, _, url = name.rpartition(" — ")
        self._hover = (name, title or APP_TITLE, url or name, wid)
        self._hover_timer.start()

    def _poll_hover(self):
        """Pointer position poll. Cinnamon forwards neither XEMBED
        activate messages nor pointer crossings of the embedded icon to
        Qt (measured on this desktop), so the pointer's root position is
        checked against the icon rectangles: entering one arms the
        hover note, leaving cancels it. The rectangles are cached by
        _find_windows and refreshed with every repaint, so a poll is a
        single round trip — fast enough to vanish right after leaving."""
        if not self.enabled or not self._wins:
            return
        try:
            d = self._open_display()
            pos = d.screen().root.query_pointer()
            hit = None
            for wid, entry in self._wins.items():
                w, h, x0, y0 = entry[1], entry[2], entry[4], entry[5]
                if x0 <= pos.root_x < x0 + w and y0 <= pos.root_y < y0 + h:
                    hit = wid
                    break
        except Exception:
            self._poll_timer.stop()
            return
        if hit == self._hover_wid:
            return
        self._hover_wid = hit
        if hit is None:
            self._cancel_hover()
        else:
            self._arm_hover(self._wins[hit][0], hit)

    def _cancel_hover(self):
        self._hover = None
        self._hover_timer.stop()
        self.close_hint()

    def close_hint(self):
        """Hide the hover note: the pointer left the icon or the app is
        about to quit."""
        if self._hint is not None and self._hint.isVisible():
            self._hint.hide()
            if os.environ.get("WEBTRAY_DEBUG"):
                print(f"tray hover {time.monotonic():.3f}: hide",
                      file=sys.stderr, flush=True)

    def _show_hover(self):
        """Show page name and URL of the hovered tray icon. The
        XEmbed ShowMessage protocol needs support of the panel and Qt's
        D-Bus tray is not compiled into this PySide6, so the note is an
        own tooltip window (HoverHint) — no desktop notification, which
        the notification server would also keep in its history. It stays
        while the pointer is on the icon; leaving hides it (close_hint)."""
        if not self._hover:
            return
        name, title, url, wid = self._hover
        self._hover = None
        current = self._current_tooltip(wid, name)
        if current != name:          # title arrived while the note was armed
            name = current
            title, _, url = name.rpartition(" — ")
            title, url = title or APP_TITLE, url or name
        if self._hint is None:
            self._hint = HoverHint()
        self._hint.show_for(title, url, self._anchor(wid))
        if os.environ.get("WEBTRAY_DEBUG"):
            print(f"tray hover {time.monotonic():.3f}: show "
                  f"{title!r} {url!r}", file=sys.stderr, flush=True)

    def _anchor(self, wid):
        """Rectangle of the tray icon in Qt's logical coordinates: the
        cached X geometry is in device pixels. Without one (window gone)
        a small square at the pointer stands in."""
        entry = self._wins.get(wid)
        if entry is None:
            pos = QCursor.pos()
            return QRect(pos.x() - 8, pos.y() - 8, 16, 16)
        _name, w, h, _depth, x, y = entry
        screen = (QGuiApplication.screenAt(QCursor.pos())
                  or QGuiApplication.primaryScreen())
        dpr = screen.devicePixelRatio() or 1.0
        return QRect(round(x / dpr), round(y / dpr),
                     max(1, round(w / dpr)), max(1, round(h / dpr)))

LOCAL_SOCKET_NAME = f"webtray-{os.getuid()}"


def system_font():
    """UI font from the desktop's interface settings (gsettings: Cinnamon,
    GNOME) incl. text scaling — Qt's generic X11 default font does not
    follow these, which makes menus/dialogs look off the system style."""
    for schema in ("org.cinnamon.desktop.interface", "org.gnome.desktop.interface"):
        try:
            raw = subprocess.run(
                ["gsettings", "get", schema, "font-name"],
                capture_output=True, text=True, timeout=5).stdout
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        name = raw.strip().strip("'").strip()
        if not name:
            continue
        # "Sans 11" style: trailing number is points (<= 20) or pixels (> 20),
        # per the GNOME font-name convention (Qt6 fromString no longer parses it)
        m = re.fullmatch(r"(.+?)\s+(\d+(?:[.,]\d+)?)", name)
        font = QFont(m.group(1) if m else name)
        if m:
            size = float(m.group(2).replace(",", "."))
            if size > 20:
                font.setPixelSize(int(size))
            else:
                font.setPointSizeF(size)
        try:
            raw = subprocess.run(
                ["gsettings", "get", schema, "text-scaling-factor"],
                capture_output=True, text=True, timeout=5).stdout
            scale = float(raw.strip().strip("'"))
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired, ValueError):
            scale = 1.0
        if font.pointSizeF() > 0 and scale != 1.0:
            font.setPointSizeF(font.pointSizeF() * scale)
        return font
    return None


def install_signal_handlers(app):
    """Ctrl+C (SIGINT) and SIGTERM end the app cleanly, geometry and zoom
    saved by the aboutToQuit handler.

    Python's default SIGINT raises KeyboardInterrupt in whatever Python
    code runs when the signal arrives — inside the tray painter's
    nativeEventFilter that prints a traceback and the event loop keeps
    running. Here the handler only writes one byte to a self-pipe; the
    QSocketNotifier wakes the Qt loop and quits it. Windows has its own
    console signal handling — left at the Python default."""
    if sys.platform == "win32":
        return
    import signal
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)

    def wake(*_args):
        try:
            os.write(write_fd, b"x")
        except OSError:
            pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, wake)
    # The Python handler runs only when the interpreter executes its next
    # bytecode — an idle Qt loop runs in C and may never get there. The C
    # trampoline of set_wakeup_fd writes to the pipe straight from the
    # signal, so the QSocketNotifier wakes the Qt loop immediately.
    signal.set_wakeup_fd(write_fd)
    notifier = QSocketNotifier(read_fd, QSocketNotifier.Type.Read)
    notifier.activated.connect(app.quit)
    app._signal_watch = (notifier, read_fd, write_fd)     # keep alive


def quiet_web_engine():
    """Keep the browser engine's own log lines off the console: Chromium
    prints its errors and warnings ("[pid:tid:…:ERROR:file.cc(n)] …")
    straight to stderr, Qt WebEngine adds its qt.webengine* categories.
    Both are read once at startup, so this runs before QApplication.
    WEBTRAY_DEBUG keeps everything, and values the user exported win."""
    if os.environ.get("WEBTRAY_DEBUG"):
        return
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--log-level" not in flags:
        # 3 = FATAL: only the messages that end the process remain
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --log-level=3").strip()
    os.environ.setdefault("QT_LOGGING_RULES", "qt.webengine*=false")


def main():
    quiet_web_engine()
    app = QApplication(sys.argv)

    # Single instance first: a second start (postinst + autostart + manual)
    # asks the running instance to show its window and exits — before this
    # process registers anything with the session.
    probe = QLocalSocket()
    probe.connectToServer(LOCAL_SOCKET_NAME)
    if probe.waitForConnected(200):
        probe.write(b"activate")
        probe.waitForBytesWritten(200)
        probe.disconnectFromServer()
        return 0

    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    if app.platformName().startswith("wayland"):
        # Wayland: the desktop file name is the app ID, used by the portal and
        # for the panel icon; on X11 the platform plugin registers the ID
        # itself, and a second registration fails as "already associated"
        app.setDesktopFileName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)    # the app keeps living in the tray

    font = system_font()
    if font is not None:
        app.setFont(font)

    server = QLocalServer(app)
    server.removeServer(LOCAL_SOCKET_NAME)  # drop stale socket of a crash
    tray = {}                                # late-bound: created below
    if server.listen(LOCAL_SOCKET_NAME):
        def on_connection():
            # PySide6 has no QLocalServer.nextConnection() (Qt 6.3 C++ API);
            # drain the pending sockets (hasPendingConnections/nextPendingConnection).
            while server.hasPendingConnections():
                conn = server.nextPendingConnection()
                if conn is not None:
                    conn.readAll()
                    conn.disconnectFromServer()
            t = tray.get("tray")
            if t is not None:
                t.toggle_last()
        server.newConnection.connect(on_connection)

    tray["tray"] = WebTray(app)
    install_signal_handlers(app)
    return app.exec()

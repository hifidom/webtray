# SPDX-License-Identifier: Apache-2.0
"""Settings of WebTray, stored as one readable JSON file.

    ~/.config/webtray/webtray.json

    {
      "version": 2,
      "autostart": true,
      "window": {"x": 955, "y": 172, "width": 1594, "height": 508,
                 "maximized": false, "zoom": 1.0},
      "sites": [
        {
          "url": "https://example.org",
          "title": "Example", "icon": "/home/me/icon.png",
          "x": 100, "y": 100, "width": 1200, "height": 800,
          "maximized": false, "zoom": 1.1
        },
        {"url": "https://just-configured.example"}
      ]
    }

One entry per configured URL, in the configured order — the URL is part of
the entry, so the data is never stored twice. Window positions are plain
rectangles, so the file can be read and edited in any editor. Everything an
entry does not need is left out: no title key means "follow the page title",
no geometry key means "use the global window", and an entry reduced to its
URL is just a configured page without its own data.

Writes are atomic — a temp file in the same directory, fsync, os.replace —
so a crash while saving leaves the previous file intact. A file that
cannot be parsed is kept as "<name>.corrupt" and the app starts with an
empty configuration instead of failing.

Earlier versions used other files: version 1 of this format had a separate
"urls" list and "sites" as a dictionary, and before that the data lived in
"webtray.conf" (QSettings INI) with the window positions as
"@ByteArray(...)" blobs. _normalize() converts a version 1 file on load,
_migrate_ini() reads the INI once, converts the blobs into rectangles
(QWidget.restoreGeometry is the only supported reader of that format),
writes the JSON file and deletes the INI.
"""

import json
import os

from PySide6.QtCore import QSettings, QStandardPaths

from . import APP_NAME

FILE_NAME = "webtray.json"
INI_NAME = "webtray.conf"       # the file written before JSON was used
VERSION = 2

# keys of the old INI format, for the migration only
INI_TITLE_KEY = "title:"
INI_ICON_KEY = "icon:"
INI_GEO_KEY = "geo/"
INI_ZOOM_KEY = "zoom/"

GEOMETRY_KEYS = ("x", "y", "width", "height")
SITE_DATA_KEYS = (*GEOMETRY_KEYS, "maximized", "zoom", "title", "icon")


def config_dir():
    """~/.config/webtray — the directory of the settings and the urls dir."""
    cfg = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.ConfigLocation)
    return os.path.join(cfg, APP_NAME)


def settings_path():
    """Path of the JSON settings file."""
    return os.path.join(config_dir(), FILE_NAME)


def valid_geometry(geo):
    """True when geo is a complete, plausible rectangle."""
    if not isinstance(geo, dict):
        return False
    values = []
    for key in GEOMETRY_KEYS:
        value = geo.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        values.append(int(value))
    return values[2] > 0 and values[3] > 0


def zoom_value(value):
    """Zoom factor as a float, None when the stored value is unusable."""
    try:
        zoom = float(value)
    except (TypeError, ValueError):
        return None
    return zoom if 0.0 < zoom < 100.0 else None


def geometry_of(widget):
    """The widget's size and position as a readable dict.

    A maximized window keeps the rectangle of the restored window
    (normalGeometry), so un-maximizing lands where the user had it."""
    maximized = bool(widget.isMaximized())
    rect = widget.normalGeometry() if maximized and hasattr(widget, "normalGeometry") \
        else widget.geometry()
    return {"x": rect.x(), "y": rect.y(),
            "width": max(int(rect.width()), 1), "height": max(int(rect.height()), 1),
            "maximized": maximized}


def apply_geometry(widget, geo):
    """Move and size the widget from a stored rectangle. Returns False for
    a missing or unusable rectangle, so the caller can center the window."""
    if not valid_geometry(geo):
        return False
    widget.setGeometry(int(geo["x"]), int(geo["y"]), int(geo["width"]), int(geo["height"]))
    if geo.get("maximized"):
        widget.showMaximized()
    return True


def _rect_from_blob(blob):
    """Old saveGeometry() bytes as a readable rectangle.

    The QDataStream blob is opaque, so a hidden widget applies it through
    QWidget.restoreGeometry and its geometry is read back — the only
    supported reader of that format."""
    if blob is None or not blob:
        return None
    try:
        from PySide6.QtWidgets import QApplication, QWidget
        if QApplication.instance() is None:      # restoreGeometry needs a widget
            return None
        probe = QWidget()
        try:
            if not probe.restoreGeometry(blob):
                return None
            return geometry_of(probe)
        finally:
            probe.deleteLater()
    except Exception:
        return None


def _split_urls(raw):
    """URLs from a list or from the old single-key string (one per line,
    comma separated works too); blanks dropped, each URL once, in order."""
    if isinstance(raw, str):
        parts = raw.splitlines() if "\n" in raw else raw.split(",")
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        return []
    urls = []
    for part in parts:
        url = str(part).strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _empty():
    """The data of a fresh, unconfigured store."""
    return {"version": VERSION, "sites": []}


class Store:
    """The settings file, read once at startup and saved on every change."""

    def __init__(self, path=None):
        self.path = path or settings_path()
        self.corrupt = None       # set when an unparseable file was moved aside
        self.data = _empty()
        self._open()

    # ---------- loading and saving ----------

    def _open(self):
        if os.path.isfile(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as exc:
                self._keep_corrupt(exc)
            else:
                self.data = self._normalize(data)
                return
        if self._migrate_ini():
            return
        self.data = _empty()

    def _normalize(self, data):
        """Accept an object, ignore everything unusable — hand editing is
        encouraged, so a stray key must not break the app. The "sites"
        array of this version and the "urls" + "sites" pair of version 1
        both become the array of entries."""
        out = _empty()
        if not isinstance(data, dict):
            return out
        if isinstance(data.get("autostart"), bool):
            out["autostart"] = data["autostart"]
        window = data.get("window")
        if isinstance(window, dict):
            clean = self._clean_fields(window)
            if clean:
                out["window"] = clean

        seen = set()
        sites = data.get("sites")
        if isinstance(sites, list):                   # this version
            for raw in sites:
                self._add_site(out, seen, raw)
        elif isinstance(sites, dict):                 # version 1
            # the configured order came from the old urls list; data of
            # URLs not in it keeps the entries that follow
            for url in _split_urls(data.get("urls")):
                raw = sites.get(url)
                self._add_site(out, seen,
                               {"url": url, **(raw if isinstance(raw, dict) else {})})
            for url, raw in sites.items():
                self._add_site(out, seen, {"url": url, **(raw if isinstance(raw, dict) else {})})
        return out

    def _add_site(self, out, seen, raw):
        """One site entry of a loaded file, usable fields only; a URL
        without its own data becomes a bare {"url": ...} entry."""
        if not isinstance(raw, dict):
            return
        url = raw.get("url")
        if not isinstance(url, str) or not url.strip():
            return
        url = url.strip()
        if url in seen:
            return                                    # duplicates: first wins
        seen.add(url)
        out["sites"].append({"url": url, **self._clean_fields(raw)})

    @staticmethod
    def _clean_fields(entry):
        """The data fields of one site (or of "window"), unusable ones
        dropped — the url key is not part of this."""
        out = {}
        for key in GEOMETRY_KEYS:
            value = entry.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = int(value)
        if valid_geometry(out):
            out["maximized"] = bool(entry.get("maximized", False))
        else:
            for key in GEOMETRY_KEYS:
                out.pop(key, None)
        for key in ("title", "icon"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                out[key] = value.strip()
        zoom = zoom_value(entry.get("zoom"))
        if zoom is not None:
            out["zoom"] = zoom
        return out

    def _keep_corrupt(self, exc):
        """Move an unparseable file aside, so the settings start empty and
        nothing is lost; the path is shown in the About dialog."""
        broken = self.path + ".corrupt"
        try:
            os.replace(self.path, broken)
        except OSError:
            pass
        self.data = _empty()
        self.corrupt = str(exc)

    def save(self):
        """Write the file atomically: temp file, fsync, replace."""
        self.data["version"] = VERSION
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # ---------- the old QSettings file ----------

    def _migrate_ini(self):
        """Convert webtray.conf of the same directory, once, then delete it.

        Only the URLs in the old "urls" key are carried over with their
        per-URL data: QSettings mangles "//" in the key names
        ("title:https://x" is stored as "title:https:/x"), so the URL list
        is the anchor. Data of URLs that were removed earlier is dead code
        in the old file and is dropped."""
        ini = os.path.join(os.path.dirname(self.path) or ".", INI_NAME)
        if not os.path.isfile(ini):
            return False
        # the two-argument form reads that exact file; the (format, scope,
        # name) form would turn the path into an organisation/application name
        settings = QSettings(ini, QSettings.Format.IniFormat)

        stored = settings.value("autostart")
        if isinstance(stored, bool):
            self.data["autostart"] = stored
        elif isinstance(stored, str) and stored:
            self.data["autostart"] = stored.strip().lower() in ("true", "1")

        window = self._clean_fields({
            **(_rect_from_blob(settings.value("geometry")) or {}),
            "zoom": settings.value("zoom"),
        })
        if window:
            self.data["window"] = window

        self.data["sites"] = []
        for url in _split_urls(settings.value("urls", "")):
            fields = self._clean_fields({
                **(_rect_from_blob(settings.value(INI_GEO_KEY + url)) or {}),
                "zoom": settings.value(INI_ZOOM_KEY + url),
                "title": settings.value(INI_TITLE_KEY + url, ""),
                "icon": settings.value(INI_ICON_KEY + url, ""),
            })
            self.data["sites"].append({"url": url, **fields})

        self.save()
        try:
            os.remove(ini)
        except OSError:
            pass
        return True

    # ---------- values ----------

    def _sites(self):
        """The site entries, in the configured order (the live list)."""
        sites = self.data.get("sites")
        if not isinstance(sites, list):
            sites = self.data["sites"] = []
        return sites

    def _index(self, url):
        """Position of a URL's entry, None when it has none."""
        for i, entry in enumerate(self._sites()):
            if entry.get("url") == url:
                return i
        return None

    def urls(self):
        """Configured URLs, in the configured order (from the site list)."""
        return [entry["url"] for entry in self._sites() if entry.get("url")]

    def sites(self):
        """The site entries — each one carries its url — in order."""
        return self._sites()

    def site(self, url):
        """Stored entry of one URL ({} when there is nothing)."""
        i = self._index(url)
        return self._sites()[i] if i is not None else {}

    def title(self, url):
        """Custom title of a URL ('' = follow the page's own title)."""
        value = self.site(url).get("title", "")
        return value.strip() if isinstance(value, str) else ""

    def icon_path(self, url):
        """Custom icon file of a URL ('' when unset or gone)."""
        value = self.site(url).get("icon", "")
        path = value.strip() if isinstance(value, str) else ""
        return path if path and os.path.isfile(path) else ""

    def window(self):
        """Global window entry ({} when nothing was stored)."""
        entry = self.data.get("window")
        return entry if isinstance(entry, dict) else {}

    def geometry_for(self, url=None):
        """Stored rectangle: the URL's own first, then the global one."""
        for entry in (self.site(url) if url else {}, self.window()):
            if valid_geometry(entry):
                return entry
        return None

    def zoom_for(self, url=None):
        """Stored zoom factor: the URL's own first, then the global one."""
        for entry in (self.site(url) if url else {}, self.window()):
            zoom = zoom_value(entry.get("zoom"))
            if zoom is not None:
                return zoom
        return 1.0

    def autostart(self):
        """Start on login as stored, None when never set (the default)."""
        value = self.data.get("autostart")
        return value if isinstance(value, bool) else None

    # ---------- writers (each one saves the file) ----------

    def set_urls(self, urls):
        """The configured list: added URLs get an entry at the end, kept
        ones keep their data, removed ones and their data go away."""
        old = {}
        for entry in self._sites():
            url = entry.get("url")
            if isinstance(url, str):
                old.setdefault(url, entry)
        self.data["sites"] = [old[url] if url in old else {"url": url}
                              for url in _split_urls(list(urls))]
        self.save()

    def set_autostart(self, enable):
        self.data["autostart"] = bool(enable)
        self.save()

    def set_title(self, url, title):
        """'' removes the custom title (the page's own title is used)."""
        self._set_field(url, "title", (title or "").strip())

    def set_icon(self, url, path):
        """'' removes the custom icon (the site's favicon is used)."""
        self._set_field(url, "icon", (path or "").strip())

    def save_window(self, widget, zoom):
        """Store the size, position and zoom of the shared window."""
        self._update_window({**geometry_of(widget), "zoom": zoom})

    def save_site_window(self, url, widget, zoom):
        """Store the size, position and zoom for one URL."""
        if url:
            self._update_site(url, {**geometry_of(widget), "zoom": zoom})

    def move_site(self, old, new):
        """Give a renamed URL the stored window data of the old address
        (title and icon are set by the URL editor for the new address).
        The new address takes the position of the old entry in the list."""
        if not old or not new or old == new:
            return
        sites = self._sites()
        i = self._index(old)
        if i is None:
            return
        entry = sites[i]
        j = self._index(new)
        if j is None:
            sites[i] = {"url": new,
                        **{k: v for k, v in entry.items() if k in SITE_DATA_KEYS}}
        else:
            target = sites[j]
            for key, value in entry.items():
                # the URL editor already wrote title and icon for the new
                # address — only the window data the new address lacks moves
                if key in SITE_DATA_KEYS and key not in target:
                    target[key] = value
            del sites[i]
        self.save()

    def drop_sites(self, urls):
        """Remove the entries of URLs that were deleted."""
        drop = set(urls)
        sites = self._sites()
        kept = [entry for entry in sites if entry.get("url") not in drop]
        if len(kept) != len(sites):
            self.data["sites"] = kept
            self.save()

    # ---------- entry helpers ----------

    def _ensure_site(self, url):
        """The entry of a URL, created at the end when it has none."""
        i = self._index(url)
        sites = self._sites()
        if i is None:
            sites.append({"url": url})
            i = len(sites) - 1
        return sites[i]

    def _set_field(self, url, key, value):
        """Set or clear one field; clearing an unconfigured URL's field does
        not create an entry, clearing a configured one leaves the bare
        {"url": ...} entry — the URL stays configured."""
        if not url:
            return
        if value:
            self._ensure_site(url)[key] = value
        else:
            i = self._index(url)
            if i is not None:
                self._sites()[i].pop(key, None)
        self.save()

    def _update_window(self, fields):
        entry = dict(self.data.get("window") or {})
        entry.update({k: v for k, v in fields.items() if v is not None})
        clean = self._clean_fields(entry)
        if clean:
            self.data["window"] = clean
        self.save()

    def _update_site(self, url, fields):
        if not url:
            return
        entry = self._ensure_site(url)
        clean = self._clean_fields({**entry,
                                    **{k: v for k, v in fields.items() if v is not None}})
        entry.clear()
        entry["url"] = url
        entry.update(clean)
        self.save()


__all__ = ["Store", "FILE_NAME", "INI_NAME", "VERSION",
           "config_dir", "settings_path", "geometry_of", "apply_geometry",
           "valid_geometry", "zoom_value"]

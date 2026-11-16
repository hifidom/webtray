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

"""Favicon fetching and caching — one set of cached icons per host.

Sources, all cached per host in the favicon cache directory:

- ``<host>.ico``       /favicon.ico as served (every embedded size)
- ``<host>.site.png``  /favicon.ico when the server sends another format
- ``<host>.svg``       an SVG icon the page declares (<link rel="icon">)
- ``<host>.best.png``  the largest raster icon the page declares
                       (<link rel="icon" sizes>, apple-touch-icon,
                       web app manifest)
- ``<host>.png``       Google's favicon service at 256 px (fallback for
                       pages that declare nothing; its 404 placeholder
                       globe is discarded)

icon_from_files() merges them into one QIcon with an exact pixmap for
every common tray size: raster images at their native sizes, the SVG
rendered for every size no raster supplies 1:1, so HiDPI panels (74 px
on Cinnamon 2x) get sharp edges instead of an upscaled 32 px ICO.
"""

import json
import os
from html.parser import HTMLParser

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QUrl
from PySide6.QtGui import QIcon, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest

# sizes the SVG is rendered at (logical tray sizes at 1x/1.5x/2x and the
# sizes menus, the hover note and the window list ask for)
RENDER_SIZES = (16, 20, 22, 24, 28, 32, 36, 40, 44, 48, 56, 64, 74, 96, 128, 192, 256)
# a declared rel="icon" raster at least this large beats touch/manifest
# icons (those are often padded squares on an opaque background)
GOOD_ICON = 64
MAX_HTML = 1 << 20          # scan at most the first MiB of the page
MAX_ICON = 4 << 20          # ignore icon files larger than this


# ---------- building the QIcon from the cache ----------

def _square(img):
    """Pad a non-square image to a transparent square (QIcon keeps the
    aspect ratio, so a non-square pixmap would miss the requested width)."""
    w, h = img.width(), img.height()
    if w == h:
        return img
    side = max(w, h)
    out = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage((side - w) // 2, (side - h) // 2, img)
    p.end()
    return out


def _raster_images(path):
    """All frames of an image file (ICO files embed several sizes)."""
    reader = QImageReader(path)
    images = []
    for _ in range(max(1, reader.imageCount())):
        img = reader.read()
        if img.isNull():
            break
        images.append(_square(img))
        if not reader.jumpToNextImage():
            break
    return images


def _render_svg(path, side):
    reader = QImageReader(path)
    src = reader.size()
    if src.isValid() and src.width() > 0 and src.height() > 0:
        src.scale(QSize(side, side), Qt.AspectRatioMode.KeepAspectRatio)
    else:
        src = QSize(side, side)
    reader.setScaledSize(src)
    img = reader.read()
    return QImage() if img.isNull() else _square(img)


def icon_from_files(cache_dir, host):
    """Build a QIcon from every cached format of the host.

    Per pixel size the first source wins: the hand-made small sizes of
    the original ICO, then the page's own rasters, then Google's. The
    SVG fills every common size no raster has exactly.
    """
    by_size = {}
    for name in (host + ".ico", host + ".site.png", host + ".best.png", host + ".png"):
        path = os.path.join(cache_dir, name)
        if os.path.isfile(path):
            for img in _raster_images(path):
                by_size.setdefault(img.width(), img)
    svg = os.path.join(cache_dir, host + ".svg")
    if os.path.isfile(svg):
        for side in RENDER_SIZES:
            if side not in by_size:
                img = _render_svg(svg, side)
                if not img.isNull() and img.width() == side:
                    by_size[side] = img
    icon = QIcon()
    for side in sorted(by_size):
        icon.addPixmap(QPixmap.fromImage(by_size[side]))
    return icon


# ---------- finding the icons a page declares ----------

class _IconLinks(HTMLParser):
    """Collect <link rel=icon|apple-touch-icon|manifest> and <base href>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []     # (rels, href, sizes, type)
        self.base = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "base" and a.get("href") and self.base is None:
            self.base = a["href"]
        elif tag == "link" and a.get("href"):
            rels = set(a.get("rel", "").lower().split())
            if rels & {"icon", "apple-touch-icon", "apple-touch-icon-precomposed", "manifest"}:
                self.links.append((rels, a["href"].strip(), a.get("sizes", ""),
                                   a.get("type", "").lower()))

    handle_startendtag = handle_starttag


def _largest(sizes):
    """Largest edge in a sizes attribute ("16x16 32x32", "any") — 0 if unknown."""
    best = 0
    for token in (sizes or "").lower().split():
        if token == "any":
            return 4096
        w, _, h = token.partition("x")
        if w.isdigit() and h.isdigit():
            best = max(best, min(int(w), int(h)))
    return best


def _is_svg(href, mime):
    return "svg" in mime or QUrl(href).path().lower().endswith((".svg", ".svgz")) \
        or href.lower().startswith("data:image/svg")


class _Candidates:
    """Icon URLs of a page, sorted into SVG / rel=icon rasters / others."""

    def __init__(self):
        self.svg = []
        self.icons = []      # (size, url) from rel="icon"
        self.others = []     # (size, url) from apple-touch-icon and the manifest

    def add(self, url, sizes, mime, is_icon):
        if not url.isValid() or url.scheme() not in ("http", "https", "data"):
            return
        if _is_svg(url.toString(), mime):
            if is_icon:
                self.svg.append(url)
            return
        (self.icons if is_icon else self.others).append((_largest(sizes), url))

    def rasters(self):
        """Raster URLs, best first: large rel=icon, then touch/manifest
        icons, then the remaining rel=icon (duplicates dropped)."""
        icons = sorted(self.icons, key=lambda c: -c[0])
        others = sorted(self.others, key=lambda c: -c[0])
        good = [c for c in icons if c[0] >= GOOD_ICON]
        rest = [c for c in icons if c[0] < GOOD_ICON]
        seen, out = set(), []
        for _, url in good + others + rest:
            key = url.toString()
            if key not in seen:
                seen.add(key)
                out.append(url)
        return out


# ---------- network ----------

def _get(nam, url, done, limit=MAX_ICON):
    """GET url; done(data, final_url) — data is None on errors/HTTP >= 400."""
    req = QNetworkRequest(QUrl(url))
    req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                     QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
    req.setMaximumRedirectsAllowed(7)
    req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0")
    reply = nam.get(req)

    def on_finished():
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        ok = reply.error() == QNetworkReply.NetworkError.NoError \
            and not (isinstance(status, int) and status >= 400)
        data = bytes(reply.read(limit).data()) if ok else b""
        final = reply.url()
        reply.deleteLater()
        done(data or None, final)

    reply.finished.connect(on_finished)


def _image_format(data):
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    return bytes(QImageReader(buf).format()).decode().lower()


def fetch(url_str, nam, cache_dir, on_ready):
    """Fetch every icon source of the page's host (see module docstring).

    Calls on_ready(icon) right away with what the cache holds and again
    whenever new material arrives, so the tray icon sharpens as soon as
    better formats are found.
    """
    host = QUrl(url_str).host()
    if not host:
        return

    def path(suffix):
        return os.path.join(cache_dir, host + suffix)

    def deliver():
        icon = icon_from_files(cache_dir, host)
        if not icon.isNull():
            on_ready(icon)

    def store(suffix, data):
        os.makedirs(cache_dir, exist_ok=True)
        with open(path(suffix), "wb") as f:
            f.write(data)
        deliver()

    deliver()   # use everything the cache already offers, right away

    # /favicon.ico — the original ICO keeps all embedded sizes
    def on_ico(data, _final):
        if not data:
            return
        fmt = _image_format(data)
        if fmt == "ico":
            store(".ico", data)
        elif fmt:
            pix = QPixmap()
            if pix.loadFromData(data) and not pix.isNull():
                os.makedirs(cache_dir, exist_ok=True)
                pix.save(path(".site.png"))
                deliver()

    _get(nam, url_str.rstrip("/") + "/favicon.ico", on_ico)

    # Google's service: 404 + a 16 px globe for hosts it cannot reach
    # (intranet names) — that placeholder must not shadow the real icons
    def on_google(data, _final):
        if not data:
            if os.path.isfile(path(".png")):
                os.remove(path(".png"))
                deliver()
            return
        pix = QPixmap()
        if pix.loadFromData(data) and not pix.isNull() and pix.width() > 16:
            os.makedirs(cache_dir, exist_ok=True)
            pix.save(path(".png"))
            deliver()

    _get(nam, "https://www.google.com/s2/favicons?domain=" + host + "&sz=256", on_google)

    # the icons the page itself declares
    cands = _Candidates()
    pending = {"manifest": False}

    def try_svg(urls):
        if not urls:
            return
        def on_svg(data, _final):
            if data and _image_format(data) in ("svg", "svgz"):
                store(".svg", data)
            else:
                try_svg(urls[1:])
        _get(nam, urls[0].toString(), on_svg)

    def try_raster(urls):
        if not urls:
            return
        def on_raster(data, _final):
            img = QImage()
            if data and img.loadFromData(data) and not img.isNull():
                # keep it only when it beats what the cache already has
                old = QImage(path(".best.png"))
                if old.isNull() or max(img.width(), img.height()) >= old.width():
                    os.makedirs(cache_dir, exist_ok=True)
                    _square(img).save(path(".best.png"))
                    deliver()
            else:
                try_raster(urls[1:])
        _get(nam, urls[0].toString(), on_raster)

    def finish():
        if pending["manifest"]:
            return
        try_svg(cands.svg)
        try_raster(cands.rasters())

    def on_manifest(data, final):
        pending["manifest"] = False
        try:
            icons = json.loads(data.decode("utf-8", "replace")).get("icons", []) if data else []
        except (ValueError, AttributeError):
            icons = []
        for entry in icons if isinstance(icons, list) else []:
            if not isinstance(entry, dict) or not entry.get("src"):
                continue
            purpose = str(entry.get("purpose", "any")).split()
            if "any" not in purpose:
                continue        # maskable/monochrome icons are cropped/flat
            cands.add(final.resolved(QUrl(str(entry["src"]))),
                      str(entry.get("sizes", "")), str(entry.get("type", "")).lower(),
                      False)
        finish()

    def on_html(data, final):
        if not data:
            return
        parser = _IconLinks()
        try:
            parser.feed(data.decode("utf-8", "replace"))
        except Exception:
            pass        # use whatever was collected before the parse error
        base = final.resolved(QUrl(parser.base)) if parser.base else final
        manifest = None
        for rels, href, sizes, mime in parser.links:
            url = base.resolved(QUrl(href))
            if "manifest" in rels:
                manifest = manifest or url
            elif "icon" in rels:
                cands.add(url, sizes, mime, True)
            else:
                cands.add(url, sizes or "180x180", mime, False)   # apple-touch default
        if manifest is not None and manifest.scheme() in ("http", "https"):
            pending["manifest"] = True
            _get(nam, manifest.toString(), on_manifest, limit=MAX_HTML)
        finish()

    _get(nam, url_str, on_html, limit=MAX_HTML)

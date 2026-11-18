# WebTray

**Tray launcher for web applications — one page per tray icon.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/hifidom/webtray/actions/workflows/ci.yml/badge.svg)](https://github.com/hifidom/webtray/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

WebTray keeps your favorite web apps close at hand: every configured
URL gets its own icon in the system tray. Click it, and the page opens in a
lightweight QtWebEngine window; click again, and it hides. No tabs, no
address bar clutter — your web apps behave like native desktop programs.

## Features

- **One tray icon per URL** — each page gets its own icon and menu; left-click toggles the window, hovering shows page name and URL for as long as the pointer stays on the icon (as a tooltip, or as an own hover note on XEmbed trays like Cinnamon's — not a desktop notification, so nothing lands in the notification history).
- **Sharp favicons everywhere** — tray and window icons use the site's favicon, cached per host: the native ICO sizes for small icons, the page's own hi-res icons (SVG, `<link rel="icon" sizes>`, apple-touch-icon, web app manifest) for HiDPI panels, Google's favicon service as fallback.
- **Custom tray icon per URL** (optional) — pick your own image (PNG, SVG, ICO, …) in the URL editor (*Configure URLs…* → *Add* / *Edit*) instead of the site favicon.
- **Custom title per URL** (optional) — the URL editor's *Title* field names the page in the tray tooltip / hover note (before the URL) and the window title; the page's own title stays appended to the window title.
- **Persistent sessions** — cookies and profile data live on disk, so logins survive restarts.
- **Per-URL window state** — size, position and zoom are remembered globally and per page.
- **Page title as window title**, favicon as window icon.
- **Crash-resilient** — a crashed renderer reloads the page automatically instead of leaving a white window.
- **Keyboard shortcuts** — zoom, reload, hide; also documented in the About dialog.
- **Configuration dialog** — add, edit, remove and reorder pages; each entry has its URL plus optional title and icon, and the `https://` scheme is added automatically.
- **Drop-in URL files** — put a file with a URL into `~/.config/webtray/urls/` and its tray icon appears (live-watched via inotify).

## Requirements

- Linux desktop with a system tray:
  - **X11:** KDE Plasma, XFCE, LXQt, Cinnamon, MATE, …
  - **GNOME:** install the *AppIndicator and KStatusNotifierItem* extension
  - **Wayland:** a compositor/shell with StatusNotifier support (KDE, GNOME with the extension above, …)
- Python 3.9+ with [PySide6](https://pypi.org/project/PySide6/) ≥ 6.5 (includes QtWebEngine/Chromium)

## Installation

### From source (recommended)

```bash
git clone https://github.com/hifidom/webtray.git
cd webtray
python3 -m venv .venv
source .venv/bin/activate
pip install .
webtray
```

### Quick try (no install)

```bash
pip install PySide6
PYTHONPATH=src python3 -m webtray
```

### Debian package

`debian/` contains full debhelper packaging. Build a `.deb` (e.g. on
Debian trixie — the reference target) with:

```bash
./build-deb.sh                     # dpkg-buildpackage -us -uc -b
```

The script checks the build tools and the state of the tree first, builds
unsigned and binary-only, and collects `webtray_*_all.deb` with the
`.changes`/`.buildinfo` in `pkg-out/`. Plain dpkg works as well:

```bash
dpkg-buildpackage -us -uc -b       # intentionally unsigned
ls ../webtray_*_all.deb
```

Install locally with `apt install ./webtray_*_all.deb`.
The CI runs this build as the `deb-build` job and uploads the `.deb` as an
artifact. The packages in the **hifidom apt repository**
(`http://sw.hifidom.com`, trixie/multiverse) are signed separately with the
repository key — signing keys are never part of this project.

Dependencies are Debian's own Qt bindings: `python3-pyside6.qtcore`,
`.qtgui`, `.qtnetwork`, `.qtwidgets`, `.qtwebenginecore`,
`.qtwebenginewidgets`, plus `python3-xlib` (native-pixel tray icons on
X11/HiDPI panels).

### Development

```bash
pip install -e ".[dev]"
webtray        # editable install, live code changes
ruff check src         # lint
```

## Usage

1. **First start:** the app's tray icon appears. Left-click it (or right-click →
   *Configure URLs…*) to open the configuration dialog and add your first page.
2. **Configure:** right-click → *Configure URLs…* to add, edit, remove and
   reorder pages. *Add* / *Edit* (double-click works too) opens the editor:
   the URL, plus an optional *Title* and *Icon* — an empty field follows
   the page, so the page's own title and its favicon are used. Each
   configured URL gets its own tray icon.
3. **Open / hide:** left-click any tray icon to show or hide its window.
   Right-click for the menu (*Configure URLs…*, *About WebTray*, *Quit*).
4. Closing the window (`Ctrl+W` or the ✕ button) only hides it — the app
   keeps running in the tray. *Quit* exits for good.

### Keyboard shortcuts

| Shortcut        | Action           |
|-----------------|------------------|
| `Ctrl + +`      | Zoom in          |
| `Ctrl + -`      | Zoom out         |
| `Ctrl + 0`      | Reset zoom       |
| `F5` / `Ctrl+R` | Reload page      |
| `Ctrl + W`      | Hide window      |

The shortcuts are also listed in **About → WebTray**.

### Data & settings locations

| What                     | Path                                        |
|--------------------------|---------------------------------------------|
| Settings                 | `~/.config/webtray/webtray.json` |
| Drop-in URL files        | `~/.config/webtray/urls/` |
| Sessions (profile, cookies) | `~/.local/share/webtray`         |
| Favicon cache            | `~/.cache/webtray/favicons`         |

### The settings file

`webtray.json` is plain JSON and meant to be read and edited:

```json
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
```

`sites` has one entry per configured URL, in the configured order — the URL
is part of the entry, so it is never stored twice. `window` is the shared
browser window, and every entry may keep its own title, icon file, window
rectangle and zoom — an URL without its own rectangle uses the `window`
one. A field that is not needed is left out, so an empty *Title*/*Icon* in
the configuration dialog simply removes the key, and an entry reduced to
its URL is a configured page without its own data.
Every write is atomic (temp file + rename), a file that cannot be parsed is
kept as `webtray.json.corrupt` and the app starts with an empty
configuration; the About dialog shows both.

Earlier layouts are converted on load: version 1 had the URLs in a separate
`urls` list with `sites` as a dictionary, and before JSON the data lived in
`webtray.conf` (QSettings INI, window positions as `@ByteArray` blobs) —
the first start reads that file, the blobs become the readable rectangles,
and it is removed.

### URL files (drop-in)

Every file in `~/.config/webtray/urls/` — e.g. `news.url` — that
contains a URL adds a tray icon. Content: a plain line with
`https://…`, or an `URL=` line (Windows `.url` INetShortcut /
`.desktop` `Type=Link` style). The name and extension are yours
(`.url` recommended); hidden files, backups and temp files are
ignored.

The directory is watched with inotify (`QFileSystemWatcher`): add,
remove or edit a file and the tray icons follow immediately — a
removed file's icon disappears and its window closes. These URLs are
managed by their files and are **not** listed in the configuration
dialog; if a file repeats a configured URL, the configured one wins.

## Autostart

`sudo apt install webtray` is all it takes: `postinst` writes the
per-user entry `~/.config/autostart/webtray.desktop` for every regular
user (the XDG user-autostart location that Cinnamon, GNOME, KDE and
XFCE all read — Cinnamon ignores the system-wide `/etc/xdg/autostart`
and lists entries there as “disabled”, so the deb ships no system-wide
entry) and **launches WebTray in your running session**, so the tray
icon appears immediately — no logout/login needed. From the next login
on, the desktop starts it automatically. Uninstalling (`apt remove`)
stops running instances, so the tray icon disappears with the package.

The app is single-instance: autostart, the install-time start and a
manual start never double the tray icon — a second start activates the
running instance. WebTray re-asserts its autostart entry on every
start; users created after installation get it on first start.

Toggle it anytime: right-click the tray icon → *Start on login*
(the entry is kept disabled if you switch it off).

### Desktop entry (manual install from source)

```bash
install -Dm644 assets/webtray.desktop \
  ~/.local/share/applications/webtray.desktop
install -Dm644 src/webtray/icons/256x256.png \
  ~/.local/share/icons/hicolor/256x256/apps/webtray.png
mkdir -p ~/.config/autostart
ln -sf ~/.local/share/applications/webtray.desktop \
  ~/.config/autostart/webtray.desktop
```

The desktop entry launches the `webtray` console script, so run it
from an activated virtual environment, install with `pipx install .`, or
adjust `Exec=` to your interpreter.

## Troubleshooting

### Tray icon does not appear on X11 (phantom StatusNotifierWatcher)

Observed on Cinnamon systems that also have KDE/Plasma packages installed
(the `kde-plasma-desktop` metapackage, `plasma-workspace`, or a Plasma-based
app stack that pulled them in). Qt 6 uses the SNI protocol whenever the
session bus has a name called `org.kde.StatusNotifierWatcher`, and falls back
to XEmbed (Cinnamon, MATE, XFCE panels) only when it is absent. Plasma's
`kded6` loads the kded module `statusnotifierwatcher` (shipped by
`plasma-workspace`) and claims that name on every desktop — on a non-KDE
session there is usually no StatusNotifier host behind it, so the icon is
registered with a watcher that forwards it nowhere, and the panel never sees
it: a *phantom watcher*. The activation chain at login is typically
xdg-desktop-portal → `plasma-xdg-desktop-portal-kde` → `plasma-kded6` (both
are D-Bus-activatable systemd user units).

Diagnosis:

```bash
# who owns the watcher name?
busctl --user status org.kde.StatusNotifierWatcher        # PID of kded6
# is the watcher object there? (phantom: name yes, object no)
busctl --user tree org.kde.StatusNotifierWatcher          # "No objects discovered"
# is the panel's XEmbed tray alive?
python3 -c "from Xlib import display; d=display.Display(); \
print(hex(d.get_selection_owner(d.intern_atom('_NET_SYSTEM_TRAY_S0')).id))"
```

Fix on the affected (non-KDE) system — keep the KDE daemon out of the
session, the panel's tray keeps working and KDE apps are unaffected:

```bash
systemctl --user mask plasma-kded6.service plasma-xdg-desktop-portal-kde.service
# log out and in again, then start webtray (or let autostart do it)
```

(Verified on Linux Mint-style Ubuntu with Cinnamon, Plasma 6.6 / kded6
6.24, Qt 6.10. The kded-module disable via `~/.config/kded6rc` /
`~/.config/kded5rc`, group `[Module-statusnotifierwatcher]`,
`autoload=false` exists in KDE's kded sources, but did **not** stop the name
claim on this Plasma version — the mask did. Nothing to do for KDE/Plasma
users: there plasmashell is the watcher's host and the icon shows up.)

## Development notes

- `src/webtray/app.py` — main application, tray icons, window, shortcuts
- `src/webtray/store.py` — the JSON settings file (read, write, migration)
- `src/webtray/config.py` — URL configuration dialog
- `src/webtray/favicons.py` — favicon fetching & caching
- `src/webtray/about.py` — About dialog (engine info, shortcuts)
- `tools/make_icons.py` — regenerates the PNG icon set (`python tools/make_icons.py`)

All user interface text, menus and documentation are in **English**.

## License

Licensed under the **Apache License, Version 2.0** — see [LICENSE](LICENSE)
and [NOTICE](NOTICE).

Unless You explicitly state otherwise, any contribution intentionally
submitted for inclusion in this work by the copyright owner(s) shall be
added to the work in accordance with the Apache-2.0 license, without any
additional terms or conditions (see section 5 of the license).

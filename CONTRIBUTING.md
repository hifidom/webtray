# Contributing to WebTray

Thanks for your interest in improving WebTray!

## Ground rules

- All user interface text, menus, code comments and documentation are in **English**.
- Keep the app lightweight: it is a tray launcher, not a full browser.
  No tabs, no address bar, no browser chrome — new features should fit that idea.
- By submitting a pull request You agree that Your contribution is licensed
  under the Apache-2.0 license (section 5 of the [LICENSE](LICENSE)),
  without any additional terms or conditions.
- New source files carry the Apache-2.0 license header (see existing files).

## Development setup

```bash
git clone https://github.com/hifidom/webtray.git
cd webtray
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the app:

```bash
webtray          # or: python -m webtray
```

Lint:

```bash
ruff check src
```

## Project layout

```
src/webtray/
  __init__.py    version and app identifiers
  __main__.py    python -m webtray
  app.py         tray icons, shared web view, shortcuts, settings
  config.py      URL configuration dialog
  favicons.py    favicon fetching & caching
  about.py       About dialog
tools/
  make_icons.py  regenerates the PNG icon set
assets/
  logo.svg       master logo, webtray.desktop  desktop entry
```

## Pull requests

- Reference an open issue when one exists (`Fixes #123` / `Refs #123`).
- Describe *what* changed and *why*.
- Keep the history readable (one topic per PR; rebase/merge on request).
- Test on a Linux desktop with a system tray and note Your desktop environment.

## Bug reports

Open an issue and include: OS/distribution, desktop environment and tray
support, WebTray version, and the Qt/PySide6/Chromium versions shown
in the About dialog.

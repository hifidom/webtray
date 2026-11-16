# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-16

Initial release.

### Features

- One system-tray icon per configured URL: clicking opens or hides the
  page in a shared QtWebEngine window, right-click opens its menu.
- Favicons are fetched per site and cached; the tray tooltip and the
  window title follow the page title.
- Optional per URL (set in the tray menu): your own icon image
  (PNG/SVG/ICO/…) instead of the favicon, and your own title — the
  page's own title stays appended in the window title.
- Drop-in URL files: files in `~/.config/webtray/urls` are watched and
  added/removed live.
- Geometry, zoom and last page are remembered per URL.
- Crisp icons on HiDPI panels — native-size pixels are painted into
  the tray's X window (the desktop panel scales nothing).
- UI font follows the system settings.
- Autostart via `~/.config/autostart`, enabled by default and per user.
- Single instance: starting again hands the page to the running app.
- Configuration and about dialogs; Apache-2.0 license.

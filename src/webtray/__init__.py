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

"""WebTray — a system tray launcher for web applications.

Each configured URL gets its own tray icon (with the site's favicon);
clicking it opens/hides the page in a single shared browser window.
"""

__version__ = "1.0.0"

APP_NAME = "webtray"        # identifier used in paths (config, data, cache)
APP_TITLE = "WebTray"       # name shown in the user interface
ORG_NAME = "webtray"        # QSettings organisation of the old webtray.conf

__all__ = ["__version__", "APP_NAME", "APP_TITLE", "ORG_NAME"]

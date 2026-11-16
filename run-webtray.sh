#!/usr/bin/env bash
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

# Start WebTray straight from the source tree — no install, no root.
#
#   ./run-webtray.sh
#
# Interpreter search: $PYTHON, ./.venv/bin/python, ./venv/bin/python, python3.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for candidate in "$ROOT/.venv/bin/python" "$ROOT/venv/bin/python" python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PY="$candidate"
      break
    fi
  done
fi

if [[ -z "$PY" ]]; then
  echo "run-webtray.sh: no Python interpreter found (tried \$PYTHON, .venv, venv, python3)." >&2
  exit 1
fi

# WebTray needs the Qt bindings; check the heaviest import so a partial
# install fails here with a hint instead of deep inside Qt.
if ! "$PY" -c 'import PySide6.QtWebEngineWidgets' >/dev/null 2>&1; then
  echo "run-webtray.sh: $PY has no PySide6 (QtWebEngine)." >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install PySide6" >&2
  echo "  … or point PYTHON= at an interpreter that provides PySide6." >&2
  exit 1
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

exec "$PY" -m webtray "$@"

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

# Build the .deb from the source tree — no root, package intentionally
# unsigned (the apt repository signs its own copies).
#
#   ./build-deb.sh                     dpkg-buildpackage -us -uc -b
#   ./build-deb.sh -tc                 extra flags go to dpkg-buildpackage
#
# The results (webtray_*_all.deb, .changes, .buildinfo) land in pkg-out/.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
OUT="$ROOT/pkg-out"
PARENT="$(dirname -- "$ROOT")"

cd "$ROOT"

if [[ ! -f debian/rules ]]; then
  echo "build-deb.sh: no debian/rules in $ROOT — run it inside the source tree." >&2
  exit 1
fi

has() { command -v "$1" >/dev/null 2>&1; }

# build-essential is dpkg's implicit Build-Essential dependency, the rest
# comes from debian/control's Build-Depends
DEPS="build-essential dpkg-dev debhelper dh-python pybuild-plugin-pyproject fakeroot python3-all python3-setuptools python3-pip python3-wheel"
if ! has dpkg-buildpackage; then
  echo "build-deb.sh: dpkg-buildpackage is missing (package dpkg-dev)." >&2
  echo "  sudo apt-get install -y --no-install-recommends $DEPS" >&2
  exit 1
fi
if ! has fakeroot; then
  # debhelper builds the install tree through fakeroot; without it the
  # build stops in the middle of dh_install
  echo "build-deb.sh: fakeroot is missing." >&2
  echo "  sudo apt-get install -y --no-install-recommends $DEPS" >&2
  exit 1
fi
# the authoritative check of debian/control's Build-Depends (for -b the
# architecture-specific ones); dpkg-buildpackage repeats it, this says it
# early and with the install line
if has dpkg-checkbuilddeps && ! dpkg-checkbuilddeps -B; then
  echo "build-deb.sh: the Build-Depends listed above are not installed." >&2
  echo "  sudo apt-get install -y --no-install-recommends $DEPS" >&2
  exit 1
fi

# dpkg-buildpackage cleans the debhelper state first and needs write access
# to it. A build run with sudo leaves root-owned files in debian/, build/
# and .pybuild/, which then blocks a normal build — say so up front, and
# skip the check when building as root (containers, CI).
if [[ "$(id -u)" != "0" ]]; then
  targets=()
  for dir in debian build .pybuild; do
    if [[ -d "$dir" ]]; then
      targets+=("$dir")
    fi
  done
  foreign=""
  if [[ ${#targets[@]} -gt 0 ]]; then
    # || true: find exits non-zero on head -1's SIGPIPE, pipefail would abort
    foreign="$(find "${targets[@]}" -maxdepth 2 -user root -print 2>/dev/null \
      | head -1 || true)"
  fi
  if [[ -n "$foreign" ]]; then
    echo "build-deb.sh: $foreign belongs to root — a sudo build left it behind." >&2
    echo "  sudo chown -R '$(id -un)' debian build .pybuild" >&2
    exit 1
  fi
fi

# the version comes from debian/changelog — read it, never change it
version="$(dpkg-parsechangelog -S Version 2>/dev/null || echo '?')"

echo "==> building webtray $version (unsigned, binary only)"

# -b: binary only, no source files; -us -uc: do not sign .changes/.buildinfo
dpkg-buildpackage -us -uc -b "$@"

# dpkg-buildpackage writes next to the tree; collect it as the CI job does
mkdir -p "$OUT"
shopt -s nullglob
artifacts=()
for f in "$PARENT"/webtray_*.deb "$PARENT"/webtray_*.changes \
         "$PARENT"/webtray_*.buildinfo "$PARENT"/webtray_*.dsc \
         "$PARENT"/webtray_*.tar.xz "$PARENT"/webtray_*.asc; do
  mv -f -- "$f" "$OUT/"
  artifacts+=("$OUT/$(basename -- "$f")")
done
shopt -u nullglob

if [[ ${#artifacts[@]} -eq 0 ]]; then
  echo "build-deb.sh: the build produced no webtray_* files in $PARENT." >&2
  exit 1
fi

deb="$OUT/webtray_${version}_all.deb"
echo "==> built webtray $version"
for f in "${artifacts[@]}"; do
  printf '    %s\n' "${f#"$ROOT"/}"
done

if has dpkg-deb && [[ -f "$deb" ]]; then
  dpkg-deb -I "$deb" | sed -n 's/^ \(Package\|Version\|Architecture\|Installed-Size\|Depends\): /    \1: /p'
  echo "==> install: sudo apt install ./pkg-out/webtray_${version}_all.deb"
fi

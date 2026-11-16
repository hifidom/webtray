#!/usr/bin/env python3
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

"""Render the WebTray app icon PNGs from assets/logo.svg.

The SVG (monochrome globe + down-left arrow triangle, white halo) is
rasterized by cairosvg at 4x the target size and downsampled with
LANCZOS — supersampling keeps the thin antialiased lines of the
artwork as designed, at every size.

Usage:  python tools/make_icons.py
Output: src/webtray/icons/{size}x{size}.png + icon.png
"""

import io
import os

import cairosvg
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_PATH = os.path.join(ROOT, "assets", "logo.svg")
OUT_DIR = os.path.join(ROOT, "src", "webtray", "icons")
SIZES = (16, 20, 22, 24, 28, 32, 36, 40, 44, 48, 56, 64, 74, 96, 128, 192, 256, 512)
SUPERSAMPLE = 4


def render(size):
    """logo.svg as a transparent size x size PNG (4x supersampled)."""
    raw = cairosvg.svg2png(url=SVG_PATH,
                           output_width=size * SUPERSAMPLE,
                           output_height=size * SUPERSAMPLE)
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for size in SIZES:
        with open(os.path.join(OUT_DIR, f"{size}x{size}.png"), "wb") as f:
            f.write(render(size))
        print(f"{size}x{size}.png")
    with open(os.path.join(OUT_DIR, "icon.png"), "wb") as f:
        f.write(render(256))
    print("icon.png (256 px fallback)")


if __name__ == "__main__":
    main()

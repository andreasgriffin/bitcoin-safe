#!/usr/bin/env python3

#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


def parse_svg_length(value: str) -> tuple[float, str]:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z%]*)\s*", value)
    if not match:
        raise RuntimeError(f"Unsupported SVG length value: {value!r}")
    return float(match.group(1)), match.group(2)


def format_svg_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def normalize_svg_canvas_to_square(source_path: Path, output_path: Path) -> None:
    content = source_path.read_text(encoding="utf-8")
    svg_tag_match = re.search(r"<svg\b[^>]*>", content)
    if svg_tag_match is None:
        raise RuntimeError(f"Expected SVG root element in {source_path}")

    svg_tag = svg_tag_match.group(0)
    width_match = re.search(r'\bwidth="([^"]+)"', svg_tag)
    height_match = re.search(r'\bheight="([^"]+)"', svg_tag)
    view_box_match = re.search(r'\bviewBox="([^"]+)"', svg_tag)
    if width_match is None or height_match is None or view_box_match is None:
        shutil.copyfile(source_path, output_path)
        return

    width_value, width_unit = parse_svg_length(width_match.group(1))
    height_value, height_unit = parse_svg_length(height_match.group(1))
    if width_unit != height_unit:
        shutil.copyfile(source_path, output_path)
        return

    try:
        min_x, min_y, box_width, box_height = [float(part) for part in view_box_match.group(1).split()]
    except ValueError as error:
        raise RuntimeError(
            f"Unsupported SVG viewBox value in {source_path}: {view_box_match.group(1)!r}"
        ) from error

    if abs(box_width - box_height) < 1e-6 and abs(width_value - height_value) < 1e-6:
        shutil.copyfile(source_path, output_path)
        return

    square_size = max(box_width, box_height)
    if box_width < square_size:
        min_x -= (square_size - box_width) / 2
        box_width = square_size
    if box_height < square_size:
        min_y -= (square_size - box_height) / 2
        box_height = square_size

    square_view_box = " ".join(format_svg_number(part) for part in (min_x, min_y, box_width, box_height))
    square_size_text = f"{format_svg_number(square_size)}{width_unit}"
    updated_tag = re.sub(r'\bwidth="[^"]+"', f'width="{square_size_text}"', svg_tag, count=1)
    updated_tag = re.sub(r'\bheight="[^"]+"', f'height="{square_size_text}"', updated_tag, count=1)
    updated_tag = re.sub(r'\bviewBox="[^"]+"', f'viewBox="{square_view_box}"', updated_tag, count=1)
    output_path.write_text(content.replace(svg_tag, updated_tag, 1), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"Usage: {Path(sys.argv[0]).name} SOURCE_SVG OUTPUT_SVG")
    normalize_svg_canvas_to_square(Path(sys.argv[1]), Path(sys.argv[2]))


if __name__ == "__main__":
    main()

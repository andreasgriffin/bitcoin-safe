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

"""Create the losslessly compressed PDF font bundle from a directory of fonts."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="directory containing the TTF and TTC files")
    parser.add_argument("output", type=Path, help="output tar.xz file")
    args = parser.parse_args()
    fonts = sorted(path for path in args.source.iterdir() if path.suffix.lower() in {".ttf", ".ttc"})
    if not fonts:
        raise ValueError(f"No fonts found in {args.source}")
    with tarfile.open(args.output, "w:xz", format=tarfile.USTAR_FORMAT, preset=9) as archive:
        for path in fonts:
            info = tarfile.TarInfo(path.name)
            info.size = path.stat().st_size
            info.mode = 0o644
            info.mtime = 0
            with path.open("rb") as source:
                archive.addfile(info, source)
    print(f"{sum(path.stat().st_size for path in fonts):,} -> {args.output.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

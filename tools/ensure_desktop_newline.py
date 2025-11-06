#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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
"""Ensure tracked desktop files have a trailing newline.

This script is intended to be used from the pre-commit hook to guarantee
that the AppImage desktop entry always ends with a newline, preventing
non-deterministic rewrites by tooling such as ``appimagetool``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_newline(path: Path) -> bool:
    """Append a trailing newline to *path* if it is missing.

    Returns ``True`` if the file was modified.
    """

    try:
        data = path.read_bytes()
    except FileNotFoundError:
        print(f"File not found: {path}", file=sys.stderr)
        return False

    if not data:
        # Empty files should still end with a newline to satisfy tools that
        # expect a terminating line feed.
        path.write_bytes(b"\n")
        return True

    if data.endswith(b"\n"):
        return False

    path.write_bytes(data + b"\n")
    return True


def main(argv: list[str]) -> int:
    """Main."""
    if not argv:
        print("No files provided", file=sys.stderr)
        return 1

    modified_any = False
    for arg in argv:
        path = Path(arg)
        if path.is_dir():
            continue
        if ensure_newline(path):
            print(f"Added missing trailing newline to {path}")
            modified_any = True

    # Exit with 0 so pre-commit will continue even if we fixed files.
    return 0 if modified_any or argv else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

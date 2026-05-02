#
# Bitcoin Safe
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

import hashlib
import os
from pathlib import Path

IGNORED_PATH_PARTS = {
    ".git",
    "__pycache__",
    ".venv",
    ".vscode",
    ".ruff_cache",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
}
IGNORED_FILE_NAMES = {".DS_Store", ".bitcoin-safe-installed.json"}
IGNORED_SUFFIXES = {".pyo"}


def iter_plugin_source_files(plugin_dir: Path) -> list[Path]:
    files: list[Path] = []
    for root, dir_names, file_names in os.walk(plugin_dir, topdown=True):
        dir_names[:] = sorted(directory for directory in dir_names if directory not in IGNORED_PATH_PARTS)
        root_path = Path(root)
        for file_name in sorted(file_names):
            path = root_path / file_name
            if file_name in IGNORED_FILE_NAMES or path.suffix in IGNORED_SUFFIXES:
                continue
            files.append(path)
    return files


def compute_plugin_folder_hash(plugin_dir: Path) -> str:
    digest = hashlib.sha256()
    for file_path in iter_plugin_source_files(plugin_dir):
        relative_path = file_path.relative_to(plugin_dir).as_posix().encode("utf-8")
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()

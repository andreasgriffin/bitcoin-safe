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

import hashlib
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import requests


def download_verified(url: str, archive: Path, expected_sha256: str) -> None:
    """Cache only complete downloads that match an authenticated release digest."""

    def valid(path: Path) -> bool:
        if not path.is_file():
            return False
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest() == expected_sha256

    if valid(archive):
        return
    with tempfile.NamedTemporaryFile(dir=archive.parent, delete=False) as file:
        temporary = Path(file.name)
    try:
        with temporary.open("wb") as file, requests.get(url, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            shutil.copyfileobj(response.raw, file)
        if not valid(temporary):
            raise ValueError(f"Checksum mismatch for {url}")
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)


def extract_verified(archive: Path, destination: Path) -> None:
    """Extract regular files and directories only, rejecting traversal and links."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()

    def check_path(name: str) -> None:
        if not (root / name).resolve().is_relative_to(root):
            raise ValueError(f"Unsafe archive path: {name}")

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                check_path(item.filename)
                mode = item.external_attr >> 16
                if mode and (mode & 0o170000) not in (0, 0o100000, 0o040000):
                    raise ValueError(f"Unsafe archive member: {item.filename}")
            source.extractall(root)
    else:
        with tarfile.open(archive, "r:gz") as source:
            for item in source.getmembers():
                check_path(item.name)
                if not (item.isfile() or item.isdir()):
                    raise ValueError(f"Unsafe archive member: {item.name}")
            source.extractall(root, filter="data")

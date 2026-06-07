#
# Bitcoin Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import datetime
import re
from dataclasses import replace
from pathlib import Path

import tomlkit

from bitcoin_safe import __version__
from bitcoin_safe.app_metadata import APP_METADATA

PYPROJECT_PATH = Path("pyproject.toml")
DESKTOP_ENTRY_PATH = Path("tools/resources/linux-bitcoin-safe.desktop")
FLATPAK_METAINFO_PATH = Path("tools/build-linux/flatpak/org.bitcoin_safe.BitcoinSafe.metainfo.xml")
WINDOWS_NSI_METADATA_PATH = Path("tools/build-wine/bitcoin_safe_metadata.nsh")
APPIMAGE_EXECUTABLE = "org.bitcoin-safe.bitcoin-safe %F"
APPIMAGE_ICON_NAME = "bitcoin-safe"
FLATPAK_DESKTOP_ID = "org.bitcoin_safe.BitcoinSafe.desktop"


def update_poetry_version(file_path: Path, new_version: str) -> None:
    """Update the Poetry version to match the application version."""
    with open(file_path, encoding="utf-8") as file:
        data = tomlkit.load(file)

    if "tool" in data and "poetry" in data["tool"] and "version" in data["tool"]["poetry"]:
        data["tool"]["poetry"]["version"] = new_version

        with open(file_path, "w", encoding="utf-8") as file:
            tomlkit.dump(data, file)
        print(f"Version updated to {new_version} in pyproject.toml")
    else:
        print("Could not find the 'tool.poetry.version' key in the pyproject.toml")


def resolve_release_date(file_path: Path, new_version: str) -> str:
    """Keep the existing release date unless the version changed."""
    with open(file_path, encoding="utf-8") as file:
        content = file.read()

    release_pattern = re.compile(r'(<release\b[^>]*\bversion=")([^"]+)(".*?\bdate=")([^"]+)(".*?/>)')
    match = release_pattern.search(content)
    if not match:
        return datetime.date.today().isoformat()

    current_version = match.group(2)
    current_date = match.group(4)
    if current_version != new_version:
        return datetime.date.today().isoformat()
    return current_date


def write_generated_packaging_files(new_version: str) -> None:
    """Write the checked-in packaging metadata derived from APP_METADATA."""
    release_date = resolve_release_date(FLATPAK_METAINFO_PATH, new_version)
    metadata = replace(APP_METADATA, release_date=release_date)

    DESKTOP_ENTRY_PATH.write_text(
        metadata.render_desktop_entry(exec_command=APPIMAGE_EXECUTABLE, icon_name=APPIMAGE_ICON_NAME),
        encoding="utf-8",
    )
    FLATPAK_METAINFO_PATH.write_text(
        metadata.render_metainfo(launchable_desktop_id=FLATPAK_DESKTOP_ID),
        encoding="utf-8",
    )
    WINDOWS_NSI_METADATA_PATH.write_text(metadata.render_windows_nsi_defines(), encoding="utf-8")
    print(f"Generated packaging metadata for {new_version}")


update_poetry_version(PYPROJECT_PATH, __version__)
write_generated_packaging_files(__version__)

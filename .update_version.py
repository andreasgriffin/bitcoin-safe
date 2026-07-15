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

from pathlib import Path

import tomlkit
from tools.build_linux.flathub_flatpak.tracked_repo_files import refresh_tracked_files

from bitcoin_safe import __version__
from bitcoin_safe.app_metadata import APP_METADATA

PROJECT_ROOT = Path(__file__).resolve().parent

PYPROJECT_PATH = Path("pyproject.toml")
DESKTOP_ENTRY_PATH = Path("tools/build_linux/flathub_flatpak/org.bitcoin_safe.BitcoinSafe.desktop")
WINDOWS_NSI_METADATA_PATH = Path("tools/build_wine/bitcoin_safe_metadata.nsh")
# The checked-in desktop entry is installed by the Flatpak/Flathub builds as
# org.bitcoin_safe.BitcoinSafe.desktop; the Flatpak runtime only ships
# /app/bin/run-bitcoin-safe.sh and icons named org.bitcoin_safe.BitcoinSafe.*,
# so Exec/Icon must reference those, not the AppImage command/icon.
FLATPAK_EXECUTABLE = "run-bitcoin-safe.sh %F"
FLATPAK_ICON_NAME = APP_METADATA.flatpak_app_id


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


def write_generated_packaging_files(new_version: str) -> None:
    """Write the checked-in packaging metadata derived from APP_METADATA."""
    DESKTOP_ENTRY_PATH.write_text(
        APP_METADATA.render_desktop_entry(exec_command=FLATPAK_EXECUTABLE, icon_name=FLATPAK_ICON_NAME),
        encoding="utf-8",
    )
    WINDOWS_NSI_METADATA_PATH.write_text(APP_METADATA.render_windows_nsi_defines(), encoding="utf-8")
    print(f"Generated packaging metadata for {new_version}")


def refresh_tracked_flathub_files(new_version: str) -> None:
    """Refresh tracked Flathub assets (metainfo, SVG, requirements) from the local checkout."""
    refresh_tracked_files(PROJECT_ROOT)
    print(f"Refreshed tracked Flathub files for {new_version}")


update_poetry_version(PYPROJECT_PATH, __version__)
write_generated_packaging_files(__version__)
refresh_tracked_flathub_files(__version__)

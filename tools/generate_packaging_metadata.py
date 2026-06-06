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

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bitcoin_safe.app_metadata import APP_METADATA

DESKTOP_ENTRY_PATH = Path("tools/resources/linux-bitcoin-safe.desktop")
FLATPAK_METAINFO_PATH = Path("tools/build-linux/flatpak/org.bitcoin_safe.BitcoinSafe.metainfo.xml")
WINDOWS_NSI_METADATA_PATH = Path("tools/build-wine/bitcoin_safe_metadata.nsh")
APPIMAGE_EXECUTABLE = "org.bitcoin-safe.bitcoin-safe %F"
APPIMAGE_ICON_NAME = "bitcoin-safe"
FLATPAK_DESKTOP_ID = "org.bitcoin_safe.BitcoinSafe.desktop"


def write_packaging_metadata(project_root: Path) -> None:
    desktop_path = project_root / DESKTOP_ENTRY_PATH
    desktop_path.write_text(
        APP_METADATA.render_desktop_entry(exec_command=APPIMAGE_EXECUTABLE, icon_name=APPIMAGE_ICON_NAME),
        encoding="utf-8",
    )

    metainfo_path = project_root / FLATPAK_METAINFO_PATH
    metainfo_path.write_text(
        APP_METADATA.render_metainfo(launchable_desktop_id=FLATPAK_DESKTOP_ID),
        encoding="utf-8",
    )

    windows_nsi_metadata_path = project_root / WINDOWS_NSI_METADATA_PATH
    windows_nsi_metadata_path.write_text(APP_METADATA.render_windows_nsi_defines(), encoding="utf-8")


def get_metadata_value(field: str) -> str:
    values = {
        "application-name": APP_METADATA.application_name,
        "homepage": APP_METADATA.homepage,
        "summary": APP_METADATA.summary,
        "macos-bundle-name": APP_METADATA.macos_bundle_name,
        "macos-dmg-volume-name": APP_METADATA.macos_dmg_volume_name,
        "macos-executable-name": APP_METADATA.macos_executable_name,
        "windows-publisher": APP_METADATA.developer_name,
    }
    return values[field]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate or query shared packaging metadata.")
    subparsers = parser.add_subparsers(dest="command", required=False)

    write_parser = subparsers.add_parser("write-files", help="Write generated packaging metadata files.")
    write_parser.add_argument(
        "--project-root",
        default=PROJECT_ROOT,
        type=Path,
        help="Project root where the metadata files should be written.",
    )

    get_parser = subparsers.add_parser("get", help="Print a shared metadata value.")
    get_parser.add_argument(
        "field",
        choices=(
            "application-name",
            "homepage",
            "summary",
            "macos-bundle-name",
            "macos-dmg-volume-name",
            "macos-executable-name",
            "windows-publisher",
        ),
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in (None, "write-files"):
        project_root = PROJECT_ROOT if args.command is None else args.project_root.resolve()
        write_packaging_metadata(project_root)
        return

    if args.command == "get":
        print(get_metadata_value(args.field))
        return

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()

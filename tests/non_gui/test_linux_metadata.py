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

from pathlib import Path

from tools.appimage_to_deb_converter import Appimage2debConverter
from tools.generate_packaging_metadata import (
    APPIMAGE_EXECUTABLE,
    APPIMAGE_ICON_NAME,
    DESKTOP_ENTRY_PATH,
    FLATPAK_DESKTOP_ID,
    FLATPAK_METAINFO_PATH,
    WINDOWS_NSI_METADATA_PATH,
)

from bitcoin_safe.app_metadata import APP_METADATA

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_desktop_entry_matches_generated_metadata() -> None:
    desktop_entry = (PROJECT_ROOT / DESKTOP_ENTRY_PATH).read_text(encoding="utf-8")
    assert desktop_entry == APP_METADATA.render_desktop_entry(
        exec_command=APPIMAGE_EXECUTABLE,
        icon_name=APPIMAGE_ICON_NAME,
    )


def test_flatpak_metainfo_matches_generated_metadata() -> None:
    metainfo = (PROJECT_ROOT / FLATPAK_METAINFO_PATH).read_text(encoding="utf-8")
    assert metainfo == APP_METADATA.render_metainfo(launchable_desktop_id=FLATPAK_DESKTOP_ID)


def test_windows_nsi_metadata_matches_generated_metadata() -> None:
    windows_nsi_metadata = (PROJECT_ROOT / WINDOWS_NSI_METADATA_PATH).read_text(encoding="utf-8")
    assert windows_nsi_metadata == APP_METADATA.render_windows_nsi_defines()


def test_macos_packaging_includes_license_file() -> None:
    osx_spec = (PROJECT_ROOT / "tools" / "build-mac" / "osx.spec").read_text(encoding="utf-8")
    make_osx = (PROJECT_ROOT / "tools" / "build-mac" / "make_osx.sh").read_text(encoding="utf-8")
    package_sh = (PROJECT_ROOT / "tools" / "build-mac" / "package.sh").read_text(encoding="utf-8")

    assert '(f"{PROJECT_ROOT}/LICENSE.md", "LICENSE.txt")' in osx_spec
    assert 'cp "LICENSE.md" "dmg-package/LICENSE.txt"' in make_osx
    assert 'cp "$LICENSE_SOURCE_PATH" /tmp/bitcoin_safe-macos/image/LICENSE.txt' in package_sh


def test_deb_converter_writes_shared_desktop_and_metainfo(tmp_path: Path) -> None:
    appimage_path = tmp_path / "bitcoin-safe.AppImage"
    appimage_path.write_text("stub", encoding="utf-8")
    package_root = tmp_path / "package-root"

    converter = Appimage2debConverter(
        appimage=appimage_path,
        package_name="bitcoin-safe",
        desktop_entry_content=APP_METADATA.render_desktop_entry(
            exec_command="/opt/bitcoin-safe/AppRun",
            icon_name="/opt/bitcoin-safe/bitcoin-safe.svg",
        ),
        desktop_file_id="org.bitcoin_safe.BitcoinSafe.desktop",
        appstream_component_id=APP_METADATA.flatpak_app_id,
        appstream_metainfo_content=APP_METADATA.render_metainfo(
            launchable_desktop_id="org.bitcoin_safe.BitcoinSafe.desktop"
        ),
        debian_copyright_content=APP_METADATA.render_debian_copyright(package_name="bitcoin-safe"),
    )

    converter._create_desktop_file(package_root)
    converter._create_appstream_metadata(package_root)
    converter._create_debian_copyright_file(package_root)

    desktop_path = package_root / "usr" / "share" / "applications" / "org.bitcoin_safe.BitcoinSafe.desktop"
    metainfo_path = (
        package_root / "usr" / "share" / "metainfo" / f"{APP_METADATA.flatpak_app_id}.metainfo.xml"
    )
    debian_copyright_path = package_root / "usr" / "share" / "doc" / "bitcoin-safe" / "copyright"

    assert desktop_path.read_text(encoding="utf-8") == APP_METADATA.render_desktop_entry(
        exec_command="/opt/bitcoin-safe/AppRun",
        icon_name="/opt/bitcoin-safe/bitcoin-safe.svg",
    )
    assert metainfo_path.read_text(encoding="utf-8") == APP_METADATA.render_metainfo(
        launchable_desktop_id="org.bitcoin_safe.BitcoinSafe.desktop"
    )
    assert debian_copyright_path.read_text(encoding="utf-8") == APP_METADATA.render_debian_copyright(
        package_name="bitcoin-safe"
    )

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


def test_windows_version_info_is_generated_from_shared_metadata() -> None:
    version_info = APP_METADATA.render_windows_version_info(
        original_filename="bitcoin_safe-portable.exe",
        file_description="Bitcoin Safe Portable",
        product_version="2.0.0rc2",
    )

    assert "filevers=(2, 0, 0, 2)" in version_info
    assert "StringStruct(u'CompanyName', u'Andreas Griffin')" in version_info
    assert "StringStruct(u'FileDescription', u'Bitcoin Safe Portable')" in version_info
    assert "StringStruct(u'OriginalFilename', u'bitcoin_safe-portable.exe')" in version_info
    assert "StringStruct(u'ProductName', u'Bitcoin Safe')" in version_info
    assert "StringStruct(u'ProductVersion', u'2.0.0rc2')" in version_info


def test_windows_build_scripts_embed_shared_version_info() -> None:
    deterministic_spec = (PROJECT_ROOT / "tools" / "build-wine" / "deterministic.spec").read_text(
        encoding="utf-8"
    )
    build_exe = (PROJECT_ROOT / "tools" / "build-wine" / "build_exe.sh").read_text(encoding="utf-8")

    assert "render_windows_version_info" in deterministic_spec
    assert "version=portable_version_info_path" in deterministic_spec
    assert "version=setup_version_info_path" in deterministic_spec
    assert "version=debug_version_info_path" in deterministic_spec
    assert "BITCOIN_SAFE_WINDOWS_VERSION" in build_exe


def test_macos_packaging_includes_license_file() -> None:
    osx_spec = (PROJECT_ROOT / "tools" / "build-mac" / "osx.spec").read_text(encoding="utf-8")
    make_osx = (PROJECT_ROOT / "tools" / "build-mac" / "make_osx.sh").read_text(encoding="utf-8")
    package_sh = (PROJECT_ROOT / "tools" / "build-mac" / "package.sh").read_text(encoding="utf-8")

    assert '(f"{PROJECT_ROOT}/LICENSE.md", "LICENSE.txt")' in osx_spec
    assert "create_styled_dmg.sh" in make_osx
    assert "LICENSE.txt" not in make_osx
    assert "LICENSE.txt" not in package_sh


def test_macos_packaging_uses_styled_dmg_with_plain_fallback() -> None:
    create_styled_dmg = (PROJECT_ROOT / "tools" / "build-mac" / "create_styled_dmg.sh").read_text(
        encoding="utf-8"
    )
    make_osx = (PROJECT_ROOT / "tools" / "build-mac" / "make_osx.sh").read_text(encoding="utf-8")
    sign_osx = (PROJECT_ROOT / "tools" / "build-mac" / "sign_osx.sh").read_text(encoding="utf-8")

    assert "tools/resources/dmg-background.png" in make_osx
    assert "tools/resources/dmg-background.png" in sign_osx
    assert 'BACKGROUND_COPY_PATH="${STAGING_DIR}/.background/dmg-background.png"' in create_styled_dmg
    assert (
        'sips -z "${WINDOW_HEIGHT}" "${WINDOW_WIDTH}" "${BACKGROUND_COPY_PATH}" >/dev/null'
        in create_styled_dmg
    )
    assert 'set dmg_folder to POSIX file "${MOUNT_DIR}" as alias' in create_styled_dmg
    assert (
        'set background_image to POSIX file "${MOUNT_DIR}/.background/dmg-background.png" as alias'
        in create_styled_dmg
    )
    assert (
        "set the bounds of dmg_window to {${WINDOW_LEFT}, ${WINDOW_TOP}, ${WINDOW_RIGHT}, ${WINDOW_BOTTOM}}"
        in create_styled_dmg
    )
    assert "ICON_SIZE=104" in create_styled_dmg
    assert "ICON_TEXT_SIZE=13" in create_styled_dmg
    assert "APP_ICON_X=132" in create_styled_dmg
    assert "APP_ICON_Y=220" in create_styled_dmg
    assert "APPLICATIONS_ICON_X=506" in create_styled_dmg
    assert "APPLICATIONS_ICON_Y=220" in create_styled_dmg
    assert "set icon size of view_options to ${ICON_SIZE}" in create_styled_dmg
    assert "set text size of view_options to ${ICON_TEXT_SIZE}" in create_styled_dmg
    assert (
        'set position of item "${APP_NAME}" of dmg_window to {${APP_ICON_X}, ${APP_ICON_Y}}'
        in create_styled_dmg
    )
    assert (
        'set position of item "Applications" of dmg_window to '
        "{${APPLICATIONS_ICON_X}, ${APPLICATIONS_ICON_Y}}" in create_styled_dmg
    )
    assert "open folder dmg_folder" in create_styled_dmg
    assert "create_plain_dmg" in create_styled_dmg
    assert "convert_compressed_dmg" in create_styled_dmg
    assert 'echo "Could not convert staged DMG."' in create_styled_dmg
    assert "hdiutil convert" in create_styled_dmg
    assert '-srcfolder "${STAGING_DIR}"' in create_styled_dmg
    assert 'ln -s /Applications "${STAGING_DIR}/Applications"' in create_styled_dmg
    assert "osascript" in create_styled_dmg


def test_macos_reproducible_package_script_preserves_cdrkit_flow() -> None:
    package_sh = (PROJECT_ROOT / "tools" / "build-mac" / "package.sh").read_text(encoding="utf-8")
    dmg_tools = (PROJECT_ROOT / "tools" / "build-mac" / "ensure_reproducible_dmg_tools.sh").read_text(
        encoding="utf-8"
    )

    assert "ensure_reproducible_dmg_tools.sh" in package_sh
    assert "ensure_reproducible_dmg_tools" in package_sh
    assert '"$BITCOIN_SAFE_GENISOIMAGE"' in package_sh
    assert '"$BITCOIN_SAFE_DMG_COMPRESSOR" dmg' in package_sh
    assert "DMG_VOLUME_NAME" in package_sh
    assert "create_styled_dmg.sh" not in package_sh
    assert 'GENISOIMAGE_PATH="${DMG_TOOLS_BIN_DIR}/genisoimage-${CDRKIT_VERSION}"' in dmg_tools
    assert 'DMG_COMPRESSOR_PATH="${DMG_TOOLS_BIN_DIR}/dmg"' in dmg_tools
    assert "cdrkit-deterministic.patch" in dmg_tools
    assert "git clone" in dmg_tools


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

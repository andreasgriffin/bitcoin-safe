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

import datetime
import subprocess
from pathlib import Path

import pytest
from tools.appimage_to_deb_converter import Appimage2debConverter
from tools.release_notes import (
    iter_release_notes,
    load_release_notes,
    release_notes_path,
    required_release_notes,
)

from bitcoin_safe import __version__
from bitcoin_safe.app_metadata import APP_METADATA, resolve_metainfo_release_date
from bitcoin_safe.constants import (
    APP_NAME,
    MACOS_BUNDLE_IDENTIFIER,
    MACOS_BUNDLE_NAME,
    WINDOWS_INSTALL_IDENTITY,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_ENTRY_PATH = Path("tools/build_linux/flathub_flatpak/org.bitcoin_safe.BitcoinSafe.desktop")
FLATPAK_METAINFO_PATH = Path("tools/build_linux/flathub_flatpak/org.bitcoin_safe.BitcoinSafe.metainfo.xml")
WINDOWS_NSI_METADATA_PATH = Path("tools/build_wine/bitcoin_safe_metadata.nsh")
FLATPAK_EXECUTABLE = "run-bitcoin-safe.sh %F"
FLATPAK_ICON_NAME = APP_METADATA.flatpak_app_id


def appstream_release_date() -> str:
    return resolve_metainfo_release_date(PROJECT_ROOT / FLATPAK_METAINFO_PATH, __version__)


def test_desktop_entry_matches_generated_metadata() -> None:
    desktop_entry = (PROJECT_ROOT / DESKTOP_ENTRY_PATH).read_text(encoding="utf-8")
    assert desktop_entry == APP_METADATA.render_desktop_entry(
        exec_command=FLATPAK_EXECUTABLE,
        icon_name=FLATPAK_ICON_NAME,
    )


def test_windows_nsi_metadata_matches_generated_metadata() -> None:
    windows_nsi_metadata = (PROJECT_ROOT / WINDOWS_NSI_METADATA_PATH).read_text(encoding="utf-8")
    assert windows_nsi_metadata == APP_METADATA.render_windows_nsi_defines()


def test_application_name_and_windows_install_identity_are_separate() -> None:
    assert APP_METADATA.application_name == APP_NAME == "Bitcoin-Safe"
    assert APP_METADATA.windows_install_identity == WINDOWS_INSTALL_IDENTITY == "Bitcoin Safe"

    windows_nsi_metadata = APP_METADATA.render_windows_nsi_defines()
    assert '!define PRODUCT_NAME "Bitcoin-Safe"' in windows_nsi_metadata
    assert '!define PRODUCT_INSTALL_IDENTITY "Bitcoin Safe"' in windows_nsi_metadata
    assert 'Uninstall\\${PRODUCT_INSTALL_IDENTITY}"' in windows_nsi_metadata

    windows_installer = (PROJECT_ROOT / "tools/build_wine/bitcoin_safe.nsi").read_text(encoding="utf-8")
    assert 'InstallDir "$PROGRAMFILES64\\${PRODUCT_INSTALL_IDENTITY}"' in windows_installer
    assert 'InstallDirRegKey HKCU "Software\\${PRODUCT_INSTALL_IDENTITY}" ""' in windows_installer
    assert 'CreateShortCut "$DESKTOP\\${PRODUCT_NAME}.lnk"' in windows_installer
    assert 'Delete "$DESKTOP\\${PRODUCT_INSTALL_IDENTITY}.lnk"' in windows_installer


def test_checked_in_metainfo_matches_generated_shared_metadata() -> None:
    checked_in_metainfo = (PROJECT_ROOT / FLATPAK_METAINFO_PATH).read_text(encoding="utf-8")
    expected_metainfo = APP_METADATA.render_checked_in_metainfo(
        existing_content=checked_in_metainfo,
        launchable_desktop_id=f"{APP_METADATA.flatpak_app_id}.desktop",
        release_date=__version__,
    )
    assert checked_in_metainfo == expected_metainfo


def test_flathub_populate_script_owns_checked_in_metainfo_generation() -> None:
    populate_cli_script = (
        PROJECT_ROOT / "tools" / "build_linux" / "flathub_flatpak" / "populate_cli.py"
    ).read_text(encoding="utf-8")
    tracked_repo_files_script = (
        PROJECT_ROOT / "tools" / "build_linux" / "flathub_flatpak" / "tracked_repo_files.py"
    ).read_text(encoding="utf-8")
    update_version_script = (PROJECT_ROOT / ".update_version.py").read_text(encoding="utf-8")
    pre_commit_config = (PROJECT_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "render_checked_in_metainfo" in tracked_repo_files_script
    assert "org.bitcoin_safe.BitcoinSafe.metainfo.xml" not in update_version_script
    assert "iter_release_notes" in tracked_repo_files_script
    assert "fetch_release_notes" not in tracked_repo_files_script
    assert "--refresh-tracked-only" in populate_cli_script
    assert "refresh_tracked_files_for_context(context)" in populate_cli_script
    assert 'if __name__ == "__main__":' in populate_cli_script
    assert "main()" in populate_cli_script
    assert "required_release_notes" in tracked_repo_files_script
    assert "from tools.build_linux.flathub_flatpak.tracked_repo_files import refresh_tracked_files" in (
        update_version_script
    )
    assert "refresh_tracked_files(PROJECT_ROOT)" in update_version_script
    assert "python .update_version.py" in pre_commit_config


def test_windows_version_info_is_generated_from_shared_metadata() -> None:
    version_info = APP_METADATA.render_windows_version_info(
        original_filename="bitcoin_safe-portable.exe",
        file_description="Bitcoin-Safe Portable",
        product_version="2.0.0rc2",
    )

    assert "filevers=(2, 0, 0, 2)" in version_info
    assert "StringStruct(u'CompanyName', u'Andreas Griffin')" in version_info
    assert "StringStruct(u'FileDescription', u'Bitcoin-Safe Portable')" in version_info
    assert "StringStruct(u'OriginalFilename', u'bitcoin_safe-portable.exe')" in version_info
    assert "StringStruct(u'ProductName', u'Bitcoin-Safe')" in version_info
    assert "StringStruct(u'ProductVersion', u'2.0.0rc2')" in version_info


def test_windows_build_scripts_embed_shared_version_info() -> None:
    deterministic_spec = (PROJECT_ROOT / "tools" / "build_wine" / "deterministic.spec").read_text(
        encoding="utf-8"
    )
    build_exe = (PROJECT_ROOT / "tools" / "build_wine" / "build_exe.sh").read_text(encoding="utf-8")

    assert "render_windows_version_info" in deterministic_spec
    assert "version=portable_version_info_path" in deterministic_spec
    assert "version=setup_version_info_path" in deterministic_spec
    assert "version=debug_version_info_path" in deterministic_spec
    assert "BITCOIN_SAFE_WINDOWS_VERSION" in build_exe


def test_macos_packaging_includes_license_file() -> None:
    osx_spec = (PROJECT_ROOT / "tools" / "build_mac" / "osx.spec").read_text(encoding="utf-8")
    make_osx = (PROJECT_ROOT / "tools" / "build_mac" / "make_osx.sh").read_text(encoding="utf-8")
    package_sh = (PROJECT_ROOT / "tools" / "build_mac" / "package.sh").read_text(encoding="utf-8")

    assert '(f"{PROJECT_ROOT}/LICENSE.md", "LICENSE.txt")' in osx_spec
    assert "create_styled_dmg.sh" in make_osx
    assert "LICENSE.txt" not in make_osx
    assert "LICENSE.txt" not in package_sh


def test_macos_bundle_keeps_install_identity_and_uses_rebranded_display_name() -> None:
    osx_spec = (PROJECT_ROOT / "tools" / "build_mac" / "osx.spec").read_text(encoding="utf-8")
    sign_osx = (PROJECT_ROOT / "tools" / "build_mac" / "sign_osx.sh").read_text(encoding="utf-8")

    assert APP_METADATA.application_name == APP_NAME
    assert APP_METADATA.macos_bundle_name == MACOS_BUNDLE_NAME == "Bitcoin Safe.app"
    assert APP_METADATA.macos_bundle_identifier == MACOS_BUNDLE_IDENTIFIER == "org.bitcoin-safe.BitcoinSafe"
    assert "name=PACKAGE_NAME" in osx_spec
    assert "bundle_identifier=APP_METADATA.macos_bundle_identifier" in osx_spec
    assert "'CFBundleDisplayName': APP_METADATA.application_name" in osx_spec
    assert 'PACKAGE_NAME="$(bitcoin_safe_macos_bundle_name "$PROJECT_ROOT")"' in sign_osx
    assert 'DoCodeSignMaybe "app bundle" "dist/${PACKAGE_NAME}"' in sign_osx
    assert '"dist/$PACKAGE_NAME"' in sign_osx


def test_macos_packaging_uses_styled_dmg_with_plain_fallback() -> None:
    create_styled_dmg = (PROJECT_ROOT / "tools" / "build_mac" / "create_styled_dmg.sh").read_text(
        encoding="utf-8"
    )
    make_osx = (PROJECT_ROOT / "tools" / "build_mac" / "make_osx.sh").read_text(encoding="utf-8")
    sign_osx = (PROJECT_ROOT / "tools" / "build_mac" / "sign_osx.sh").read_text(encoding="utf-8")

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
    assert "APP_ICON_Y=170" in create_styled_dmg
    assert "APPLICATIONS_ICON_X=506" in create_styled_dmg
    assert "APPLICATIONS_ICON_Y=170" in create_styled_dmg
    assert 'TEMP_ROOT="$(cd "${TEMP_ROOT}" && pwd -P)"' in create_styled_dmg
    assert "DMG_RETRY_ATTEMPTS=5" in create_styled_dmg
    assert "DMG_RETRY_DELAY_SECONDS=10" in create_styled_dmg
    assert "DMG_DETACH_GRACE_ATTEMPTS=5" in create_styled_dmg
    assert "DMG_HELPER_RELEASE_ATTEMPTS=10" in create_styled_dmg
    assert "local delay=$((DMG_RETRY_DELAY_SECONDS * (2 ** (failed_attempts - 1))))" in create_styled_dmg
    assert 'wait_before_dmg_retry "${attempts}"' in create_styled_dmg
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
    assert "wait_for_dmg_release" in create_styled_dmg
    assert "staged_dmg_is_attached" in create_styled_dmg
    assert 'image_info="$(hdiutil info)"' in create_styled_dmg
    assert 'grep -Fq "${RW_DMG_PATH}" <<<"${image_info}"' in create_styled_dmg
    assert "sed -E 's/s[0-9]+$//'" in create_styled_dmg
    assert 'hdiutil detach "${DEVICE_NAME}" -quiet' in create_styled_dmg
    assert "staged_dmg_process_ids" in create_styled_dmg
    assert 'matches_image && $1 == "process" && $2 == "ID"' in create_styled_dmg
    assert '[[ "${process_name}" != *diskimage* ]]' in create_styled_dmg
    assert "terminate_staged_dmg_helpers TERM" in create_styled_dmg
    assert "terminate_staged_dmg_helpers KILL" in create_styled_dmg
    assert "print_dmg_diagnostics" in create_styled_dmg
    assert 'lsof "${RW_DMG_PATH}"' in create_styled_dmg
    assert 'echo "Timed out waiting for staged DMG to detach completely."' in create_styled_dmg
    assert "create_plain_dmg" in create_styled_dmg
    assert "convert_compressed_dmg" in create_styled_dmg
    assert 'echo "Could not convert staged DMG."' in create_styled_dmg
    assert "hdiutil convert" in create_styled_dmg
    assert '-srcfolder "${STAGING_DIR}"' in create_styled_dmg
    assert 'ln -s /Applications "${STAGING_DIR}/Applications"' in create_styled_dmg
    assert "osascript" in create_styled_dmg


def test_macos_reproducible_package_script_preserves_cdrkit_flow() -> None:
    package_sh = (PROJECT_ROOT / "tools" / "build_mac" / "package.sh").read_text(encoding="utf-8")
    dmg_tools = (PROJECT_ROOT / "tools" / "build_mac" / "ensure_reproducible_dmg_tools.sh").read_text(
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


def test_release_date_resolver_preserves_existing_date_for_same_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metainfo_path = tmp_path / "same-version.metainfo.xml"
    metainfo_path.write_text('<release version="2.0.0rc2" date="2026-06-06"/>', encoding="utf-8")
    monkeypatch.setattr(
        "bitcoin_safe.app_metadata.resolve_git_tag_date", lambda repository_root, version: None
    )

    assert (
        resolve_metainfo_release_date(
            metainfo_path,
            "2.0.0rc2",
            current_date=datetime.date(2030, 1, 2),
            repository_root=PROJECT_ROOT,
        )
        == "2026-06-06"
    )


def test_release_date_resolver_uses_latest_tag_when_version_tag_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metainfo_path = tmp_path / "new-version.metainfo.xml"
    metainfo_path.write_text('<release version="2.0.0rc2" date="2026-06-06"/>', encoding="utf-8")
    monkeypatch.setattr(
        "bitcoin_safe.app_metadata.resolve_git_tag_date", lambda repository_root, version: None
    )
    monkeypatch.setattr(
        "bitcoin_safe.app_metadata.resolve_latest_git_tag_date", lambda repository_root: "2026-06-12"
    )

    assert (
        resolve_metainfo_release_date(
            metainfo_path,
            "9.9.9rc9",
            current_date=datetime.date(2030, 1, 2),
            repository_root=PROJECT_ROOT,
        )
        == "2026-06-12"
    )


def test_release_date_resolver_uses_version_tag_when_release_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metainfo_path = tmp_path / "missing-release.metainfo.xml"
    metainfo_path.write_text("<component></component>", encoding="utf-8")
    monkeypatch.setattr(
        "bitcoin_safe.app_metadata.resolve_git_tag_date", lambda repository_root, version: "2026-04-14"
    )

    assert (
        resolve_metainfo_release_date(
            metainfo_path,
            "2.0.0rc2",
            current_date=datetime.date(2030, 1, 2),
            repository_root=PROJECT_ROOT,
        )
        == "2026-04-14"
    )


def test_release_date_resolver_falls_back_to_clock_without_git_metadata(tmp_path: Path) -> None:
    metainfo_path = tmp_path / "no-git.metainfo.xml"
    metainfo_path.write_text("<component></component>", encoding="utf-8")

    assert (
        resolve_metainfo_release_date(
            metainfo_path,
            "2.0.0rc2",
            current_date=datetime.date(2030, 1, 2),
        )
        == "2030-01-02"
    )


def test_macos_scripts_use_repo_root_bound_metadata_helper(tmp_path: Path) -> None:
    helper_path = PROJECT_ROOT / "tools" / "build_mac" / "app_metadata.sh"
    helper_content = helper_path.read_text(encoding="utf-8")

    assert 'PYTHONPATH="${pythonpath}" python3 - "${field_name}"' in helper_content
    for script_name in ("make_osx.sh", "package.sh", "sign_osx.sh", "compare_dmg"):
        script_content = (PROJECT_ROOT / "tools" / "build_mac" / script_name).read_text(encoding="utf-8")
        assert "app_metadata.sh" in script_content
        assert "python3 -c 'from bitcoin_safe.app_metadata import APP_METADATA" not in script_content

    result = subprocess.run(
        [
            "bash",
            "-lc",
            f'cd "{tmp_path}" && source "{helper_path}" && bitcoin_safe_application_name "{PROJECT_ROOT}"',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == APP_METADATA.application_name


def test_deb_converter_writes_shared_desktop_and_metainfo(tmp_path: Path) -> None:
    appimage_path = tmp_path / "bitcoin-safe.AppImage"
    appimage_path.write_text("stub", encoding="utf-8")
    package_root = tmp_path / "package-root"
    release_date = appstream_release_date()

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
            launchable_desktop_id="org.bitcoin_safe.BitcoinSafe.desktop",
            release_date=release_date,
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
        launchable_desktop_id="org.bitcoin_safe.BitcoinSafe.desktop",
        release_date=release_date,
    )
    assert debian_copyright_path.read_text(encoding="utf-8") == APP_METADATA.render_debian_copyright(
        package_name="bitcoin-safe"
    )


def test_release_notes_helpers_resolve_versioned_markdown_files(tmp_path: Path) -> None:
    version = "9.9.9"
    notes_path = release_notes_path(tmp_path, version)
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text("### Changes\n\n- Example\n", encoding="utf-8")

    assert notes_path == tmp_path / "release-notes" / "9.9.9.md"
    assert load_release_notes(tmp_path, version) == "### Changes\n\n- Example"
    assert required_release_notes(tmp_path, version) == "### Changes\n\n- Example"
    assert iter_release_notes(tmp_path)[0].version == version


def test_required_release_notes_rejects_empty_file(tmp_path: Path) -> None:
    version = "9.9.9"
    notes_path = release_notes_path(tmp_path, version)
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="is empty"):
        required_release_notes(tmp_path, version)


def test_required_release_notes_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Missing release notes"):
        required_release_notes(tmp_path, "9.9.9")


def test_checked_in_metainfo_release_history_is_moved_to_local_markdown_files() -> None:
    checked_in_metainfo = (PROJECT_ROOT / FLATPAK_METAINFO_PATH).read_text(encoding="utf-8")

    assert '<release version="2.0.0" date="2026-06-29">' in checked_in_metainfo
    assert (PROJECT_ROOT / "release-notes" / "2.0.0.md").exists()
    assert "Compact Block Filters by default" in (PROJECT_ROOT / "release-notes" / "2.0.0.md").read_text(
        encoding="utf-8"
    )
    assert "Compact Block Filters by default" in checked_in_metainfo

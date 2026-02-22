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

from __future__ import annotations

from pathlib import Path

from bitcoin_safe.update_applier import (
    UpdateApplier,
    UpdateApplierAction,
    UpdateArtifactFormat,
    UpdateHandler,
)


class ApplierDouble(UpdateApplier):
    def __init__(
        self,
        system: str | None = None,
        current_binary: Path | None = None,
        env: dict[str, str] | None = None,
        launch_result: bool = True,
        admin_result: bool = False,
        uac_result: bool = False,
        command_exists: dict[str, bool] | None = None,
    ) -> None:
        super().__init__(system=system, current_binary=current_binary, env=env)
        self.launch_result = launch_result
        self.admin_result = admin_result
        self.uac_result = uac_result
        self.command_exists = command_exists or {}
        self.started_commands: list[list[str]] = []
        self.elevated_calls: list[Path] = []

    def _launch_detached(self, cmd: list[str]) -> bool:
        self.started_commands.append(cmd)
        return self.launch_result

    def _default_admin_checker(self) -> bool:
        return self.admin_result

    def _launch_windows_setup_with_uac_prompt(self, executable: Path) -> bool:
        self.elevated_calls.append(executable)
        return self.uac_result

    def _command_exists(self, command: str) -> bool:
        if command in self.command_exists:
            return self.command_exists[command]
        return super()._command_exists(command)


def test_linux_appimage_is_replaced_in_place(tmp_path: Path) -> None:
    current_appimage = tmp_path / "Bitcoin-Safe.AppImage"
    current_appimage.write_text("old-binary")
    current_appimage.chmod(0o755)
    new_appimage = tmp_path / "Bitcoin-Safe-1.8.0-x86_64.AppImage"
    new_appimage.write_text("new-binary")
    new_appimage.chmod(0o755)

    replacer = UpdateApplier(
        system="Linux",
        current_binary=current_appimage,
        env={"APPIMAGE": str(current_appimage)},
    )
    result = replacer.apply(new_appimage)

    assert result.was_applied
    assert result.action == UpdateApplierAction.restart
    assert result.launch_command == [str(new_appimage)]
    assert not current_appimage.exists()
    assert new_appimage.read_text() == "new-binary"


def test_linux_appimage_keeps_new_filename_and_deletes_old_binary(tmp_path: Path) -> None:
    app_dir = tmp_path / "appdir"
    downloads_dir = tmp_path / "downloads"
    app_dir.mkdir()
    downloads_dir.mkdir()

    current_appimage = app_dir / "Bitcoin-Safe-1.7.1-x86_64.AppImage"
    current_appimage.write_text("old-binary")
    current_appimage.chmod(0o755)

    downloaded_appimage = downloads_dir / "Bitcoin-Safe-1.8.0-x86_64.AppImage"
    downloaded_appimage.write_text("new-binary")
    downloaded_appimage.chmod(0o755)

    replacer = UpdateApplier(
        system="Linux",
        current_binary=current_appimage,
        env={"APPIMAGE": str(current_appimage)},
    )
    result = replacer.apply(downloaded_appimage)

    expected_installed_binary = app_dir / downloaded_appimage.name
    assert result.was_applied
    assert result.action == UpdateApplierAction.restart
    assert result.launch_command == [str(expected_installed_binary)]
    assert expected_installed_binary.exists()
    assert expected_installed_binary.read_text() == "new-binary"
    assert not current_appimage.exists()


def test_linux_deb_requires_admin_rights(tmp_path: Path) -> None:
    deb_file = tmp_path / "Bitcoin-Safe-1.8.0-amd64.deb"
    deb_file.write_text("deb")
    replacer = ApplierDouble(system="Linux", launch_result=True, admin_result=False)
    result = replacer.apply(deb_file)

    assert not result.was_applied
    assert result.action == UpdateApplierAction.none
    assert not replacer.started_commands


def test_windows_setup_exe_starts_installer(tmp_path: Path) -> None:
    setup_exe = tmp_path / "Bitcoin-Safe-1.8.0-setup.exe"
    setup_exe.write_text("setup")
    replacer = ApplierDouble(system="Windows", launch_result=True, uac_result=False)
    result = replacer.apply(setup_exe)

    assert result.was_applied
    assert result.action == UpdateApplierAction.close
    assert replacer.started_commands == [[str(setup_exe)]]


def test_windows_setup_exe_can_apply_from_portable_runtime(tmp_path: Path) -> None:
    setup_exe = tmp_path / "Bitcoin-Safe-1.8.0-setup.exe"
    setup_exe.write_text("setup")
    current_portable = tmp_path / "Bitcoin-Safe-1.7.1-portable.exe"
    current_portable.write_text("current")
    replacer = ApplierDouble(
        system="Windows",
        current_binary=current_portable,
        launch_result=True,
        uac_result=False,
    )

    assert replacer.can_apply(setup_exe)
    result = replacer.apply(setup_exe)
    assert result.was_applied
    assert result.action == UpdateApplierAction.close


def test_windows_setup_exe_prefers_uac_launcher(tmp_path: Path) -> None:
    setup_exe = tmp_path / "Bitcoin-Safe-1.8.0-setup.exe"
    setup_exe.write_text("setup")
    replacer = ApplierDouble(
        system="Windows",
        launch_result=True,
        uac_result=True,
    )
    result = replacer.apply(setup_exe)

    assert result.was_applied
    assert result.action == UpdateApplierAction.close
    assert replacer.elevated_calls == [setup_exe]
    assert replacer.started_commands == []


def test_windows_portable_exe_is_prepared_for_restart(tmp_path: Path) -> None:
    app_dir = tmp_path / "appdir"
    downloads_dir = tmp_path / "downloads"
    app_dir.mkdir()
    downloads_dir.mkdir()

    current_exe = app_dir / "Bitcoin-Safe-1.7.1-portable.exe"
    current_exe.write_text("old-portable")
    portable_exe = downloads_dir / "Bitcoin-Safe-1.8.0-portable.exe"
    portable_exe.write_text("portable")
    replacer = UpdateApplier(system="Windows", current_binary=current_exe)

    result = replacer.apply(portable_exe)

    expected_target = app_dir / portable_exe.name
    assert result.was_applied
    assert result.action == UpdateApplierAction.restart
    assert result.launch_command == [str(expected_target)]
    assert expected_target.exists()
    assert expected_target.read_text() == "portable"


def test_windows_portable_exe_uses_stable_runtime_path_in_pyinstaller_onefile(tmp_path: Path) -> None:
    app_dir = tmp_path / "appdir"
    downloads_dir = tmp_path / "downloads"
    meipass_dir = tmp_path / "_MEI12345"
    app_dir.mkdir()
    downloads_dir.mkdir()
    meipass_dir.mkdir()

    portable_runtime = app_dir / "Bitcoin-Safe-1.7.1-portable.exe"
    portable_runtime.write_text("old-portable")
    bootloader_exe = meipass_dir / "Bitcoin-Safe.exe"
    bootloader_exe.write_text("bootloader")
    downloaded_portable = downloads_dir / "Bitcoin-Safe-1.8.0-portable.exe"
    downloaded_portable.write_text("portable")

    replacer = UpdateApplier(
        system="Windows",
        current_binary=bootloader_exe,
        env={"_MEIPASS": str(meipass_dir)},
        runtime_entrypoint=portable_runtime,
    )

    assert replacer.can_apply(downloaded_portable)
    result = replacer.apply(downloaded_portable)

    expected_target = app_dir / downloaded_portable.name
    assert result.was_applied
    assert result.action == UpdateApplierAction.restart
    assert result.launch_command == [str(expected_target)]
    assert expected_target.exists()
    assert expected_target.read_text() == "portable"


def test_unsupported_format_returns_no_action(tmp_path: Path) -> None:
    archive = tmp_path / "Bitcoin-Safe-1.8.0.zip"
    archive.write_text("zip")
    replacer = UpdateApplier(system="Linux")

    result = replacer.apply(archive)

    assert not result.was_applied
    assert result.action == UpdateApplierAction.none


def test_can_apply_depends_on_platform_and_format(tmp_path: Path) -> None:
    appimage = tmp_path / "Bitcoin-Safe-1.8.0-x86_64.AppImage"
    appimage.write_text("appimage")
    appimage.chmod(0o755)
    setup_exe = tmp_path / "Bitcoin-Safe-1.8.0-setup.exe"
    setup_exe.write_text("setup")
    current_appimage = tmp_path / "Bitcoin-Safe-current.AppImage"
    current_appimage.write_text("current")
    current_appimage.chmod(0o755)

    linux_applier = UpdateApplier(
        system="Linux",
        current_binary=current_appimage,
        env={"APPIMAGE": str(current_appimage)},
    )
    windows_applier = UpdateApplier(system="Windows")

    assert linux_applier.can_apply(appimage)
    assert not linux_applier.can_apply(setup_exe)
    assert windows_applier.can_apply(setup_exe)
    assert not windows_applier.can_apply(appimage)


def test_can_apply_linux_appimage_is_false_when_current_binary_is_not_appimage(tmp_path: Path) -> None:
    current_binary = tmp_path / "bitcoin-safe"
    current_binary.write_text("current")
    appimage = tmp_path / "Bitcoin-Safe-1.8.0-x86_64.AppImage"
    appimage.write_text("appimage")
    appimage.chmod(0o755)
    applier = UpdateApplier(
        system="Linux",
        current_binary=current_binary,
        env={"APPIMAGE": str(appimage)},
    )

    assert not applier.can_apply(appimage)
    result = applier.apply(appimage)
    assert not result.was_applied
    assert result.action == UpdateApplierAction.none


def test_can_apply_windows_portable_is_false_when_current_binary_is_non_portable_exe(
    tmp_path: Path,
) -> None:
    current_exe = tmp_path / "Bitcoin-Safe.exe"
    current_exe.write_text("current")
    portable_exe = tmp_path / "Bitcoin-Safe-1.8.0-portable.exe"
    portable_exe.write_text("portable")
    applier = UpdateApplier(system="Windows", current_binary=current_exe)

    assert not applier.can_apply(portable_exe)
    result = applier.apply(portable_exe)
    assert not result.was_applied
    assert result.action == UpdateApplierAction.none


def test_can_apply_linux_deb_is_false_for_system_install(tmp_path: Path) -> None:
    deb_file = tmp_path / "Bitcoin-Safe-1.8.0-amd64.deb"
    deb_file.write_text("deb")
    applier = UpdateApplier(
        system="Linux",
        current_binary=Path("/usr/bin/bitcoin-safe"),
    )

    assert not applier.can_apply(deb_file)


def test_can_apply_linux_deb_depends_on_admin_and_dpkg_not_current_binary_path(tmp_path: Path) -> None:
    deb_file = tmp_path / "Bitcoin-Safe-1.8.0-amd64.deb"
    deb_file.write_text("deb")
    applier = ApplierDouble(
        system="Linux",
        current_binary=Path("/usr/bin/bitcoin-safe"),
        admin_result=True,
        command_exists={"dpkg": True},
    )
    original_handler = applier._handlers["Linux"][UpdateArtifactFormat.deb]
    applier._handlers["Linux"][UpdateArtifactFormat.deb] = UpdateHandler(
        apply=original_handler.apply,
        can_apply=original_handler.can_apply,
        dialog_texts=original_handler.dialog_texts,
        enabled=True,
    )

    assert applier.can_apply(deb_file)


def test_can_apply_linux_deb_is_false_when_handler_disabled(tmp_path: Path) -> None:
    deb_file = tmp_path / "Bitcoin-Safe-1.8.0-amd64.deb"
    deb_file.write_text("deb")
    applier = UpdateApplier(
        system="Linux",
        current_binary=tmp_path / "bitcoin-safe",
    )

    assert not applier.can_apply(deb_file)
    result = applier.apply(deb_file)
    assert not result.was_applied
    assert result.action == UpdateApplierAction.none


def test_update_handler_enabled_flag_overrides_capability(tmp_path: Path) -> None:
    appimage = tmp_path / "Bitcoin-Safe-1.8.0-x86_64.AppImage"
    appimage.write_text("appimage")
    appimage.chmod(0o755)
    current_appimage = tmp_path / "Bitcoin-Safe-current.AppImage"
    current_appimage.write_text("current")
    current_appimage.chmod(0o755)

    applier = UpdateApplier(
        system="Linux",
        current_binary=current_appimage,
        env={"APPIMAGE": str(current_appimage)},
    )
    original_handler = applier._handlers["Linux"][UpdateArtifactFormat.appimage]
    applier._handlers["Linux"][UpdateArtifactFormat.appimage] = UpdateHandler(
        apply=original_handler.apply,
        can_apply=original_handler.can_apply,
        dialog_texts=original_handler.dialog_texts,
        enabled=False,
    )

    assert not applier.can_apply(appimage)
    result = applier.apply(appimage)
    assert not result.was_applied
    assert result.action == UpdateApplierAction.none


def test_can_apply_windows_msi_is_false_when_handler_disabled(tmp_path: Path) -> None:
    msi_file = tmp_path / "Bitcoin-Safe-1.8.0-installer.msi"
    msi_file.write_text("msi")
    applier = UpdateApplier(system="Windows")

    assert not applier.can_apply(msi_file)
    result = applier.apply(msi_file)
    assert not result.was_applied
    assert result.action == UpdateApplierAction.none


def test_can_apply_macos_pkg_is_false_when_handler_disabled(tmp_path: Path) -> None:
    pkg_file = tmp_path / "Bitcoin-Safe-1.8.0-installer.pkg"
    pkg_file.write_text("pkg")
    applier = UpdateApplier(system="Darwin")

    assert not applier.can_apply(pkg_file)
    result = applier.apply(pkg_file)
    assert not result.was_applied
    assert result.action == UpdateApplierAction.none


def test_dialog_texts_open_update_for_macos_dmg(tmp_path: Path) -> None:
    dmg_file = tmp_path / "Bitcoin-Safe-1.8.0-arm64.dmg"
    dmg_file.write_text("dmg")
    applier = UpdateApplier(system="Darwin")
    texts = applier.get_apply_dialog_texts(dmg_file)

    assert texts.title == "Open update"
    assert texts.true_button == "Open update"

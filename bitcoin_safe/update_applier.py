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

import enum
import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from bitcoin_safe.i18n import translate
from bitcoin_safe.pyqt6_restart import resolve_windows_runtime_executable

logger = logging.getLogger(__name__)


class UpdateApplierAction(enum.Enum):
    restart = "restart"
    close = "close"
    none = "none"


@dataclass(frozen=True)
class UpdateApplyDialogTexts:
    title: str
    text: str
    true_button: str
    false_button: str


@dataclass(frozen=True)
class UpdateApplierResult:
    was_applied: bool
    action: UpdateApplierAction
    message: str
    launch_command: list[str] | None = None


@dataclass(frozen=True)
class UpdateHandler:
    apply: Callable[[Path], UpdateApplierResult]
    can_apply: Callable[[Path], bool]
    dialog_texts: Callable[[], UpdateApplyDialogTexts]
    enabled: bool = True


class UpdateArtifactFormat(enum.Enum):
    appimage = "appimage"
    deb = "deb"
    dmg = "dmg"
    pkg = "pkg"
    msi = "msi"
    exe_setup = "exe_setup"
    exe_portable = "exe_portable"
    unknown = "unknown"


class UpdateApplier:
    """Install or replace a verified update artifact based on platform and format."""

    def __init__(
        self,
        system: str | None = None,
        current_binary: Path | None = None,
        env: Mapping[str, str] | None = None,
        runtime_entrypoint: Path | None = None,
    ) -> None:
        self.system = system or platform.system()
        self.current_binary = (current_binary or Path(sys.executable)).resolve(strict=False)
        self.env = dict(env) if env is not None else dict(os.environ)
        self.runtime_entrypoint = (runtime_entrypoint or Path(sys.argv[0])).resolve(strict=False)
        self._handlers: dict[str, dict[UpdateArtifactFormat, UpdateHandler]] = {
            "Linux": {
                UpdateArtifactFormat.appimage: UpdateHandler(
                    apply=self._replace_linux_appimage,
                    can_apply=self._can_apply_linux_appimage,
                    dialog_texts=self._dialog_texts_for_apply_update,
                ),
                UpdateArtifactFormat.deb: UpdateHandler(
                    apply=self._install_linux_deb,
                    can_apply=self._can_apply_linux_deb,
                    dialog_texts=self._dialog_texts_for_start_installer,
                    enabled=False,
                ),
            },
            "Darwin": {
                UpdateArtifactFormat.dmg: UpdateHandler(
                    apply=self._open_macos_installer,
                    can_apply=self._can_apply_macos_dmg,
                    dialog_texts=self._dialog_texts_for_open_update,
                ),
                UpdateArtifactFormat.pkg: UpdateHandler(
                    apply=self._install_or_open_macos_pkg,
                    can_apply=self._can_apply_macos_pkg,
                    dialog_texts=self._dialog_texts_for_start_installer,
                    enabled=False,
                ),
            },
            "Windows": {
                UpdateArtifactFormat.exe_setup: UpdateHandler(
                    apply=self._start_windows_setup_exe,
                    can_apply=self._can_apply_windows_setup_exe,
                    dialog_texts=self._dialog_texts_for_start_installer,
                ),
                UpdateArtifactFormat.exe_portable: UpdateHandler(
                    apply=self._replace_windows_portable_exe,
                    can_apply=self._can_apply_windows_portable_exe,
                    dialog_texts=self._dialog_texts_for_apply_update,
                ),
                UpdateArtifactFormat.msi: UpdateHandler(
                    apply=self._start_windows_msi,
                    can_apply=self._can_apply_windows_msi,
                    dialog_texts=self._dialog_texts_for_start_installer,
                    enabled=False,
                ),
            },
        }

    def apply(self, artifact_path: Path) -> UpdateApplierResult:
        artifact = artifact_path.resolve(strict=False)
        if not artifact.exists():
            logger.debug("Apply denied: artifact does not exist: %s", artifact)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message=f"Update artifact not found: {artifact}",
            )

        binary_format = self.detect_format(artifact)
        update_handler = self._handlers.get(self.system, {}).get(binary_format)
        if update_handler is None:
            logger.debug("Apply denied: no handler for system=%s format=%s", self.system, binary_format.value)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message=f"No replacement strategy for {self.system} / {binary_format.value}.",
            )
        if not update_handler.enabled:
            logger.debug(
                "Apply denied: handler disabled for system=%s format=%s",
                self.system,
                binary_format.value,
            )
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message=f"Update handling disabled for {self.system} / {binary_format.value}.",
            )

        try:
            return update_handler.apply(artifact)
        except OSError as exc:
            logger.exception("Failed to process update artifact %s", artifact)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message=f"Failed to process update artifact: {exc}",
            )

    def can_apply(self, artifact_path: Path) -> bool:
        artifact = artifact_path.resolve(strict=False)
        if not artifact.exists():
            logger.debug("Can-apply denied: artifact does not exist: %s", artifact)
            return False
        binary_format = self.detect_format(artifact)
        update_handler = self._handlers.get(self.system, {}).get(binary_format)
        if update_handler is None:
            logger.debug(
                "Can-apply denied: no handler for system=%s format=%s", self.system, binary_format.value
            )
            return False
        if not update_handler.enabled:
            logger.debug(
                "Can-apply denied: handler disabled for system=%s format=%s",
                self.system,
                binary_format.value,
            )
            return False
        can_apply = update_handler.can_apply(artifact)
        logger.debug(
            "Can-apply evaluated: system=%s format=%s result=%s",
            self.system,
            binary_format.value,
            can_apply,
        )
        return can_apply

    def get_apply_dialog_texts(self, artifact_path: Path) -> UpdateApplyDialogTexts:
        artifact = artifact_path.resolve(strict=False)
        binary_format = self.detect_format(artifact)
        update_handler = self._handlers.get(self.system, {}).get(binary_format)
        if update_handler is None:
            return self._dialog_texts_for_apply_update()
        return update_handler.dialog_texts()

    @staticmethod
    def _dialog_texts_for_apply_update() -> UpdateApplyDialogTexts:
        return UpdateApplyDialogTexts(
            title=translate("updater", "Apply update"),
            text=translate("updater", "Update verified. Do you want to apply the update now?"),
            true_button=translate("updater", "Apply update"),
            false_button=translate("updater", "Open download folder"),
        )

    @staticmethod
    def _dialog_texts_for_start_installer() -> UpdateApplyDialogTexts:
        return UpdateApplyDialogTexts(
            title=translate("updater", "Start installer"),
            text=translate("updater", "Update verified. Do you want to start the installer now?"),
            true_button=translate("updater", "Start installer"),
            false_button=translate("updater", "Open download folder"),
        )

    @staticmethod
    def _dialog_texts_for_open_update() -> UpdateApplyDialogTexts:
        return UpdateApplyDialogTexts(
            title=translate("updater", "Open update"),
            text=translate("updater", "Update verified. Do you want to open the update file now?"),
            true_button=translate("updater", "Open update"),
            false_button=translate("updater", "Open download folder"),
        )

    @staticmethod
    def detect_format(artifact_path: Path) -> UpdateArtifactFormat:
        lower_name = artifact_path.name.lower()
        if lower_name.endswith(".appimage"):
            return UpdateArtifactFormat.appimage
        if lower_name.endswith(".deb"):
            return UpdateArtifactFormat.deb
        if lower_name.endswith(".dmg"):
            return UpdateArtifactFormat.dmg
        if lower_name.endswith(".pkg"):
            return UpdateArtifactFormat.pkg
        if lower_name.endswith(".msi"):
            return UpdateArtifactFormat.msi
        if lower_name.endswith(".exe"):
            if "setup" in lower_name or "install" in lower_name:
                return UpdateArtifactFormat.exe_setup
            if "portable" in lower_name:
                return UpdateArtifactFormat.exe_portable
            return UpdateArtifactFormat.exe_portable
        return UpdateArtifactFormat.unknown

    def _replace_linux_appimage(self, artifact: Path) -> UpdateApplierResult:
        # Replace-style update: only valid when the current runtime is itself an AppImage.
        current_binary = self._current_binary_path()
        if current_binary is None:
            logger.debug("Linux AppImage replace denied: current binary path cannot be resolved.")
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message=f"Current binary not found: {self.current_binary}",
            )
        current_binary_format = self.detect_format(current_binary)
        if current_binary_format != UpdateArtifactFormat.appimage:
            logger.debug(
                "Linux AppImage replace denied: current binary format is %s.",
                current_binary_format.value,
            )
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message="Current runtime is not an AppImage; skipping in-place replacement.",
            )
        current_appimage = current_binary

        if not os.access(current_appimage.parent, os.W_OK):
            logger.debug("Linux AppImage replace denied: missing write access to %s", current_appimage.parent)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message=f"Missing write permission for {current_appimage.parent}",
            )

        target_appimage = current_appimage.parent / artifact.name
        if target_appimage.resolve(strict=False) != artifact.resolve(strict=False):
            staging_path = current_appimage.parent / f".{artifact.name}.new"
            shutil.copy2(artifact, staging_path)
            mode = staging_path.stat().st_mode
            staging_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            os.replace(staging_path, target_appimage)
        else:
            mode = target_appimage.stat().st_mode
            target_appimage.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        if current_appimage.resolve(strict=False) != target_appimage.resolve(strict=False):
            try:
                if current_appimage.exists() and current_appimage.is_file():
                    current_appimage.unlink()
            except OSError:
                logger.debug("Could not remove previous AppImage %s", current_appimage)

        return UpdateApplierResult(
            was_applied=True,
            action=UpdateApplierAction.restart,
            message=f"Installed AppImage {target_appimage.name}.",
            launch_command=[str(target_appimage)],
        )

    def _install_linux_deb(self, artifact: Path) -> UpdateApplierResult:
        # Installer-style update: we only allow this when already elevated.
        if not self._default_admin_checker():
            logger.debug("Linux .deb install denied: process is not running with admin rights.")
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message="Installing a .deb requires administrative rights. No installer was started.",
            )

        if not self._launch_detached(["dpkg", "-i", str(artifact)]):
            logger.debug("Linux .deb install denied: failed to start dpkg for %s", artifact)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message="Could not start dpkg installer.",
            )

        logger.debug("Linux .deb install started for %s", artifact)
        return UpdateApplierResult(
            was_applied=True,
            action=UpdateApplierAction.close,
            message="Started .deb installation.",
        )

    def _open_macos_installer(self, artifact: Path) -> UpdateApplierResult:
        # Open-style update: just open the verified artifact for the user.
        if not self._launch_detached(["open", str(artifact)]):
            logger.debug("macOS open denied: failed to open %s", artifact)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message="Could not open macOS installer.",
            )
        logger.debug("macOS open started for %s", artifact)
        return UpdateApplierResult(
            was_applied=True,
            action=UpdateApplierAction.close,
            message="Opened macOS installer.",
        )

    def _install_or_open_macos_pkg(self, artifact: Path) -> UpdateApplierResult:
        # If elevated we can install directly, otherwise we can still open the package.
        if self._default_admin_checker() and self._launch_detached(
            ["installer", "-pkg", str(artifact), "-target", "/"]
        ):
            logger.debug("macOS .pkg installer started for %s", artifact)
            return UpdateApplierResult(
                was_applied=True,
                action=UpdateApplierAction.close,
                message="Started macOS package installation.",
            )
        logger.debug("macOS .pkg falling back to open for %s", artifact)
        return self._open_macos_installer(artifact)

    def _start_windows_setup_exe(self, artifact: Path) -> UpdateApplierResult:
        # Setup executables are installer-style: valid from any current install format.
        if self.system == "Windows" and self._launch_windows_setup_with_uac_prompt(artifact):
            logger.debug("Windows setup started via UAC prompt for %s", artifact)
            return UpdateApplierResult(
                was_applied=True,
                action=UpdateApplierAction.close,
                message="Started installer executable.",
            )
        if not self._launch_detached([str(artifact)]):
            logger.debug("Windows setup denied: failed to start executable %s", artifact)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message="Could not start installer executable.",
            )
        logger.debug("Windows setup started directly for %s", artifact)
        return UpdateApplierResult(
            was_applied=True,
            action=UpdateApplierAction.close,
            message="Started installer executable.",
        )

    def _start_windows_msi(self, artifact: Path) -> UpdateApplierResult:
        if not self._launch_detached(["msiexec", "/i", str(artifact)]):
            logger.debug("Windows MSI denied: failed to start msiexec for %s", artifact)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message="Could not start MSI installer.",
            )
        logger.debug("Windows MSI installer started for %s", artifact)
        return UpdateApplierResult(
            was_applied=True,
            action=UpdateApplierAction.close,
            message="Started MSI installer.",
        )

    def _replace_windows_portable_exe(self, artifact: Path) -> UpdateApplierResult:
        # Replace-style portable update: allowed only when the current runtime is portable.
        current_format = self._current_binary_format()
        if current_format != UpdateArtifactFormat.exe_portable:
            logger.debug(
                "Windows portable replace denied: current binary format is %s",
                current_format.value if current_format else "unknown",
            )
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message="Current runtime is not a portable executable; skipping replacement.",
            )

        target_directory = self._get_windows_target_directory(artifact)
        if not target_directory.exists():
            logger.debug("Windows portable replace denied: target directory missing: %s", target_directory)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message=f"Target directory does not exist: {target_directory}",
            )

        if not os.access(target_directory, os.W_OK):
            logger.debug("Windows portable replace denied: missing write access to %s", target_directory)
            return UpdateApplierResult(
                was_applied=False,
                action=UpdateApplierAction.none,
                message=f"Missing write permission for {target_directory}",
            )

        target_exe = target_directory / artifact.name
        if target_exe.resolve(strict=False) != artifact.resolve(strict=False):
            staging_path = target_directory / f".{artifact.name}.new"
            shutil.copy2(artifact, staging_path)
            os.replace(staging_path, target_exe)

        return UpdateApplierResult(
            was_applied=True,
            action=UpdateApplierAction.restart,
            message=f"Prepared portable executable {target_exe.name} for restart.",
            launch_command=[str(target_exe)],
        )

    def _get_windows_target_directory(self, artifact: Path) -> Path:
        current_binary = self._current_runtime_binary_path()
        if current_binary and current_binary.suffix.lower() == ".exe":
            return current_binary.parent
        return artifact.parent

    def _can_apply_linux_appimage(self, _artifact: Path) -> bool:
        # Replace-style: require AppImage runtime and writable install directory.
        current_binary = self._current_binary_path()
        if current_binary is None:
            logger.debug("Can-apply Linux AppImage denied: current binary path cannot be resolved.")
            return False
        if self.detect_format(current_binary) != UpdateArtifactFormat.appimage:
            logger.debug(
                "Can-apply Linux AppImage denied: current format is %s",
                self.detect_format(current_binary).value,
            )
            return False
        can_write = os.access(current_binary.parent, os.W_OK)
        if not can_write:
            logger.debug("Can-apply Linux AppImage denied: missing write access to %s", current_binary.parent)
        return can_write

    def _can_apply_linux_deb(self, _artifact: Path) -> bool:
        # Installer-style: independent from current binary location; needs elevation + dpkg.
        if not self._default_admin_checker():
            logger.debug("Can-apply Linux .deb denied: process is not elevated.")
            return False
        has_dpkg = self._command_exists("dpkg")
        if not has_dpkg:
            logger.debug("Can-apply Linux .deb denied: dpkg command not found.")
        return has_dpkg

    def _can_apply_macos_dmg(self, _artifact: Path) -> bool:
        has_open = self._command_exists("open")
        if not has_open:
            logger.debug("Can-apply macOS .dmg denied: open command not found.")
        return has_open

    def _can_apply_macos_pkg(self, _artifact: Path) -> bool:
        # If elevated we can install directly; otherwise we still allow opening the package.
        if self._default_admin_checker() and self._command_exists("installer"):
            logger.debug("Can-apply macOS .pkg allowed: elevated and installer command exists.")
            return True
        has_open = self._command_exists("open")
        if not has_open:
            logger.debug("Can-apply macOS .pkg denied: neither installer nor open is available.")
        return has_open

    def _can_apply_windows_setup_exe(self, _artifact: Path) -> bool:
        # Installer-style: setup executables can be started from portable and installed variants.
        logger.debug("Can-apply Windows setup allowed: installer startup is independent of current format.")
        return True

    def _can_apply_windows_portable_exe(self, artifact: Path) -> bool:
        # Replace-style: do not overwrite installed setups with portable binaries.
        current_format = self._current_binary_format()
        if current_format != UpdateArtifactFormat.exe_portable:
            logger.debug(
                "Can-apply Windows portable denied: current format is %s",
                current_format.value if current_format else "unknown",
            )
            return False
        target_directory = self._get_windows_target_directory(artifact)
        can_apply = target_directory.exists() and os.access(target_directory, os.W_OK)
        if can_apply and self._is_windows_protected_target_directory(target_directory):
            logger.debug(
                "Can-apply Windows portable denied: protected system directory: %s",
                target_directory,
            )
            return False
        if not can_apply:
            logger.debug(
                "Can-apply Windows portable denied: target directory invalid or not writable: %s",
                target_directory,
            )
        return can_apply

    def _is_windows_protected_target_directory(self, target_directory: Path) -> bool:
        path = PureWindowsPath(str(target_directory).replace("/", "\\"))
        if path.drive.upper() != "C:":
            return False
        relative_parts = tuple(part.casefold() for part in path.parts[1:])
        protected_roots = (
            ("program files",),
            ("program files (x86)",),
            ("programdata",),
            ("windows",),
        )
        return any(relative_parts[: len(root)] == root for root in protected_roots)

    def _can_apply_windows_msi(self, _artifact: Path) -> bool:
        has_msiexec = self._command_exists("msiexec")
        if not has_msiexec:
            logger.debug("Can-apply Windows MSI denied: msiexec command not found.")
        return has_msiexec

    def _command_exists(self, command: str) -> bool:
        return shutil.which(command) is not None

    def _current_binary_path(self) -> Path | None:
        current_binary = self.current_binary.resolve(strict=False)
        if current_binary.exists():
            # AppImage processes often run from a mounted runtime path while APPIMAGE points to the file to replace.
            if self._is_running_from_appimage_mount(current_binary):
                if appimage_path := self.env.get("APPIMAGE"):
                    appimage_binary = Path(appimage_path).resolve(strict=False)
                    if appimage_binary.exists():
                        return appimage_binary
            return current_binary
        if appimage_path := self.env.get("APPIMAGE"):
            appimage_binary = Path(appimage_path).resolve(strict=False)
            if appimage_binary.exists():
                return appimage_binary
        return None

    def _current_binary_format(self) -> UpdateArtifactFormat | None:
        current_binary = self._current_runtime_binary_path()
        if current_binary is None:
            return None
        return self.detect_format(current_binary)

    def _current_runtime_binary_path(self) -> Path | None:
        current_binary = self._current_binary_path()
        if current_binary is None or self.system != "Windows":
            return current_binary
        return resolve_windows_runtime_executable(
            current_binary=current_binary,
            runtime_entrypoint=self.runtime_entrypoint,
            env=self.env,
            os_name="nt",
        )

    @staticmethod
    def _is_running_from_appimage_mount(binary_path: Path) -> bool:
        return any(part.startswith(".mount_") for part in binary_path.parts)

    @staticmethod
    def _launch_detached(cmd: list[str]) -> bool:
        executable = cmd[0]
        if not os.path.isabs(executable) and shutil.which(executable) is None:
            return False
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            return False

    def _default_admin_checker(self) -> bool:
        if self.system == "Windows":
            try:
                import ctypes

                ctypes_module: Any = ctypes
                return bool(ctypes_module.windll.shell32.IsUserAnAdmin())
            except Exception:
                return False
        if hasattr(os, "geteuid"):
            return os.geteuid() == 0
        return False

    def _launch_windows_setup_with_uac_prompt(self, executable: Path) -> bool:
        if self.system != "Windows":
            return False
        try:
            import ctypes

            ctypes_module: Any = ctypes
            result = ctypes_module.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(executable),
                None,
                None,
                1,
            )
            return int(result) > 32
        except Exception:
            return False

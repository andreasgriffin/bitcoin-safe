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

import argparse
import hashlib
import logging
import os
import platform
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from appimage_to_deb_converter import Appimage2debConverter
from translation_handler import TranslationHandler, run_local

from bitcoin_safe import __version__
from bitcoin_safe.execute_config import ENABLE_THREADING, ENABLE_TIMERS, IS_PRODUCTION
from bitcoin_safe.signature_manager import (
    KnownGPGKeys,
    SignatureSigner,
    SignatureVerifyer,
)
from tools.release import get_git_tag

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


assert IS_PRODUCTION
assert ENABLE_THREADING
assert ENABLE_TIMERS

TARGET_LITERAL = Literal["windows", "mac", "appimage", "deb", "flatpak"]


def calc_hashes_of_files(folder: Path) -> dict[Path, str]:
    """Calculates SHA-256 hashes for all files in a specified directory and returns a
    dictionary where the keys are the file paths and the values are the SHA-256 hashes.

    :param folder: Path object representing the directory to scan
    :return: Dictionary mapping file paths to their hashes
    """
    hashes = {}
    for file_path in folder.glob("*"):
        if file_path.is_file():  # Ensure it's a file
            # Open the file in binary read mode
            with open(file_path, "rb") as file:
                file_data = file.read()
                # Calculate SHA-256 hash
                hash_sha256 = hashlib.sha256(file_data).hexdigest()
                hashes[file_path] = hash_sha256
    return hashes


class Builder:
    build_dir = "build"

    def __init__(self, module_name, clean_all=False):
        """Initialize instance."""
        self.module_name = module_name
        self.version = __version__ if __version__ else "unknown-version"
        if __version__ != get_git_tag():
            # i still proceed with this, since I need to test the builds,
            # before the git tag is set
            logger.error(f"__version__ {__version__} != git tag {get_git_tag()}")

        self.app_name = (
            f"{self.app_name_formatter(module_name)}_{self.version}" if self.version else "unknown-version"
        )

        if clean_all:
            if os.path.exists(self.build_dir):
                shutil.rmtree(self.build_dir, ignore_errors=True)
                print(f"The directory {self.build_dir} has been removed successfully.")
        Path(self.build_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_target_arch():
        """Get target arch."""
        arch = platform.machine()
        if arch == "x86_64":
            return "x86_64"
        elif arch in ("arm", "arm64", "aarch64"):
            return "arm64"
        else:
            return "universal2"  # Defaulting to universal for other cases (as a fallback)

    @staticmethod
    def app_name_formatter(module_name: str, join_character="-") -> str:
        """App name formatter."""
        parts = [s.capitalize() for s in module_name.split("_")]

        return join_character.join(parts)

    @staticmethod
    def list_files(directory: str, extension: str) -> list[Path]:
        """List all files in the given directory with the specified extension.

        Args:
            directory (str): The directory to search.
            extension (str): The file extension to filter by (e.g., '.txt', '.py').

        Returns:
            List[Path]: A list of Path objects for files matching the extension.
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise ValueError(f"{directory} is not a valid directory.")
        return list(dir_path.glob(f"*{extension}"))

    @staticmethod
    def stop_existing_container(container_name: str) -> None:
        """Stop and remove a leftover docker container if it exists."""
        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--format",
                    "{{.ID}}",
                    "--filter",
                    f"name=^{container_name}$",
                ],
                stdout=subprocess.PIPE,
                check=True,
                text=True,
            )
        except FileNotFoundError:
            logger.warning("Docker command not found. Skipping container cleanup.")
            return
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to check for existing docker containers: %s", exc)
            return

        container_ids = [c for c in result.stdout.splitlines() if c]
        for container_id in container_ids:
            logger.info("Stopping leftover container '%s' (%s)", container_name, container_id)
            try:
                run_local(f"docker container stop {container_id}")
                run_local(f"docker container rm {container_id}")
            except subprocess.CalledProcessError:
                logger.warning("Failed to stop container '%s'. Attempting to force remove.", container_id)
                try:
                    run_local(f"docker container rm -f {container_id}")
                except subprocess.CalledProcessError as remove_error:
                    raise RuntimeError(
                        f"Unable to stop or remove existing container '{container_name}' ({container_id})."
                    ) from remove_error

    def appimage2deb(self, **kwargs):
        """Appimage2deb."""
        for filename in self.list_files("dist/", extension=".AppImage"):
            converter = Appimage2debConverter(
                appimage=filename,
                output_deb=filename.with_suffix(".deb"),
                package_name=self.app_name_formatter(self.module_name).lower(),
                version=self.version,
                maintainer="Andreas Griffin <andreasgriffin@proton.me>",
                description="A bitcoin savings wallet for the entire family.",
                homepage="https://www.bitcoin-safe.org",
                desktop_name=self.app_name_formatter(self.module_name, join_character=" "),
                desktop_icon_name=self.app_name_formatter(self.module_name).lower() + ".svg",
                desktop_categories="Utility",
            )
            converter.convert()

    def build_appimage_docker(
        self, no_cache=False, build_commit: None | str | Literal["current_commit"] = "current_commit"
    ):
        """Build appimage docker."""
        self.build_in_docker(
            "bitcoin_safe-appimage-builder-img",
            Path("tools/build-linux/appimage"),
            no_cache=no_cache,
            build_commit=build_commit,
        )

    def build_windows_exe_and_installer_docker(
        self, no_cache=False, build_commit: None | str | Literal["current_commit"] = "current_commit"
    ):
        """Build windows exe and installer docker."""
        self.build_in_docker(
            "bitcoin_safe-wine-builder-img",
            Path("tools/build-wine"),
            no_cache=no_cache,
            build_commit=build_commit,
        )

    def build_in_docker(
        self,
        docker_image: str,
        build_folder: Path,
        no_cache=False,
        build_commit: None | str | Literal["current_commit"] = "current_commit",
    ):
        """_summary_

        Args:
            docker_image (str): Example: "bitcoin_safe-wine-builder-img"
            build_folder (Path): Example: Path("tools/build-wine"), or Path("tools/build-linux/appimage")
            no_cache (bool, optional): _description_. Defaults to False.
            build_commit (None | str | Literal['current_commit'], optional): _description_. Defaults to 'current_commit'.
                    'current_commit' = which means it will build the current HEAD.
                    None = uses the cwd
                    commit_hash = clones this commit hash into /tmp
        """

        PROJECT_ROOT = Path(".").resolve().absolute()
        PROJECT_ROOT_OR_FRESHCLONE_ROOT = PROJECT_ROOT
        path_build = PROJECT_ROOT / build_folder
        DISTDIR = PROJECT_ROOT / "dist"
        BUILD_UID = PROJECT_ROOT.stat().st_uid
        BUILD_CACHEDIR = path_build / ".cache"
        original_dir = os.getcwd()

        # Initialize DOCKER_BUILD_FLAGS
        DOCKER_BUILD_FLAGS = ""

        if no_cache:
            logger.info("BITCOINSAFE_DOCKER_NOCACHE is set. Forcing rebuild of docker image.")
            DOCKER_BUILD_FLAGS = "--pull --no-cache"
            logger.info(f"BITCOINSAFE_DOCKER_NOCACHE is set. Deleting {BUILD_CACHEDIR}")
            run_local(f'rm -rf "{BUILD_CACHEDIR}"')

        if build_commit == "current_commit":
            # Get the current git HEAD commit
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], stdout=subprocess.PIPE, check=True, text=True
            )
            build_commit = result.stdout.strip()

        if not build_commit:
            # Local development build
            DOCKER_BUILD_FLAGS += f" --build-arg UID={BUILD_UID}"
            logger.info("Building within current project")

        logger.info("Building docker image.")
        run_local(f'docker build {DOCKER_BUILD_FLAGS} -t {docker_image} "{path_build}"')

        # Possibly do a fresh clone
        cloned_path: Path | None = None
        if build_commit:
            logger.info(f"BITCOINSAFE_BUILD_COMMIT={build_commit}. Doing fresh clone and git checkout.")
            cloned_path = Path(f"/tmp/{docker_image.replace(' ', '')}/fresh_clone/bitcoin_safe")
            try:
                run_local(f'rm -rf "{cloned_path}"')
            except subprocess.CalledProcessError:
                logger.info("We need sudo to remove previous FRESH_CLONE.")
                run_local(f'sudo rm -rf "{cloned_path}"')
            os.umask(0o022)
            run_local(f'git clone "{PROJECT_ROOT}" "{cloned_path}"')
            os.chdir(str(cloned_path))
            run_local(f'git checkout "{build_commit}"')
            os.chdir(original_dir)
            PROJECT_ROOT_OR_FRESHCLONE_ROOT = cloned_path
        else:
            logger.info("Not doing fresh clone.")

        Source_Dist_dir = PROJECT_ROOT_OR_FRESHCLONE_ROOT / build_folder / "dist"

        logger.info("Building binary...")
        self.stop_existing_container(f"{docker_image}-container")
        run_local(
            f"docker run "
            f"--name {docker_image}-container "
            f'-v "{PROJECT_ROOT_OR_FRESHCLONE_ROOT}":/opt/wine64/drive_c/bitcoin_safe '
            f"--rm "
            f"--workdir /opt/wine64/drive_c/bitcoin_safe/{build_folder} "
            f"  -i   {docker_image} "
            f"./run_in_docker.sh"
        )

        # Ensure the resulting binary location is independent of fresh_clone
        if Source_Dist_dir != DISTDIR:
            os.makedirs(DISTDIR, exist_ok=True)
            for file in Source_Dist_dir.iterdir():
                if not file.is_file():
                    continue
                logger.info(f"Moving {file} --> {DISTDIR / file.name}")
                shutil.move(
                    file,
                    DISTDIR
                    / (file.name.replace(self.module_name, self.app_name_formatter(self.module_name))),
                )

    def build_dmg(
        self,
        build_commit: None | str | Literal["current_commit"] = "current_commit",
    ):
        """Build dmg."""
        PROJECT_ROOT_OR_FRESHCLONE_ROOT = PROJECT_ROOT = Path(".").resolve().absolute()
        DISTDIR = PROJECT_ROOT / "dist"

        if build_commit == "current_commit":
            # Get the current git HEAD commit
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], stdout=subprocess.PIPE, check=True, text=True
            )
            build_commit = result.stdout.strip()

        if not build_commit:
            # Local development build
            logger.info("Building within current project")

        # Possibly do a fresh clone
        cloned_path: Path | None = None
        if build_commit:
            logger.info(f"BITCOINSAFE_BUILD_COMMIT={build_commit}. Doing fresh clone and git checkout.")
            cloned_path = Path(f"/tmp/{build_commit.replace(' ', '')}/fresh_clone/bitcoin_safe")
            try:
                run_local(f'rm -rf "{cloned_path}"')
            except subprocess.CalledProcessError:
                logger.info("We need sudo to remove previous FRESH_CLONE.")
                run_local(f'sudo rm -rf "{cloned_path}"')
            os.umask(0o022)
            run_local(f'git clone "{PROJECT_ROOT}" "{cloned_path}"')
            os.chdir(str(cloned_path))
            run_local(f'git checkout "{build_commit}"')
            PROJECT_ROOT_OR_FRESHCLONE_ROOT = cloned_path
        else:
            logger.info("Not doing fresh clone.")

        Source_Dist_dir = PROJECT_ROOT_OR_FRESHCLONE_ROOT / "dist"

        os.chdir(str(PROJECT_ROOT_OR_FRESHCLONE_ROOT))
        run_local(f"bash {PROJECT_ROOT_OR_FRESHCLONE_ROOT / 'tools' / 'build-mac' / 'make_osx.sh'}")

        os.chdir(str(PROJECT_ROOT))

        # Ensure the resulting binary location is independent of fresh_clone
        os.makedirs(DISTDIR, exist_ok=True)
        for file in Source_Dist_dir.iterdir():
            if file.name.endswith(".dmg"):
                logger.info(f"Moving {file} --> {DISTDIR / file.name}")
                # Replace module name with formatted app name in the directory name
                new_name = file.name.replace(self.module_name, self.app_name_formatter(self.module_name))
                if new_name.endswith("-unsigned.dmg"):
                    new_name = new_name.replace("-unsigned.dmg", f"-{self.get_target_arch()}.dmg")
                # Perform the move
                shutil.move(str(file), str(DISTDIR / new_name))

    def package_application(
        self,
        targets: list[TARGET_LITERAL],
        build_commit: None | str | Literal["current_commit"] = None,
    ):
        """Package application."""
        f_map: dict[str, Callable[..., None]] = {
            "appimage": self.build_appimage_docker,
            "windows": self.build_windows_exe_and_installer_docker,
            "mac": self.build_dmg,
            "deb": self.appimage2deb,
            "snap": self.build_snap,
        }

        for target in targets:
            f_map[target](build_commit=build_commit)

        if "appimage" in targets:
            # must be done after all builds are finished
            self.package_appimage_tarball()

        # calc hashes
        hashes = calc_hashes_of_files(Path(".") / "dist")
        print("Resulting hashes:")
        for file, hash in hashes.items():
            print(f"{file.name}: {hash}")

        print(f"Packaging completed for version {self.version}.")

    def package_appimage_tarball(self):
        """Ensure AppImage binaries are executable and provide a tarball version."""

        dist_dir = Path("dist")
        if not dist_dir.exists():
            logger.info("No dist directory found. Skipping AppImage tarball packaging.")
            return

        for appimage_path in dist_dir.glob("*.AppImage"):
            logger.info(f"Ensuring executable flag for {appimage_path}")
            appimage_path.chmod(appimage_path.stat().st_mode | 0o111)

            tarball_path = appimage_path.with_suffix(appimage_path.suffix + ".tar.gz")
            logger.info(f"Creating tarball {tarball_path}")
            with tarfile.open(tarball_path, "w:gz") as tar:
                tar.add(appimage_path, arcname=appimage_path.name)

            logger.info(f"Removing original AppImage {appimage_path}")
            appimage_path.unlink()

    def sign(self):
        """Sign."""
        manager = SignatureSigner(
            version=self.version,
            app_name=self.app_name_formatter(self.module_name),
            list_of_known_keys=[KnownGPGKeys.andreasgriffin],
        )
        signed_files = manager.sign_files(KnownGPGKeys.andreasgriffin)
        assert self.verify(signed_files), "Error: Signature Verification failed!!!!"

    def lock(self):
        """Lock."""
        run_local("poetry lock --no-cache --no-update")

    def verify(self, signed_files: list[Path]):
        """Verify."""
        manager = SignatureVerifyer(list_of_known_keys=[KnownGPGKeys.andreasgriffin], proxies=None)

        assert signed_files
        for filepath in signed_files:
            is_valid = manager.verify_signature(
                binary_filename=filepath, expected_public_key=KnownGPGKeys.andreasgriffin
            )
            if not is_valid:
                return False
        return True

    def build_snap(self, **kwargs):
        """Build a Snap package for a Python application."""

        # Create necessary directories
        build_snap_dir = Path(self.build_dir) / "snap"
        bin_dir = build_snap_dir / "bin"
        gui_dir = build_snap_dir / "gui"

        os.makedirs(build_snap_dir, exist_ok=True)
        os.makedirs(bin_dir, exist_ok=True)
        os.makedirs(gui_dir, exist_ok=True)

        # Copy the entire module folder to the build/snap directory
        src_folder = Path(self.module_name)
        dst_folder = build_snap_dir / self.module_name
        if dst_folder.exists():
            shutil.rmtree(dst_folder)  # Remove if already exists to avoid conflicts
        shutil.copytree(src_folder, dst_folder)

        # Copy the application entry point to the build/snap/bin directory
        app_entry_point = src_folder / "__main__.py"
        shutil.copy(app_entry_point, bin_dir)

        # Create desktop file in the gui subfolder
        app_name = self.app_name_formatter(self.module_name).lower()
        desktop_file_path = gui_dir / f"{app_name}.desktop"
        with open(desktop_file_path, "w") as desktop_file:
            desktop_file.write(
                f"""
[Desktop Entry]
Version=1.0
Type=Application
Name={app_name}
Exec={app_name} %F
Icon={app_name}/gui/icons/logo.svg
Comment={app_name} application
Terminal=false
Categories=Utility;
        """
            )

        # Path to snapcraft.yaml
        snapcraft_yaml_path = build_snap_dir / "snapcraft.yaml"

        # Generate a basic snapcraft.yaml if it doesn't exist
        if not snapcraft_yaml_path.exists():
            with open(snapcraft_yaml_path, "w") as snapcraft_file:
                snapcraft_file.write(
                    f"""
name: {app_name}
version: '{self.version}'
summary: {app_name} Snap Package
description: |
    This is a Snap package for {app_name}.

grade: stable
confinement: strict
base: core22  # Base set to Ubuntu 22.04

parts:
    {app_name}:
        plugin: python
        python-packages: ['PyQt6']
        source: .
        stage-packages:
            - libqt6gui6
            - libqt6widgets6
            - libqt6core6
            - libqt6network6
            - libqt6svg6 
            
            
apps:
    {app_name}:
        command: python -m {self.module_name}

        plugs:
            - raw-usb
            - hardware-observe

        desktop: $SNAP/gui/{app_name}.desktop 
            """
                )

        original_dir = os.getcwd()
        # Check if Snapcraft is installed
        os.chdir(build_snap_dir)
        run_local("snapcraft")

        # Find the resulting .snap file
        dist_dir = Path(self.build_dir) / "dist"
        dist_dir.mkdir(exist_ok=True)
        snap_file = next(build_snap_dir.glob("*.snap"), None)

        if snap_file:
            # Move the resulting Snap file to the dist directory
            shutil.move(snap_file, dist_dir / snap_file.name)
            print(f"Snap package built successfully: {dist_dir / snap_file.name}")
        else:
            raise RuntimeError("Snap package build was successful, but the .snap file was not found.")

        # Return to the original directory
        os.chdir(original_dir)


def get_default_targets() -> list[TARGET_LITERAL]:
    """Get default targets."""
    if platform.system() == "Windows":
        return ["windows"]
    elif platform.system() == "Linux":
        return [
            "appimage",
            # "flatpak",
            "deb",
        ]
    elif platform.system() == "Darwin":
        return ["mac"]
    return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package the Python application.")
    parser.add_argument("--clean", action="store_true", help=f"Removes the {Builder.build_dir} folder")
    parser.add_argument(
        "--commit",
        type=str,
        help="The commit to be build. tag|commit_hash|'None'|'current_commit' .   The default is 'current_commit'.  None, will build within the current project.",
        default="current_commit",
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        help=f"The target formats.  The default is {get_default_targets()}",
        default=None,
    )
    parser.add_argument("--sign", action="store_true", help="Signs all files in dist")
    parser.add_argument("--verify", action="store_true", help="Signs all files in dist")
    parser.add_argument(
        "--update_translations", action="store_true", help="Updates the translation locales files"
    )
    parser.add_argument(
        "--insert_chatgpt_translations",
        action="store_true",
        help="Pastes the chatgpt translations into the csv files",
    )
    parser.add_argument("--csv_to_ts", action="store_true", help="Overwrites the ts files with csv as source")
    parser.add_argument(
        "--weblate_correct",
        action="store_true",
        help="Equal to --update_translations and --csv_to_ts. It ensures special characters are restored, which were lost by weblate, by ts-->csv-->ts",
    )
    parser.add_argument(
        "--lock",
        action="store_true",
        help="poetry lock --no-update --no-cache. This is important to ensure all hashes are included in the lockfile. ",
    )
    args = parser.parse_args()

    if args.lock:
        builder = Builder(module_name="bitcoin_safe", clean_all=args.clean)
        builder.lock()

    if args.commit == "None":
        args.commit = None

    if args.targets is not None:
        # clean args
        targets: list[TARGET_LITERAL] = args.targets
        if not targets:
            print("--targets was given without any values.")
            targets = get_default_targets()
        else:
            print(f"--targets was given with the values: {args.targets}")
            targets = [t.replace(",", "") for t in targets]  # type: ignore

        builder = Builder(module_name="bitcoin_safe", clean_all=args.clean)
        builder.package_application(targets=targets, build_commit=args.commit)

    if args.update_translations:
        translation_handler = TranslationHandler(module_name="bitcoin_safe")
        translation_handler.update_translations_from_py()
    if args.csv_to_ts:
        translation_handler = TranslationHandler(module_name="bitcoin_safe")
        translation_handler.csv_to_ts()
    if args.insert_chatgpt_translations:
        translation_handler = TranslationHandler(module_name="bitcoin_safe")
        translation_handler.insert_chatgpt_translations()
    if args.weblate_correct:
        translation_handler = TranslationHandler(module_name="bitcoin_safe")
        translation_handler.update_translations_from_py()
        translation_handler.csv_to_ts()

    if args.sign:
        builder = Builder(module_name="bitcoin_safe", clean_all=args.clean)
        builder.sign()

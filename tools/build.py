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


import argparse
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import List, Literal

import tomlkit
from translation_handler import TranslationHandler, run_local

from bitcoin_safe import __version__
from bitcoin_safe.signature_manager import (
    KnownGPGKeys,
    SignatureSigner,
    SignatureVerifyer,
)
from tools.release import get_git_tag

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


TARGET_LITERAL = Literal["windows", "mac", "appimage", "deb", "flatpak"]


class Builder:
    build_dir = "build"

    def __init__(self, module_name, clean_all=False):
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
    def app_name_formatter(module_name: str) -> str:
        parts = [s.capitalize() for s in module_name.split("_")]

        return "-".join(parts)

    def update_briefcase_requires(
        self,
        pyproject_path="pyproject.toml",
        poetry_lock_path="poetry.lock",
        additional_requires=[],
    ):

        # Load pyproject.toml
        with open(pyproject_path, "r") as file:
            pyproject_data = tomlkit.load(file)

        # Load and parse poetry lock file
        with open(poetry_lock_path, "r") as file:
            poetry_lock_data = tomlkit.load(file)

        briefcase_requires = []
        # Extract packages from the lock file
        for package in poetry_lock_data["package"]:
            name = package["name"]
            if name in ["xattr", "poetry"]:
                continue
            version = package["version"]
            if package.get("source"):
                briefcase_requires.append(package.get("source", {}).get("url"))
            else:
                briefcase_requires.append(f"{name}=={version}")

        # Append any additional requires
        briefcase_requires.extend(additional_requires)

        # Ensure the structure exists before updating it
        pyproject_data.setdefault("tool", {}).setdefault("briefcase", {}).setdefault("app", {}).setdefault(
            "bitcoin-safe", {}
        )["requires"] = briefcase_requires

        # update version
        pyproject_data.setdefault("tool", {}).setdefault("briefcase", {})["version"] = self.version
        # update version
        pyproject_data.setdefault("tool", {}).setdefault("poetry", {})["version"] = self.version

        # Write updated pyproject.toml
        with open(pyproject_path, "w") as file:
            tomlkit.dump(pyproject_data, file)

    def build_appimage_docker(
        self, no_cache=False, build_commit: None | str | Literal["current_commit"] = "current_commit"
    ):
        self.build_in_docker(
            "bitcoin_safe-appimage-builder-img",
            Path("tools/build-linux/appimage"),
            no_cache=no_cache,
            build_commit=build_commit,
        )

    def build_windows_exe_and_installer_docker(
        self, no_cache=False, build_commit: None | str | Literal["current_commit"] = "current_commit"
    ):
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
            logger.info(f"Building within current project")

        logger.info("Building docker image.")
        run_local(f'docker build {DOCKER_BUILD_FLAGS} -t {docker_image} "{path_build}"')

        # Possibly do a fresh clone
        FRESH_CLONE = False
        if build_commit:
            logger.info(f"BITCOINSAFE_BUILD_COMMIT={build_commit}. Doing fresh clone and git checkout.")
            FRESH_CLONE = Path(f"/tmp/{docker_image.replace(' ','')}/fresh_clone/bitcoin_safe")
            try:
                run_local(f'rm -rf "{FRESH_CLONE}"')
            except subprocess.CalledProcessError:
                logger.info("We need sudo to remove previous FRESH_CLONE.")
                run_local(f'sudo rm -rf "{FRESH_CLONE}"')
            os.umask(0o022)
            run_local(f'git clone "{PROJECT_ROOT}" "{FRESH_CLONE}"')
            os.chdir(str(FRESH_CLONE))
            run_local(f'git checkout "{build_commit}"')
            os.chdir(original_dir)
            PROJECT_ROOT_OR_FRESHCLONE_ROOT = FRESH_CLONE
        else:
            logger.info("Not doing fresh clone.")

        Source_Dist_dir = PROJECT_ROOT_OR_FRESHCLONE_ROOT / build_folder / "dist"

        logger.info("Building binary...")
        run_local(
            f"docker run -it "
            f"--name {docker_image}-container "
            f'-v "{PROJECT_ROOT_OR_FRESHCLONE_ROOT}":/opt/wine64/drive_c/bitcoin_safe '
            f"--rm "
            f"--workdir /opt/wine64/drive_c/bitcoin_safe/{build_folder} "
            f"{docker_image} "
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

    def briefcase_appimage(self, **kwargs):
        # briefcase appimage building works on some systems, but not on others... unknown why.
        # so we build using the bitcoin_safe docker by default
        run_local("poetry run briefcase -u  package    linux  appimage")

    def briefcase_windows(self, **kwargs):
        run_local("poetry run briefcase -u  package    windows")

    def briefcase_mac(self, **kwargs):
        run_local("python3 -m poetry run   briefcase -u  package    macOS  app --no-notarize")

    def briefcase_deb(self, **kwargs):
        # _run_local(" briefcase -u  package --target ubuntu:23.10") # no bdkpython for python3.11
        # _run_local(" briefcase -u  package --target ubuntu:23.04") # no bdkpython for python3.11
        run_local("poetry run briefcase -u  package --target ubuntu:22.04 -p deb")

    def briefcase_flatpak(self, **kwargs):
        run_local("poetry run briefcase   package linux flatpak")

        shutil.rmtree("build")

    def package_application(
        self,
        targets: List[TARGET_LITERAL],
        build_commit: None | str | Literal["current_commit"] = None,
    ):
        self.update_briefcase_requires()

        f_map = {
            "appimage": self.build_appimage_docker,
            "windows": self.build_windows_exe_and_installer_docker,
            "mac": self.briefcase_mac,
            "deb": self.briefcase_deb,
            "flatpak": self.briefcase_flatpak,
            "snap": self.build_snap,
        }

        for target in targets:
            f_map[target](build_commit=build_commit)

        # if "linux" in targets:
        #     self.create_briefcase_binaries_in_docker(target_platform="linux")
        # if "windows" in targets:
        #     self.create_pyinstaller_binaries_in_docker(target_platform="windows")
        # # if "macos" in targets:
        # #     self.create_pyinstaller_binaries_in_docker(target_platform="macos")

        # if "appimage" in targets:
        #     self.create_appimage_with_appimage_tool()

        print(f"Packaging completed for version {self.version}.")

    def sign(self):

        manager = SignatureSigner(
            version=self.version,
            app_name=self.app_name_formatter(self.module_name),
            list_of_known_keys=[KnownGPGKeys.andreasgriffin],
        )
        signed_files = manager.sign_files(KnownGPGKeys.andreasgriffin)
        assert self.verify(signed_files), "Error: Signature Verification failed!!!!"

    def lock(self):
        run_local("poetry lock --no-cache --no-update")

    def verify(self, signed_files: List[Path]):
        manager = SignatureVerifyer(
            list_of_known_keys=[KnownGPGKeys.andreasgriffin],
        )

        assert signed_files
        for filepath in signed_files:
            is_valid = manager.verify_signature(
                binary_filename=filepath, expected_public_key=KnownGPGKeys.andreasgriffin
            )
            if not is_valid:
                return False
        return True

    def build_snap(self, **kwargs):
        """
        Build a Snap package for a Python application.
        """

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


def get_default_targets() -> List[TARGET_LITERAL]:
    if platform.system() == "Windows":
        return ["windows"]
    elif platform.system() == "Linux":
        return [
            "appimage",
            # "flatpak",
            # "deb",
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
        help=f"The commit to be build. tag|commit_hash|'None'|'current_commit' .   The default is 'current_commit'.  None, will build within the current project.",
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
    parser.add_argument("--csv_to_ts", action="store_true", help="Overwrites the ts files with csv as source")
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
        targets: List[TARGET_LITERAL] = args.targets
        if not targets:
            print("--targets was given without any values.")
            targets = get_default_targets()
        else:
            print(f"--targets was given with the values: {args.targets}")
            targets = [t.replace(",", "") for t in targets]

        builder = Builder(module_name="bitcoin_safe", clean_all=args.clean)
        builder.package_application(targets=targets, build_commit=args.commit)

    if args.update_translations:
        translation_handler = TranslationHandler(module_name="bitcoin_safe")
        translation_handler.update_translations_from_py()
    if args.csv_to_ts:
        translation_handler = TranslationHandler(module_name="bitcoin_safe")
        translation_handler.csv_to_ts()

    if args.sign:
        builder = Builder(module_name="bitcoin_safe", clean_all=args.clean)
        builder.sign()

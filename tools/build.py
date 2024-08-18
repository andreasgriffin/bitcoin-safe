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
from pathlib import Path
from typing import List, Literal

import tomlkit
from translation_handler import TranslationHandler, run_local

from bitcoin_safe import __version__
from bitcoin_safe.signature_manager import KnownGPGKeys, SignatureSigner
from tools.dependency_check import DependencyCheck

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class Builder:
    build_dir = "build"

    def __init__(self, module_name, clean_all=False):
        self.module_name = module_name
        self.version = __version__ if __version__ else "unknown-version"

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
        # electrumsv-secp256k1 offers libsecp256k1 prebuild for different platforms
        # which is needed for bitcointx.
        # bitcointx and with it the prebuild libsecp256k1 is not used for anything security critical
        # key derivation with bitcointx is restricted to testnet/regtest/signet
        # and the PSBTTools using bitcointx is safe because it handles no key material
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

        if platform.system() == "Linux":
            DependencyCheck.check_local_files_match_lockfile()
        else:
            pass
            # the whl files build in Windows have a different checksum, and therefore the check will fail

    def briefcase_appimage(self):
        run_local("poetry run briefcase -u  package    linux  appimage")

    def briefcase_windows(self):
        run_local("poetry run briefcase -u  package    windows")

    def briefcase_mac(self):
        run_local("python3 -m poetry run   briefcase -u  package    macOS  app --no-notarize")

    def briefcase_deb(self):
        # _run_local(" briefcase -u  package --target ubuntu:23.10") # no bdkpython for python3.11
        # _run_local(" briefcase -u  package --target ubuntu:23.04") # no bdkpython for python3.11
        run_local("poetry run briefcase -u  package --target ubuntu:22.04 -p deb")

    def briefcase_flatpak(self):
        run_local("poetry run briefcase   package linux flatpak")

    def package_application(self, targets: List[Literal["windows", "mac", "appimage", "deb", "flatpak"]]):
        shutil.rmtree("build")
        self.update_briefcase_requires()

        f_map = {
            "appimage": self.briefcase_appimage,
            "windows": self.briefcase_windows,
            "mac": self.briefcase_mac,
            "deb": self.briefcase_deb,
            "flatpak": self.briefcase_flatpak,
            "snap": self.build_snap,
        }

        for target in targets:
            f_map[target]()

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
        manager.sign_files(KnownGPGKeys.andreasgriffin)
        assert self.verify(), "Error: Signatures do NOT match fingerprint!!!!"

    def verify(self):
        manager = SignatureSigner(
            version=self.version,
            app_name=self.app_name_formatter(self.module_name),
            list_of_known_keys=[KnownGPGKeys.andreasgriffin],
        )

        files = manager.get_files_to_sign()
        assert files
        for filepath in files:
            is_valid = manager.verify_signature(
                binary_filename=filepath, expected_public_key=KnownGPGKeys.andreasgriffin
            )
            if not is_valid:
                return False
        return True

    def build_snap(self):
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
Exec={app_name}
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
        os.chdir(Path.cwd().parent.parent.parent)


def get_default_targets() -> List[str]:
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
        "--targets",
        nargs="*",
        help=f"The target formats.  The default is {get_default_targets()}",
    )
    parser.add_argument("--sign", action="store_true", help="Signs all files in dist")
    parser.add_argument("--verify", action="store_true", help="Signs all files in dist")
    parser.add_argument(
        "--update_translations", action="store_true", help="Updates the translation locales files"
    )
    parser.add_argument("--csv_to_ts", action="store_true", help="Overwrites the ts files with csv as source")
    args = parser.parse_args()
    # clean args
    targets = args.targets
    # clean targets
    if targets is None:
        print("No --targets argument was given.")
        targets = []
    elif not targets:
        print("--targets was given without any values.")
        targets = get_default_targets()
    else:
        print(f"--targets was given with the values: {args.targets}")
        targets = [t.replace(",", "") for t in targets]

    builder = Builder(module_name="bitcoin_safe", clean_all=args.clean)
    builder.package_application(targets=targets)

    translation_handler = TranslationHandler(module_name="bitcoin_safe")
    if args.update_translations:
        translation_handler.update_translations_from_py()
    if args.csv_to_ts:
        translation_handler.csv_to_ts()

    if args.sign:
        builder.sign()

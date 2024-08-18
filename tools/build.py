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
import csv
import logging
import operator
import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import List, Literal, Tuple, Union

import tomlkit

from bitcoin_safe import __version__
from bitcoin_safe.signature_manager import KnownGPGKeys, SignatureSigner

logger = logging.getLogger(__name__)


def run_local(cmd) -> CompletedProcess:
    completed_process = subprocess.run(shlex.split(cmd), check=True)
    return completed_process


# https://www.fincher.org/Utilities/CountryLanguageList.shtml
class TranslationHandler:
    def __init__(
        self,
        module_name,
        languages=["zh_CN", "es_ES", "ru_RU", "hi_IN", "pt_PT", "ja_JP", "ar_AE", "it_IT"],
        prefix="app",
    ) -> None:
        self.module_name = module_name
        self.ts_folder = Path(module_name) / "gui" / "locales"
        self.prefix = prefix
        self.languages = languages

    def delete_po_files(self):
        for file in self.ts_folder.glob("*.po"):
            file.unlink()

    def get_all_python_files(self) -> List[str]:
        project_dir = Path(self.module_name)
        python_files = [str(file) for file in project_dir.rglob("*.py")]
        return python_files

    def get_all_ts_files(self) -> List[str]:
        python_files = [str(file) for file in self.ts_folder.rglob("*.ts")]
        return python_files

    def _ts_file(self, language: str) -> Path:
        return self.ts_folder / f"{self.prefix}_{language}.ts"

    @staticmethod
    def sort_csv(input_file: Path, output_file: Path, sort_columns: Union[Tuple[str, ...], List[str]]):
        """
        Sorts a CSV file by specified columns and writes the sorted data to another CSV file.

        Parameters:
            input_file (Path): The input CSV file path.
            output_file (Path): The output CSV file path.
            sort_columns (Tuple[str, ...]): A tuple of column names to sort the CSV data by (in priority order).
        """
        # Read the CSV file into a list of dictionaries
        with open(str(input_file), mode="r", newline="", encoding="utf-8") as infile:
            reader = csv.DictReader(infile)
            rows = list(reader)

        # Validate that all sort columns are in the fieldnames
        fieldnames = reader.fieldnames
        assert fieldnames
        for col in sort_columns:
            if col not in fieldnames:
                raise ValueError(f"Column '{col}' not found in CSV file")

        # Sort the rows by the specified columns (in priority order)
        sorted_rows = sorted(rows, key=operator.itemgetter(*sort_columns))

        # Write the sorted data to the output CSV file
        with open(str(output_file), mode="w", newline="", encoding="utf-8") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(sorted_rows)

    def update_translations_from_py(self):
        for language in self.languages:
            ts_file = self._ts_file(language)
            run_local(
                f"pylupdate6  {' '.join(self.get_all_python_files())} -no-obsolete  -ts {ts_file}"
            )  # -no-obsolete
            run_local(f"ts2po {ts_file}  -o {ts_file.with_suffix('.po')}")
            run_local(f"po2csv {ts_file.with_suffix('.po')}  -o {ts_file.with_suffix('.csv')}")
            self.sort_csv(
                ts_file.with_suffix(".csv"),
                ts_file.with_suffix(".csv"),
                sort_columns=["target", "location", "source"],
            )

        self.delete_po_files()
        self.compile()

    @staticmethod
    def quote_csv(input_file, output_file):
        # Read the CSV content from the input file
        with open(input_file, newline="") as infile:
            reader = csv.reader(infile)
            rows = list(reader)

        # Write the CSV content with quotes around each item to the output file
        with open(output_file, "w", newline="") as outfile:
            writer = csv.writer(outfile, quoting=csv.QUOTE_ALL)
            writer.writerows(rows)

    def csv_to_ts(self):
        for language in self.languages:
            ts_file = self._ts_file(language)

            # csv2po cannot handle partially quoted files
            self.sort_csv(
                ts_file.with_suffix(".csv"),
                ts_file.with_suffix(".csv"),
                sort_columns=["location", "source", "target"],
            )
            run_local(f"csv2po {ts_file.with_suffix('.csv')}  -o {ts_file.with_suffix('.po')}")
            run_local(f"po2ts {ts_file.with_suffix('.po')}  -o {ts_file}")
        self.delete_po_files()
        self.compile()

    def compile(self):
        run_local(f"/usr/lib/qt6/bin/lrelease   {' '.join(self.get_all_ts_files())}")


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
        # and the PSBTFinalizer using bitcointx is safe because it handles no key material
        additional_requires=[],
    ):
        # Load pyproject.toml
        with open(pyproject_path, "r") as file:
            pyproject_data = tomlkit.load(file)

        # Load and parse poetry lock file
        with open(poetry_lock_path, "r") as file:
            poetry_lock_content = file.read()

        briefcase_requires = []
        packages = poetry_lock_content.split("[[package]]")
        for package in packages[1:]:  # Skip the first part as it's before the first package
            lines = package.split("\n")
            name = version = None
            for line in lines:
                if line.strip().startswith("name ="):
                    name = line.split('"')[1].strip()
                elif line.strip().startswith("version ="):
                    version = line.split('"')[1].strip()
            if name and version:
                briefcase_requires.append(f"{name}=={version}")
        briefcase_requires += additional_requires

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
        if self.version is None:
            print("Version could not be determined.")
            return
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
            "deb",
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

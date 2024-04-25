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
import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import List, Literal

import toml

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
        languages=["zh_CN", "es_ES", "ru_RU", "hi_IN", "pt_PT", "ja_JP", "ar_AE"],
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

    def update_translations_from_py(self):
        for language in self.languages:
            ts_file = self._ts_file(language)
            run_local(
                f"pylupdate6  {' '.join(self.get_all_python_files())} -no-obsolete  -ts {ts_file}"
            )  # -no-obsolete
            run_local(f"ts2po {ts_file}  -o {ts_file.with_suffix('.po')}")
            run_local(f"po2csv {ts_file.with_suffix('.po')}  -o {ts_file.with_suffix('.csv')}")
        self.delete_po_files()
        self.compile()

    def quote_csv(self, input_file, output_file):
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
            self.quote_csv(ts_file.with_suffix(".csv"), ts_file.with_suffix(".csv"))
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
            pyproject_data = toml.load(file)

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
            toml.dump(pyproject_data, file)

    def briefcase_appimage(self):
        run_local("poetry run briefcase -u  package    linux  appimage")

    def briefcase_windows(self):
        run_local("poetry run briefcase -u  package    windows")

    def briefcase_mac(self):
        run_local("python3 -m poetry run   briefcase -u  package    macOS  app --no-notarize")

    def briefcase_deb(self):
        # _run_local(" briefcase -u  package --target ubuntu:23.10") # no bdkpython for python3.11
        # _run_local(" briefcase -u  package --target ubuntu:23.04") # no bdkpython for python3.11
        run_local("poetry run briefcase -u  package --target ubuntu:22.04")

    def package_application(self, targets: List[Literal["windows", "mac", "appimage", "deb", "snap"]]):
        if self.version is None:
            print("Version could not be determined.")
            return

        shutil.rmtree("build")
        self.update_briefcase_requires()
        if "appimage" in targets:
            self.briefcase_appimage()
        if "windows" in targets:
            self.briefcase_windows()
        if "mac" in targets:
            self.briefcase_mac()
        if "deb" in targets:
            self.briefcase_deb()

        # if "linux" in targets:
        #     self.create_briefcase_binaries_in_docker(target_platform="linux")
        # if "windows" in targets:
        #     self.create_pyinstaller_binaries_in_docker(target_platform="windows")
        # # if "macos" in targets:
        # #     self.create_pyinstaller_binaries_in_docker(target_platform="macos")

        # if "appimage" in targets:
        #     self.create_appimage_with_appimage_tool()
        # if "snap" in targets:
        #     self.create_snapcraft_yaml()
        #     subprocess.run(["snapcraft"], cwd="./")

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


def get_default_targets() -> List[str]:
    if platform.system() == "Windows":
        return ["windows"]
    elif platform.system() == "Linux":
        return ["appimage"]
    elif platform.system() == "Darwin":
        return ["mac"]
    return []


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Package the Python application.")
    parser.add_argument("--snap", action="store_true", help="Build a snap package")
    parser.add_argument("--clean", action="store_true", help=f"Removes the {Builder.build_dir} folder")
    parser.add_argument(
        "--targets",
        nargs="*",
        help=f"The targets: linux windows mac appimage snap .  The default is {get_default_targets()}",
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

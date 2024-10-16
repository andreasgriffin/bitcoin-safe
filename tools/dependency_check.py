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

import hashlib
import logging
from pathlib import Path
from typing import Dict, List

import tomlkit

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class DependencyCheck:

    @staticmethod
    def compute_sha256(file_path: Path):
        hash_sha256 = hashlib.sha256()
        with open(str(file_path), "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    @classmethod
    def compare_hashes(
        cls, pakckage_name: str, hash_list: List[Dict[str, str]], dist_directory: Path
    ) -> List[str]:
        dist_files = [item.name for item in dist_directory.iterdir() if item.is_file()]

        matches = [hash_dict for hash_dict in hash_list if hash_dict["file"] in dist_files]

        if not matches:
            raise Exception(
                f"No file found in {dist_directory} that matches the filename in {[hash_dict['file']   for hash_dict in hash_list  ]}"
            )

        for match_dict in matches:
            assert match_dict["hash"].startswith("sha256:"), f"Error: wrong hash type of {match_dict['hash']}"
            expected_hash = match_dict["hash"].replace("sha256:", "")

            file_hash = cls.compute_sha256(dist_directory / match_dict["file"])

            if file_hash == expected_hash:
                logger.info(
                    f"{pakckage_name}: {dist_directory / match_dict['file']} matches the hash from the lock file"
                )
            else:
                raise Exception(
                    f"Hash of {dist_directory / match_dict['file']} == {file_hash} doesnt match  {expected_hash}  , len ({len(expected_hash)})"
                )

    @classmethod
    def check_local_files_match_lockfile(
        cls, source_package_path: Path = Path("../"), poetry_file=Path("poetry.lock")
    ) -> List[str]:
        directory_names = cls.list_directories(folder_path=source_package_path)
        poetry_packages = cls.extract_packages(lock_file_path=poetry_file)

        for pakckage_name, hash_list in poetry_packages.items():
            if pakckage_name in directory_names:
                if not hash_list:
                    continue
                cls.compare_hashes(
                    pakckage_name=pakckage_name,
                    hash_list=hash_list,
                    dist_directory=source_package_path / pakckage_name / "dist",
                )

    @staticmethod
    def list_directories(folder_path: Path) -> List[str]:
        """
        List all directories in a given folder using pathlib.

        :param folder_path: Path, the path to the folder in which to list directories
        :return: List[str], list of directory names found in the folder
        """
        # List comprehension to filter directories
        directories = [item.name for item in folder_path.iterdir() if item.is_dir()]
        return directories

    @staticmethod
    def extract_packages(lock_file_path: Path) -> Dict[str, List[Dict[str, str]]]:
        with open(str(lock_file_path), "r", encoding="utf-8") as file:
            data = tomlkit.parse(file.read())

        packages = {}
        for package in data["package"]:
            if "name" in package and "version" in package:
                packages[package["name"]] = package["files"]
        return packages


if __name__ == "__main__":
    packages = DependencyCheck.check_local_files_match_lockfile()
    print(packages)

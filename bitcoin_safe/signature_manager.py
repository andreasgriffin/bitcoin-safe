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

import glob
import hashlib
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pgpy  # Python-native OpenPGP library
import requests

gnupg = None
logger = logging.getLogger(__name__)


@dataclass
class SimpleGPGKey:
    key: str
    repository: str  # org/repo_name
    prefix: str
    manifest_ending: Optional[str] = None

    @staticmethod
    def extract_prefix_and_version(filename: str) -> tuple[Optional[str], Optional[str]]:
        import re

        if filename.endswith(".deb"):
            match = re.search(r"(.+)_(.+?)(?:-.+)?_.*\.deb", filename)
            if match:
                return (match.group(1), match.group(2))

        # try with - separator
        match = re.search(r"(.*?)-([\d\.]+[a-zA-Z0-9]*)", filename)
        if match:
            return (match.group(1), match.group(2))

        # try with _ separator
        match = re.search(r"(.*?)_([\d\.]+[a-zA-Z0-9]*)", filename)
        if match:
            return (match.group(1), match.group(2))
        return (None, None)

    def get_tag_if_mine(self, filename: str) -> Optional[str]:
        prefix, version = self.extract_prefix_and_version(filename)
        if prefix and prefix.lower() == self.prefix.lower():
            return version
        return None


@dataclass
class Asset:
    tag: str
    url: str
    name: str


class GitHubAssetDownloader:
    def __init__(self, repository: str) -> None:
        self.repository = repository
        logger.debug(f"initialized {self}")

    def _get_assets(self, api_url) -> List[Asset]:
        try:
            logger.debug(f"Get assets from {api_url}")
            response = requests.get(api_url, timeout=2)
            response.raise_for_status()
            assets = response.json().get("assets", [])

            return [
                Asset(
                    tag=response.json().get("tag_name", ""),
                    url=asset["browser_download_url"],
                    name=asset["name"],
                )
                for asset in assets
            ]
        except requests.RequestException as e:
            logger.error(f"Failed to download: {api_url}")
            return []

    def get_assets_by_tag(self, tag: str) -> List[Asset]:
        return self._get_assets(f"https://api.github.com/repos/{self.repository}/releases/tags/{tag}")

    def get_assets_latest(self) -> List[Asset]:
        return self._get_assets(f"https://api.github.com/repos/{self.repository}/releases/latest")


class SignatureVerifyer:
    def __init__(
        self,
        list_of_known_keys: Optional[List[SimpleGPGKey]],
    ) -> None:
        self.list_of_known_keys = list_of_known_keys if list_of_known_keys else []
        self.public_keys: Dict[str, pgpy.PGPKey] = {}
        self.import_known_keys()

    def import_public_key_file(self, path: Path) -> pgpy.PGPKey:
        with open(str(path), "r") as file:
            return self.import_public_key_block(file.read())

    def import_public_key_block(self, public_key_block: str) -> pgpy.PGPKey:
        """
        Import a public key block and return its fingerprint.

        :param public_key_block: The public key block in ASCII armor format.
        :return: The fingerprint of the imported public key.
        """

        result = pgpy.PGPKey.from_blob(public_key_block)
        public_key = None
        if isinstance(result, pgpy.PGPKey):
            public_key = result
        elif isinstance(result, tuple):
            public_key, _ = result

        if isinstance(public_key, pgpy.PGPKey):
            fingerprint = str(public_key.fingerprint)
            self.public_keys[fingerprint] = public_key
            logger.info(f"Public key imported with fingerprint: {public_key.fingerprint}")
            return public_key

        raise Exception(f"Could not process result f{result}")

    def import_known_keys(self) -> None:
        for key in self.list_of_known_keys:
            self.import_public_key_block(key.key)

    @staticmethod
    def verify_manifest_hashes(manifest_file: Path) -> bool:
        # Check if the manifest file exists
        if not manifest_file.exists():
            print("Manifest file does not exist.")
            return False

        file_found = False  # To track if at least one file is found

        with manifest_file.open("r") as file:
            for line in file:
                # Extract expected hash and file name from each line
                parts = line.strip().split(" *")
                if len(parts) != 2:
                    print("Invalid line format in manifest:", line)
                    continue  # Skip invalid lines

                expected_hash, file_name = parts
                file_path = manifest_file.parent / file_name

                # Check if the file exists
                if not file_path.exists():
                    logger.debug(f"File {file_name} listed in the manifest does not exist.")
                    continue  # It's okay if some files don't exist, but at least one must be found

                file_found = True  # Mark that we've found at least one file

                # Compute the file's SHA-256 hash
                file_hash = hashlib.sha256()
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        file_hash.update(chunk)

                # Compare the computed hash with the expected hash
                if file_hash.hexdigest() != expected_hash:
                    logger.error(f"Hash mismatch for {file_name}.")
                    return False

        if not file_found:
            print("None of the files listed in the manifest are present.")
            return False  # Return False if none of the files are found

        return True

    def get_valid_manifest(self, signature_file: Path) -> Optional[Path]:
        manifest = signature_file.parent / signature_file.name.removesuffix(".asc")
        return manifest if self.verify_manifest_hashes(manifest) else None

    def verify_signature(self, binary_filename: Path, expected_public_key: SimpleGPGKey) -> bool:
        signature_file = self.get_signature_file(binary_filename)
        if not signature_file:
            signature_file = self.get_signature_from_web(binary_filename)
            if not signature_file:
                logger.error("Could not download signature file")
                return False

        key = self.get_key(binary_filename)
        public_key = self.import_public_key_block(expected_public_key.key)
        if not public_key:
            logger.error("Expected public key not found.")
            return False

        binary_file_to_check = binary_filename
        if key and key.manifest_ending:
            manifest_file = self.get_valid_manifest(signature_file)
            if not manifest_file:
                return False
            binary_file_to_check = manifest_file

        verification_result = self._verify_file(
            public_key=public_key, binary_file=binary_file_to_check, signature_file=signature_file
        )

        return verification_result

    def _verify_file(
        self, public_key: pgpy.PGPKey, binary_file: Union[Path, str], signature_file: Union[Path, str]
    ) -> bool:
        try:
            with open(str(signature_file), "rb") as sig_file:
                signature = pgpy.PGPSignature.from_blob(sig_file.read())

            with open(str(binary_file), "rb") as bin_file:
                message_data = bin_file.read()

            pgpmessage = pgpy.PGPMessage.new(message_data, file=True)

            # Verify the signature
            verify_result = public_key.verify(pgpmessage.message, signature)
            if not verify_result:
                return False
            good_signatures = list(verify_result.good_signatures)
            bad_signatures = list(verify_result.bad_signatures)
            # 1 single bad signature creates a False result
            return bool(good_signatures) and not bool(bad_signatures)
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False

    @staticmethod
    def _get_asset_url(assets: List[Asset], ending: str) -> Optional[str]:
        for asset in assets:
            if asset.name.endswith(ending):
                return asset.url
        return None

    @staticmethod
    def _download_file(download_url: str, filename: Path) -> Path:
        sig_response = requests.get(download_url, timeout=2)
        sig_response.raise_for_status()
        with open(filename, "wb") as f:
            f.write(sig_response.content)
        return filename

    @staticmethod
    def _download_asset_file(
        assets: List[Asset], target_directory: Path, asset_ending: str
    ) -> Optional[Path]:
        if url := SignatureVerifyer._get_asset_url(assets, asset_ending):
            url_filename = Path(url).name
            filename = target_directory / url_filename
            SignatureVerifyer._download_file(url, filename)
            return filename
        return None

    def get_signature_file(self, binary_filename: Path) -> Optional[Path]:
        key = self.get_key(binary_filename)
        if key and key.manifest_ending:
            manifest_files = glob.glob(str(binary_filename.parent / f"*{key.manifest_ending}"))
            sig_files = glob.glob(str(binary_filename.parent / f"*{key.manifest_ending}.asc"))

            if not manifest_files or not sig_files:
                return None
            return Path(sig_files[0])
        else:
            return binary_filename.parent / (binary_filename.name + ".asc")

    def is_signature_file_available(self, binary_filename: Path) -> bool:
        sig_file = self.get_signature_file(binary_filename)
        return sig_file.exists() if sig_file else False

    def get_key(self, binary_filename: Path) -> Optional[SimpleGPGKey]:
        for key in self.list_of_known_keys:
            tag = key.get_tag_if_mine(binary_filename.name)
            if tag:
                return key
        return None

    def get_signature_from_web(self, binary_filename: Path) -> Optional[Path]:
        sig_filename = None
        key = self.get_key(binary_filename)
        if not key:
            return None
        tag = key.get_tag_if_mine(binary_filename.name)
        if not tag:
            return None

        assets = GitHubAssetDownloader(repository=key.repository).get_assets_by_tag(tag)
        if assets:
            if key.manifest_ending:
                self._download_asset_file(
                    assets, target_directory=binary_filename.parent, asset_ending=key.manifest_ending
                )
                sig_filename = self._download_asset_file(
                    assets,
                    target_directory=binary_filename.parent,
                    asset_ending=f"{key.manifest_ending}.asc",
                )
            else:
                sig_filename = self._download_asset_file(
                    assets,
                    target_directory=binary_filename.parent,
                    asset_ending=f"{binary_filename.name}.asc",
                )
        return sig_filename

    def get_key_meta_info(self, key: SimpleGPGKey) -> Dict:
        """
        Retrieve meta-information about a key given its fingerprint.

        :param key: The GPGKey object containing the key data.
        :return: A dictionary containing the key's meta-information.
        """
        public_key = self.import_public_key_block(key.key)

        key_info = {
            "fingerprint": public_key.fingerprint,
            "userids": [uid.name for uid in public_key.userids],
            "created": public_key.created,
            "algorithm": public_key.key_algorithm.name,
        }
        return key_info


class GPGSignatureVerifyer:
    def __init__(
        self,
        list_of_known_keys: Optional[List[SimpleGPGKey]],
    ) -> None:
        self.list_of_known_keys = list_of_known_keys if list_of_known_keys else []
        self._gpg: Any = None
        self.import_known_keys()

    @staticmethod
    def _get_gpg_path() -> Optional[str]:
        command = "gpg"
        gpg_path = shutil.which(command)
        if gpg_path:
            try:
                subprocess.run(
                    [command, "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                return command
            except subprocess.CalledProcessError:
                return None
        elif platform.system() == "Windows":
            import winreg

            try:
                # Open the registry key
                with winreg.OpenKey(  # type: ignore
                    winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GnuPG", 0, winreg.KEY_READ  # type: ignore
                ) as key:
                    # Read the value of the Install Directory
                    install_dir, _ = winreg.QueryValueEx(key, "Install Directory")  # type: ignore
                    gpg_path = os.path.join(install_dir, "bin", "gpg.exe")
                    if os.path.isfile(gpg_path):
                        return gpg_path
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"Error accessing registry: {e}")
            return None
        return None

    @classmethod
    def is_gnupg_installed(cls) -> bool:
        return bool(cls._get_gpg_path())

    @property
    def gpg(self) -> Any:
        if self._gpg:
            return self._gpg

        if self.is_gnupg_installed():
            global gnupg
            import gnupg as _gnupg

            gnupg = _gnupg

            gpg_path = self._get_gpg_path()
            if not gpg_path:
                raise EnvironmentError("GnuPG path could not be determined.")
            self._gpg = gnupg.GPG(gpgbinary=gpg_path)
            return self._gpg
        else:
            raise EnvironmentError("GnuPG is not installed on this system.")

    def import_known_keys(self) -> None:
        for key in self.list_of_known_keys:
            self.gpg.import_keys(key.key)

    def import_public_key_block(self, public_key_block: str) -> str:
        """
        Import a public key block into the GnuPG keyring and return its fingerprint.

        :param public_key_block: The public key block in ASCII armor format.
        :return: The fingerprint of the imported public key.
        """
        import_result = self.gpg.import_keys(public_key_block)

        if not import_result.results:
            raise ValueError("Failed to import public key.")

        # The 'fingerprint' attribute is available in the import result.
        # For multiple keys, this simple implementation assumes you're interested in the first.
        fingerprint = import_result.results[0]["fingerprint"]
        logger.info(f"Public key imported with fingerprint: {fingerprint}")
        return fingerprint


class SignatureSigner(GPGSignatureVerifyer):
    def __init__(
        self,
        version: str,
        app_name: str,
        list_of_known_keys: Optional[List[SimpleGPGKey]],
        file_dir: str = "dist/",
    ) -> None:
        super().__init__(list_of_known_keys=list_of_known_keys)

        self.file_dir = file_dir
        self.version = version
        self.app_name = app_name

    def get_files_to_sign(self) -> List[Path]:
        return [
            f
            for f in Path(self.file_dir).iterdir()
            if f.is_file() and (not f.name.endswith(".asc")) and (not f.name.startswith("."))
        ]

    def sign_files(self, key: SimpleGPGKey) -> List[Path]:
        my_fingerprint = self.import_public_key_block(key.key)
        files = self.get_files_to_sign()
        for file_path in files:

            self.gpg.sign_file(
                open(file_path, "rb"), keyid=my_fingerprint, detach=True, output=str(file_path) + ".asc"
            )
            logger.info(f"File signed: {file_path.name}.asc")
        return files


@dataclass
class KnownGPGKeys:

    andreasgriffin = SimpleGPGKey(
        key="""
-----BEGIN PGP PUBLIC KEY BLOCK-----

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
26s3OWCbYId2XIroAoNjRiIp
=aRyX
-----END PGP PUBLIC KEY BLOCK-----               
                   """,
        repository="andreasgriffin/bitcoin-safe",
        prefix="bitcoin-safe",
    )
    craigraw = SimpleGPGKey(
        repository="sparrowwallet/sparrow",
        prefix="sparrow",
        manifest_ending="manifest.txt",
        key="""
-----BEGIN PGP PUBLIC KEY BLOCK-----
Comment: GPGTools - http://gpgtools.org

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
EmR2yA==
=t5JY
-----END PGP PUBLIC KEY BLOCK-----

               """,
    )

    @classmethod
    def all(cls) -> List[SimpleGPGKey]:
        return [v for v in cls.__dict__.values() if isinstance(v, SimpleGPGKey)]

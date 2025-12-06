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

import logging
import os
import platform
import shutil
import subprocess
import tarfile
import time
import zipfile
from collections.abc import Generator
from pathlib import Path

import bdkpython as bdk
import pytest
import requests

from bitcoin_safe.util import SATOSHIS_PER_BTC

from .setup_bitcoin_core import (
    BITCOIN_HOST,
    BITCOIN_RPC_PORT,
    RPC_PASSWORD,
    RPC_USER,
    TEST_DIR,
    mine_blocks,
)
from .util import make_psbt

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Globals (examples – adjust them to fit your project’s paths/configuration)
# -------------------------------------------------------------------------
FULCRUM_VERSION = "1.11.1"  # Example version; update as needed
FULCRUM_DIR = TEST_DIR / "fulcrum"
FULCRUM_DATA_DIR = FULCRUM_DIR / "data"
FULCRUM_CONF = FULCRUM_DIR / "fulcrum.conf"
FULCRUM_HOST = BITCOIN_HOST
FULCRUM_PORT = "51001"
FULCRUM_BIN_DIR = FULCRUM_DIR / f"Fulcrum-{FULCRUM_VERSION}"


def _fulcrum_process_name() -> str:
    return "Fulcrum.exe" if platform.system() == "Windows" else "Fulcrum"


def _fulcrum_executable_path() -> Path:
    return FULCRUM_BIN_DIR / _fulcrum_process_name()


# -------------------------------------------------------------------------
# Example content for fulcrum.conf (adjust as needed for your environment)
# -------------------------------------------------------------------------
FULCRUM_CONF_CONTENT = f"""\
# Sample Fulcrum config
datadir={FULCRUM_DATA_DIR}
network=regtest
rpcuser={RPC_USER}
rpcpassword={RPC_PASSWORD}
bitcoind={BITCOIN_HOST}:{BITCOIN_RPC_PORT}

# Fulcrum-specific settings
tcp=127.0.0.1:{FULCRUM_PORT}
"""


# -------------------------------------------------------------------------
# 1) Download and extract Fulcrum
# -------------------------------------------------------------------------
def download_fulcrum():
    """Downloads and extracts the Fulcrum binaries for your platform.

    Adjust the URLs, archive names, and extraction logic as needed.
    """
    system = platform.system()

    if system == "Windows":
        archive_extension = "zip"
        name = f"Fulcrum-{FULCRUM_VERSION}-win64"
        extension = ".zip"
        build_from_source = False
    elif system == "Darwin":  # macOS
        archive_extension = "tar.gz"
        name = f"Fulcrum-{FULCRUM_VERSION}-src"
        extension = ".tar.gz"
        build_from_source = True
    else:  # Assume Linux
        archive_extension = "tar.gz"
        # Example Linux link; update to the actual release artifact name
        name = f"Fulcrum-{FULCRUM_VERSION}-x86_64-linux"
        extension = ".tar.gz"
        build_from_source = False

    url = f"https://github.com/cculianu/Fulcrum/releases/download/v{FULCRUM_VERSION}/{name}{extension}"
    fulcrum_archive = FULCRUM_DIR / f"fulcrum-{FULCRUM_VERSION}.{archive_extension}"

    # Download Fulcrum if necessary
    if not fulcrum_archive.exists():
        logger.info(f"Downloading Fulcrum {FULCRUM_VERSION} from {url} ...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        fulcrum_archive.write_bytes(response.content)
        logger.info("Fulcrum downloaded successfully.")

    # Extract Fulcrum if necessary
    if not FULCRUM_BIN_DIR.exists():
        logger.info(f"Extracting Fulcrum {FULCRUM_VERSION}...")
        if archive_extension == "tar.gz":
            with tarfile.open(fulcrum_archive, "r:gz") as tar:
                tar.extractall(path=FULCRUM_BIN_DIR)
        elif archive_extension == "zip":
            with zipfile.ZipFile(fulcrum_archive, "r") as zip_ref:
                zip_ref.extractall(path=FULCRUM_BIN_DIR)
        else:
            raise ValueError(f"Unsupported archive extension: {archive_extension}")

        # remove 1 layer of the fulcrum folder depths
        shutil.move(FULCRUM_BIN_DIR / name, FULCRUM_DIR)
        shutil.rmtree(FULCRUM_BIN_DIR)
        shutil.move(FULCRUM_DIR / name, FULCRUM_BIN_DIR)

    if system == "Darwin" and build_from_source:
        _build_fulcrum_from_source()

    logger.info(f"Fulcrum {FULCRUM_VERSION} is ready to use.")


def _build_fulcrum_from_source() -> None:
    build_dir = FULCRUM_DIR / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    qmake_path = _locate_qmake()
    logger.info("Configuring Fulcrum build for macOS using %s...", qmake_path)

    # Fulcrum ships a qmake project (Fulcrum.pro). Configure into a build directory to
    # keep the extracted sources pristine.
    subprocess.run(
        [str(qmake_path), str(FULCRUM_BIN_DIR / "Fulcrum.pro")],
        cwd=build_dir,
        check=True,
    )

    logger.info("Building Fulcrum from source for macOS...")
    subprocess.run(
        [
            "make",
            "-j",
            str(os.cpu_count() or 2),
        ],
        cwd=build_dir,
        check=True,
    )

    candidate_paths = [
        build_dir / "Fulcrum",
        build_dir / "bin" / "Fulcrum",
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            shutil.copy2(candidate, FULCRUM_BIN_DIR / "Fulcrum")
            break
    else:
        raise FileNotFoundError("Fulcrum binary not found after building from source on macOS.")


def _locate_qmake() -> Path:
    """Locate a qmake binary provided by Homebrew or the PATH on macOS."""

    candidates = [
        Path("/usr/local/opt/qt@5/bin/qmake"),
        Path("/opt/homebrew/opt/qt@5/bin/qmake"),
        Path(shutil.which("qmake") or ""),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate

    raise FileNotFoundError("qmake not found. Ensure Qt5 is installed (e.g. brew install qt@5).")


def is_fulcrum_running() -> bool:
    """Checks if Fulcrum is running by looking for a matching process name.

    Returns:
        bool: True if Fulcrum is running, False otherwise.
    """
    process_name = _fulcrum_process_name()
    if platform.system() == "Windows":
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            capture_output=True,
            text=True,
        )
        return process_name.lower() in result.stdout.lower()

    result = subprocess.run(["pgrep", "-x", process_name], capture_output=True)
    return result.returncode == 0  # 0 means a match was found


def stop_fulcrum():
    """Stops Fulcrum by sending a kill signal to the process if it is running, using
    pkill."""
    if is_fulcrum_running():
        logger.info("Stopping Fulcrum...")
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/IM", _fulcrum_process_name(), "/F"], check=False)
        else:
            # pkill will send SIGTERM by default, which should gracefully stop Fulcrum.
            subprocess.run(["pkill", "-x", _fulcrum_process_name()], check=False)
        logger.info("Fulcrum has been stopped.")
    else:
        logger.info("Fulcrum is not running.")


def start_fulcrum():
    """Starts Fulcrum."""
    logger.info("Starting Fulcrum...")

    # Create fulcrum.conf
    FULCRUM_CONF.write_text(FULCRUM_CONF_CONTENT)

    # Example: Adjust command, config file path, arguments, etc.
    fulcrum_executable = _fulcrum_executable_path()
    # TODO: tailor command to your environment
    cmd = [
        str(fulcrum_executable),
        str(FULCRUM_CONF),
    ]
    # Start Fulcrum as a background process (example)
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Fulcrum is launched.")


def remove_fulcrum_data():
    """Removes old Fulcrum data, if desired, between test runs."""
    data_dir = FULCRUM_DIR / "data"
    if data_dir.exists():
        logger.info("Removing old Fulcrum data folder...")
        shutil.rmtree(data_dir)


# -------------------------------------------------------------------------
# 2) Pytest fixture: fulcrum
# -------------------------------------------------------------------------
@pytest.fixture(scope="session")
def fulcrum(bitcoin_core: Path) -> Generator[str, None, None]:
    """Ensures Bitcoin Core is running (through the bitcoin_core fixture), then
    downloads, configures, and starts Fulcrum.

    Yields the path to Fulcrum's binary directory for test usage, then tears it down.
    """
    # Make sure the Fulcrum directory exists
    FULCRUM_DIR.mkdir(parents=True, exist_ok=True)

    # Download Fulcrum if not already present
    download_fulcrum()

    # Kill Fulcrum if it is already running
    stop_fulcrum()

    # Remove old data if you want a fresh environment
    remove_fulcrum_data()

    # otherwise fulcrum will not be able to start
    mine_blocks(bitcoin_core)

    # Start Fulcrum
    start_fulcrum()

    # Give Fulcrum a few seconds to initialize
    time.sleep(5)

    yield f"{FULCRUM_HOST}:{FULCRUM_PORT}"

    # Stop Fulcrum after tests
    stop_fulcrum()


class Faucet:
    def __init__(
        self,
        bitcoin_core: Path,
        fulcrum: str,
        mnemonic="romance slush habit speed type also grace coffee grape inquiry receive filter",
    ) -> None:
        """Initialize instance."""
        self.bitcoin_core = bitcoin_core

        self.seed = mnemonic
        self.mnemonic = bdk.Mnemonic.from_string(self.seed)

        self.network = bdk.Network.REGTEST
        self.client = bdk.ElectrumClient(url=fulcrum)

        self.descriptor = bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(self.network, self.mnemonic, ""),
            keychain_kind=bdk.KeychainKind.EXTERNAL,
            network=self.network,
        )
        self.change_descriptor = bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(self.network, self.mnemonic, ""),
            keychain_kind=bdk.KeychainKind.INTERNAL,
            network=self.network,
        )

        self.connection = bdk.Persister.new_in_memory()
        self.bdk_wallet = bdk.Wallet(
            descriptor=self.descriptor,
            change_descriptor=self.change_descriptor,
            network=self.network,
            persister=self.connection,
        )
        self.initial_mine()

    def send(self, destination_address: str, amount=SATOSHIS_PER_BTC, fee_rate=1):
        """Send."""
        psbt_for_signing = make_psbt(
            bdk_wallet=self.bdk_wallet,
            network=self.network,
            destination_address=destination_address,
            amount=amount,
            fee_rate=fee_rate,
        )
        self.bdk_wallet.sign(psbt_for_signing, None)
        self.bdk_wallet.persist(self.connection)

        tx = psbt_for_signing.extract_tx()
        self.client.transaction_broadcast(tx)
        # let fulcrum index the tx
        time.sleep(2)
        self.sync()
        return tx

    def sync(self):
        """Sync."""
        request = self.bdk_wallet.start_full_scan()
        changeset = self.client.full_scan(
            request=request.build(), stop_gap=20, batch_size=10, fetch_prev_txouts=True
        )
        self.bdk_wallet.apply_update(changeset)
        self.bdk_wallet.persist(self.connection)

    def mine(self, blocks=1, address=None):
        """Mine."""
        txs = self.bdk_wallet.transactions()
        address = (
            address
            if address
            else str(self.bdk_wallet.next_unused_address(keychain=bdk.KeychainKind.EXTERNAL).address)
        )
        block_hashes = mine_blocks(
            self.bitcoin_core,
            blocks,
            address=address,
        )
        while len(self.bdk_wallet.transactions()) - len(txs) < len(block_hashes):
            time.sleep(0.5)
            self.sync()
        logger.debug(f"Faucet Wallet balance is: {self.bdk_wallet.balance().total.to_sat()}")

    def initial_mine(self):
        """Initial mine."""
        self.mine(
            blocks=200,
            address=str(self.bdk_wallet.next_unused_address(keychain=bdk.KeychainKind.EXTERNAL).address),
        )


@pytest.fixture(scope="session")
def faucet(bitcoin_core: Path, fulcrum: str) -> Faucet:
    """Faucet."""
    return Faucet(bitcoin_core=bitcoin_core, fulcrum=fulcrum)

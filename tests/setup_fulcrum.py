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


import logging
import platform
import shutil
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Generator

import bdkpython as bdk
import pytest
import requests

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
    """
    Downloads and extracts the Fulcrum binaries for your platform.
    Adjust the URLs, archive names, and extraction logic as needed.
    """
    system = platform.system()

    if system == "Windows":
        raise NotImplementedError("Killing and starting fulcrum is not implemented on windows")
        archive_extension = "zip"
        # Example Windows link; update to the actual release artifact name
        name = f"Fulcrum-{FULCRUM_VERSION}-win64"
        extension = ".zip"
    elif system == "Darwin":  # macOS
        raise NotImplementedError("Fulcrum is not available for mac")
        archive_extension = "tar.gz"
        # Example macOS link; update to the actual release artifact name
        name = f"Fulcrum-{FULCRUM_VERSION}-macos"
        extension = ".tgz"
    else:  # Assume Linux
        archive_extension = "tar.gz"
        # Example Linux link; update to the actual release artifact name
        name = f"Fulcrum-{FULCRUM_VERSION}-x86_64-linux"
        extension = ".tar.gz"

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

    logger.info(f"Fulcrum {FULCRUM_VERSION} is ready to use.")


def is_fulcrum_running() -> bool:
    """
    Checks if Fulcrum is running by looking for a matching process name
    in the process list on Linux using pgrep.

    Returns:
        bool: True if Fulcrum is running, False otherwise.
    """
    # We use pgrep with the -f option to match against the entire command line,
    # and -x to ensure an exact match if you want to precisely match the command "fulcrum".
    # Adjust the pattern if needed (e.g. path to fulcrum, or script name).
    result = subprocess.run(["pgrep", "-x", "Fulcrum"], capture_output=True)
    return result.returncode == 0  # 0 means a match was found


def stop_fulcrum():
    """
    Stops Fulcrum by sending a kill signal to the process if it is running,
    using pkill.
    """
    if is_fulcrum_running():
        logger.info("Stopping Fulcrum...")
        # pkill will send SIGTERM by default, which should gracefully stop Fulcrum.
        subprocess.run(["pkill", "-x", "Fulcrum"], check=False)
        logger.info("Fulcrum has been stopped.")
    else:
        logger.info("Fulcrum is not running.")


def start_fulcrum():
    """
    Starts Fulcrum.
    """
    logger.info("Starting Fulcrum...")

    # Create fulcrum.conf
    FULCRUM_CONF.write_text(FULCRUM_CONF_CONTENT)

    # Example: Adjust command, config file path, arguments, etc.
    fulcrum_executable = FULCRUM_BIN_DIR / "Fulcrum"
    # TODO: tailor command to your environment
    cmd = [
        str(fulcrum_executable),
        str(FULCRUM_CONF),
    ]
    # Start Fulcrum as a background process (example)
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Fulcrum is launched.")


def remove_fulcrum_data():
    """
    Removes old Fulcrum data, if desired, between test runs.
    """
    data_dir = FULCRUM_DIR / "data"
    if data_dir.exists():
        logger.info("Removing old Fulcrum data folder...")
        shutil.rmtree(data_dir)


# -------------------------------------------------------------------------
# 2) Pytest fixture: fulcrum
# -------------------------------------------------------------------------
@pytest.fixture(scope="session")
def fulcrum(bitcoin_core: Path) -> Generator[str, None, None]:
    """
    Ensures Bitcoin Core is running (through the bitcoin_core fixture),
    then downloads, configures, and starts Fulcrum. Yields the path to
    Fulcrum's binary directory for test usage, then tears it down.
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
        self.bitcoin_core = bitcoin_core

        self.seed = mnemonic
        self.mnemonic = bdk.Mnemonic.from_string(self.seed)

        self.network = bdk.Network.REGTEST
        self.client = bdk.ElectrumClient(url=fulcrum)

        self.descriptor = bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(self.network, self.mnemonic, ""),
            keychain=bdk.KeychainKind.EXTERNAL,
            network=self.network,
        )
        self.change_descriptor = bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(self.network, self.mnemonic, ""),
            keychain=bdk.KeychainKind.INTERNAL,
            network=self.network,
        )

        self.connection = bdk.Connection.new_in_memory()
        self.bdk_wallet = bdk.Wallet(
            descriptor=self.descriptor,
            change_descriptor=self.change_descriptor,
            network=self.network,
            connection=self.connection,
        )
        self.initial_mine()

    def send(self, destination_address: str, amount=100_000_000, fee_rate=1):
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
        time.sleep(1)
        self.sync()
        return tx

    def sync(self):
        request = self.bdk_wallet.start_full_scan()
        changeset = self.client.full_scan(
            request=request.build(), stop_gap=20, batch_size=10, fetch_prev_txouts=True
        )
        self.bdk_wallet.apply_update(changeset)
        self.bdk_wallet.persist(self.connection)

    def mine(self, blocks=1, address=None):
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
        self.mine(
            blocks=200,
            address=str(self.bdk_wallet.next_unused_address(keychain=bdk.KeychainKind.EXTERNAL).address),
        )


@pytest.fixture(scope="session")
def faucet(bitcoin_core: Path, fulcrum: str) -> Faucet:
    return Faucet(bitcoin_core=bitcoin_core, fulcrum=fulcrum)

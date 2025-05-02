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


import json
import logging
import os
import platform
import shlex
import shutil
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Generator, List

import pytest
import requests

logger = logging.getLogger(__name__)

BITCOIN_HOST = "127.0.0.1"
BITCOIN_RPC_PORT = 17143  # not the default 18443 to not get conflicts
BITCOIN_LISTEN_PORT = 17144  # not the default 18444 to not get conflicts
RPC_USER = "bitcoin"
RPC_PASSWORD = "bitcoin"
BITCOIN_CONF_CONTENT = f"""
regtest=1

[regtest]


# RPC server options
rpcport={BITCOIN_RPC_PORT}
rpcbind={BITCOIN_HOST}
rpcallowip={BITCOIN_HOST}
rpcuser={RPC_USER}
rpcpassword={RPC_PASSWORD}
server=1
port={BITCOIN_LISTEN_PORT}



# Enable serving of bloom filters (useful for SPV clients)
peerbloomfilters=1

# Enable serving compact block filters
blockfilterindex=1

# Enable serving of historic blocks
txindex=1
"""

BITCOIN_VERSION = "28.1"
# Define the Bitcoin Core directory relative to the current test directory
TEST_DIR = Path(__file__).parent  # If this script is in the tests directory
BITCOIN_DIR = TEST_DIR / "bitcoin_core"
BITCOIN_CONF = BITCOIN_DIR / "bdk.conf"
BITCOIN_ARCHIVE = BITCOIN_DIR / f"bitcoin-{BITCOIN_VERSION}-x86_64-linux-gnu.tar.gz"
BITCOIN_EXTRACT_DIR = BITCOIN_DIR / f"bitcoin-{BITCOIN_VERSION}"
BITCOIN_BIN_DIR = BITCOIN_EXTRACT_DIR / "bin"


def runcmd(cmd, background=False):
    try:
        system = platform.system()
        if system == "Windows":
            # On Windows, use subprocess.Popen to start the process without blocking
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        else:
            process = subprocess.Popen(
                shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )

        if background:
            return process
        stdout, stderr = process.communicate()
        if stderr:
            raise Exception(stderr)
        return stdout

    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running bitcoind: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None


def bitcoind():
    """ """
    system = platform.system()
    executable = "bitcoind.exe" if system == "Windows" else "bitcoind"
    cmd = f"{BITCOIN_BIN_DIR / executable}    -conf={BITCOIN_CONF}"

    if system != "Windows":
        cmd += " -daemon"

    runcmd(cmd, background=True)


def bitcoin_cli(
    command,
    bitcoin_core: Path,
    bitcoin_host=BITCOIN_HOST,
    bitcoin_port=BITCOIN_RPC_PORT,
    rpc_user=RPC_USER,
    rpc_password=RPC_PASSWORD,
):
    """
    Run a bitcoin-cli command with the specified parameters.

    Parameters:
    - command: The bitcoin-cli command to execute.
    - bitcoin_core: Path to the directory containing bitcoin-cli.
    - bitcoin_host: Host for RPC connection (default: localhost).
    - bitcoin_port: Port for RPC connection (default: 8332).
    - rpc_user: RPC username (default: bitcoin).
    - rpc_password: RPC password (default: bitcoin).

    Returns:
    - The result of subprocess.run containing stdout, stderr, and return code.
    """
    system = platform.system()
    executable = "bitcoin-cli.exe" if system == "Windows" else "bitcoin-cli"
    cmd = (
        str(bitcoin_core / executable)
        + f" -rpcconnect={bitcoin_host} -rpcport={bitcoin_port} -chain=regtest -rpcuser={rpc_user} -rpcpassword={rpc_password} "
        + command
    )
    return runcmd(cmd)


def get_default_bitcoin_data_dir():
    """Get the default Bitcoin data directory based on the operating system."""
    system = platform.system()
    if system == "Windows":
        appdata = os.getenv("APPDATA")
        assert appdata
        return Path(appdata) / "Bitcoin"
    elif system == "Darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "Bitcoin"
    else:  # Assume Linux/Unix
        return Path.home() / ".bitcoin"


def remove_bitcoin_regtest_folder(custom_datadir=None):
    """
    Remove the regtest folder from the Bitcoin data directory.

    Parameters:
    - custom_datadir: Optional custom Bitcoin data directory.
    """
    try:
        if custom_datadir:
            bitcoin_data_dir = Path(custom_datadir)
        else:
            bitcoin_data_dir = get_default_bitcoin_data_dir()

        regtest_dir = bitcoin_data_dir / "regtest"

        if regtest_dir.exists() and regtest_dir.is_dir():
            shutil.rmtree(regtest_dir)
            print(f"Removed {regtest_dir}")
        else:
            print(f"{regtest_dir} does not exist or is not a directory")
    except Exception as e:
        print(f"An error occurred: {e}")


def download_bitcoin():
    system = platform.system()

    if system == "Windows":
        archive_extension = "zip"
        url = (
            f"https://bitcoincore.org/bin/bitcoin-core-{BITCOIN_VERSION}/bitcoin-{BITCOIN_VERSION}-win64.zip"
        )
    elif system == "Darwin":  # macOS
        archive_extension = "tar.gz"
        url = f"https://bitcoincore.org/bin/bitcoin-core-{BITCOIN_VERSION}/bitcoin-{BITCOIN_VERSION}-x86_64-apple-darwin.tar.gz"
    else:  # Assume Linux
        archive_extension = "tar.gz"
        url = f"https://bitcoincore.org/bin/bitcoin-core-{BITCOIN_VERSION}/bitcoin-{BITCOIN_VERSION}-x86_64-linux-gnu.tar.gz"

    BITCOIN_ARCHIVE = BITCOIN_DIR / f"bitcoin-{BITCOIN_VERSION}.{archive_extension}"

    # Download Bitcoin Core if necessary
    if not BITCOIN_ARCHIVE.exists():
        logger.info(f"Downloading Bitcoin Core {BITCOIN_VERSION}...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        BITCOIN_ARCHIVE.write_bytes(response.content)

    # Extract Bitcoin Core if necessary
    if not BITCOIN_BIN_DIR.exists():
        logger.info(f"Extracting Bitcoin Core {BITCOIN_VERSION}...")
        if archive_extension == "tar.gz":
            with tarfile.open(BITCOIN_ARCHIVE, "r:gz") as tar:
                tar.extractall(path=BITCOIN_DIR)
        elif archive_extension == "zip":
            with zipfile.ZipFile(BITCOIN_ARCHIVE, "r") as zip_ref:
                zip_ref.extractall(path=BITCOIN_DIR)
        else:
            raise ValueError(f"Unsupported archive extension: {archive_extension}")

    logger.info(f"Bitcoin Core {BITCOIN_VERSION} is ready to use.")


@pytest.fixture(scope="session")
def bitcoin_core() -> Generator[Path, None, None]:
    # Ensure Bitcoin Core directory exists
    BITCOIN_DIR.mkdir(exist_ok=True)

    download_bitcoin()
    # Create bdk.conf
    BITCOIN_CONF.write_text(BITCOIN_CONF_CONTENT)

    # stop it if it is running
    bitcoin_cli("stop", BITCOIN_BIN_DIR)
    # to ensure bitcoind is stopped
    time.sleep(1)
    # remove the previous chain
    remove_bitcoin_regtest_folder()

    # Start Bitcoin Core
    bitcoind()

    # Wait for Bitcoin Core to start
    time.sleep(5)

    yield BITCOIN_BIN_DIR

    # Stop Bitcoin Core
    bitcoin_cli("stop", BITCOIN_BIN_DIR)


# Assuming the bitcoin_core fixture sets up Bitcoin Core and yields the binary directory
def test_get_blockchain_info(bitcoin_core: Path):
    # Execute the command to get blockchain information
    result = bitcoin_cli("getblockchaininfo", bitcoin_core)

    # Parse the output as JSON
    blockchain_info = json.loads(result)

    # Verify some expected fields are present and correct
    assert blockchain_info["chain"] == "regtest", "The chain type should be 'regtest'"
    assert "blocks" in blockchain_info, "'blocks' field is missing from blockchain info"
    assert "headers" in blockchain_info, "'headers' field is missing from blockchain info"


def mine_blocks(
    bitcoin_core: Path, n=1, address="bcrt1qdlxaahyrtx7g76c9l6szn4qn979ku4j6wx67vv5qvtf888y7lcpqdsnhxg"
) -> List[str]:
    # Mine n blocks to the specified address
    result = bitcoin_cli(f"generatetoaddress {n} {address}", bitcoin_core)
    return json.loads(result.strip())


def test_mine_blocks(bitcoin_core: Path):
    block_hashes = mine_blocks(bitcoin_core, 10)
    assert len(block_hashes) > 0

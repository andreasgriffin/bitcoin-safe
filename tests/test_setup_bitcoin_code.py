import json
import shlex
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Generator

import pytest
import requests

BITCOIN_HOST = "127.0.0.1"
BITCOIN_PORT = 18143  # not the default 18443 to not get conflicts
RPC_USER = "bitcoin"
RPC_PASSWORD = "bitcoin"
BITCOIN_CONF_CONTENT = f"""
regtest=1

[regtest]


# RPC server options
rpcport={BITCOIN_PORT}
rpcallowip={BITCOIN_HOST}
rpcuser={RPC_USER}
rpcpassword={RPC_PASSWORD}
server=1



# Enable serving of bloom filters (useful for SPV clients)
peerbloomfilters=1

# Enable serving compact block filters
blockfilterindex=1

# Enable serving of historic blocks
txindex=1
"""

BITCOIN_VERSION = "0.21.0"
# Define the Bitcoin Core directory relative to the current test directory
TEST_DIR = Path(__file__).parent  # If this script is in the tests directory
BITCOIN_DIR = TEST_DIR / "bitcoin_core"
BITCOIN_CONF = BITCOIN_DIR / "bitcoin.conf"
BITCOIN_ARCHIVE = BITCOIN_DIR / f"bitcoin-{BITCOIN_VERSION}-x86_64-linux-gnu.tar.gz"
BITCOIN_EXTRACT_DIR = BITCOIN_DIR / f"bitcoin-{BITCOIN_VERSION}"
BITCOIN_BIN_DIR = BITCOIN_EXTRACT_DIR / "bin"


def bitcoin_cli(command, bitcoin_core: Path):
    cmd = (
        str(bitcoin_core / "bitcoin-cli")
        + f" -rpcconnect={BITCOIN_HOST}  -rpcport={BITCOIN_PORT} -regtest -rpcuser=bitcoin -rpcpassword=bitcoin "
        + command
    )
    return subprocess.run(shlex.split(cmd), capture_output=True, text=True)


@pytest.fixture(scope="session", autouse=True)
def bitcoin_core() -> Generator[Path, None, None]:
    # Ensure Bitcoin Core directory exists
    BITCOIN_DIR.mkdir(exist_ok=True)

    # Download Bitcoin Core if necessary
    if not BITCOIN_ARCHIVE.exists():
        print(f"Downloading Bitcoin Core {BITCOIN_VERSION}...")
        url = f"https://bitcoincore.org/bin/bitcoin-core-{BITCOIN_VERSION}/bitcoin-{BITCOIN_VERSION}-x86_64-linux-gnu.tar.gz"
        response = requests.get(url)
        BITCOIN_ARCHIVE.write_bytes(response.content)

    # Extract Bitcoin Core if necessary
    if not BITCOIN_BIN_DIR.exists():
        print(f"Extracting Bitcoin Core {BITCOIN_VERSION}...")
        with tarfile.open(BITCOIN_ARCHIVE, "r:gz") as tar:
            tar.extractall(path=BITCOIN_DIR)

    # Create bitcoin.conf
    BITCOIN_CONF.write_text(BITCOIN_CONF_CONTENT)

    # Start Bitcoin Core
    subprocess.run([BITCOIN_BIN_DIR / "bitcoind", "-regtest", "-daemon", f"-conf={BITCOIN_CONF}"])

    # Wait for Bitcoin Core to start
    time.sleep(5)

    yield BITCOIN_BIN_DIR

    # Stop Bitcoin Core
    bitcoin_cli("stop", BITCOIN_BIN_DIR)


# Assuming the bitcoin_core fixture sets up Bitcoin Core and yields the binary directory
def test_get_blockchain_info(bitcoin_core):
    # Execute the command to get blockchain information
    result = bitcoin_cli("getblockchaininfo", bitcoin_core)

    # Check if there was an error
    assert result.stderr == "", f"Error getting blockchain info: {result.stderr}"

    # Parse the output as JSON
    blockchain_info = json.loads(result.stdout)

    # Verify some expected fields are present and correct
    assert blockchain_info["chain"] == "regtest", "The chain type should be 'regtest'"
    assert "blocks" in blockchain_info, "'blocks' field is missing from blockchain info"
    assert "headers" in blockchain_info, "'headers' field is missing from blockchain info"


def mine_blocks(
    bitcoin_core, n=1, address="bcrt1qdlxaahyrtx7g76c9l6szn4qn979ku4j6wx67vv5qvtf888y7lcpqdsnhxg"
):
    # Mine n blocks to the specified address
    result = bitcoin_cli(f"generatetoaddress {n} {address}", bitcoin_core)
    return result.stdout.strip()


def test_mine_blocks(bitcoin_core):
    block_hashes = mine_blocks(bitcoin_core, 10)
    assert len(block_hashes) > 0

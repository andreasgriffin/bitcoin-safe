#
# Bitcoin-Safe
# Copyright (C) 2025-2026 Andreas Griffin
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
#

from __future__ import annotations

import json
import logging
import os
import platform
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Generator
from pathlib import Path

import psutil
import pytest

from .release_archive import download_verified, extract_verified

logger = logging.getLogger(__name__)

BITCOIN_HOST = "127.0.0.1"
BITCOIN_RPC_PORT = 17143  # not the default 18443 to not get conflicts
BITCOIN_LISTEN_PORT = 17144  # not the default 18444 to not get conflicts
RPC_USER = "bitcoin"
RPC_PASSWORD = "bitcoin"
BITCOIN_DATA_DIR = Path(__file__).parent / "bitcoin_data"
BITCOIN_CONF_CONTENT = f"""
regtest=1

[regtest]

datadir={BITCOIN_DATA_DIR}


# RPC server options
rpcport={BITCOIN_RPC_PORT}
rpcbind={BITCOIN_HOST}
rpcallowip={BITCOIN_HOST}
rpcuser={RPC_USER}
rpcpassword={RPC_PASSWORD}
v2transport=1
server=1
port={BITCOIN_LISTEN_PORT}



# Enable serving of bloom filters (useful for SPV clients)
peerbloomfilters=1

# Enable serving compact block filters to peers (BIP157/158)
peerblockfilters=1

# Enable serving compact block filters
blockfilterindex=1

# Enable serving of historic blocks
txindex=1
"""

BITCOIN_VERSION = "32.1"
# SHA256SUMS signed by Ava Chow (152812300785C96444D3334D17565732E08E5E41).
BITCOIN_CHECKSUMS = {
    "x86_64-linux-gnu.tar.gz": "61545c17c3120fb7412f896d248b11993af04ec8817aad3649c55b2afb044963",
    "x86_64-apple-darwin.tar.gz": "53b1e6ffd92843ca82ef4a737d7a53cb0a9fab15816a417a41f12fc954071447",
    "arm64-apple-darwin.tar.gz": "cd3dcdacb4ff861e862b2d7df4786ecef66472e2468dca1673a70dd761e064e7",
    "win64.zip": "b5b0c2cd007d69e96880907c79f9ae19ae82728f95fc8c923b4a07dab795b45d",
}
# Define the Bitcoin Core directory relative to the current test directory
TEST_DIR = Path(__file__).parent  # If this script is in the tests directory
BITCOIN_DIR = TEST_DIR / "bitcoin_core"
BITCOIN_CONF = BITCOIN_DIR / "bdk.conf"
BITCOIN_EXTRACT_DIR = BITCOIN_DIR / f"bitcoin-{BITCOIN_VERSION}"
BITCOIN_BIN_DIR = BITCOIN_EXTRACT_DIR / "bin"
BITCOIN_ARTIFACT_STAMP = BITCOIN_DIR / ".artifact_name"


BITCOIN_executable = "bitcoind.exe" if platform.system() == "Windows" else "bitcoind"


def bitcoin_release_artifact() -> str:
    """Return the platform-specific archive filename for Bitcoin Core."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return f"bitcoin-{BITCOIN_VERSION}-win64.zip"
    if system == "Darwin" and machine in {"arm64", "aarch64", "x86_64"}:
        architecture = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
        return f"bitcoin-{BITCOIN_VERSION}-{architecture}-apple-darwin.tar.gz"
    if system == "Linux" and machine in {"amd64", "x86_64"}:
        return f"bitcoin-{BITCOIN_VERSION}-x86_64-linux-gnu.tar.gz"
    raise NotImplementedError(f"Unsupported Bitcoin Core platform: {system} {machine}")


def runcmd(cmd, background: bool = False):
    """Run a shell command and return stdout; raise with stderr on failure."""
    try:
        system = platform.system()
        if background:
            if system == "Windows":
                return subprocess.Popen(
                    cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
            return subprocess.Popen(
                shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )

        if system == "Windows":
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        else:
            proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True)

        if proc.returncode != 0:
            raise RuntimeError(f"{cmd} failed with {proc.returncode}: {proc.stderr.strip()}")

        return proc.stdout.strip()

    except Exception as e:  # noqa: BLE001
        logger.error("Command failed: %s", e)
        return None


def bitcoind() -> None:
    """"""
    system = platform.system()
    cmd = f"{BITCOIN_BIN_DIR / BITCOIN_executable}    -conf={BITCOIN_CONF}"

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
    """Run a bitcoin-cli command with the specified parameters.

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
        + f" -datadir={BITCOIN_DATA_DIR}"
        + f" -rpcconnect={bitcoin_host} -rpcport={bitcoin_port} -chain=regtest"
        + f" -rpcuser={rpc_user} -rpcpassword={rpc_password} "
        + command
    )
    return runcmd(cmd)


def _remove_tree_with_retries(path: Path, attempts: int = 20, delay: float = 0.25) -> None:
    """Remove a directory tree while tolerating transient Windows file-handle races."""
    if not path.exists():
        return

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(delay * (attempt + 1))

    if last_error:
        raise last_error


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


def remove_bitcoin_regtest_folder(custom_datadir: Path | None = None) -> None:
    """Remove the fixture's regtest chain, raising if cleanup fails."""
    bitcoin_data_dir = custom_datadir or get_default_bitcoin_data_dir()
    _remove_tree_with_retries(bitcoin_data_dir / "regtest")


def download_bitcoin():
    """Download bitcoin."""
    artifact_name = bitcoin_release_artifact()
    suffix = artifact_name.removeprefix(f"bitcoin-{BITCOIN_VERSION}-")
    url = f"https://bitcoincore.org/bin/bitcoin-core-{BITCOIN_VERSION}/{artifact_name}"
    bitcoin_archive = BITCOIN_DIR / artifact_name
    download_verified(url, bitcoin_archive, BITCOIN_CHECKSUMS[suffix])

    if BITCOIN_ARTIFACT_STAMP.exists() and BITCOIN_ARTIFACT_STAMP.read_text().strip() != artifact_name:
        shutil.rmtree(BITCOIN_EXTRACT_DIR, ignore_errors=True)
    if not BITCOIN_BIN_DIR.exists():
        shutil.rmtree(BITCOIN_EXTRACT_DIR, ignore_errors=True)
        # A failed extraction cannot leave a directory that looks like a complete cache.
        with tempfile.TemporaryDirectory(dir=BITCOIN_DIR) as temporary:
            extract_verified(bitcoin_archive, Path(temporary))
            shutil.move(str(Path(temporary) / BITCOIN_EXTRACT_DIR.name), str(BITCOIN_EXTRACT_DIR))

    BITCOIN_ARTIFACT_STAMP.write_text(artifact_name)
    logger.info(f"Bitcoin Core {BITCOIN_VERSION} is ready to use.")


def stop_bitcoind(
    ports: tuple[int, ...] = (BITCOIN_RPC_PORT, BITCOIN_LISTEN_PORT), timeout: float = 10.0
) -> None:
    """Stop bitcoind processes listening on the fixture's ports."""
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").lower() not in {"bitcoind", "bitcoind.exe"}:
                continue
            connections = process.net_connections(kind="tcp")
            if not any(
                connection.status == psutil.CONN_LISTEN and connection.laddr.port in ports
                for connection in connections
            ):
                continue
            logger.info("Stopping bitcoind on a fixture port (pid %s)", process.pid)
            rpc_listening = any(
                connection.status == psutil.CONN_LISTEN
                and connection.laddr.port == BITCOIN_RPC_PORT
                and connection.laddr.ip in {BITCOIN_HOST, "0.0.0.0"}
                for connection in connections
            )
            if rpc_listening and bitcoin_cli("stop", BITCOIN_BIN_DIR) is not None:
                try:
                    process.wait(timeout=timeout)
                    continue
                except psutil.TimeoutExpired:
                    pass
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
            continue


def ensure_fixture_ports_available() -> None:
    """Fail before deleting data when a port is held by a process we could not stop."""
    for port in (BITCOIN_RPC_PORT, BITCOIN_LISTEN_PORT):
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex((BITCOIN_HOST, port)) == 0:
                raise RuntimeError(f"Bitcoin Core fixture port {port} is already in use")


@pytest.fixture(scope="session")
def bitcoin_core() -> Generator[Path, None, None]:
    # Ensure Bitcoin Core directory exists
    """Bitcoin core."""
    BITCOIN_DIR.mkdir(exist_ok=True)
    BITCOIN_DATA_DIR.mkdir(parents=True, exist_ok=True)

    stop_bitcoind()
    ensure_fixture_ports_available()
    download_bitcoin()
    # Create bdk.conf
    BITCOIN_CONF.write_text(BITCOIN_CONF_CONTENT)

    # remove the previous chain
    remove_bitcoin_regtest_folder(custom_datadir=BITCOIN_DATA_DIR)

    # Start Bitcoin Core
    bitcoind()

    # Wait for Bitcoin Core to start responding on RPC
    def wait_for_rpc(timeout: float = 30.0, interval: float = 0.5) -> None:
        """Poll getblockchaininfo until bitcoind responds or timeout."""
        start = time.time()
        while True:
            proc = subprocess.run(
                [
                    str(
                        BITCOIN_BIN_DIR
                        / ("bitcoin-cli.exe" if platform.system() == "Windows" else "bitcoin-cli")
                    ),
                    f"-datadir={BITCOIN_DATA_DIR}",
                    f"-rpcconnect={BITCOIN_HOST}",
                    f"-rpcport={BITCOIN_RPC_PORT}",
                    "-chain=regtest",
                    f"-rpcuser={RPC_USER}",
                    f"-rpcpassword={RPC_PASSWORD}",
                    "getblockchaininfo",
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                return
            if time.time() - start > timeout:
                raise TimeoutError(f"bitcoind did not become ready in time: {proc.stderr.strip()}")
            time.sleep(interval)

    try:
        wait_for_rpc()
        yield BITCOIN_BIN_DIR
    finally:
        stop_bitcoind()


# Assuming the bitcoin_core fixture sets up Bitcoin Core and yields the binary directory
def test_get_blockchain_info(bitcoin_core: Path):
    # Execute the command to get blockchain information
    """Test get blockchain info."""
    result = bitcoin_cli("getblockchaininfo", bitcoin_core)

    # Parse the output as JSON
    blockchain_info = json.loads(result)

    # Verify some expected fields are present and correct
    assert blockchain_info["chain"] == "regtest", "The chain type should be 'regtest'"
    assert "blocks" in blockchain_info, "'blocks' field is missing from blockchain info"
    assert "headers" in blockchain_info, "'headers' field is missing from blockchain info"


def mine_blocks(
    bitcoin_core: Path, n=1, address="bcrt1qdlxaahyrtx7g76c9l6szn4qn979ku4j6wx67vv5qvtf888y7lcpqdsnhxg"
) -> list[str]:
    # Mine n blocks to the specified address
    """Mine blocks."""
    result = bitcoin_cli(f"generatetoaddress {n} {address}", bitcoin_core)
    return json.loads(result.strip())


def test_mine_blocks(bitcoin_core: Path):
    """Test mine blocks."""
    block_hashes = mine_blocks(bitcoin_core, 10)
    assert len(block_hashes) > 0

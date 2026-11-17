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
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from .release_archive import download_verified, extract_verified
from .setup_bitcoin_core import (
    BITCOIN_HOST,
    BITCOIN_RPC_PORT,
    RPC_PASSWORD,
    RPC_USER,
    TEST_DIR,
    bitcoin_cli,
    mine_blocks,
)

logger = logging.getLogger(__name__)

FULCRUM_VERSION = "2.1.4"
FULCRUM_DIR = TEST_DIR / "fulcrum"
FULCRUM_DATA_DIR = FULCRUM_DIR / "data"
FULCRUM_CONF = FULCRUM_DIR / "fulcrum.conf"
FULCRUM_HOST = BITCOIN_HOST
FULCRUM_PORT = "51001"
FULCRUM_BIN_DIR = FULCRUM_DIR / f"Fulcrum-{FULCRUM_VERSION}"
# SHA256 sums signed by Calin Culianu (D465135F97D0047E18E99DC321810A542031C02C).
FULCRUM_SHA256 = "faf7cb36266c1694c834ad551d9592c0aef357bca66fdb5efdfe0d131c4b38ae"

FULCRUM_CONF_CONTENT = f"""\
datadir={FULCRUM_DATA_DIR}
network=regtest
rpcuser={RPC_USER}
rpcpassword={RPC_PASSWORD}
bitcoind={BITCOIN_HOST}:{BITCOIN_RPC_PORT}
tcp={FULCRUM_HOST}:{FULCRUM_PORT}
"""


def download_fulcrum() -> None:
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise NotImplementedError("The Fulcrum fixture supports x86-64 Linux only")
    name = f"Fulcrum-{FULCRUM_VERSION}-x86_64-linux"
    archive = FULCRUM_DIR / f"fulcrum-{FULCRUM_VERSION}.tar.gz"
    url = f"https://github.com/cculianu/Fulcrum/releases/download/v{FULCRUM_VERSION}/{name}.tar.gz"
    download_verified(url, archive, FULCRUM_SHA256)
    if not (FULCRUM_BIN_DIR / "Fulcrum").is_file():
        shutil.rmtree(FULCRUM_BIN_DIR, ignore_errors=True)
        with tempfile.TemporaryDirectory(dir=FULCRUM_DIR) as temporary:
            extract_verified(archive, Path(temporary))
            shutil.move(str(Path(temporary) / name), str(FULCRUM_BIN_DIR))


def is_fulcrum_running() -> bool:
    """Checks if Fulcrum is running by looking for a matching process name in the
    process list on Linux using pgrep.

    Returns:
        bool: True if Fulcrum is running, False otherwise.
    """
    # We use pgrep with the -f option to match against the entire command line,
    # and -x to ensure an exact match if you want to precisely match the command "fulcrum".
    # Adjust the pattern if needed (e.g. path to fulcrum, or script name).
    result = subprocess.run(["pgrep", "-x", "Fulcrum"], capture_output=True)
    return result.returncode == 0  # 0 means a match was found


def stop_fulcrum() -> None:
    """Stops Fulcrum by sending a kill signal to the process if it is running, using
    pkill."""
    if is_fulcrum_running():
        logger.info("Stopping Fulcrum...")
        # pkill will send SIGTERM by default, which should gracefully stop Fulcrum.
        subprocess.run(["pkill", "-x", "Fulcrum"], check=False)
        logger.info("Fulcrum has been stopped.")
    else:
        logger.info("Fulcrum is not running.")


def start_fulcrum() -> subprocess.Popen[bytes]:
    """Starts Fulcrum."""
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
    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Fulcrum is launched.")
    return process


def wait_for_fulcrum(process: subprocess.Popen[bytes], height: int, timeout: float = 90) -> None:
    """Wait until the Electrum server answers and has indexed the Bitcoin tip."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Fulcrum exited with status {process.returncode}")
        try:
            with socket.create_connection((FULCRUM_HOST, int(FULCRUM_PORT)), timeout=1) as connection:
                connection.settimeout(1)
                connection.sendall(b'{"id":1,"method":"blockchain.headers.subscribe","params":[]}\n')
                with connection.makefile("rb") as response:
                    result = json.loads(response.readline())
                tip = result.get("result")
                if isinstance(tip, dict) and tip.get("height", -1) >= height:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise TimeoutError("Fulcrum did not synchronize and answer Electrum requests")


@pytest.fixture(scope="session")
def fulcrum(bitcoin_core: Path, backend: str) -> Generator[str | None, None, None]:
    if backend != "fulcrum":
        yield None
        return

    FULCRUM_DIR.mkdir(parents=True, exist_ok=True)
    download_fulcrum()
    stop_fulcrum()
    if FULCRUM_DATA_DIR.exists():
        shutil.rmtree(FULCRUM_DATA_DIR)
    FULCRUM_DATA_DIR.mkdir()
    mine_blocks(bitcoin_core)
    height = bitcoin_cli("getblockcount", bitcoin_core)
    if height is None:
        raise RuntimeError("Could not read Bitcoin Core height")
    process = start_fulcrum()
    try:
        wait_for_fulcrum(process, int(height))
        yield f"{FULCRUM_HOST}:{FULCRUM_PORT}"
    finally:
        stop_fulcrum()

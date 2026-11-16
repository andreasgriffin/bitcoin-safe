#
# Bitcoin-Safe
# Copyright (C) 2024-2026 Andreas Griffin
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
import socket
import subprocess
import time
from pathlib import Path

from .setup_bitcoin_core import BITCOIN_executable, bitcoin_cli, stop_bitcoind


# Assuming the bitcoin_core fixture sets up Bitcoin Core and yields the binary directory
def test_get_blockchain_info(bitcoin_core: Path) -> None:
    # Execute the command to get blockchain information
    """Test get blockchain info."""
    # Call bitcoin-cli and parse JSON output.
    result = bitcoin_cli("getblockchaininfo", bitcoin_core)

    # Parse the output as JSON
    blockchain_info = json.loads(result)

    # Verify some expected fields are present and correct
    assert blockchain_info["chain"] == "regtest", "The chain type should be 'regtest'"
    assert "blocks" in blockchain_info, "'blocks' field is missing from blockchain info"
    assert "headers" in blockchain_info, "'headers' field is missing from blockchain info"


def mine_blocks(
    bitcoin_core: Path,
    n: int = 1,
    address: str = "bcrt1qdlxaahyrtx7g76c9l6szn4qn979ku4j6wx67vv5qvtf888y7lcpqdsnhxg",
) -> str:
    # Mine n blocks to the specified address
    """Mine blocks."""
    # Use generatetoaddress for deterministic block creation.
    result = bitcoin_cli(f"generatetoaddress {n} {address}", bitcoin_core)
    return result.strip()


def test_mine_blocks(bitcoin_core: Path) -> None:
    """Test mine blocks."""
    # Mining should return at least one block hash.
    block_hashes = mine_blocks(bitcoin_core, 10)
    assert len(block_hashes) > 0


def test_core_psbt_versions(bitcoin_core: Path) -> None:
    """Core 32 defaults to v2; explicitly request v0 for BDK consumers."""
    import bdkpython as bdk

    default = bitcoin_cli("-named createpsbt inputs=[] outputs={}", bitcoin_core)
    assert default is not None
    decoded = bitcoin_cli(f"decodepsbt {default}", bitcoin_core)
    assert decoded is not None
    assert json.loads(decoded)["psbt_version"] == 2

    compatible = bitcoin_cli("-named createpsbt inputs=[] outputs={} psbt_version=0", bitcoin_core)
    assert compatible is not None
    bdk.Psbt(compatible)


def test_stop_bitcoind_only_stops_matching_port(bitcoin_core: Path, tmp_path: Path) -> None:
    sockets = [socket.socket(), socket.socket()]
    for listener in sockets:
        listener.bind(("127.0.0.1", 0))
    ports = [listener.getsockname()[1] for listener in sockets]
    for listener in sockets:
        listener.close()

    processes: list[subprocess.Popen[bytes]] = []
    try:
        for port in ports:
            data_dir = tmp_path / str(port)
            data_dir.mkdir()
            processes.append(
                subprocess.Popen(
                    [
                        str(bitcoin_core / BITCOIN_executable),
                        f"-datadir={data_dir}",
                        "-regtest",
                        "-server=0",
                        "-listen=1",
                        f"-bind=127.0.0.1:{port}",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        deadline = time.monotonic() + 15
        for process, port in zip(processes, ports, strict=True):
            while True:
                assert process.poll() is None
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        break
                assert time.monotonic() < deadline, f"bitcoind did not listen on {port}"
                time.sleep(0.1)

        stop_bitcoind((ports[0],))
        assert processes[0].wait(timeout=10) is not None
        assert processes[1].poll() is None
        assert bitcoin_cli("getblockchaininfo", bitcoin_core) is not None
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def test_stop_bitcoind_leaves_other_listeners_alone() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        stop_bitcoind((port,))
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass

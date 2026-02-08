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

import json
from pathlib import Path

from .setup_bitcoin_core import bitcoin_cli


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

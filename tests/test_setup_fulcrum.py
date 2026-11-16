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

import hashlib
import json
import socket
from pathlib import Path

from .setup_bitcoin_core import bitcoin_cli, mine_blocks


def test_fulcrum_history_and_subscriptions(bitcoin_core: Path, fulcrum: str | None) -> None:
    if fulcrum is None:
        return
    address = "bcrt1qdlxaahyrtx7g76c9l6szn4qn979ku4j6wx67vv5qvtf888y7lcpqdsnhxg"
    result = bitcoin_cli(f"validateaddress {address}", bitcoin_core)
    assert result is not None
    script = bytes.fromhex(json.loads(result)["scriptPubKey"])
    script_hash = hashlib.sha256(script).digest()[::-1].hex()
    host, port = fulcrum.split(":")
    with socket.create_connection((host, int(port)), timeout=15) as connection:
        connection.settimeout(15)
        with connection.makefile("rwb") as stream:

            def request(request_id: int, method: str, params: list[object]) -> dict:
                stream.write(
                    json.dumps({"id": request_id, "method": method, "params": params}).encode() + b"\n"
                )
                stream.flush()
                while True:
                    response = json.loads(stream.readline())
                    if response.get("id") == request_id:
                        assert response.get("error") is None
                        return response

            request(1, "blockchain.scripthash.subscribe", [script_hash])
            mine_blocks(bitcoin_core, address=address)
            notification = json.loads(stream.readline())
            assert notification["method"] == "blockchain.scripthash.subscribe"
            assert notification["params"][0] == script_hash
            history = request(2, "blockchain.scripthash.get_history", [script_hash])["result"]
            assert history
            transaction = request(3, "blockchain.transaction.get", [history[-1]["tx_hash"]])["result"]
            assert bytes.fromhex(transaction)

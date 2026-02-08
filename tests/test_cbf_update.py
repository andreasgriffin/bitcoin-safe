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


"""
This is a minimal example on how to get cbf working
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import bdkpython as bdk

from bitcoin_safe.cbf.cbf_sync import CbfSync

from .setup_bitcoin_core import BITCOIN_LISTEN_PORT, bitcoin_cli, mine_blocks


def _build_test_wallet(network: bdk.Network) -> tuple[bdk.Wallet, bdk.Persister, str]:
    """Create a deterministic regtest wallet and reveal the first receive address."""
    mnemonic = bdk.Mnemonic.from_string(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    )
    external_descriptor = bdk.Descriptor.new_bip86(
        secret_key=bdk.DescriptorSecretKey(network, mnemonic, ""),
        keychain_kind=bdk.KeychainKind.EXTERNAL,
        network=network,
    )
    change_descriptor = bdk.Descriptor.new_bip86(
        secret_key=bdk.DescriptorSecretKey(network, mnemonic, ""),
        keychain_kind=bdk.KeychainKind.INTERNAL,
        network=network,
    )
    persister = bdk.Persister.new_in_memory()
    wallet = bdk.Wallet(
        descriptor=external_descriptor,
        change_descriptor=change_descriptor,
        network=network,
        persister=persister,
    )
    receive_address = str(wallet.reveal_next_address(keychain=bdk.KeychainKind.EXTERNAL).address)
    wallet.persist(persister)
    return wallet, persister, receive_address


def test_cbf_update_against_local_bitcoind(bitcoin_core: Path, tmp_path: Path) -> None:
    """Spin up bitcoind, sync a dummy BDK wallet via CBF, and apply the update."""

    async def _run() -> None:
        network = bdk.Network.REGTEST
        wallet, persister, receive_address = _build_test_wallet(network)

        # Fund the wallet and confirm the coinbase so the update has something to discover.
        bitcoin_cli(f"generatetoaddress 1 {receive_address}", bitcoin_core)
        mine_blocks(bitcoin_core, 100)

        cbf_data_dir = tmp_path / "cbf_data"
        cbf_data_dir.mkdir(parents=True, exist_ok=True)

        peer = bdk.Peer(
            address=bdk.IpAddress.from_ipv4(127, 0, 0, 1),
            port=BITCOIN_LISTEN_PORT,
            v2_transport=True,
        )

        # Start CBF sync against the local node.
        cbf_sync = CbfSync(
            wallet_id="test-cbf-sync",
            wallet=wallet,
            peers=[peer],
            data_dir=cbf_data_dir,
            proxy_info=None,
            cbf_connections=1,
            is_new_wallet=True,
        )

        cbf_sync.build_node()
        try:
            # Poll for updates until one arrives or the deadline elapses.
            update_info = None
            deadline = asyncio.get_event_loop().time() + 120
            while update_info is None and asyncio.get_event_loop().time() < deadline:
                try:
                    update_info = await asyncio.wait_for(cbf_sync.next_update_info(), timeout=10)
                except asyncio.TimeoutError:
                    update_info = None
        finally:
            cbf_sync.shutdown_node()

        # Apply the update and verify the wallet now has funds.
        assert update_info is not None
        wallet.apply_update(update_info.update)
        wallet.persist(persister)
        assert wallet.balance().total.to_sat() > 0

    asyncio.run(_run())

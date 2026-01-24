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
import time
from collections.abc import Generator
from pathlib import Path

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.tx_util import serialized_to_hex
from bitcoin_usb.address_types import AddressTypes
from bitcoin_usb.software_signer import SoftwareSigner
from bitcoin_usb.software_signer import derive as software_signer_derive
from pytestqt.qtbot import QtBot

from bitcoin_safe.descriptors import descriptor_from_keystores
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.util import SATOSHIS_PER_BTC
from bitcoin_safe.wallet import LOCAL_TX_LAST_SEEN

from .helpers import TestConfig
from .setup_bitcoin_core import bitcoin_cli
from .util import make_psbt
from .wallet_factory import create_test_wallet

logger = logging.getLogger(__name__)


class Faucet:
    def __init__(
        self,
        backend: str,
        bitcoin_core: Path,
        test_config: TestConfig,
        loop_in_thread: LoopInThread,
        mnemonic="romance slush habit speed type also grace coffee grape inquiry receive filter",
    ) -> None:
        """Initialize instance."""
        self.bitcoin_core = bitcoin_core
        self.seed = mnemonic
        self.loop_in_thread = loop_in_thread
        self.mnemonic = bdk.Mnemonic.from_string(self.seed)
        self.network = bdk.Network.REGTEST
        self.address_type = AddressTypes.p2wpkh
        self.backend = backend
        self.config = test_config

        self.wallet_handle = self._build_wallet_handle()
        self.wallet = self.wallet_handle.wallet
        self.wallet.client.BROADCAST_TIMEOUT = 10
        self.descriptor, self.change_descriptor = self.wallet.multipath_descriptor.to_single_descriptors()
        self.software_signer = SoftwareSigner(
            mnemonic=str(self.mnemonic),
            network=self.network,
            receive_descriptor=str(self.descriptor),
            change_descriptor=str(self.change_descriptor),
        )

        # Reveal and persist the first receive address so recovery scans have a known tip
        self.wallet.persist()

    def _build_wallet_handle(self):
        """Construct the full Wallet handle used by the faucet."""
        key_origin = self.address_type.key_origin(self.network)
        xpub, fingerprint = software_signer_derive(str(self.mnemonic), key_origin, self.network)
        keystore = KeyStore(
            xpub=xpub,
            fingerprint=fingerprint,
            key_origin=key_origin,
            label="faucet",
            network=self.network,
            mnemonic=str(self.mnemonic),
            description="faucet",
        )
        multipath_descriptor = descriptor_from_keystores(
            threshold=1,
            spk_providers=[keystore],
            address_type=self.address_type,
            network=self.network,
        )
        return create_test_wallet(
            wallet_id="faucet",
            descriptor_str=multipath_descriptor.to_string_with_secret(),
            keystores=[keystore],
            backend=self.backend,
            config=self.config,
            is_new_wallet=True,
            bitcoin_core=self.bitcoin_core,
            loop_in_thread=self.loop_in_thread,
        )

    def _broadcast(self, tx: bdk.Transaction):
        """Broadcast a transaction using the active backend."""
        hex_tx = serialized_to_hex(tx.serialize())
        for attempt in range(10):
            try:
                result = bitcoin_cli(f"sendrawtransaction {hex_tx}", self.bitcoin_core)
                logger.info("bitcoin_cli sendrawtransaction answer result=%s", result)
                if result:
                    return
            except RuntimeError as err:
                message = str(err)
                # Transient startup issues while bitcoind warms up
                if "in warmup" in message or "refused" in message or "Connection reset" in message:
                    logger.warning("bitcoin-cli not ready (attempt %d): %s", attempt + 1, message)
                else:
                    logger.warning(
                        "bitcoin-cli sendrawtransaction error (attempt %d): %s", attempt + 1, message
                    )

            time.sleep(1)

        raise Exception(f"Broadcasting {tx} failed. No txid received from bitcoin_cli after retries")

    def send(
        self, destination_address: str, qtbot: QtBot, amount=SATOSHIS_PER_BTC, fee_rate=1
    ) -> bdk.Transaction:
        """Send."""

        psbt_for_signing = make_psbt(
            wallet=self.wallet,
            destination_address=destination_address,
            amount=amount,
            fee_rate=fee_rate,
        )
        signed_psbt = self.software_signer.sign_psbt(psbt_for_signing)
        if not signed_psbt:
            raise RuntimeError("Faucet failed to sign transaction")

        tx = signed_psbt.extract_tx()
        # apply as local
        self.wallet.apply_unconfirmed_txs([tx], last_seen=LOCAL_TX_LAST_SEEN)
        self._broadcast(tx)
        if self.backend == "cbf":
            # since I sent the tx, I will not get notified by the bitcoin core node
            # so to get an update I mine a block to confirm the tx
            # self.mine(blocks=1)
            pass
        else:
            # let the backend index the tx
            time.sleep(2)
            self.sync(qtbot=qtbot)
        return tx

    def mine(self, qtbot: QtBot, blocks=1, address=None):
        return self.wallet_handle.mine(blocks=blocks, address=address, qtbot=qtbot)

    def sync(self, qtbot: QtBot):
        self.wallet_handle.sync(qtbot=qtbot)

    def _initial_mine(self, qtbot: QtBot):
        """Initial mine."""
        # Keep initial funding lightweight to avoid long CBF syncs.
        self.wallet_handle.mine(blocks=200, qtbot=qtbot, timeout=120_000)

    def close(self):
        """Clean up backend resources."""
        if hasattr(self, "wallet_handle") and self.wallet_handle:
            self.wallet_handle.close()


@pytest.fixture(scope="session")
def faucet_session(
    bitcoin_core: Path,
    backend: str,
    loop_in_thread: LoopInThread,
    test_config_session: TestConfig,
) -> Generator[Faucet, None, None]:
    """Faucet."""
    faucet_instance = Faucet(
        bitcoin_core=bitcoin_core,
        loop_in_thread=loop_in_thread,
        test_config=test_config_session,
        backend=backend,
    )
    yield faucet_instance
    faucet_instance.close()


@pytest.fixture()
def faucet(faucet_session: Faucet, qtbot: QtBot) -> Generator[Faucet, None, None]:
    """Faucet."""
    if faucet_session.wallet.get_balance().total == 0:
        # cannot send, what we dont have
        faucet_session._initial_mine(qtbot=qtbot)
    yield faucet_session

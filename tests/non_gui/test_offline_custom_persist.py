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

import bdkpython as bdk

from bitcoin_safe.persister.changeset_converter import ChangeSetConverter

initial_txs = [
    "0200000000010101d7eb881ab8cac7d6adc6a7f9aa13e694813d95330c7299cee3623e5d14bd590000000000fdffffff02c5e6c1010000000016001407103a1cccf6a1ea654bee964a4020d20c41fb055c819725010000001600146337ec04bf42015e5d077b90cae05c06925c491a0247304402206aae2bf32da4c3b71cb95e6633c22f9f5a4a4f459975965c0c39b0ab439737b702200c4b16d2029383190965b07adeb87e6d634c68c70d2742f25e456874e8dc273a012103930326d6d72f8663340ce4341d0d3bdb1a1c0734d46e5df8a3003ab6bb50073b00000000",
    "02000000000101b0db431cffebeeeeec19ee8a09a2ae4755722ea73232dbb99b8e754eaad6ac300100000000fdffffff024ad24201000000001600146a7b71a68b261b0b7c79e5bb00f0f3d65d5ae4a285ae542401000000160014e43ff61232ca20061ef1d241e73f322a149a23d902473044022059f4b2fa8b9da34dbb57e491f3d5b8a47a623d7e6ebc1b6adfe6d2be744c9640022073cfc8311c49a8d48d69076466d32be591d3c0092b965828cfbcaca69fd409c90121027aa62d03db46272fa31bc1a6cb095bb66bc5409dd74b25e88e3099d84a17a3e469000000",
]
descriptor: bdk.Descriptor = bdk.Descriptor(
    "wpkh([44250c36/84'/1'/0']tpubDCrUjjHLB1fxk1oRveETjw62z8jsUuqx7JkBUW44VBszGmcY3Eun3apwVcE5X2bfF5MsM3uvuQDed6Do33ZN8GiWcnj2QPqVDspFT1AyZJ9/0/*)",
    bdk.Network.REGTEST,
)
change_descriptor: bdk.Descriptor = bdk.Descriptor(
    "wpkh([44250c36/84'/1'/0']tpubDCrUjjHLB1fxk1oRveETjw62z8jsUuqx7JkBUW44VBszGmcY3Eun3apwVcE5X2bfF5MsM3uvuQDed6Do33ZN8GiWcnj2QPqVDspFT1AyZJ9/1/*)",
    bdk.Network.REGTEST,
)


serialized_persistence = '{"descriptor": "wpkh([44250c36/84\'/1\'/0\']tpubDCrUjjHLB1fxk1oRveETjw62z8jsUuqx7JkBUW44VBszGmcY3Eun3apwVcE5X2bfF5MsM3uvuQDed6Do33ZN8GiWcnj2QPqVDspFT1AyZJ9/0/*)#9q4e992d", "change_descriptor": "wpkh([44250c36/84\'/1\'/0\']tpubDCrUjjHLB1fxk1oRveETjw62z8jsUuqx7JkBUW44VBszGmcY3Eun3apwVcE5X2bfF5MsM3uvuQDed6Do33ZN8GiWcnj2QPqVDspFT1AyZJ9/1/*)#55sccs64", "network": "REGTEST", "local_chain": {"changes": [{"height": 0, "hash": "06226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910f"}]}, "tx_graph": {"txs": ["0200000000010101d7eb881ab8cac7d6adc6a7f9aa13e694813d95330c7299cee3623e5d14bd590000000000fdffffff02c5e6c1010000000016001407103a1cccf6a1ea654bee964a4020d20c41fb055c819725010000001600146337ec04bf42015e5d077b90cae05c06925c491a0247304402206aae2bf32da4c3b71cb95e6633c22f9f5a4a4f459975965c0c39b0ab439737b702200c4b16d2029383190965b07adeb87e6d634c68c70d2742f25e456874e8dc273a012103930326d6d72f8663340ce4341d0d3bdb1a1c0734d46e5df8a3003ab6bb50073b00000000", "02000000000101b0db431cffebeeeeec19ee8a09a2ae4755722ea73232dbb99b8e754eaad6ac300100000000fdffffff024ad24201000000001600146a7b71a68b261b0b7c79e5bb00f0f3d65d5ae4a285ae542401000000160014e43ff61232ca20061ef1d241e73f322a149a23d902473044022059f4b2fa8b9da34dbb57e491f3d5b8a47a623d7e6ebc1b6adfe6d2be744c9640022073cfc8311c49a8d48d69076466d32be591d3c0092b965828cfbcaca69fd409c90121027aa62d03db46272fa31bc1a6cb095bb66bc5409dd74b25e88e3099d84a17a3e469000000"], "txouts": {}, "anchors": [], "last_seen": {"2d2f7cedc21b4272bf57e3eaaeec241959d15bfa7b710ae984ec1ef2b804c1c0": 0, "b0db431cffebeeeeec19ee8a09a2ae4755722ea73232dbb99b8e754eaad6ac30": 0}, "first_seen": {"b0db431cffebeeeeec19ee8a09a2ae4755722ea73232dbb99b8e754eaad6ac30": 0, "2d2f7cedc21b4272bf57e3eaaeec241959d15bfa7b710ae984ec1ef2b804c1c0": 0}, "last_evicted": {}}, "indexer": {"last_revealed": {"d29ab90c8fe23b5f43f94462e9128ae15368e83d628a466108d64a08c4abd41f": 8}}}'


# --- Minimal in-memory Persistence for tests --------------------------------


class MyMemoryPersistence(bdk.Persistence):
    def __init__(self) -> None:
        """Initialize instance."""
        self.memory = []

    def merge_all(self) -> bdk.ChangeSet:
        """Merge all."""
        # Merge all accumulated changesets into one.
        total = bdk.ChangeSet()
        for cs in self.memory:
            total = bdk.ChangeSet.from_merge(total, cs)
        return total

    def initialize(self) -> bdk.ChangeSet:
        """Initialize."""
        # BDK calls initialize to load the persisted state.
        return self.merge_all()

    def persist(self, changeset: bdk.ChangeSet) -> None:
        """Persist."""
        # Append each changeset so we can merge them later.
        self.memory.append(changeset)


# --- The test ----------------------------------------------------------------


def test_synced_transactions_roundtrip() -> None:
    # Build first wallet and persist its state
    """Test synced transactions roundtrip."""
    myp = MyMemoryPersistence()
    persister = bdk.Persister.custom(myp)

    # Create a wallet and apply unconfirmed txs.
    wallet: bdk.Wallet = bdk.Wallet(descriptor, change_descriptor, bdk.Network.REGTEST, persister)

    wallet.apply_unconfirmed_txs(
        [bdk.UnconfirmedTx(tx=bdk.Transaction(bytes.fromhex(tx)), last_seen=0) for tx in initial_txs]
    )

    # Persist the state for later comparison.
    wallet.persist(persister=persister)

    # Initialize a new wallet from provided serialized persistence
    myp2 = MyMemoryPersistence()
    myp2.memory = [ChangeSetConverter.from_dict(json.loads(serialized_persistence))]
    persister2 = bdk.Persister.custom(myp2)

    # Load a fresh wallet from the serialized changeset.
    wallet2 = bdk.Wallet.load(
        descriptor=descriptor,
        change_descriptor=change_descriptor,
        persister=persister2,
    )

    # Compare outputs
    outputs = wallet.list_output()
    outputs2 = wallet2.list_output()
    assert len(outputs) == len(outputs2)
    # Outputs should match in outpoint identity.
    for o, o2 in zip(outputs, outputs2, strict=False):
        assert o.outpoint.txid == o2.outpoint.txid
        assert o.outpoint.vout == o2.outpoint.vout

    # Compare transactions (by txid bytes)
    txs = wallet.transactions()
    txs2 = wallet2.transactions()
    assert txs, "Sync error: no transactions returned"
    assert len(txs) == len(txs2)
    # Transaction IDs should match exactly.
    for tx, tx2 in zip(txs, txs2, strict=False):
        assert tx.transaction.compute_txid().serialize() == tx2.transaction.compute_txid().serialize()

    # Balance check
    # Balance should match the known expected value.
    assert wallet.balance().total.to_sat() == 50_641_167

    # Persistence round-trip equivalence (dict compare is order-insensitive)
    d_myp = ChangeSetConverter.to_dict(myp.initialize())
    d_myp2 = ChangeSetConverter.to_dict(myp2.initialize())
    assert d_myp == d_myp2

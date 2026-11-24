#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
from unittest.mock import AsyncMock, MagicMock

import bdkpython as bdk
import pytest

from bitcoin_safe.foreign_utxo import ForeignUtxo
from bitcoin_safe.foreign_utxo_serialization import dump_foreign_inputs, load_foreign_inputs
from bitcoin_safe.mempool_manager import MempoolManager
from bitcoin_safe.pythonbdk_types import OutPoint
from bitcoin_safe.wallet import Wallet
from tests.non_gui.test_foreign_utxo import NETWORK, make_wallet, transaction


def test_persist_all_inputs_and_reject_corrupt_previous_output() -> None:
    tx = transaction([b"\x00\x14" + b"\x42" * 20, b"\x00\x14" + b"\x43" * 20])
    points = [OutPoint(txid=tx.compute_txid(), vout=i) for i in range(2)]
    inputs = {op: ForeignUtxo.from_outpoint(op, tx.output()[op.vout], tx, [], NETWORK) for op in points}
    saved = json.loads(json.dumps(dump_foreign_inputs(inputs)))
    restored = load_foreign_inputs(saved)
    assert set(restored) == set(points)
    assert all(
        item.psbt_input.non_witness_utxo.compute_txid() == tx.compute_txid() for item in restored.values()
    )
    saved[str(points[0])]["txout"][1] += 1
    assert set(load_foreign_inputs(saved)) == {points[1]}


def test_restored_inputs_require_full_previous_transaction() -> None:
    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    item = ForeignUtxo.from_outpoint(op, tx.output()[0], tx, [], NETWORK)
    item.psbt_input.non_witness_utxo = None
    with pytest.raises(ValueError, match="full previous transaction"):
        ForeignUtxo.previous_output(op, item.psbt_input)


def test_missing_metadata_or_transaction_is_rejected() -> None:
    import asyncio

    active = make_wallet(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "active",
    )
    tx = transaction([b"\x00\x20" + b"\x42" * 32])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(return_value=tx)
    result, errors = asyncio.run(Wallet.resolve_foreign_outpoints(active, [op], [active], manager))
    assert not result and "descriptor" in errors[0]
    manager.fetch_transaction = AsyncMock(side_effect=ValueError("offline"))
    result, errors = asyncio.run(Wallet.resolve_foreign_outpoints(active, [op], [active], manager))
    assert not result and "full previous transaction" in errors[0]


def test_taproot_wallet_input_survives_restoration() -> None:
    import asyncio

    from bitcoin_safe_lib.util import network_kind

    from bitcoin_safe.wallet import BdkWallet

    active = make_wallet(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "active",
    )
    seed = "legal winner thank year wave sausage worth useful legal winner thank yellow"
    other = make_wallet(seed, "taproot")
    key = bdk.DescriptorSecretKey(network_kind(NETWORK), bdk.Mnemonic.from_string(seed), "")
    receive = bdk.Descriptor.new_bip86(key, bdk.KeychainKind.EXTERNAL, network_kind(NETWORK))
    change = bdk.Descriptor.new_bip86(key, bdk.KeychainKind.INTERNAL, network_kind(NETWORK))
    other.bdkwallet = BdkWallet(receive, change, NETWORK, bdk.Persister.new_in_memory())
    address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())])
    other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
    point = OutPoint(txid=funding.compute_txid(), vout=0)
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock()
    imported, errors = asyncio.run(
        Wallet.resolve_foreign_outpoints(active, [point], [active, other], manager)
    )
    assert not errors
    restored = load_foreign_inputs(dump_foreign_inputs(imported))[point]
    assert restored.psbt_input.non_witness_utxo.compute_txid() == funding.compute_txid()
    assert restored.psbt_input.tap_internal_key is not None
    assert restored.psbt_input.tap_key_origins
    manager.fetch_transaction.assert_not_awaited()


def test_backend_wrong_transaction_id_is_rejected() -> None:
    import asyncio

    active = make_wallet(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "active",
    )
    point = OutPoint.from_str("aa" * 32 + ":0")
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(return_value=transaction([b"\x00\x14" + b"\x44" * 20]))
    imported, errors = asyncio.run(Wallet.resolve_foreign_outpoints(active, [point], [active], manager))
    assert not imported and "invalid previous transaction" in errors[0]

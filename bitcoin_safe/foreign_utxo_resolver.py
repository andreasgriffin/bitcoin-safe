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

"""Resolve foreign transaction inputs from wallet data, PSBTs and an optional fetcher."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from copy import copy

import bdkpython as bdk

from .foreign_utxo import ForeignUtxo
from .pythonbdk_types import OutPoint, TxOut
from .wallet import SpentWalletOutputError, Wallet


async def resolve_foreign_outpoints(
    active_wallet: Wallet,
    outpoints: list[OutPoint],
    wallets: list[Wallet],
    fetch_transaction: Callable[[bdk.Txid], Awaitable[bdk.Transaction]] | None = None,
    psbt_inputs: dict[OutPoint, bdk.Input] | None = None,
    existing_inputs: dict[OutPoint, ForeignUtxo] | None = None,
    skip_spent: bool = False,
) -> tuple[dict[OutPoint, ForeignUtxo], list[str]]:
    """Resolve foreign inputs; omit the fetcher for local-only resolution.

    Keep input-specific failures separate and fetch each missing funding transaction
    at most once, even if several requested outputs share the same TXID.
    """
    resolved: dict[OutPoint, ForeignUtxo] = {}
    errors: list[str] = []
    supplied_inputs = psbt_inputs or {}
    saved_inputs = existing_inputs or {}
    descriptors = [(wallet.id, wallet.bdkwallet) for wallet in wallets]
    known_outputs, local_transactions = Wallet.get_known_wallet_outputs_and_transactions(
        set(outpoints), wallets
    )
    transactions: dict[str, bdk.Transaction | Exception] = dict(local_transactions)
    # Saved inputs override wallet parents; supplied PSBT parents override both.
    for point, item in saved_inputs.items():
        if item.psbt_input.non_witness_utxo is not None:
            transactions[point.txid_str] = item.psbt_input.non_witness_utxo
    for point, psbt_input in supplied_inputs.items():
        if psbt_input.non_witness_utxo is not None:
            transactions[point.txid_str] = psbt_input.non_witness_utxo

    for outpoint in dict.fromkeys(outpoints):
        try:
            known = known_outputs[outpoint]
            if skip_spent and isinstance(known, SpentWalletOutputError):
                continue
            if isinstance(known, Exception):
                raise known
            if outpoint.txid_str not in transactions:
                if fetch_transaction is None:
                    raise ValueError("full previous transaction is not available locally")
                try:
                    transactions[outpoint.txid_str] = await fetch_transaction(outpoint.txid)
                except Exception as exc:
                    transactions[outpoint.txid_str] = exc
            transaction = transactions[outpoint.txid_str]
            if isinstance(transaction, Exception):
                raise ValueError(f"Could not obtain full previous transaction: {transaction}")
            resolved[outpoint] = _resolve_foreign_input(
                active_wallet,
                outpoint,
                transaction,
                known,
                supplied_inputs.get(outpoint),
                saved_inputs.get(outpoint),
                descriptors,
            )
        except Exception as exc:
            errors.append(f"{outpoint}: {exc}")
    return resolved, errors


def _resolve_foreign_input(
    active_wallet: Wallet,
    outpoint: OutPoint,
    transaction: bdk.Transaction,
    known: bdk.TxOut | None,
    supplied: bdk.Input | None,
    existing: ForeignUtxo | None,
    descriptors: Sequence[tuple[str, bdk.Wallet]],
) -> ForeignUtxo:
    """Validate one funding output and construct its signing metadata without I/O."""
    outputs = transaction.output()
    if transaction.compute_txid() != outpoint.txid or not 0 <= outpoint.vout < len(outputs):
        raise ValueError("invalid previous transaction or output index")
    txout = outputs[outpoint.vout]
    if known is not None and TxOut.from_bdk(known) != TxOut.from_bdk(txout):
        raise ValueError("previous output conflicts with wallet data")
    if supplied:
        if supplied.non_witness_utxo is not None:
            ForeignUtxo.previous_output(outpoint, supplied)
        if supplied.witness_utxo is not None and TxOut.from_bdk(supplied.witness_utxo) != TxOut.from_bdk(
            txout
        ):
            raise ValueError("PSBT previous output conflicts with transaction")
    if active_wallet.bdkwallet.is_mine(txout.script_pubkey):
        raise ValueError("This output belongs to the active wallet but is not spendable")
    if existing:
        if existing.utxo.txout != TxOut.from_bdk(txout):
            raise ValueError("previous output conflicts with imported metadata")
        ForeignUtxo.previous_output(outpoint, existing.psbt_input)
        return existing
    item = ForeignUtxo.from_outpoint(outpoint, txout, transaction, descriptors, active_wallet.network)
    # Wallet descriptors are authoritative; imported signatures belong to the old transaction.
    if supplied and item.wallet_id is None:
        item.use_imported_input(copy(supplied))
    ForeignUtxo.previous_output(outpoint, item.psbt_input)
    return item

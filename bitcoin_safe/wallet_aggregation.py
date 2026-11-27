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

"""Combine transaction graph evidence from multiple wallets."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from itertools import tee

import bdkpython as bdk

from .input_signature_verifier import Prevout
from .pythonbdk_types import OutPoint, TxOut, get_prev_outpoints
from .wallet import Wallet

logger = logging.getLogger(__name__)


def collect_known_outputs_and_transactions(
    outpoints: set[OutPoint], wallets: Iterable[Wallet]
) -> tuple[dict[OutPoint, bdk.TxOut | Exception | None], dict[str, bdk.Transaction]]:
    """Merge wallet evidence, retaining errors and the first complete parent for each TXID."""
    if not outpoints:
        return {}, {}
    results: dict[OutPoint, bdk.TxOut | Exception | None] = dict.fromkeys(outpoints)
    parents: dict[str, bdk.Transaction] = {}
    for wallet in wallets:
        outputs, transactions = wallet.get_known_outputs_and_transactions(outpoints)
        for txid, parent in transactions.items():
            parents.setdefault(txid, parent)
        for point, output in outputs.items():
            previous = results[point]
            if isinstance(previous, Exception) or output is None:
                continue
            if isinstance(output, Exception):
                results[point] = output
            elif previous is not None and TxOut.from_bdk(previous) != TxOut.from_bdk(output):
                results[point] = ValueError(f"{point}: conflicting wallet previous outputs")
            else:
                results[point] = output
    return results, parents


def collect_known_outputs(
    outpoints: set[OutPoint], wallets: Iterable[Wallet]
) -> dict[OutPoint, bdk.TxOut | Exception | None]:
    """Collect output evidence across wallets, including spent/conflicting-output errors."""
    outputs, _ = collect_known_outputs_and_transactions(outpoints, wallets)
    return outputs


def prevouts_from_wallets(
    txs: list[bdk.Transaction], wallets: Iterable[Wallet]
) -> dict[tuple[str, int], Prevout]:
    """Collect prevouts, preferring complete parents over consistent standalone data."""
    candidate_ids = {str(tx.compute_txid()) for tx in txs}
    unresolved: dict[str, set[OutPoint]] = defaultdict(set)
    for tx in txs:
        for point in get_prev_outpoints(tx):
            if point.txid_str not in candidate_ids:
                unresolved[point.txid_str].add(point)

    prevouts: dict[tuple[str, int], Prevout] = {}
    standalone: dict[tuple[str, int], set[Prevout]] = defaultdict(set)
    for wallet in wallets:
        if not unresolved:
            break
        # Both lookups share the same lazily materialized changesets.
        transaction_graphs, output_graphs = tee(wallet.get_graph_changesets())
        parents = wallet.get_graph_transactions(unresolved, graphs=transaction_graphs)
        for txid, parent in parents.items():
            outputs = parent.output()
            # A full parent is authoritative, even if the requested vout does not exist.
            for point in unresolved.pop(txid):
                if 0 <= point.vout < len(outputs):
                    output = outputs[point.vout]
                    prevouts[(txid, point.vout)] = Prevout(
                        TxOut.from_bdk(output).spk_bytes, output.value.to_sat()
                    )

        remaining = (point for points in unresolved.values() for point in points)
        for point, output in wallet.iter_graph_txouts(remaining, graphs=output_graphs):
            standalone[(point.txid_str, point.vout)].add(
                Prevout(TxOut.from_bdk(output).spk_bytes, output.value.to_sat())
            )

    # Full parents found in later wallets supersede earlier standalone observations.
    for key, observations in standalone.items():
        if key[0] not in unresolved:
            continue
        if len(observations) == 1:
            prevouts[key] = next(iter(observations))
        else:
            logger.warning(f"Conflicting standalone previous outputs for {key[0]}:{key[1]}")
    return prevouts

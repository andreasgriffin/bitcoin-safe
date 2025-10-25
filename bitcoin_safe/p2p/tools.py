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

import bdkpython as bdk

from bitcoin_safe.pythonbdk_types import TxOut, robust_address_str_from_txout

logger = logging.getLogger(__name__)


def address_match(tx: bdk.Transaction, network: bdk.Network, address_filter: set[str]) -> bool:
    """Address match."""
    for output in tx.output():
        address = robust_address_str_from_txout(TxOut.from_bdk(output), network=network)
        if address in address_filter:
            return True
    return False


def outpoint_match(tx: bdk.Transaction, outpoint_filter: set[str]) -> bool:
    """Outpoint match."""
    for inp in tx.input():
        outpoint = f"{inp.previous_output.txid}:{inp.previous_output.vout}"
        if outpoint in outpoint_filter:
            return True
    return False


def output_addresses_values(
    transaction: bdk.Transaction, network: bdk.Network
) -> list[tuple[str, int | None]]:
    # print(f'Getting output addresses for txid {transaction.txid}')
    """Output addresses values."""
    columns: list[tuple[str, int | None]] = []
    for output in transaction.output():
        try:
            add = "" if output.value == 0 else str(bdk.Address.from_script(output.script_pubkey, network))
            value = output.value.to_sat()
        except Exception:
            add = ""
            value = None
        columns.append((add, value))
    return columns


def transaction_table(tx: bdk.Transaction, network: bdk.Network, op_return_limit: int | None = None):
    """Transaction table."""
    try:
        from prettytable import PrettyTable

        # --- Inputs column, with explicit coinbase label if empty ---
        inp_objs = list(tx.input())
        if not inp_objs:
            input_column = ["<coinbase>"]
        else:
            input_column = [f"{inp.previous_output.txid}:{inp.previous_output.vout}" for inp in inp_objs]

        # --- Outputs: address, amount, and op_return payload if any ---
        output_addrs = []
        output_vals = []
        op_returns = []

        for out in tx.output():
            # amount in sats
            output_vals.append(str(out.value))

            # try to derive an address
            try:
                addr = bdk.Address.from_script(out.script_pubkey, network)
            except Exception:
                addr = None

            if addr:
                output_addrs.append(addr)
                op_returns.append("")  # blank when it's a normal spend
            elif op_return_limit is not None:
                # raw script bytes: the first byte is OP_RETURN (0x6a), next is push opcode
                raw = bytes(out.script_pubkey.to_bytes())
                # strip OP_RETURN + the push-data opcode byte
                payload = raw[2:]
                # decode as ASCII, replace un-decodable bytes
                try:
                    text = payload.decode("ascii", errors="replace")
                except Exception:
                    text = "<invalid ASCII>"
                op_returns.append(text[:op_return_limit])
                output_addrs.append("")  # no address for OP_RETURN
            else:
                op_returns.append("")
                output_addrs.append("Unknown")

        # match row count across all columns
        max_rows = max(len(input_column), len(output_addrs), len(output_vals), len(op_returns))

        def stretch(col):
            """Stretch."""
            return list(col) + [""] * (max_rows - len(col))

        # build table
        tbl = PrettyTable()
        tbl.title = f"Transaction: {tx.compute_txid()}"
        tbl.add_column("Inputs", stretch(input_column))
        tbl.add_column("Output Addr", stretch(output_addrs))
        tbl.add_column("Amount (sats)", stretch(output_vals))
        if op_return_limit is not None:
            tbl.add_column("OP_RETURN", stretch(op_returns))

        return tbl
    except Exception as e:
        logger.exception(str(e))

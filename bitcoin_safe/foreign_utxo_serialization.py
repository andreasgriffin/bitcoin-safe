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

"""Persistence for validated foreign transaction inputs."""

import logging
from typing import NotRequired, TypedDict

import bdkpython as bdk
from bitcoin_safe_lib.util import network_kind

from bitcoin_safe.foreign_utxo import ForeignUtxo
from bitcoin_safe.pythonbdk_types import OutPoint, PythonUtxo, TxOut

logger = logging.getLogger(__name__)


class SerializedForeignInput(TypedDict):
    address: str
    txout: tuple[str, int]
    psbt: str
    satisfaction_weight: int
    wallet_id: NotRequired[str | None]


def dump_foreign_inputs(inputs: dict[OutPoint, ForeignUtxo]) -> dict[str, SerializedForeignInput]:
    if not inputs:
        return {}
    network = bdk.Network.REGTEST
    receive = bdk.Descriptor(
        "wpkh(0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798)",
        network_kind(network),
    )
    change = bdk.Descriptor(
        "wpkh(02c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5)",
        network_kind(network),
    )
    wallet = bdk.Wallet(receive, change, network, bdk.Persister.new_in_memory())
    return {
        str(op): {
            "address": item.utxo.address,
            "txout": item.utxo.txout.seralized_tuple(),
            "psbt": item.serialize_input(wallet),
            "satisfaction_weight": item.satisfaction_weight,
            "wallet_id": item.wallet_id,
        }
        for op, item in inputs.items()
    }


def load_foreign_inputs(data: dict[str, SerializedForeignInput]) -> dict[OutPoint, ForeignUtxo]:
    inputs: dict[OutPoint, ForeignUtxo] = {}
    for key, item in data.items():
        try:
            outpoint = OutPoint.from_str(key)
            utxo = PythonUtxo(
                address=item["address"],
                outpoint=outpoint,
                txout=TxOut.from_seralized_tuple(item["txout"]),
            )
            weight = item["satisfaction_weight"]
            if type(weight) is not int or weight <= 0:
                raise ValueError("invalid satisfaction weight")
            inputs[outpoint] = ForeignUtxo.from_serialized_input(
                utxo, item["psbt"], 0, weight, item.get("wallet_id")
            )
        except Exception as exc:
            logger.warning("Cannot restore foreign input %s: %s", key, exc)
    return inputs

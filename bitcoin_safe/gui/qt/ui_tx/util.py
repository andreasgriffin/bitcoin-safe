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
from bitcoin_safe_lib.gui.qt.satoshis import format_fee_rate

from bitcoin_safe.i18n import translate
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import TransactionDetails
from bitcoin_safe.tx import short_tx_id

logger = logging.getLogger(__name__)


def get_rbf_fee_label(
    current_fee: FeeInfo | None,
    min_fee_rate: float,
    conflicing_txids: set[str],
    network: bdk.Network,
) -> tuple[str, str]:
    url = "https://learnmeabitcoin.com/technical/transaction/fee/#rbf"
    tooltip = translate(
        "utils",
        "Replace-By-Fee: This transaction replaces transaction {txid} with fee rate {rate_org}. \nPick a fee above the minimum fee rate {rate_min}.",
    ).format(
        rate_min=format_fee_rate(min_fee_rate, network=network),
        rate_org=format_fee_rate(current_fee.fee_rate(), network=network)
        if current_fee
        else translate("utils", "unknown"),
        txid=", ".join([short_tx_id(txid) for txid in conflicing_txids]),
    )

    return url, tooltip


def get_cpfp_label(
    unconfirmed_parents_fee_info: FeeInfo,
    combined_fee_info: FeeInfo,
    unconfirmed_ancestors: dict[str, TransactionDetails],
    network: bdk.Network,
):
    url = "https://learnmeabitcoin.com/technical/transaction/fee/#cpfp"
    num_parents = len(unconfirmed_ancestors or [])
    parent_str = (
        translate("utils", "unconfirmed parent transaction")
        if num_parents <= 1
        else translate("utils", "{number} unconfirmed parent transactions").format(number=num_parents)
    )
    combined_rate = format_fee_rate(combined_fee_info.fee_rate(), network=network)
    parent_rate = format_fee_rate(unconfirmed_parents_fee_info.fee_rate(), network=network)

    if combined_fee_info.fee_rate() > unconfirmed_parents_fee_info.fee_rate():
        tooltip = translate(
            "utils",
            "Child-Pays-For-Parent: This transaction speeds up the confirmation of the {parent_str}, \n"
            "since it increases the total fee rate to {combined_rate}.",
        ).format(combined_rate=combined_rate, parent_rate=parent_rate, parent_str=parent_str)
    else:
        tooltip = translate(
            "utils",
            "Child-Pays-For-Parent: This transactions fee is too low to speeds up the confirmation of the {parent_str}, \n"
            "since it descreases the total fee rate to {combined_rate}. Pick at least {parent_rate}.",
        ).format(combined_rate=combined_rate, parent_rate=parent_rate, parent_str=parent_str)
    return url, tooltip

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
from bitcoin_safe_lib.tx_util import serialized_to_hex

from bitcoin_safe.pythonbdk_types import AddressInfoMin

from ...signals import UpdateFilter, UpdateFilterReason, WalletFunctions, WalletSignals
from ...wallet import Wallet, get_wallet_of_address

logger = logging.getLogger(__name__)


def advance_tip_to_address_info(
    address_info: AddressInfoMin, wallet: Wallet, wallet_signals: WalletSignals, min_advance: int = 1
) -> list[bdk.AddressInfo]:
    """Advance tip to address info."""
    revealed_address_infos = wallet.advance_tip_to_addresses([str(address_info.address)])
    if revealed_address_infos:
        wallet_signals.updated.emit(
            UpdateFilter(
                addresses=set([str(address_info.address) for address_info in revealed_address_infos]),
                reason=UpdateFilterReason.NewAddressRevealed,
            )
        )
    return revealed_address_infos


def advance_tip_for_addresses(
    addresses: list[str], wallet_functions: WalletFunctions
) -> list[bdk.AddressInfo]:
    """Advance tip for addresses."""
    address_infos: list[bdk.AddressInfo] = []
    for address in addresses:
        if not address:
            continue
        wallet = get_wallet_of_address(address, wallet_functions)
        if not wallet:
            continue
        if address_info := wallet.is_my_address_with_peek(address):
            address_infos += advance_tip_to_address_info(
                address_info=address_info,
                wallet=wallet,
                wallet_signals=wallet_functions.wallet_signals[wallet.id],
            )
    return address_infos


def are_txs_identical(tx1: bdk.Transaction, tx2: bdk.Transaction) -> bool:
    """Are txs identical."""
    return serialized_to_hex(tx1.serialize()) == serialized_to_hex(tx2.serialize())

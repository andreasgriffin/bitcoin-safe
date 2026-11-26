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

from functools import partial

from bitcoin_safe_lib.gui.qt.satoshis import Satoshis

from bitcoin_safe.config import UserConfig
from bitcoin_safe.i18n import translate
from bitcoin_safe.pythonbdk_types import PythonUtxo
from bitcoin_safe.tx import short_tx_id
from bitcoin_safe.wallet import Wallet

from .util import do_copy, svg_tools
from .wrappers import Menu


def add_utxo_copy_menus(
    menu: Menu,
    wallet_utxos: list[tuple[Wallet, PythonUtxo]],
    config: UserConfig,
    copy_menu: Menu | None = None,
) -> None:
    """Add menus for copying unspent outpoints, grouped by address type."""
    if not wallet_utxos:
        return
    if copy_menu is None:
        copy_menu = menu.add_menu(translate("MyTreeView", "Copy"))
        copy_menu.setIcon(svg_tools.get_QIcon("bi--copy.svg"))

    for is_change, title in (
        (False, translate("utxo_copy_menu", "Receiving UTXO")),
        (True, translate("utxo_copy_menu", "Change UTXO")),
    ):
        utxos = {
            str(utxo.outpoint): utxo
            for wallet, utxo in wallet_utxos
            if wallet.is_change(utxo.address) == is_change
        }
        if not utxos:
            continue
        submenu = copy_menu.add_menu(title)
        sorted_utxos = sorted(utxos.values(), key=lambda utxo: (utxo.outpoint.txid_str, utxo.outpoint.vout))
        if len(sorted_utxos) > 1:
            total = Satoshis(sum(utxo.value for utxo in sorted_utxos), config.network).str_with_unit(
                color_formatting=None, btc_symbol=config.bitcoin_symbol.value
            )
            submenu.add_action(
                translate("utxo_copy_menu", "All entries - total: {amount}").format(amount=total),
                partial(do_copy, "\n".join(str(utxo.outpoint) for utxo in sorted_utxos), title=title),
            )
        for utxo in sorted_utxos:
            amount = Satoshis(utxo.value, config.network).str_with_unit(
                color_formatting=None, btc_symbol=config.bitcoin_symbol.value
            )
            outpoint = str(utxo.outpoint)
            submenu.add_action(f"{short_tx_id(outpoint)} - {amount}", partial(do_copy, outpoint, title=title))

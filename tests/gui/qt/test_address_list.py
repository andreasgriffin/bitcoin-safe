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

import inspect
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.address_list import AddressTypeFilter, AddressUsageStateFilter
from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet

from ...faucet import Faucet
from ...helpers import TestConfig
from .helpers import Shutter, do_modal_click, fund_wallet, main_window_context, save_wallet

logger = logging.getLogger(__name__)


def _edit_label(address_list, source_row: int, label_text: str, qtbot: QtBot) -> None:
    source_index = address_list._source_model.index(source_row, address_list.Columns.LABEL)
    proxy_index = address_list.proxy.mapFromSource(source_index)
    assert proxy_index.isValid()
    address_list.setCurrentIndex(proxy_index)
    address_list.setFocus()
    QTest.keyClick(address_list, Qt.Key.Key_F2)

    def editor_ready() -> bool:
        return isinstance(address_list.findChild(QLineEdit), QLineEdit)

    qtbot.waitUntil(editor_ready, timeout=5_000)
    editor = address_list.findChild(QLineEdit)
    assert isinstance(editor, QLineEdit)
    editor.setText(label_text)
    QTest.keyClick(editor, Qt.Key.Key_Return)


@pytest.mark.marker_qt_3
def test_address_list_label_filter_and_utxo_selection(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    wallet_name: str = "address_list_label_filter",
) -> None:
    """Test address list label edit, filters, and UTXO selection for sending."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        wallet_id = f"{wallet_name}_{int(mytest_start_time.timestamp())}"
        button = main_window.welcome_screen.pushButton_custom_wallet

        def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
            shutter.save(dialog)
            dialog.name_input.setText(wallet_id)
            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()

        do_modal_click(button, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        qt_protowallet = main_window.tab_wallets.root.findNodeByTitle(wallet_id).data
        assert isinstance(qt_protowallet, QTProtoWallet)

        qt_protowallet.wallet_descriptor_ui.spin_req.setValue(1)
        qt_protowallet.wallet_descriptor_ui.spin_signers.setValue(1)
        key = list(qt_protowallet.wallet_descriptor_ui.keystore_uis.getAllTabData().values())[0]
        key.tabs_import_type.setCurrentWidget(key.tab_manual)
        if key.edit_seed.mnemonic_button:
            key.edit_seed.mnemonic_button.click()

        save_wallet(
            test_config=test_config,
            wallet_name=wallet_id,
            save_button=qt_protowallet.wallet_descriptor_ui.button_box.button(
                QDialogButtonBox.StandardButton.Apply
            ),
        )

        qt_wallet = main_window.tab_wallets.root.findNodeByTitle(wallet_id).data
        assert isinstance(qt_wallet, QTWallet)

        qt_wallet.tabs.setCurrentWidget(qt_wallet.address_tab)
        address_list = qt_wallet.address_list
        address_toolbar = qt_wallet.address_list_with_toolbar

        qtbot.waitUntil(lambda: address_list._source_model.rowCount() > 0, timeout=10_000)
        shutter.save(main_window)

        wallet = qt_wallet.wallet
        receiving_addresses = wallet.get_receiving_addresses()
        if len(receiving_addresses) < 2:
            receiving_addresses.append(str(wallet.get_address(force_new=True).address))
        address = receiving_addresses[0]
        row = address_list.find_row_by_key(address)
        assert row is not None

        label_text = f"label_{int(mytest_start_time.timestamp())}"
        _edit_label(address_list, row, label_text, qtbot)

        def label_applied() -> bool:
            return qt_wallet.wallet.get_label_for_address(address) == label_text

        qtbot.waitUntil(label_applied, timeout=10_000)
        shutter.save(main_window)

        # Ensure the label filter keeps receiving addresses visible.
        address_toolbar.used_button.setCurrentIndex(AddressUsageStateFilter.ALL)
        address_toolbar.change_button.setCurrentIndex(AddressTypeFilter.RECEIVING)

        qtbot.wait(200)
        source_index = address_list._source_model.index(row, address_list.Columns.ADDRESS)
        proxy_index = address_list.proxy.mapFromSource(source_index)
        assert proxy_index.isValid()
        assert not address_list.isRowHidden(proxy_index.row(), QModelIndex())

        change_address = next((addr for addr in wallet.get_addresses() if wallet.is_change(addr)), None)
        if change_address:
            change_row = address_list.find_row_by_key(change_address)
            assert change_row is not None
            change_index = address_list._source_model.index(change_row, address_list.Columns.ADDRESS)
            change_proxy = address_list.proxy.mapFromSource(change_index)
            assert change_proxy.isValid()
            assert address_list.isRowHidden(change_proxy.row(), QModelIndex())

        shutter.save(main_window)

        # Fund a different address so the labeled address stays unfunded.
        other_address = next(addr for addr in receiving_addresses if addr != address)
        fund_wallet(
            qtbot=qtbot,
            faucet=faucet,
            qt_wallet=qt_wallet,
            amount=120_000,
            address=other_address,
        )

        utxos = address_list._utxos_for_addresses(wallet, [address])
        assert utxos == []
        shutter.save(main_window)


@pytest.mark.marker_qt_3
def test_address_list_filters_with_funding_and_quick_receive(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    wallet_file: str = "0.2.0.wallet",
) -> None:
    """Test funded address updates filters, quick receive, and UTXO selection."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        temp_dir = Path(tempfile.mkdtemp()) / wallet_file
        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert isinstance(qt_wallet, QTWallet)

        qt_wallet.tabs.setCurrentWidget(qt_wallet.history_tab)
        quick_receive = qt_wallet.quick_receive
        qtbot.waitUntil(lambda: len(quick_receive.group_boxes) > 0, timeout=10_000)
        shutter.save(main_window)

        # Funding the first quick receive address should advance to a new unused address.
        initial_receive = quick_receive.group_boxes[0].address
        fund_wallet(qtbot=qtbot, faucet=faucet, qt_wallet=qt_wallet, amount=200_000, address=initial_receive)

        def quick_receive_updated() -> bool:
            return bool(quick_receive.group_boxes) and quick_receive.group_boxes[0].address != initial_receive

        qtbot.waitUntil(quick_receive_updated, timeout=10_000)
        shutter.save(main_window)

        qt_wallet.tabs.setCurrentWidget(qt_wallet.address_tab)
        address_list = qt_wallet.address_list
        address_toolbar = qt_wallet.address_list_with_toolbar

        qtbot.waitUntil(lambda: address_list._source_model.rowCount() > 0, timeout=10_000)

        row = address_list.find_row_by_key(initial_receive)
        assert row is not None

        def funded_balance() -> bool:
            return qt_wallet.wallet.get_addr_balance(initial_receive).total > 0

        qtbot.waitUntil(funded_balance, timeout=10_000)

        # "Funded + receiving" filters should surface the funded address.
        address_toolbar.used_button.setCurrentIndex(AddressUsageStateFilter.FUNDED)
        address_toolbar.change_button.setCurrentIndex(AddressTypeFilter.RECEIVING)
        qtbot.wait(200)

        source_index = address_list._source_model.index(row, address_list.Columns.ADDRESS)
        proxy_index = address_list.proxy.mapFromSource(source_index)
        assert proxy_index.isValid()
        assert not address_list.isRowHidden(proxy_index.row(), QModelIndex())

        shutter.save(main_window)

        captured = []

        def on_open_tx_like(tx_ui_infos) -> None:  # noqa: ANN001
            captured.append(tx_ui_infos)

        qt_wallet.wallet_functions.signals.open_tx_like.connect(on_open_tx_like)
        try:
            address_list._select_utxos_for_sending({qt_wallet.wallet.id: [initial_receive]})
            qtbot.waitUntil(lambda: qt_wallet.tabs.currentWidget() is qt_wallet.uitx_creator)
        finally:
            qt_wallet.wallet_functions.signals.open_tx_like.disconnect(on_open_tx_like)

        assert captured
        tx_ui_infos = captured[-1]
        # The send flow should include only the funded address from this wallet.
        assert tx_ui_infos.main_wallet_id == qt_wallet.wallet.id
        assert tx_ui_infos.spend_all_utxos is True
        assert tx_ui_infos.hide_UTXO_selection is False
        assert {utxo.address for utxo in tx_ui_infos.utxo_dict.values()} == {initial_receive}

        shutter.save(main_window)

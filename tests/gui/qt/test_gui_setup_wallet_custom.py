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


import inspect
import logging
from datetime import datetime
from pathlib import Path
from time import sleep

import bdkpython as bdk
from bitcoin_usb.address_types import AddressTypes
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.block_change_signals import BlockChangesSignals
from bitcoin_safe.gui.qt.descriptor_edit import DescriptorExport
from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.logging_setup import setup_logging  # type: ignore
from tests.gui.qt.test_gui_setup_wallet import (
    close_wallet,
    get_tab_with_title,
    save_wallet,
)

from ...test_helpers import test_config  # type: ignore
from ...test_setup_bitcoin_core import Faucet, bitcoin_core, faucet  # type: ignore
from .test_helpers import (  # type: ignore
    Shutter,
    close_wallet,
    do_modal_click,
    get_tab_with_title,
    get_widget_top_level,
    main_window_context,
    save_wallet,
    test_start_time,
)

logger = logging.getLogger(__name__)


def test_custom_wallet_setup_custom_single_sig(
    qapp: QApplication,
    qtbot: QtBot,
    test_start_time: datetime,
    test_config: UserConfig,
    bitcoin_core: Path,
    faucet: Faucet,
    wallet_name: str = "test_custom_wallet_setup_custom_single_sig",
    amount: int = int(1e6),
) -> None:  # bitcoin_core: Path,
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{test_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window)  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        button = main_window.welcome_screen.pushButton_custom_wallet

        def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
            shutter.save(dialog)
            dialog.name_input.setText(wallet_name)
            shutter.save(dialog)

            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()
            shutter.save(main_window)

        do_modal_click(button, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        w = get_tab_with_title(main_window.tab_wallets, title=wallet_name)
        qt_proto_wallet = main_window.tab_wallets.get_data_for_tab(w)
        assert isinstance(qt_proto_wallet, QTProtoWallet)

        def test_block_change_signals() -> None:
            with BlockChangesSignals([qt_proto_wallet.wallet_descriptor_ui.tab]):
                assert qt_proto_wallet.wallet_descriptor_ui.spin_req.signalsBlocked()
            with BlockChangesSignals([qt_proto_wallet.wallet_descriptor_ui.tab]):
                with BlockChangesSignals([qt_proto_wallet.wallet_descriptor_ui.tab]):
                    assert qt_proto_wallet.wallet_descriptor_ui.spin_req.signalsBlocked()
                assert qt_proto_wallet.wallet_descriptor_ui.spin_req.signalsBlocked()

        def check_consistent() -> None:
            signers = qt_proto_wallet.wallet_descriptor_ui.spin_signers.value()
            qt_proto_wallet.wallet_descriptor_ui.spin_req.value()

            assert signers == qt_proto_wallet.wallet_descriptor_ui.keystore_uis.count()
            for i in range(signers):
                assert qt_proto_wallet.wallet_descriptor_ui.keystore_uis.tabText(
                    i
                ) == qt_proto_wallet.protowallet.signer_name(i)

            if qt_proto_wallet.protowallet.is_multisig():
                assert AddressTypes.p2wsh in [
                    qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.itemData(i)
                    for i in range(qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.count())
                ]
            else:
                assert AddressTypes.p2pkh in [
                    qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.itemData(i)
                    for i in range(qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.count())
                ]

        def page1() -> None:
            shutter.save(main_window)

            assert qt_proto_wallet.wallet_descriptor_ui.spin_req.value() == 3
            assert qt_proto_wallet.wallet_descriptor_ui.spin_signers.value() == 5
            assert (
                qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.currentData() == AddressTypes.p2wsh
            )
            assert qt_proto_wallet.wallet_descriptor_ui.spin_gap.value() == 20
            assert qt_proto_wallet.wallet_descriptor_ui.keystore_uis.count() == 5

            shutter.save(main_window)
            check_consistent()
            test_block_change_signals()

        page1()

        def change_to_single_sig() -> None:
            assert qt_proto_wallet.protowallet.is_multisig()
            qt_proto_wallet.wallet_descriptor_ui.spin_req.setValue(1)
            assert qt_proto_wallet.wallet_descriptor_ui.spin_req.value() == 1

            # change to single sig
            qt_proto_wallet.wallet_descriptor_ui.spin_signers.setValue(1)
            assert qt_proto_wallet.wallet_descriptor_ui.spin_signers.value() == 1

            assert not qt_proto_wallet.protowallet.is_multisig()

            shutter.save(main_window)
            check_consistent()

        change_to_single_sig()

        def do_save_wallet() -> None:
            key = list(qt_proto_wallet.wallet_descriptor_ui.keystore_uis.getAllTabData().values())[0]
            key.tabs_import_type.setCurrentWidget(key.tab_manual)

            shutter.save(main_window)

            if key.edit_seed.mnemonic_button:
                key.edit_seed.mnemonic_button.click()

            assert key.edit_seed.text()
            assert key.edit_xpub.text()
            assert key.edit_fingerprint.text()
            assert (
                key.edit_key_origin.text()
                == f"m/84h/{0 if bdk.Network.REGTEST==bdk.Network.BITCOIN else 1}h/0h"
            )

            shutter.save(main_window)

            save_wallet(
                shutter=shutter,
                test_config=test_config,
                wallet_name=wallet_name,
                qtbot=qtbot,
                save_button=qt_proto_wallet.wallet_descriptor_ui.button_box.button(
                    QDialogButtonBox.StandardButton.Apply
                ),
            )

            assert main_window.tab_wallets.count() == 1, "there should be only 1 wallet open"

        do_save_wallet()

        # get the new qt wallet
        qt_wallet = main_window.tab_wallets.get_data_for_tab(
            get_tab_with_title(main_window.tab_wallets, title=wallet_name)
        )
        assert isinstance(qt_wallet, QTWallet)

        def export_wallet_descriptor() -> None:
            def on_dialog(dialog: DescriptorExport):
                shutter.save(dialog)
                assert dialog.isVisible()
                dialog.close()

            do_modal_click(main_window.export_wallet_for_coldcard_q, on_dialog, qtbot, cls=DescriptorExport)

            shutter.save(main_window)

        export_wallet_descriptor()

        def do_close_wallet() -> None:

            close_wallet(
                shutter=shutter,
                test_config=test_config,
                wallet_name=wallet_name,
                qtbot=qtbot,
                main_window=main_window,
            )

            shutter.save(main_window)

        do_close_wallet()

        def check_that_it_is_in_recent_wallets() -> None:
            assert any(
                [
                    (wallet_name in name)
                    for name in main_window.config.recently_open_wallets[main_window.config.network]
                ]
            )

            shutter.save(main_window)

        check_that_it_is_in_recent_wallets()

        def switch_language() -> None:
            main_window.language_chooser.switchLanguage("zh_CN")

            shutter.save(main_window)

        switch_language()

        # end
        shutter.save(main_window)
        sleep(2)

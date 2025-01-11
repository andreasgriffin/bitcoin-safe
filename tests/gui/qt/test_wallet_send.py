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
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from time import sleep

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.keystore_ui import SignerUI
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.tx_signing_steps import HorizontalImporters
from bitcoin_safe.gui.qt.ui_tx import UITx_Viewer
from bitcoin_safe.logging_setup import setup_logging  # type: ignore
from tests.gui.qt.test_setup_wallet import close_wallet, get_tab_with_title, save_wallet

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


@pytest.mark.marker_qt_2
def test_wallet_send(
    qapp: QApplication,
    qtbot: QtBot,
    test_start_time: datetime,
    test_config: UserConfig,
    bitcoin_core: Path,
    faucet: Faucet,
    wallet_file: str = "send_test.wallet",
    amount: int = int(1e6),
) -> None:  # bitcoin_core: Path,
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{test_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        temp_dir = Path(tempfile.mkdtemp()) / wallet_file

        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert qt_wallet

        qt_wallet.tabs.setCurrentWidget(qt_wallet.addresses_tab)

        shutter.save(main_window)
        # check wallet address
        assert qt_wallet.wallet.get_addresses()[0] == "bcrt1q3y9dezdy48czsck42q5udzmlcyjlppel5eg92k"

        def fund_wallet() -> None:
            # to be able to import a recipient list with amounts
            # i need to fund the wallet first
            faucet.send(qt_wallet.wallet.get_address().address.as_string(), amount=10000000)
            counter = 0
            while qt_wallet.wallet.get_balance().total == 0:
                with qtbot.waitSignal(qt_wallet.signal_after_sync, timeout=10000):
                    qt_wallet.sync()

                shutter.save(main_window)
                counter += 1
                if counter > 20:
                    raise Exception(
                        f"After {counter} syncing, the wallet balance is still {qt_wallet.wallet.get_balance().total}"
                    )

        fund_wallet()

        def import_recipients() -> None:
            qt_wallet.tabs.setCurrentWidget(qt_wallet.send_tab)
            shutter.save(main_window)
            qt_wallet.uitx_creator.recipients.add_recipient_button.click()
            shutter.save(main_window)

            test_file_path = "tests/data/recipients.csv"
            with open(str(test_file_path), "r") as file:
                test_file_content = file.read()

            qt_wallet.uitx_creator.recipients.import_csv(test_file_path)
            shutter.save(main_window)

            assert len(qt_wallet.uitx_creator.recipients.recipients) == 2
            r = qt_wallet.uitx_creator.recipients.recipients[0]
            assert r.address == "bcrt1q8tzpytutwlxpqjyhku3c4pyzz62sx5dv9ly67cx4qvran7stwlgqvmvhrw"
            assert r.amount == 1000
            assert r.label == "1"

            r = qt_wallet.uitx_creator.recipients.recipients[1]
            assert r.address == "bcrt1q6dqexpz2rp3r08nm6w8l5h3tgvqgn3c96jl6jt9vv3heylvmr8lskchhzn"
            assert r.amount == 2000
            assert r.label == "2"

            shutter.save(main_window)

            with tempfile.TemporaryDirectory() as tempdir:
                file_path = Path(tempdir) / "test.csv"
                qt_wallet.uitx_creator.recipients.export_csv(
                    qt_wallet.uitx_creator.recipients.recipients, file_path=file_path
                )

                assert file_path.exists()

                with open(str(file_path), "r") as file:
                    output_file_content = file.read()

                assert test_file_content == output_file_content

        import_recipients()

        def create_signed_tx() -> None:
            with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10000):
                qt_wallet.uitx_creator.button_ok.click()
            shutter.save(main_window)

            ui_tx_viewer = main_window.tab_wallets.getCurrentTabData()
            assert isinstance(ui_tx_viewer, UITx_Viewer)
            assert len(ui_tx_viewer.recipients.recipients) == 3

            sorted_recipients = sorted(
                ui_tx_viewer.recipients.recipients, key=lambda recipient: recipient.address
            )

            r = sorted_recipients[1]
            assert r.address == "bcrt1q8tzpytutwlxpqjyhku3c4pyzz62sx5dv9ly67cx4qvran7stwlgqvmvhrw"
            assert r.amount == 1000
            assert r.label == "1"

            r = sorted_recipients[0]
            assert r.address == "bcrt1q6dqexpz2rp3r08nm6w8l5h3tgvqgn3c96jl6jt9vv3heylvmr8lskchhzn"
            assert r.amount == 2000
            assert r.label == "2"

            r = sorted_recipients[2]
            assert r.address == "bcrt1qdcn67p707adhet4a9lh6pt8m5h4yjjf2nayqlq"
            assert r.address == qt_wallet.wallet.get_change_addresses()[0]
            assert r.amount == 9996804
            assert r.label == "Change of: 1, 2"

            ui_tx_viewer.button_next.click()

            horizontal_importer = ui_tx_viewer.tx_singning_steps.stacked_widget.widget(1)
            assert isinstance(horizontal_importer, HorizontalImporters)
            signer_ui = horizontal_importer.group_seed.data
            assert isinstance(signer_ui, SignerUI)
            assert signer_ui.buttons[0].text() == "Sign with mnemonic seed"

            with qtbot.waitSignal(signer_ui.signal_signature_added, timeout=10000):
                signer_ui.buttons[0].click()

            shutter.save(main_window)

        create_signed_tx()

        def send_tx() -> None:
            shutter.save(main_window)

            ui_tx_viewer = main_window.tab_wallets.getCurrentTabData()
            assert isinstance(ui_tx_viewer, UITx_Viewer)
            assert len(ui_tx_viewer.recipients.recipients) == 3

            sorted_recipients = sorted(
                ui_tx_viewer.recipients.recipients, key=lambda recipient: recipient.address
            )

            r = sorted_recipients[1]
            assert r.address == "bcrt1q8tzpytutwlxpqjyhku3c4pyzz62sx5dv9ly67cx4qvran7stwlgqvmvhrw"
            assert r.amount == 1000
            assert r.label == "1"

            r = sorted_recipients[0]
            assert r.address == "bcrt1q6dqexpz2rp3r08nm6w8l5h3tgvqgn3c96jl6jt9vv3heylvmr8lskchhzn"
            assert r.amount == 2000
            assert r.label == "2"

            r = sorted_recipients[2]
            assert r.address == "bcrt1qdcn67p707adhet4a9lh6pt8m5h4yjjf2nayqlq"
            assert r.address == qt_wallet.wallet.get_change_addresses()[0]
            assert r.amount == 9996804
            assert r.label == "Change of: 1, 2"

            with qtbot.waitSignal(qt_wallet.signal_after_sync, timeout=10000):
                ui_tx_viewer.button_send.click()

            shutter.save(main_window)
            qt_wallet_tab = main_window.tab_wallets.getCurrentTabData()
            assert isinstance(qt_wallet_tab, QTWallet)
            assert qt_wallet_tab.history_list._source_model.rowCount() == 1

        send_tx()

        def do_close_wallet() -> None:

            close_wallet(
                shutter=shutter,
                test_config=test_config,
                wallet_name=qt_wallet.wallet.id,
                qtbot=qtbot,
                main_window=main_window,
            )

            shutter.save(main_window)

        do_close_wallet()

        def check_that_it_is_in_recent_wallets() -> None:
            assert any(
                [
                    (wallet_file in name)
                    for name in main_window.config.recently_open_wallets[main_window.config.network]
                ]
            )

            shutter.save(main_window)

        check_that_it_is_in_recent_wallets()

        # end
        shutter.save(main_window)
        sleep(2)

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

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.dialog_import import ImportDialog
from bitcoin_safe.gui.qt.import_export import HorizontalImportExportAll
from bitcoin_safe.gui.qt.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.signer import SignatureImporterFile

from .helpers import Shutter, do_modal_click, main_window_context

logger = logging.getLogger(__name__)


@pytest.mark.marker_qt_2
def test_signature_import_of_psbt_without_utxos(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: UserConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(
        qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }"
    )

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        original_psbt_with_utxos = "cHNidP8BAHEBAAAAAeiHh9h+004gbKuOsftsvi1P8enQp7QXj2/f/h6k/rMJAAAAAAD9////Av4ZAAAAAAAAFgAU5ytVX56aHKFd1BCiUqgZhL0Hi4gbDgAAAAAAABYAFFBhg6P35dEjPH34fODiPRO9OJKF1/IDAAABAL8BAAAAAAEBcP3O2sajhJ1yG0zM8WuYb8wrA88K4aGLd+Al7y488QEBAAAAAP3///8BUigAAAAAAAAWABQ73GqQQhGGkxmRnebMJC65HIumYAJHMEQCIGzG1xsqSw2ZJSQcFhos5VEgIs+G20p3zoIUpyjeVXyYAiANdH1K5zIqNqCmWo9AE8kM2xCOv01fpghjRQrVvI2jwgEhAmtY5HMmAWGm3b0x23LNBgkKTghfLtusJRJJfcus+sKiBOYDAAEBH1IoAAAAAAAAFgAUO9xqkEIRhpMZkZ3mzCQuuRyLpmAiBgJgyxjKpjXG2L1+X23h78bcNOyOlp1xVi1R+AaLcDRTvBhgxsdBVAAAgAEAAIAAAACAAAAAABUAAAAAIgIDwbk3IqMd2FY+Jx0yXnbsX1cZlKK5p2L67qL/pbN5ngIYYMbHQVQAAIABAACAAAAAgAEAAAAWAAAAACICA0YS01vBUDnuhTE4wNtNXQpvPBWO0UDZWFeevJ74ZkQaGGDGx0FUAACAAQAAgAAAAIAAAAAASgAAAAA="
        signed_psbt = "70736274ff0100710100000001e88787d87ed34e206cab8eb1fb6cbe2d4ff1e9d0a7b4178f6fdffe1ea4feb3090000000000fdffffff02fe19000000000000160014e72b555f9e9a1ca15dd410a252a81984bd078b881b0e000000000000160014506183a3f7e5d1233c7df87ce0e23d13bd389285d7f203000022020260cb18caa635c6d8bd7e5f6de1efc6dc34ec8e969d71562d51f8068b703453bc463043022006706c689b59e0de113c45422775e1778cb1a801df09f1f2e092a11b3e1b06c9021f2e45dde2ff6adc3bb02e503c8c051d539240d36731685bceb1005623dee46801000000"
        main_window.open_tx_like_in_tab(original_psbt_with_utxos)

        QApplication.processEvents()

        uitx_viewer = list(main_window.tab_wallets.getAllTabData().values())[-1]
        assert isinstance(uitx_viewer, UITx_Viewer)
        assert uitx_viewer.tx_singning_steps

        assert not uitx_viewer.button_send.isEnabled()
        assert uitx_viewer.button_send.isVisible()
        assert not uitx_viewer.button_send.isEnabled()
        assert uitx_viewer.button_send.isVisible()

        assert not uitx_viewer.button_rbf.isVisible()
        assert not uitx_viewer.button_cpfp_tx.isVisible()
        assert not uitx_viewer.button_next.isVisible()
        assert not uitx_viewer.button_save_local_tx.isVisible()
        assert not uitx_viewer.button_previous.isVisible()

        assert uitx_viewer.tx_singning_steps.isVisible()
        assert len(uitx_viewer.tx_singning_steps.signature_importer_dict) == 1
        importer = list(uitx_viewer.tx_singning_steps.signature_importer_dict.values())[0]

        assert isinstance(importer[1], SignatureImporterFile)

        widget_import_export = uitx_viewer.tx_singning_steps.stacked_widget.widget(0)
        assert isinstance(widget_import_export, HorizontalImportExportAll)

        dialog_was_opened = False

        def text_entry(dialog: ImportDialog) -> None:
            shutter.save(dialog)
            nonlocal dialog_was_opened
            dialog_was_opened = True

            dialog.text_edit.setText(signed_psbt)
            assert dialog.button_ok

            shutter.save(dialog)
            dialog.button_ok.click()

        assert widget_import_export.file
        do_modal_click(
            widget_import_export.file.button_import.buttons[0].click, text_entry, qtbot, cls=ImportDialog
        )

        # let ui tx update with the new info
        QApplication.processEvents()

        assert uitx_viewer.button_send.isEnabled()
        assert uitx_viewer.button_edit_tx.isEnabled()
        assert uitx_viewer.button_save_local_tx.isEnabled()

        assert uitx_viewer.button_send.isVisible()
        assert uitx_viewer.button_edit_tx.isVisible()
        assert uitx_viewer.button_save_local_tx.isVisible()

        assert not uitx_viewer.button_rbf.isVisible()
        assert not uitx_viewer.button_cpfp_tx.isVisible()
        assert not uitx_viewer.button_next.isVisible()
        assert not uitx_viewer.button_previous.isVisible()

        # end
        shutter.save(main_window)
        qtbot.waitUntil(lambda: dialog_was_opened, timeout=10000)

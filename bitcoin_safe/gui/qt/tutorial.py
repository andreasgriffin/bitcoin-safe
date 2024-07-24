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


import logging
from abc import abstractmethod

from bitcoin_safe.gui.qt.export_data import ExportDataSimple
from bitcoin_safe.html import html_f
from bitcoin_safe.i18n import translate
from bitcoin_safe.signals import Signals

logger = logging.getLogger(__name__)

import enum
from math import ceil
from typing import Callable, Dict, List, Optional

import bdkpython as bdk
import numpy as np
from bitcoin_qr_tools.data import Data
from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpacerItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.descriptor_ui import KeyStoreUIs
from bitcoin_safe.gui.qt.dialogs import question_dialog
from bitcoin_safe.gui.qt.qt_wallet import QTWallet, QtWalletBase
from bitcoin_safe.gui.qt.tutorial_screenshots import (
    ScreenshotsExportXpub,
    ScreenshotsGenerateSeed,
    ScreenshotsRegisterMultisig,
    ScreenshotsTutorial,
    ScreenshotsViewSeed,
)

from ...pdfrecovery import make_and_open_pdf
from ...pythonbdk_types import Recipient
from ...tx import TxUiInfos
from ...util import Satoshis
from .qr_components.quick_receive import ReceiveGroup
from .spinning_button import SpinningButton
from .step_progress_bar import StepProgressContainer, TutorialWidget
from .taglist.main import hash_color
from .util import (
    Message,
    MessageType,
    add_centered_icons,
    caught_exception_message,
    create_button_box,
    icon_path,
    one_time_signal_connection,
    open_website,
)


class TutorialStep(enum.Enum):
    buy = enum.auto()
    generate = enum.auto()
    import_xpub = enum.auto()
    backup_seed = enum.auto()
    validate_backup = enum.auto()
    receive = enum.auto()
    register = enum.auto()
    reset = enum.auto()
    send = enum.auto()
    send2 = enum.auto()
    send3 = enum.auto()
    send4 = enum.auto()
    send5 = enum.auto()
    send6 = enum.auto()
    send7 = enum.auto()
    send8 = enum.auto()
    send9 = enum.auto()
    send10 = enum.auto()
    distribute = enum.auto()


class FloatingButtonBar(QDialogButtonBox):
    class TxSendStatus(enum.Enum):
        not_filled = enum.auto()
        filled = enum.auto()
        finalized = enum.auto()
        sent = enum.auto()

    def __init__(
        self,
        fill_tx: Callable,
        create_tx: Callable,
        go_to_next_index: Callable,
        go_to_previous_index: Callable,
        signals: Signals,
    ) -> None:
        super().__init__()
        self.status = None
        self._fill_tx = fill_tx
        self._create_tx = create_tx
        self._go_to_next_index = go_to_next_index
        self._go_to_previous_index = go_to_previous_index
        self.signals = signals

        self.signals.language_switch.connect(self.updateUi)

    def set_visibilities(self) -> None:
        self.tutorial_button_prefill.setVisible(self.status in [self.TxSendStatus.not_filled])
        self.button_create_tx.setVisible(self.status in [self.TxSendStatus.filled])
        self.tutorial_button_prev_step.setVisible(True)
        self.button_yes_it_is_in_hist.setVisible(
            self.status in [self.TxSendStatus.finalized, self.TxSendStatus.sent]
        )
        self.button_create_tx_again.setVisible(
            self.status in [self.TxSendStatus.finalized, self.TxSendStatus.sent]
        )

    def set_status(self, status=TxSendStatus) -> None:
        if self.status == status:
            return
        self.status = status
        self.set_visibilities()

    def fill_tx(self) -> None:
        self._fill_tx()
        self.set_status(self.TxSendStatus.filled)

    def create_tx(self) -> None:
        # before do _create_tx, setup a 1 time connection
        # so I can catch the tx and ensure that TxSendStatus == finalized
        # just in case the suer clicked "go back"
        def catch_txid(tx: bdk.Transaction) -> None:
            self.set_status(self.TxSendStatus.finalized)

        one_time_signal_connection(self.signals.signal_broadcast_tx, catch_txid)

        self._create_tx()
        self.set_status(self.TxSendStatus.finalized)

    def go_to_next_index(self) -> None:
        self._go_to_next_index()
        self.set_status(self.TxSendStatus.not_filled)

    def go_to_previous_index(self) -> None:
        self._go_to_previous_index()
        self.set_status(self.TxSendStatus.not_filled)

    def fill(self) -> QDialogButtonBox:
        self.setVisible(False)

        self.tutorial_button_prefill = QPushButton()
        self.tutorial_button_prefill.clicked.connect(self.fill_tx)
        self.addButton(self.tutorial_button_prefill, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_create_tx = QPushButton()
        self.button_create_tx.clicked.connect(self.create_tx)
        self.addButton(self.button_create_tx, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_yes_it_is_in_hist = QPushButton()
        self.button_yes_it_is_in_hist.setVisible(False)
        self.button_yes_it_is_in_hist.clicked.connect(self.go_to_next_index)
        self.addButton(self.button_yes_it_is_in_hist, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_create_tx_again = QPushButton()
        self.button_create_tx_again.setVisible(False)
        self.button_create_tx_again.clicked.connect(self.fill_tx)
        self.addButton(self.button_create_tx_again, QDialogButtonBox.ButtonRole.AcceptRole)

        self.tutorial_button_prev_step = QPushButton()
        self.tutorial_button_prev_step.clicked.connect(self.go_to_previous_index)
        self.addButton(self.tutorial_button_prev_step, QDialogButtonBox.ButtonRole.RejectRole)

        self.set_status(self.TxSendStatus.not_filled)

    def updateUi(self) -> None:

        self.tutorial_button_prefill.setText(self.tr("Fill the transaction fields"))
        self.button_create_tx.setText(self.tr("Create Transaction"))
        self.button_create_tx_again.setText(self.tr("Create Transaction again"))
        self.button_yes_it_is_in_hist.setText(self.tr("Yes, I see the transaction in the history"))
        self.tutorial_button_prev_step.setText(self.tr("Previous Step"))


class TabInfo:
    def __init__(
        self,
        container: StepProgressContainer,
        wallet_tabs: QTabWidget,
        qtwalletbase: QtWalletBase,
        go_to_next_index: Callable,
        go_to_previous_index: Callable,
        floating_button_box: FloatingButtonBar,
        signal_create_wallet,
        max_test_fund: int,
        qt_wallet: QTWallet = None,
    ) -> None:
        self.container = container
        self.wallet_tabs = wallet_tabs
        self.qtwalletbase = qtwalletbase
        self.go_to_next_index = go_to_next_index
        self.go_to_previous_index = go_to_previous_index
        self.floating_button_box = floating_button_box
        self.signal_create_wallet = signal_create_wallet
        self.qt_wallet = qt_wallet
        self.max_test_fund = max_test_fund


class BaseTab(QObject):
    def __init__(self, refs: TabInfo) -> None:
        super().__init__(parent=refs.container)
        self.refs = refs

        self.buttonbox, self.buttonbox_buttons = create_button_box(
            self.refs.go_to_next_index,
            self.refs.go_to_previous_index,
            ok_text="",
            cancel_text="",
        )
        self.refs.qtwalletbase.signals.language_switch.connect(self.updateUi)

    @abstractmethod
    def create(self) -> TutorialWidget:
        pass

    def updateUi(self) -> None:
        self.buttonbox_buttons[0].setText(translate("basetab", "Next step"))
        self.buttonbox_buttons[1].setText(translate("basetab", "Previous Step"))
        self.refs.floating_button_box.updateUi()

    def num_keystores(self) -> int:
        return self.refs.qtwalletbase.get_mn_tuple()[1]

    def get_never_label_text(self) -> str:
        return html_f(
            html_f(
                translate("tutorial", "Never share the 24 secret words with anyone!"),
                p=True,
                size=12,
                color="red",
            )
            + html_f(
                translate("tutorial", "Never type them into any computer or cellphone!"),
                p=True,
                size=12,
                color="red",
            )
            + html_f(translate("tutorial", "Never make a picture of them!"), p=True, size=12, color="red"),
            add_html_and_body=True,
        )


class BuyHardware(BaseTab):
    def create(self) -> TutorialWidget:
        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["coldcard-only.svg"] * int(np.ceil(self.num_keystores() / 2))
            + ["usb-stick.svg"] * int(np.floor(self.num_keystores() / 2)),
            widget,
            max_sizes=[(100, 80)] * self.num_keystores(),
        )

        widget.layout().itemAt(0).widget().setMaximumWidth(150)

        right_widget = QWidget()
        right_widget.setLayout(QVBoxLayout())
        right_widget.layout().setAlignment(Qt.AlignmentFlag.AlignVCenter)
        widget.layout().addWidget(right_widget)

        self.label_buy = QLabel(widget)
        self.label_buy.setWordWrap(True)
        right_widget.layout().addWidget(self.label_buy)

        self.button_buycoldcard = QPushButton()
        self.button_buycoldcard.setIcon(QIcon(icon_path("coldcard-only.svg")))
        self.button_buycoldcard.clicked.connect(
            lambda: open_website("https://store.coinkite.com/promo/8BFF877000C34A86F410")
        )
        right_widget.layout().addWidget(self.button_buycoldcard)
        self.button_buycoldcard.setIconSize(QSize(32, 32))  # Set the icon size to 64x64 pixels

        self.button_buybitbox = QPushButton()
        self.button_buybitbox.setIcon(QIcon(icon_path("usb-stick.svg")))
        self.button_buybitbox.clicked.connect(
            lambda: open_website("https://shiftcrypto.ch/bitbox02/?ref=MOB4dk7gpm")
        )
        self.button_buybitbox.setIconSize(QSize(32, 32))  # Set the icon size to 64x64 pixels
        right_widget.layout().addWidget(self.button_buybitbox)

        right_widget.layout().addItem(QSpacerItem(1, 40))

        self.label_turn_on = QLabel(widget)
        self.label_turn_on.setWordWrap(True)

        right_widget.layout().addWidget(self.label_turn_on)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(self.refs.wallet_tabs, set_also_visible=False)

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        self.label_buy.setText(
            html_f(self.tr("Do you need to buy a hardware signer?"), add_html_and_body=True, p=True, size=12)
        )

        self.button_buybitbox.setText(self.tr("Buy a {name}").format(name="Bitbox02\nBitcoin Only Edition"))
        self.button_buycoldcard.setText(self.tr("Buy a Coldcard\n5% off"))
        self.label_turn_on.setText(
            html_f(
                self.tr("Turn on your {n} hardware signers").format(n=self.num_keystores())
                if self.num_keystores() > 1
                else self.tr("Turn on your hardware signer"),
                add_html_and_body=True,
                p=True,
                size=12,
            ),
        )


class GenerateSeed(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.screenshot = ScreenshotsGenerateSeed()
        widget.layout().addWidget(self.screenshot)

        self.never_label = QLabel()
        self.never_label.setWordWrap(True)
        self.never_label.setMinimumWidth(300)
        widget.layout().addWidget(self.never_label)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(self.refs.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.refs.floating_button_box, set_also_visible=False)

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        self.screenshot.updateUi()
        self.never_label.setText(self.get_never_label_text())


class ValidateBackup(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.screenshot = ScreenshotsViewSeed()
        widget.layout().addWidget(self.screenshot)
        self.never_label = QLabel()
        self.never_label.setWordWrap(True)
        self.never_label.setMinimumWidth(300)
        widget.layout().addWidget(self.never_label)

        buttonbox = QDialogButtonBox()
        self.custom_yes_button = QPushButton()
        self.custom_yes_button.clicked.connect(self.refs.go_to_next_index)
        buttonbox.addButton(self.custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.custom_cancel_button = QPushButton()
        self.custom_cancel_button.clicked.connect(self.refs.go_to_previous_index)
        buttonbox.addButton(self.custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(self.refs.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.refs.floating_button_box, set_also_visible=False)

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        self.custom_yes_button.setText(self.tr("Yes, I am sure all 24 words are correct"))
        self.custom_cancel_button.setText(self.tr("Previous Step"))
        self.screenshot.updateUi()
        self.never_label.setText(self.get_never_label_text())


class ImportXpubs(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget.setLayout(QVBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.screenshot = ScreenshotsExportXpub()
        widget.layout().addWidget(self.screenshot)

        self.label_import = QLabel()
        # handle protowallet and qt_wallet differently:
        self.button_create_wallet = QPushButton("")
        if self.refs.qt_wallet:
            # show the full walet descriptor tab below
            pass

        else:
            # integrater the KeyStoreUIs into the tutorials, hide wallet_tabs

            self.label_import.setFont(self.screenshot.title.font())
            widget.layout().addWidget(self.label_import)

            # this is used in TutorialStep.import_xpub
            self.keystore_uis = KeyStoreUIs(
                get_editable_protowallet=self.refs.qtwalletbase.get_editable_protowallet,
                get_address_type=lambda: self.refs.qtwalletbase.get_editable_protowallet().address_type,
                signals_min=self.refs.qtwalletbase.signals,
            )
            self.keystore_uis.setCurrentIndex(0)
            widget.layout().addWidget(self.keystore_uis)

            def create_wallet() -> None:
                try:
                    self.keystore_uis.set_protowallet_from_keystore_ui()
                    self.refs.qtwalletbase.get_editable_protowallet().tutorial_index = (
                        self.refs.container.current_index() + 1
                    )
                    self.refs.signal_create_wallet.emit()
                except Exception as e:
                    caught_exception_message(e)

            # hide the next button
            self.buttonbox_buttons[0].setHidden(True)
            # and add the create wallet button
            self.buttonbox_buttons.append(self.button_create_wallet)
            self.buttonbox.addButton(self.button_create_wallet, QDialogButtonBox.ButtonRole.AcceptRole)
            self.button_create_wallet.clicked.connect(create_wallet)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )

        def callback() -> None:
            self.refs.wallet_tabs.setCurrentWidget(self.refs.qtwalletbase.wallet_descriptor_tab)
            tutorial_widget.synchronize_visiblity(
                self.refs.wallet_tabs, set_also_visible=bool(self.refs.qt_wallet)
            )

        tutorial_widget.set_callback(callback)
        tutorial_widget.synchronize_visiblity(
            self.refs.wallet_tabs, set_also_visible=bool(self.refs.qt_wallet)
        )
        tutorial_widget.synchronize_visiblity(self.refs.floating_button_box, set_also_visible=False)

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        self.label_import.setText(self.tr("2. Import wallet information into Bitcoin Safe"))
        if self.refs.qt_wallet:
            self.button_create_wallet.setText(self.tr("Skip step"))
        else:
            self.button_create_wallet.setText(self.tr("Next step"))
        self.buttonbox_buttons[1].setText(self.tr("Previous Step"))
        self.screenshot.updateUi()


class BackupSeed(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["descriptor-backup.svg"],
            widget,
            max_sizes=[(100 * self.num_keystores(), 120)],
        )

        self.label_print_instructions = QLabel(widget)
        self.label_print_instructions.setWordWrap(True)

        widget.layout().addWidget(self.label_print_instructions)

        def do_pdf() -> None:
            if not self.refs.qt_wallet:
                Message(self.tr("Please complete the previous steps."))
                return
            make_and_open_pdf(self.refs.qt_wallet.wallet)

        # button = create_button(
        #     "Print the descriptor", icon_path("pdf-file.svg"), widget, layout
        # )
        # button.setMaximumWidth(150)
        # button.clicked.connect(do_pdf)

        buttonbox = QDialogButtonBox()
        self.custom_yes_button = QPushButton()
        self.custom_yes_button.setIcon(QIcon(icon_path("print.svg")))
        self.custom_yes_button.clicked.connect(do_pdf)
        self.custom_yes_button.clicked.connect(self.refs.go_to_next_index)
        buttonbox.addButton(self.custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.custom_cancel_button = QPushButton()
        self.custom_cancel_button.clicked.connect(self.refs.go_to_previous_index)
        buttonbox.addButton(self.custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(self.refs.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.refs.floating_button_box, set_also_visible=False)

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()

        self.custom_yes_button.setText(self.tr("Print recovery sheet"))
        self.custom_cancel_button.setText(self.tr("Previous Step"))

        self.label_print_instructions.setText(
            html_f(
                f"""<ol>
        <li>{self.tr('Print the pdf (it also contains the wallet descriptor)')}</li>
        <li>{self.tr('Write each 24-word seed onto the printed pdf.') if self.num_keystores()>1 else self.tr('Write the 24-word seed onto the printed pdf.') }</li>
        </ol>""",
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )


class ReceiveTest(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(10, 0, 0, 0)  # Left, Top, Right, Bottom margins
        widget.layout().setSpacing(20)
        self.quick_receive: Optional[ReceiveGroup] = None

        if self.refs.qt_wallet:
            category = self.refs.qt_wallet.wallet.labels.get_default_category()
            address_info = self.refs.qt_wallet.wallet.get_unused_category_address(category)
            self.quick_receive = ReceiveGroup(
                category,
                hash_color(category).name(),
                address_info.address.as_string(),
                address_info.address.to_qr_uri(),
            )
            self.quick_receive.setMaximumHeight(300)
            widget.layout().addWidget(self.quick_receive)
        else:
            add_centered_icons(["receive.svg"], widget, max_sizes=[(50, 80)])
            widget.layout().itemAt(0).widget().setMaximumWidth(150)

        self.label_receive_description = QLabel(widget)
        self.label_receive_description.setWordWrap(True)

        widget.layout().addWidget(self.label_receive_description)

        buttonbox = QDialogButtonBox()
        self.next_button = QPushButton()
        self.next_button.clicked.connect(self.refs.go_to_next_index)
        buttonbox.addButton(self.next_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.check_button = SpinningButton("")
        buttonbox.addButton(self.check_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.refs.go_to_previous_index)
        buttonbox.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        self.next_button.setHidden(True)

        def on_sync_done(sync_status) -> None:
            if not self.refs.qt_wallet:
                return
            txos = self.refs.qt_wallet.wallet.get_all_txos(include_not_mine=False)
            self.check_button.setHidden(bool(txos))
            self.next_button.setHidden(not bool(txos))
            if txos:
                Message(
                    self.tr("Received {amount}").format(
                        amount=Satoshis(
                            txos[0].txout.value, self.refs.qt_wallet.wallet.network
                        ).str_with_unit()
                    )
                )

        def start_sync() -> None:
            if not self.refs.qt_wallet:
                Message(self.tr("No wallet setup yet"), type=MessageType.Error)
                return

            self.refs.qt_wallet.sync()
            self.check_button.set_enable_signal(self.refs.qtwalletbase.signal_after_sync)
            one_time_signal_connection(self.refs.qtwalletbase.signal_after_sync, on_sync_done)

        self.check_button.clicked.connect(start_sync)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(self.refs.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.refs.floating_button_box, set_also_visible=False)

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        test_amount = (
            f"(less than {Satoshis( self.refs.max_test_fund, self.refs.qt_wallet.wallet.network).str_with_unit()}) "
            if self.refs.qt_wallet
            else ""
        )
        self.label_receive_description.setText(
            html_f(
                self.tr("Receive a small amount {test_amount} to an address of this wallet").format(
                    test_amount=test_amount
                ),
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )
        self.next_button.setText(self.tr("Next step"))
        self.check_button.setText(self.tr("Check if received"))
        self.cancel_button.setText(self.tr("Previous Step"))


class RegisterMultisig(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # width = 300
        # svg_widgets = add_centered_icons(["reset-signer.svg"], widget, max_sizes=[(width, 120)])
        # widget.layout().itemAt(0).widget().setMaximumWidth(width)
        self.groupbox1 = ScreenshotsTutorial()
        if self.refs.qt_wallet:

            title = "Coldcard - Mk4"
            export_widget = ExportDataSimple(
                data=Data.from_str(
                    self.refs.qt_wallet.wallet.multipath_descriptor.as_string(),
                    network=self.refs.qt_wallet.wallet.network,
                ),
                signals_min=self.refs.qt_wallet.signals,
                enable_clipboard=False,
                enable_usb=False,
                enable_qr=False,
                layout=QVBoxLayout(),
            )
            self.groupbox1.sync_tab.addTab(export_widget, title)

            title = "Coldcard - Q"
            export_widget = ExportDataSimple(
                data=Data.from_str(
                    self.refs.qt_wallet.wallet.multipath_descriptor.as_string(),
                    network=self.refs.qt_wallet.wallet.network,
                ),
                signals_min=self.refs.qt_wallet.signals,
                enable_clipboard=False,
                enable_usb=False,
                layout=QVBoxLayout(),
            )
            self.groupbox1.sync_tab.addTab(export_widget, title)

            widget.layout().addWidget(self.groupbox1)

        self.screenshot = ScreenshotsRegisterMultisig()
        widget.layout().addWidget(self.screenshot)

        buttonbox = QDialogButtonBox()
        self.custom_yes_button = QPushButton()
        self.custom_yes_button.clicked.connect(self.refs.go_to_next_index)
        buttonbox.addButton(self.custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.custom_cancel_button = QPushButton()
        self.custom_cancel_button.clicked.connect(self.refs.go_to_previous_index)
        buttonbox.addButton(self.custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(self.refs.wallet_tabs, set_also_visible=False)

        def callback() -> None:
            if not self.refs.qt_wallet:
                return
            balance = self.refs.qt_wallet.wallet.bdkwallet.get_balance().total
            if balance > self.refs.max_test_fund:
                Message(
                    self.tr(
                        "Your balance {balance} is greater than a maximally allowed test amount of {amount}!\nPlease do the hardware signer reset only  with a lower balance!  (Send some funds out before)"
                    ).format(
                        balance=Satoshis(balance, self.refs.qt_wallet.wallet.network).str_with_unit(),
                        amount=Satoshis(
                            self.refs.max_test_fund, self.refs.qt_wallet.wallet.network
                        ).str_with_unit(),
                    ),
                    type=MessageType.Warning,
                )

        tutorial_widget.set_callback(callback)
        tutorial_widget.synchronize_visiblity(self.refs.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.refs.floating_button_box, set_also_visible=False)

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        self.groupbox1.title.setText(self.tr("1. Export wallet descriptor"))
        self.custom_yes_button.setText(
            self.tr("Yes, I registered the multisig on the {n} hardware signer").format(
                n=self.num_keystores()
            )
        )
        self.custom_cancel_button.setText(self.tr("Previous Step"))
        self.screenshot.updateUi()
        self.screenshot.set_title(
            self.tr("2. Import in each hardware signer")
            if self.num_keystores() > 1
            else self.tr("2. Import in the hardware signer")
        )


class DistributeSeeds(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        if self.num_keystores() > 1:
            add_centered_icons(
                ["distribute-multisigsig-export.svgz"],
                widget,
                max_sizes=[(400, 350)] * self.num_keystores(),
            )
        else:
            add_centered_icons(
                ["distribute-singlesig-export.svgz"],
                widget,
                max_sizes=[(400, 350)] * self.num_keystores(),
            )

        widget.layout().itemAt(0).widget().setMaximumWidth(400)

        right_widget = QWidget()
        right_widget.setLayout(QVBoxLayout())
        right_widget.layout().setAlignment(Qt.AlignmentFlag.AlignVCenter)
        widget.layout().addWidget(right_widget)

        self.label_main = QLabel(widget)
        self.label_main.setWordWrap(True)

        right_widget.layout().addWidget(self.label_main)

        right_widget.layout().addItem(QSpacerItem(1, 40))
        self.buttonbox_buttons[0].setIcon(QIcon(icon_path("checkmark.png")))

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(self.refs.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.refs.floating_button_box, set_also_visible=False)

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()

        if self.num_keystores() > 1:
            self.label_main.setText(
                html_f(
                    f"""<ul>
  <li>{self.tr('Place each seed backup and hardware signer in a secure location, such:')}</li>
   <ul>
   {''.join([f"<li>{self.tr('Seed backup {j} and hardware signer {j} should be in location {j}').format(j=i+1)}</li>" for i in  range(self.num_keystores())]) if self.num_keystores()>1 else ""}
   </ul>   
   <li>{self.tr('Choose the secure places carefully, considering that you need to go to {m} of the {n}, to spend from your multisig-wallet.').format(m=self.refs.qtwalletbase.get_mn_tuple()[0], n=self.num_keystores())}</li>
</ul> """,
                    add_html_and_body=True,
                    p=True,
                    size=12,
                )
            )
        else:
            self.label_main.setText(
                html_f(
                    f"""<ul>
  <li>{self.tr('Store the  seed backup   in a <b>very</b> secure location (like a vault).')}</li>
   <ul>
      <li>{self.tr('The seed backup (24 words) give total control over the funds.')}</li>
   </ul>     
  <li>{self.tr('Store the   hardware signer   in secure location.')}</li>
   </ul>  
</ul>""",
                    add_html_and_body=True,
                    p=True,
                    size=12,
                )
            )
        self.buttonbox_buttons[0].setText(self.tr("Finish"))


class SendTest(BaseTab):
    def __init__(self, test_label, test_number, tx_text, refs: TabInfo) -> None:
        super().__init__(refs)
        self.test_label = test_label
        self.test_number = test_number
        self.tx_text = tx_text

    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(["send.svg"], widget, max_sizes=[(50, 80)])
        widget.layout().itemAt(0).widget().setMaximumWidth(150)

        inner_widget = QWidget()
        inner_widget_layout = QVBoxLayout(inner_widget)
        self.label = QLabel()
        if self.num_keystores() == 1:

            inner_widget_layout.addWidget(self.label)

        else:

            self.label = QLabel(html_f(self.tx_text, add_html_and_body=True, p=True, size=12))
            inner_widget_layout.addWidget(self.label)

        widget.layout().addWidget(inner_widget)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.setMinimumHeight(30)

        def callback() -> None:
            if not self.refs.qt_wallet:
                return
            logger.debug(f"tutorial callback")

            # compare how many tx were already done , to the current test_number
            def should_offer_skip() -> bool:
                if not spend_txos:
                    return False
                return len(spend_txos) >= self.test_number + 1

            # offer to skip this step if it was spend from this wallet
            txos = self.refs.qt_wallet.wallet.get_all_txos(include_not_mine=False)
            spend_txos = [txo for txo in txos if txo.is_spent_by_txid]

            if not should_offer_skip():
                return

            if question_dialog(
                text=self.tr(
                    "You made {n} outgoing transactions already. Would you like to skip this spend test?"
                ).format(n=len(spend_txos)),
                title=self.tr("Skip spend test?"),
                buttons=QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
            ):
                self.refs.go_to_next_index()
                return

            self.refs.floating_button_box.fill_tx()

        tutorial_widget.set_callback(callback)
        tutorial_widget.synchronize_visiblity(
            self.refs.wallet_tabs, set_also_visible=bool(self.refs.qt_wallet)
        )
        tutorial_widget.synchronize_visiblity(self.refs.floating_button_box, set_also_visible=True)
        tutorial_widget.synchronize_visiblity(tutorial_widget.button_box, set_also_visible=False)
        if self.refs.qt_wallet:
            tutorial_widget.synchronize_visiblity(
                self.refs.qt_wallet.uitx_creator.button_box, set_also_visible=False
            )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()

        self.label.setText(
            html_f(
                self.tr("Complete the send test to ensure the hardware signer works!"),
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )


class WalletSteps(StepProgressContainer):
    signal_create_wallet = pyqtSignal()

    def __init__(
        self,
        qtwalletbase: QtWalletBase,
        wallet_tabs: QTabWidget,
        max_test_fund=1_000_000,
        qt_wallet: QTWallet = None,
    ) -> None:
        super().__init__(step_labels=[""] * 3)  # initialize with 3 steps (doesnt matter)
        self.qtwalletbase = qtwalletbase
        self.qt_wallet = qt_wallet
        m, n = self.qtwalletbase.get_mn_tuple()

        # floating_button_box
        self.floating_button_box = FloatingButtonBar(
            self.fill_tx,
            self.qt_wallet.uitx_creator.create_tx
            if self.qt_wallet
            else lambda: Message(self.tr("You must have an initilized wallet first")),
            self.go_to_next_index,
            self.go_to_previous_index,
            self.qtwalletbase.signals,
        )
        self.floating_button_box.fill()
        self.qtwalletbase.outer_layout.addWidget(self.floating_button_box)

        refs = TabInfo(
            container=self,
            wallet_tabs=wallet_tabs,
            qtwalletbase=qtwalletbase,
            go_to_next_index=self.go_to_next_index,
            go_to_previous_index=self.go_to_previous_index,
            floating_button_box=self.floating_button_box,
            signal_create_wallet=self.signal_create_wallet,
            qt_wallet=self.qt_wallet,
            max_test_fund=max_test_fund,
        )

        self.tab_generators: Dict[TutorialStep, BaseTab] = {
            TutorialStep.buy: BuyHardware(refs=refs),
            TutorialStep.generate: GenerateSeed(refs=refs),
            TutorialStep.import_xpub: ImportXpubs(refs=refs),
            TutorialStep.backup_seed: BackupSeed(refs=refs),
            TutorialStep.validate_backup: ValidateBackup(refs=refs),
            TutorialStep.receive: ReceiveTest(refs=refs),
        }
        if n > 1:
            self.tab_generators[TutorialStep.register] = RegisterMultisig(refs=refs)

        for test_number, tutoral_step in enumerate(self.get_send_tests_steps()):
            self.tab_generators[tutoral_step] = SendTest(
                self.get_send_test_labels()[test_number],
                test_number=test_number,
                tx_text=self.tx_text(test_number),
                refs=refs,
            )

        self.tab_generators[TutorialStep.distribute] = DistributeSeeds(refs=refs)

        self.wallet_tabs = wallet_tabs
        self.max_test_fund = max_test_fund

        self.qtwalletbase.outer_layout.insertWidget(0, self)

        self.widgets: Dict[TutorialStep, TutorialWidget] = {
            key: generator.create() for key, generator in self.tab_generators.items()
        }

        # set_custom_widget  from StepProgressContainer
        for i, widget in enumerate(self.widgets.values()):
            self.set_custom_widget(i, widget)

        if self.qt_wallet:
            if self.qt_wallet.wallet.tutorial_index is not None:
                self.set_current_index(self.qt_wallet.wallet.tutorial_index)
            # save after every step
            self.signal_set_current_widget.connect(lambda widget: self.qt_wallet.save())

        self.updateUi()
        self.set_visibilities()

        self.qtwalletbase.signals.language_switch.connect(self.updateUi)

    def current_step(self) -> TutorialStep:
        return self.get_step_of_index(self.current_index())

    def index_of_step(self, step: TutorialStep) -> int:
        return list(TutorialStep).index(step)

    def get_step_of_index(self, index: int) -> TutorialStep:
        members = list(self.tab_generators.keys())
        if index < 0:
            index = 0
        if index >= len(members):
            index = len(members) - 1
        return members[index]

    def get_wallet_tutorial_index(self) -> int:
        return (
            (self.qt_wallet.wallet.tutorial_index)
            if self.qt_wallet
            else self.qtwalletbase.get_editable_protowallet().tutorial_index
        )

    def set_wallet_tutorial_index(self, value: Optional[int]) -> None:
        if self.qt_wallet:
            self.qt_wallet.wallet.tutorial_index = value
        else:
            self.qtwalletbase.get_editable_protowallet().tutorial_index = value

    def set_visibilities(self) -> None:
        should_be_visible = self.get_wallet_tutorial_index() != None
        self.setVisible(should_be_visible)

        if should_be_visible:
            self.signal_widget_focus.emit(self.widgets[self.current_step()])
        else:
            self.wallet_tabs.setVisible(True)
            self.floating_button_box.setVisible(False)
            if self.qt_wallet:
                self.qt_wallet.uitx_creator.button_box.setVisible(True)

    def num_keystores(self) -> int:
        return self.qtwalletbase.get_mn_tuple()[1]

    def change_index(self, index: int) -> None:
        self.set_current_index(index)

    def go_to_previous_index(self) -> None:
        logger.info(f"go_to_previous_index: Old index {self.current_index()} = {self.current_step()}")
        self.change_index(max(self.current_index() - 1, 0))
        logger.info(f"go_to_previous_index: Switched index {self.current_index()} = {self.current_step()}")

    def go_to_next_index(self) -> None:
        if self.step_bar.current_index + 1 >= self.step_bar.number_of_steps:
            self.set_wallet_tutorial_index(None)
            self.set_visibilities()

            return
        logger.info(f"go_to_next_index: Old index {self.current_index()} = {self.current_step()}")
        self.change_index(min(self.step_bar.current_index + 1, self.step_bar.number_of_steps - 1))
        logger.info(f"go_to_next_index: Switched index {self.current_index()} = {self.current_step()}")

    def get_send_tests_steps(self) -> List[TutorialStep]:
        m, n = self.qtwalletbase.get_mn_tuple()

        number = ceil(n / m)

        start_index = self.index_of_step(TutorialStep.send)

        return list(TutorialStep)[start_index : start_index + number]

    def get_send_test_labels(self) -> List[str]:
        m, n = self.qtwalletbase.get_mn_tuple()
        keystore_labels = self.qtwalletbase.get_keystore_labels()

        send_test_labels = []
        for i_send_tests, tutorial_step in enumerate(self.get_send_tests_steps()):

            start_signer = m * i_send_tests
            end_signer = min(m * i_send_tests + m, n)

            missing_signers = m - (end_signer - start_signer)
            start_signer -= missing_signers

            labels = [keystore_labels[j] for j in range(start_signer, end_signer)]
            send_test_labels.append(self.tr(" and ").join([f'"{label}"' for label in labels]))

        return send_test_labels

    def tx_text(self, test_number: int) -> str:
        if self.num_keystores() == 1:
            return self.tr("Send Test")
        else:

            return self.tr("Sign with {label}").format(label=self.get_send_test_labels()[test_number])

    def open_tx(self, test_number: int) -> None:
        if not self.qt_wallet:
            return

        label = self.tx_text(test_number)

        utxos = self.qt_wallet.wallet.bdkwallet.list_unspent()
        if not utxos:
            Message(self.tr("The wallet is not funded. Please fund the wallet."))
            return

        txinfos = TxUiInfos()
        txinfos.main_wallet_id = self.qt_wallet.wallet.id
        # inputs
        txinfos.fill_utxo_dict_from_utxos(utxos)
        # outputs
        txinfos.recipients.append(
            Recipient(
                self.qt_wallet.wallet.get_address().address.as_string(),
                0,
                checked_max_amount=True,
                label=label,
            )
        )

        self.qtwalletbase.signals.open_tx_like.emit(txinfos)

    def fill_tx(self) -> None:
        if not self.qt_wallet:
            return

        self.wallet_tabs.setCurrentWidget(self.qt_wallet.send_tab)

        # use the current_step, but if I highlighted another signing
        if self.current_step() in self.get_send_tests_steps():
            test_number = self.get_send_tests_steps().index(self.current_step())
        else:
            hightligted_step = self.get_step_of_index(self.current_highlighted_index())
            if hightligted_step in self.get_send_tests_steps():
                test_number = self.get_send_tests_steps().index(hightligted_step)
            else:
                # don't know what tx to fill
                return

        # set all tabs except the send as hidden
        for i in range(self.qt_wallet.tabs.count()):
            tab_widget = self.qt_wallet.tabs.widget(i)
            tab_widget.setHidden(tab_widget != self.qt_wallet.send_tab)
        self.open_tx(test_number)

    def updateUi(self) -> None:
        # step_bar
        labels: Dict[TutorialStep, str] = {
            TutorialStep.buy: self.tr("Turn on hardware signer"),
            TutorialStep.generate: self.tr("Generate Seed"),
            TutorialStep.import_xpub: self.tr("Import signer info"),
            TutorialStep.backup_seed: self.tr("Backup Seed"),
            TutorialStep.validate_backup: self.tr("Validate Backup"),
            TutorialStep.receive: self.tr("Receive Test"),
            TutorialStep.distribute: self.tr("Put in secure locations"),
            TutorialStep.register: self.tr("Register multisig on signers"),
        }
        for i, tutoral_step in enumerate(self.get_send_tests_steps()):
            labels[tutoral_step] = (
                self.tr("Send test {j}").format(j=i + 1)
                if len(self.get_send_tests_steps()) > 1
                else self.tr("Send test")
            )

        self.set_labels([labels[key] for key in self.tab_generators])

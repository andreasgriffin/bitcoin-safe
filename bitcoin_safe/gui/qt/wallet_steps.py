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
import xml.etree.ElementTree as ET
from abc import abstractmethod

from bitcoin_usb.address_types import AddressTypes
from bitcoin_usb.gui import USBGui

from bitcoin_safe.gui.qt.bitcoin_quick_receive import BitcoinQuickReceive
from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget
from bitcoin_safe.gui.qt.export_data import ExportDataSimple
from bitcoin_safe.gui.qt.keystore_ui import (
    HardwareSignerInteractionWidget,
    icon_for_label,
)
from bitcoin_safe.gui.qt.qr_types import QrType
from bitcoin_safe.gui.qt.register_multisig import USBRegisterMultisigWidget
from bitcoin_safe.gui.qt.wallet_steps_base import WalletStepsBase
from bitcoin_safe.html_utils import html_f
from bitcoin_safe.i18n import translate
from bitcoin_safe.signals import Signals, UpdateFilter, UpdateFilterReason
from bitcoin_safe.threading_manager import ThreadingManager
from bitcoin_safe.wallet import ProtoWallet, Wallet

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
    QInputDialog,
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
from bitcoin_safe.gui.qt.qt_wallet import QTWallet, QtWalletBase, SyncStatus
from bitcoin_safe.gui.qt.tutorial_screenshots import (
    HardwareSigners,
    ScreenshotsGenerateSeed,
    ScreenshotsRegisterMultisig,
    ScreenshotsTutorial,
    ScreenshotsViewSeed,
)

from ...pdfrecovery import TEXT_24_WORDS, make_and_open_pdf
from ...pythonbdk_types import Recipient
from ...tx import TxUiInfos
from ...util import Satoshis
from .spinning_button import SpinningButton
from .step_progress_bar import StepProgressContainer, TutorialWidget, VisibilityOption
from .util import (
    AspectRatioSvgWidget,
    Message,
    MessageType,
    add_centered_icons,
    caught_exception_message,
    center_in_widget,
    create_button_box,
    icon_path,
    one_time_signal_connection,
    open_website,
)


class TutorialStep(enum.Enum):
    buy = enum.auto()
    sticker = enum.auto()
    generate = enum.auto()
    import_xpub = enum.auto()
    backup_seed = enum.auto()
    validate_backup = enum.auto()
    register = enum.auto()
    receive = enum.auto()
    #    reset = enum.auto()
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
        self.status: FloatingButtonBar.TxSendStatus | None = None
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

    def set_status(self, status: TxSendStatus) -> None:
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
        # just in case the user clicked "go back"
        def catch_tx(tx: bdk.Transaction) -> None:
            self.set_status(self.TxSendStatus.finalized)
            logger.info(f"tx {tx.txid()} is assumed to be the send test")

        one_time_signal_connection(self.signals.signal_broadcast_tx, catch_tx)

        self._create_tx()
        self.set_status(self.TxSendStatus.finalized)

    def go_to_next_index(self) -> None:
        self._go_to_next_index()
        self.set_status(self.TxSendStatus.not_filled)

    def go_to_previous_index(self) -> None:
        self._go_to_previous_index()
        self.set_status(self.TxSendStatus.not_filled)

    def fill(self):
        self.setVisible(False)

        self.tutorial_button_prefill = QPushButton()
        self.tutorial_button_prefill.clicked.connect(self.fill_tx)
        self.addButton(self.tutorial_button_prefill, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_create_tx = QPushButton()
        self.button_create_tx.clicked.connect(self.create_tx)
        self.addButton(self.button_create_tx, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_yes_it_is_in_hist = QPushButton()
        self.button_yes_it_is_in_hist.setVisible(False)

        def next_step_and_prefill():
            self.go_to_next_index()
            self.fill_tx()

        self.button_yes_it_is_in_hist.clicked.connect(next_step_and_prefill)
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

        self.tutorial_button_prefill.setText(self.tr("Prefill transaction fields"))
        self.button_create_tx.setText(self.tr("Create Transaction"))
        self.button_create_tx_again.setText(self.tr("Prefill Transaction again"))
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
        qt_wallet: QTWallet | None = None,
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


class BaseTab(QObject, ThreadingManager):
    def __init__(self, refs: TabInfo, threading_parent: ThreadingManager | None = None) -> None:
        self.refs = refs
        self.threading_parent = (
            threading_parent
            if threading_parent
            else (self.refs.qt_wallet if self.refs.qt_wallet else self.refs.qtwalletbase)
        )
        super().__init__(parent=refs.container, threading_parent=self.threading_parent)  # type: ignore

        self.buttonbox, self.buttonbox_buttons = create_button_box(
            self.refs.go_to_next_index,
            self.refs.go_to_previous_index,
            ok_text="",
            cancel_text="",
        )
        self.refs.qtwalletbase.signals.language_switch.connect(self.updateUi)

    @property
    def button_next(self) -> QPushButton:
        return self.buttonbox_buttons[0]

    @property
    def button_previous(self) -> QPushButton:
        return self.buttonbox_buttons[1]

    @abstractmethod
    def create(self) -> TutorialWidget:
        pass

    def updateUi(self) -> None:
        self.button_next.setText(translate("basetab", "Next step"))
        self.button_previous.setText(translate("basetab", "Previous Step"))
        self.refs.floating_button_box.updateUi()

    def num_keystores(self) -> int:
        return self.refs.qtwalletbase.get_mn_tuple()[1]

    def get_never_label_text(self) -> str:
        return html_f(
            html_f(
                translate("tutorial", "Never share the {number} secret words with anyone!").format(
                    number=TEXT_24_WORDS
                ),
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
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        num_coldcards = int(np.ceil(self.num_keystores() / 2))
        num_bitbox = int(np.floor(self.num_keystores() / 2))
        add_centered_icons(
            ["coldcard-only.svg"] * num_coldcards + ["bitbox02.svg"] * num_bitbox,
            widget_layout,
            max_sizes=[(60, 80)] * num_coldcards + [(60, 50)] * num_bitbox,
        )

        if (_layout_item := widget_layout.itemAt(0)) and (_widget := _layout_item.widget()):
            _widget.setMaximumWidth(200)

        right_widget = QWidget()
        right_widget_layout = QVBoxLayout(right_widget)
        right_widget_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        widget_layout.addWidget(right_widget)

        self.label_buy = QLabel(widget)
        self.label_buy.setWordWrap(True)
        right_widget_layout.addWidget(self.label_buy)

        self.button_buy_q = QPushButton()
        self.button_buy_q.setIcon(QIcon(icon_path("coldcard-only.svg")))
        self.button_buy_q.clicked.connect(
            lambda: open_website("https://store.coinkite.com/promo/8BFF877000C34A86F410")
        )
        if HardwareSigners.q in ScreenshotsTutorial.enabled_hardware_signers:
            right_widget_layout.addWidget(self.button_buy_q)
        self.button_buy_q.setIconSize(QSize(32, 32))  # Set the icon size to 64x64 pixels

        self.button_buycoldcard = QPushButton()
        self.button_buycoldcard.setIcon(QIcon(icon_path("coldcard-only.svg")))
        self.button_buycoldcard.clicked.connect(
            lambda: open_website("https://store.coinkite.com/promo/8BFF877000C34A86F410")
        )
        if HardwareSigners.coldcard in ScreenshotsTutorial.enabled_hardware_signers:
            right_widget_layout.addWidget(self.button_buycoldcard)
        self.button_buycoldcard.setIconSize(QSize(32, 32))  # Set the icon size to 64x64 pixels

        self.button_buybitbox = QPushButton()
        self.button_buybitbox.setIcon(QIcon(icon_path("bitbox02.svg")))
        self.button_buybitbox.clicked.connect(
            lambda: open_website("https://shiftcrypto.ch/bitbox02/?ref=MOB4dk7gpm")
        )
        self.button_buybitbox.setIconSize(QSize(45, 32))  # Set the icon size to 64x64 pixels
        if HardwareSigners.bitbox02 in ScreenshotsTutorial.enabled_hardware_signers:
            right_widget_layout.addWidget(self.button_buybitbox)

        self.button_buyjade = QPushButton()
        self.button_buyjade.setIcon(QIcon(icon_path("jade.png")))
        self.button_buyjade.clicked.connect(
            lambda: open_website("https://store.blockstream.com/?code=XEocg5boS77D")
        )
        self.button_buyjade.setIconSize(QSize(45, 32))  # Set the icon size to 64x64 pixels
        if HardwareSigners.jade in ScreenshotsTutorial.enabled_hardware_signers:
            right_widget_layout.addWidget(self.button_buyjade)

        right_widget_layout.addItem(QSpacerItem(1, 40))

        # self.label_turn_on = QLabel(widget)
        # self.label_turn_on.setWordWrap(True)
        # right_widget_layout.addWidget(self.label_turn_on)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        self.label_buy.setText(
            html_f(
                self.tr(
                    """Buy {number} hardware signers.                            
                        <ul>
                            <li>Most secure is to buy from different reputable vendors</li> 
                            <li>Great choices are:</li> 
                        </ul>
                           """
                ).format(number=self.num_keystores()),
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )

        self.button_buybitbox.setText(self.tr("Buy a {name}").format(name="Bitbox02\nBitcoin Only Edition"))
        self.button_buycoldcard.setText(self.tr("Buy a Coldcard Mk4"))
        self.button_buy_q.setText(self.tr("Buy a Coldcard Q"))
        self.button_buyjade.setText(self.tr("Buy a Blockstream Jade\n10% off"))
        # self.label_turn_on.setText(
        #     html_f(
        #         self.tr("Buy {n} hardware signers").format(n=self.num_keystores())
        #         if self.num_keystores() > 1
        #         else self.tr("Buy the hardware signer"),
        #         add_html_and_body=True,
        #         p=True,
        #         size=12,
        #     ),
        # )


class StickerTheHardware(BaseTab):
    @staticmethod
    def modify_svg_text(svg_path, old_text, new_text):
        # Define the namespaces to search for SVG elements
        namespaces = {"svg": "http://www.w3.org/2000/svg"}

        # Load and parse the SVG file
        tree = ET.parse(svg_path)
        root = tree.getroot()

        # Find all text elements in the SVG
        for text in root.findall(".//svg:text", namespaces):
            if text.text == old_text:
                text.text = new_text

        # Save the modified SVG content to the same file or a new file
        tree.write(svg_path)

    def create(self) -> TutorialWidget:
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)

        self.label = QLabel()
        widget_layout.addWidget(self.label)

        paths: List[str] = [icon_path("coldcard-sticker.svg")] * int(np.ceil(self.num_keystores() / 2)) + [
            icon_path("bitbox02-sticker.svg")
        ] * int(np.floor(self.num_keystores() / 2))
        svg_widgets = []
        for i in range(self.num_keystores()):
            svg_widget = AspectRatioSvgWidget(paths[i], max_width=400, max_height=200, parent=widget)
            svg_widget.modify_svg_text(
                old_text="Label", new_text=self.refs.qtwalletbase.get_editable_protowallet().sticker_name(i)
            )
            svg_widgets.append(svg_widget)

        widget1 = QWidget(parent=widget)
        widget_layout.addWidget(widget1)
        inner_layout = center_in_widget(
            svg_widgets, widget1, direction="h", alignment=Qt.AlignmentFlag.AlignCenter
        )
        inner_layout.setContentsMargins(1, 0, 1, 0)  # left, top, right, bottom

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def device_name(self, i) -> str:
        protowallet = self.refs.qtwalletbase.get_editable_protowallet()
        threshold, n = protowallet.get_mn_tuple()
        return ProtoWallet.signer_names(threshold=threshold, i=i)

    def updateUi(self) -> None:
        super().updateUi()
        self.label.setText(
            html_f(
                self.tr("Put the following stickers on your hardware:")
                + "<ul>"
                + "".join(
                    [
                        f"""<li>{self.tr('"{sticker}" on {device_name}').format(
                            sticker= self.refs.qtwalletbase.get_editable_protowallet().sticker_name(i ) ,
                            device_name=html_f(  self.device_name(i), bf=True))}</li>"""
                        for i in range(self.num_keystores())
                    ]
                )
                + "</ul>",
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )


class GenerateSeed(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.screenshot = ScreenshotsGenerateSeed()
        widget_layout.addWidget(self.screenshot)

        self.hardware_signer_interactions: Dict[str, HardwareSignerInteractionWidget] = {}
        usb_device_names = [
            enabled_hardware_signer.name
            for enabled_hardware_signer in self.screenshot.enabled_hardware_signers
            if enabled_hardware_signer.usb_preferred
        ]
        for usb_device_name in usb_device_names:
            if usb_device_name in self.screenshot.tabs:

                hardware_signer_interaction = HardwareSignerInteractionWidget()
                self.hardware_signer_interactions[usb_device_name] = hardware_signer_interaction
                button_hwi = hardware_signer_interaction.add_hwi_button()
                button_hwi.clicked.connect(self.on_hwi_click)

                tab = self.screenshot.tabs[usb_device_name]
                tab.layout().addWidget(hardware_signer_interaction)  # type: ignore

        self.never_label = QLabel()
        self.never_label.setWordWrap(True)
        self.never_label.setMinimumWidth(300)
        widget_layout.addWidget(self.never_label)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        self.screenshot.updateUi()
        self.never_label.setText(self.get_never_label_text())

        for hardware_signer_interaction in self.hardware_signer_interactions.values():
            hardware_signer_interaction.updateUi()

    def on_hwi_click(self, initalization_label="") -> None:
        initalization_label, ok = QInputDialog.getText(
            None,
            self.tr("Sticker Label"),
            self.tr("Please enter the name (sticker label) of the hardware signer"),
            text=self.refs.qtwalletbase.get_editable_protowallet().sticker_name(""),
        )
        if not ok:
            Message("Aborted setup.")
            return

        address_type = AddressTypes.p2wpkh  # any address type is OK, since we wont use it
        usb = USBGui(self.refs.qtwalletbase.config.network, initalization_label=initalization_label)
        key_origin = address_type.key_origin(self.refs.qtwalletbase.config.network)
        try:
            result = usb.get_fingerprint_and_xpub(key_origin=key_origin)
        except Exception as e:
            Message(
                str(e)
                + "\n\n"
                + self.tr("Please ensure that there are no other programs accessing the Hardware signer"),
                type=MessageType.Error,
            )
            return
        if not result:
            Message(self.tr("The setup didnt complete. Please repeat."), type=MessageType.Error)
            return

        Message(
            self.tr("Success! Please complete this step with all hardware signers and then click Next."),
            type=MessageType.Info,
        )


class ValidateBackup(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.screenshot = ScreenshotsViewSeed()
        widget_layout.addWidget(self.screenshot)
        self.never_label = QLabel()
        self.never_label.setWordWrap(True)
        self.never_label.setMinimumWidth(300)
        widget_layout.addWidget(self.never_label)

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
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        self.custom_yes_button.setText(
            self.tr("Yes, I am sure all {number} words are correct").format(number=TEXT_24_WORDS)
        )
        self.custom_cancel_button.setText(self.tr("Previous Step"))
        self.screenshot.updateUi()
        self.never_label.setText(self.get_never_label_text())


class ImportXpubs(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.label_import = QLabel()
        # handle protowallet and qt_wallet differently:
        self.button_previous_signer = QPushButton("")
        self.button_next_signer = QPushButton("")
        self.button_create_wallet = QPushButton("")
        if self.refs.qt_wallet:
            # show the full walet descriptor tab below
            self.keystore_uis = None

        else:
            # integrater the KeyStoreUIs into the tutorials, hide wallet_tabs

            # this is used in TutorialStep.import_xpub
            self.keystore_uis = KeyStoreUIs(
                get_editable_protowallet=self.refs.qtwalletbase.get_editable_protowallet,
                get_address_type=lambda: self.refs.qtwalletbase.get_editable_protowallet().address_type,
                signals_min=self.refs.qtwalletbase.signals,
            )
            self.set_current_signer(0)
            self.keystore_uis.setMovable(False)
            widget_layout.addWidget(self.keystore_uis)

            def create_wallet() -> None:
                if not self.keystore_uis:
                    return

                if not self.ask_if_can_proceed():
                    return

                try:
                    self.keystore_uis.set_protowallet_from_keystore_ui()
                    self.refs.qtwalletbase.get_editable_protowallet().tutorial_index = (
                        self.refs.container.current_index() + 1
                    )
                    self.refs.signal_create_wallet.emit()
                except Exception as e:
                    caught_exception_message(e)

            # hide the next button
            self.button_next.setHidden(True)
            # and add the prev signer button
            self.buttonbox_buttons.append(self.button_previous_signer)
            self.buttonbox.addButton(self.button_previous_signer, QDialogButtonBox.ButtonRole.RejectRole)
            self.button_previous_signer.clicked.connect(self.previous_signer)
            # and add the next signer button
            self.buttonbox_buttons.append(self.button_next_signer)
            self.buttonbox.addButton(self.button_next_signer, QDialogButtonBox.ButtonRole.AcceptRole)
            self.button_next_signer.clicked.connect(self.next_signer)
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
                VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=bool(self.refs.qt_wallet))
            )

        tutorial_widget.set_callback(callback)
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=bool(self.refs.qt_wallet))
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def set_current_signer(self, value: int):
        if not self.keystore_uis:
            return
        self.keystore_uis.setCurrentIndex(value)
        for i in range(self.keystore_uis.count()):
            self.keystore_uis.setTabEnabled(i, value == i)
        self.keystore_uis.setMovable(value >= self.keystore_uis.count() - 1)
        self.updateUi()

    def ask_if_can_proceed(self) -> bool:
        if not self.keystore_uis:
            return False

        messages = self.keystore_uis.get_warning_and_error_messages(
            keystore_uis=list(self.keystore_uis.getAllTabData().values())[
                : self.keystore_uis.currentIndex() + 1
            ],
        )

        # error_messages are blocking and MUST be fixed before one can proceed
        error_messages = [message for message in messages if message.type == MessageType.Error]
        if error_messages:
            error_messages[0].show()
            return False

        # show all warning messages. but do not block
        warning_messages = [message for message in messages if message.type == MessageType.Warning]
        if warning_messages:
            for warning_message in warning_messages:
                if not warning_message.ask(
                    yes_button=QMessageBox.StandardButton.Ignore, no_button=QMessageBox.StandardButton.Cancel
                ):
                    return False
        return True

    def next_signer(self):
        if not self.keystore_uis:
            return

        if not self.ask_if_can_proceed():
            return

        if self.keystore_uis.currentIndex() + 1 < self.keystore_uis.count():
            self.set_current_signer(self.keystore_uis.currentIndex() + 1)

    def previous_signer(self):
        if not self.keystore_uis:
            return
        if self.keystore_uis.currentIndex() - 1 >= 0:
            self.set_current_signer(self.keystore_uis.currentIndex() - 1)

    def updateUi(self) -> None:
        super().updateUi()
        self.label_import.setText(self.tr("2. Import wallet information into Bitcoin Safe"))
        if self.refs.qt_wallet:
            self.button_create_wallet.setText(self.tr("Skip step"))
        else:
            self.button_create_wallet.setText(self.tr("Next step"))
        self.button_next_signer.setText(self.tr("Next signer"))
        self.button_previous_signer.setText(self.tr("Previous signer"))
        self.button_previous.setText(self.tr("Previous Step"))

        if self.keystore_uis:
            self.button_create_wallet.setVisible(
                self.keystore_uis.currentIndex() == self.keystore_uis.count() - 1
            )
            self.button_next_signer.setVisible(
                self.keystore_uis.currentIndex() != self.keystore_uis.count() - 1
            )
            self.button_previous_signer.setVisible(self.keystore_uis.currentIndex() > 0)

            # previous button
            self.button_previous.setVisible(self.keystore_uis.currentIndex() == 0)


class BackupSeed(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["descriptor-backup.svg"] * self.num_keystores(),
            widget_layout,
            max_sizes=[(100, 200)] * self.num_keystores(),
        )

        self.label_print_instructions = QLabel(widget)
        self.label_print_instructions.setWordWrap(True)

        widget_layout.addWidget(self.label_print_instructions)

        def do_pdf() -> None:
            if not self.refs.qt_wallet:
                Message(self.tr("Please complete the previous steps."))
                return
            make_and_open_pdf(self.refs.qt_wallet.wallet, lang_code=self.refs.qtwalletbase.get_lang_code())

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
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

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
        <li>{self.tr('Glue the {number} word seed onto the matching printed pdf.').format(number=TEXT_24_WORDS) if self.num_keystores()>1 else self.tr('Glue the {number} word seed onto the printed pdf.').format(number=TEXT_24_WORDS) }</li>""",
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )


class ReceiveTest(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(10, 0, 0, 0)  # Left, Top, Right, Bottom margins
        widget_layout.setSpacing(20)
        self.quick_receive: Optional[BitcoinQuickReceive] = None

        if self.refs.qt_wallet:
            self.quick_receive = BitcoinQuickReceive(
                wallet_signals=self.refs.qt_wallet.wallet_signals,
                wallet=self.refs.qt_wallet.wallet,
            )
            self.quick_receive.setMaximumWidth(300)
            widget_layout.addWidget(self.quick_receive)
        else:
            add_centered_icons(["receive.svg"], widget_layout, max_sizes=[(50, 80)])
            if (_layout_item := widget_layout.itemAt(0)) and (_widget := _layout_item.widget()):
                _widget.setMaximumWidth(150)

        right_widget = QWidget()
        right_widget.setContentsMargins(0, 0, 0, 0)
        right_widget_layout = QVBoxLayout(right_widget)
        widget_layout.addWidget(right_widget)

        self.label_receive_description = QLabel(widget)
        self.label_receive_description.setWordWrap(True)

        right_widget_layout.addWidget(self.label_receive_description)

        right_widget_layout.insertStretch(0, 1)  # Stretch before widgets
        right_widget_layout.addStretch(1)  # Stretch after widgets

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
            utxos = self.refs.qt_wallet.wallet.get_all_utxos(include_not_mine=False)
            self.check_button.setHidden(bool(utxos))
            self.next_button.setHidden(not bool(utxos))
            if utxos:
                Message(
                    self.tr("Balance = {amount}").format(
                        amount=Satoshis(
                            utxos[0].txout.value, self.refs.qt_wallet.wallet.network
                        ).str_with_unit()
                    )
                )

        def start_sync() -> None:
            if not self.refs.qt_wallet:
                Message(self.tr("No wallet setup yet"), type=MessageType.Error)
                return

            self.check_button.set_enable_signal(self.refs.qtwalletbase.signal_after_sync)
            one_time_signal_connection(self.refs.qtwalletbase.signal_after_sync, on_sync_done)
            self.refs.qt_wallet.sync()

        self.check_button.clicked.connect(start_sync)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        if self.quick_receive:
            self.quick_receive.update_content(UpdateFilter(refresh_all=True))
        return tutorial_widget

    def updateUi(self) -> None:
        super().updateUi()
        test_amount = (
            Satoshis(self.refs.max_test_fund, self.refs.qt_wallet.wallet.network).str_with_unit()
            if self.refs.qt_wallet
            else ""
        )
        self.label_receive_description.setText(
            html_f(
                self.tr(
                    """Receive a <b>small</b> amount (less than {test_amount}) to 1 address of this wallet.
                    <br><br>
                    <b>Why?</b> <br>
                    To know if you control the funds, you have to test spending from the wallet. 
                    <br>
                    So before you send a substantial amount of Bitcoin into the wallet, it is <b>crucial</b> to spend from the wallet and test all signers.     
                    <br>
                    <br>
                    <b>Do NOT send in large funds into the wallet before you didn't complete all send tests!</b>   
                    """
                ).format(test_amount=test_amount),
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )
        self.next_button.setText(self.tr("Next step"))
        self.check_button.setText(self.tr("Check if received"))
        self.cancel_button.setText(self.tr("Previous Step"))


# class SingleEnabledTab(BaseTab):
#     def create(self) -> TutorialWidget:


#         widget = QWidget()
#         widget_layout = QVBoxLayout(widget)
#         widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

#         self.hardware_signer_tabs = DataTabWidget(data_type=HardwareSignerInteractionWidget)
#         widget_layout.addWidget(self.hardware_signer_tabs)
#         for label in self.refs.qtwalletbase.get_keystore_labels():
#             hardware_signer_interaction = HardwareSignerInteractionWidget()
#             self.hardware_signer_tabs.addTab(
#                 hardware_signer_interaction,
#                 icon=icon_for_label(label),
#                 description=label,
#                 data=hardware_signer_interaction,
#             )

#         widget_layout.addWidget(self.hardware_signer_tabs)

#         # hide the next button
#         self.button_next.setHidden(True)
#         # and add the prev signer button
#         self.buttonbox_buttons.append(self.button_previous_signer)
#         self.buttonbox.addButton(self.button_previous_signer, QDialogButtonBox.ButtonRole.RejectRole)
#         self.button_previous_signer.clicked.connect(self.previous_signer)
#         # and add the next signer button
#         self.buttonbox_buttons.append(self.button_next_signer)
#         self.buttonbox.addButton(self.button_next_signer, QDialogButtonBox.ButtonRole.AcceptRole)
#         self.button_next_signer.clicked.connect(self.next_signer)

#         tutorial_widget = TutorialWidget(
#             self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
#         )

#         def callback() -> None:
#             self.updateUi()
#             tutorial_widget.synchronize_visiblity(
#                 VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
#             )

#         tutorial_widget.set_callback(callback)
#         tutorial_widget.synchronize_visiblity(
#             VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
#         )
#         tutorial_widget.synchronize_visiblity(
#             VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
#         )

#         self.updateUi()
#         self.set_current_signer(0)
#         return tutorial_widget

#     def set_current_signer(self, value: int):
#         if value>= self.hardware_signer_tabs.count():
#             return
#         self.hardware_signer_tabs.setCurrentIndex(value)
#         for i in range(self.hardware_signer_tabs.count()):
#             self.hardware_signer_tabs.setTabEnabled(i, value == i)
#         self.updateUi()

#     def next_signer(self):
#         if self.hardware_signer_tabs.currentIndex() + 1 < self.hardware_signer_tabs.count():
#             self.set_current_signer(self.hardware_signer_tabs.currentIndex() + 1)

#     def previous_signer(self):
#         if self.hardware_signer_tabs.currentIndex() - 1 >= 0:
#             self.set_current_signer(self.hardware_signer_tabs.currentIndex() - 1)

#     def updateUi(self) -> None:
#         super().updateUi()
#         self.label_import.setText(self.tr("2. Import wallet information into Bitcoin Safe"))
#         if self.refs.qt_wallet:
#             self.custom_yes_button.setText(self.tr("Skip step"))
#         else:
#             self.custom_yes_button.setText(self.tr("Next step"))
#         self.button_next_signer.setText(self.tr("Next signer"))
#         self.button_previous_signer.setText(self.tr("Previous signer"))
#         self.button_previous.setText(self.tr("Previous Step"))

#         self.custom_yes_button.setText(
#             self.tr("Yes, I registered the multisig on the {n} hardware signer").format(
#                 n=self.num_keystores()
#             )
#         )
#         for i in range(self.hardware_signer_tabs.count()):
#             hardware_signer_interaction = self.hardware_signer_tabs.tabData(
#                 i
#             )
#             hardware_signer_interaction.updateUi()

#         self.custom_yes_button.setVisible(
#             self.hardware_signer_tabs.currentIndex() == self.hardware_signer_tabs.count() - 1
#         )
#         self.button_next_signer.setVisible(
#             self.hardware_signer_tabs.currentIndex() != self.hardware_signer_tabs.count() - 1
#         )
#         self.button_previous_signer.setVisible(self.hardware_signer_tabs.currentIndex() > 0)

#         # previous button
#         self.button_previous.setVisible(self.hardware_signer_tabs.currentIndex() == 0)


class RegisterMultisig(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.label_import = QLabel()
        # handle protowallet and qt_wallet differently:
        self.button_previous_signer = QPushButton("")
        self.button_next_signer = QPushButton("")
        self.custom_yes_button = QPushButton("")
        self.custom_yes_button.clicked.connect(self.refs.go_to_next_index)
        self.buttonbox.addButton(self.custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)

        # export widgets
        self.export_qr_widget = None
        if self.refs.qt_wallet:
            self.export_qr_widget = ExportDataSimple(
                data=Data.from_str(
                    self.refs.qt_wallet.wallet.multipath_descriptor.as_string(),
                    network=self.refs.qt_wallet.wallet.network,
                ),
                signals_min=self.refs.qt_wallet.signals,
                enable_clipboard=False,
                enable_usb=False,
                enable_file=False,
                enable_qr=True,
                network=self.refs.qtwalletbase.config.network,
                threading_parent=self.threading_parent,
            )

        # ui hardware_signer_interactions
        self.hardware_signer_tabs = DataTabWidget(HardwareSignerInteractionWidget)
        widget_layout.addWidget(self.hardware_signer_tabs)
        for label in self.refs.qtwalletbase.get_keystore_labels():

            hardware_signer_interaction = HardwareSignerInteractionWidget()
            self.hardware_signer_tabs.addTab(
                hardware_signer_interaction,
                icon=icon_for_label(label),
                description=label,
                data=hardware_signer_interaction,
            )

            ## help
            screenshots = ScreenshotsRegisterMultisig()
            hardware_signer_interaction.add_help_button(screenshots)
            button_export_file = hardware_signer_interaction.add_export_file_button()
            export_qr_button, export_qr_menu = hardware_signer_interaction.add_export_qr_button()
            button_hwi = hardware_signer_interaction.add_hwi_button()

            if self.export_qr_widget and self.refs.qt_wallet:
                ## file
                def export():
                    if self.export_qr_widget and self.refs.qt_wallet:
                        self.export_qr_widget.export_to_file(
                            default_filename=f"{self.refs.qt_wallet.wallet.id}.txt"
                        )

                button_export_file.clicked.connect(export)

                ## qr

                def factory_show_export_widget(qr_type: QrType):
                    def show_export_widget(qr_type: QrType = qr_type):
                        if not self.export_qr_widget:
                            return
                        self.export_qr_widget.setCurrentQrType(value=qr_type)
                        self.export_qr_widget.setMinimumSize(450, 300)
                        self.export_qr_widget.show()

                    return show_export_widget

                for qr_type in self.export_qr_widget.qr_types:
                    text = f"{qr_type.display_name} - {', '.join([hardware_signer.display_name for name, hardware_signer in  HardwareSigners.__dict__.items()  if not name.startswith('__')  and hardware_signer.qr_type==qr_type])}"
                    export_qr_menu.add_action(text, factory_show_export_widget(qr_type))

                ## hwi

                addresses = self.refs.qt_wallet.wallet.get_addresses()
                index = 0
                address = addresses[index] if len(addresses) > index else ""
                usb_widget = USBRegisterMultisigWidget(
                    network=self.refs.qt_wallet.wallet.network,
                    signals=self.refs.qt_wallet.signals,
                )
                usb_widget.set_descriptor(
                    keystores=self.refs.qt_wallet.wallet.keystores,
                    descriptor=self.refs.qt_wallet.wallet.multipath_descriptor,
                    expected_address=address,
                    kind=bdk.KeychainKind.EXTERNAL,
                    address_index=index,
                )
                button_hwi.clicked.connect(lambda: usb_widget.show())

        widget_layout.addWidget(self.hardware_signer_tabs)

        # hide the next button
        self.button_next.setHidden(True)
        # and add the prev signer button
        self.buttonbox_buttons.append(self.button_previous_signer)
        self.buttonbox.addButton(self.button_previous_signer, QDialogButtonBox.ButtonRole.RejectRole)
        self.button_previous_signer.clicked.connect(self.previous_signer)
        # and add the next signer button
        self.buttonbox_buttons.append(self.button_next_signer)
        self.buttonbox.addButton(self.button_next_signer, QDialogButtonBox.ButtonRole.AcceptRole)
        self.button_next_signer.clicked.connect(self.next_signer)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )

        def callback() -> None:
            self.updateUi()
            tutorial_widget.synchronize_visiblity(
                VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
            )

        tutorial_widget.set_callback(callback)
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        self.set_current_signer(0)
        return tutorial_widget

    def set_current_signer(self, value: int) -> None:
        if value >= self.hardware_signer_tabs.count():
            return
        self.hardware_signer_tabs.setCurrentIndex(value)
        for i in range(self.hardware_signer_tabs.count()):
            self.hardware_signer_tabs.setTabEnabled(i, value == i)
        self.updateUi()

    def next_signer(self) -> None:
        if self.hardware_signer_tabs.currentIndex() + 1 < self.hardware_signer_tabs.count():
            self.set_current_signer(self.hardware_signer_tabs.currentIndex() + 1)

    def previous_signer(self) -> None:
        if self.hardware_signer_tabs.currentIndex() - 1 >= 0:
            self.set_current_signer(self.hardware_signer_tabs.currentIndex() - 1)

    def updateUi(self) -> None:
        super().updateUi()
        self.label_import.setText(self.tr("2. Import wallet information into Bitcoin Safe"))
        if self.refs.qt_wallet:
            self.custom_yes_button.setText(self.tr("Skip step"))
        else:
            self.custom_yes_button.setText(self.tr("Next step"))
        self.button_next_signer.setText(self.tr("Next signer"))
        self.button_previous_signer.setText(self.tr("Previous signer"))
        self.button_previous.setText(self.tr("Previous Step"))

        self.custom_yes_button.setText(
            self.tr("Yes, I registered the multisig on the {n} hardware signer").format(
                n=self.num_keystores()
            )
        )
        for tab_data in self.hardware_signer_tabs.getAllTabData().values():
            tab_data.updateUi()

        self.custom_yes_button.setVisible(
            self.hardware_signer_tabs.currentIndex() == self.hardware_signer_tabs.count() - 1
        )
        self.button_next_signer.setVisible(
            self.hardware_signer_tabs.currentIndex() != self.hardware_signer_tabs.count() - 1
        )
        self.button_previous_signer.setVisible(self.hardware_signer_tabs.currentIndex() > 0)

        # previous button
        self.button_previous.setVisible(self.hardware_signer_tabs.currentIndex() == 0)


class DistributeSeeds(BaseTab):
    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        if self.num_keystores() > 1:
            add_centered_icons(
                ["distribute-multisigsig-export.svgz"],
                widget_layout,
                max_sizes=[(400, 350)] * self.num_keystores(),
            )
        else:
            add_centered_icons(
                ["distribute-singlesig-export.svgz"],
                widget_layout,
                max_sizes=[(400, 350)] * self.num_keystores(),
            )

        if (_layout_item := widget_layout.itemAt(0)) and (_widget := _layout_item.widget()):
            _widget.setMaximumWidth(400)

        right_widget = QWidget()
        right_widget_layout = QVBoxLayout(right_widget)
        right_widget_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        widget_layout.addWidget(right_widget)

        self.label_main = QLabel(widget)
        self.label_main.setWordWrap(True)

        right_widget_layout.addWidget(self.label_main)

        right_widget_layout.addItem(QSpacerItem(1, 40))
        self.button_next.setIcon(QIcon(icon_path("checkmark.svg")))

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

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
        self.button_next.setText(self.tr("Finish"))


class SendTest(BaseTab):
    def __init__(self, test_label, test_number, tx_text, refs: TabInfo) -> None:
        super().__init__(refs)
        self.test_label = test_label
        self.test_number = test_number
        self.tx_text = tx_text

    def create(self) -> TutorialWidget:

        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(["send.svg"], widget_layout, max_sizes=[(50, 80)])
        if (layout_item := widget_layout.itemAt(0)) and (sub_widget := layout_item.widget()):
            sub_widget.setMaximumWidth(150)

        inner_widget = QWidget()
        inner_widget_layout = QVBoxLayout(inner_widget)
        self.label = QLabel()
        if self.num_keystores() == 1:

            inner_widget_layout.addWidget(self.label)

        else:

            self.label = QLabel(html_f(self.tx_text, add_html_and_body=True, p=True, size=12))
            inner_widget_layout.addWidget(self.label)

        widget_layout.addWidget(inner_widget)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.setMinimumHeight(30)

        def callback() -> None:
            if not self.refs.qt_wallet:
                return
            if self.refs.qt_wallet.sync_status in [SyncStatus.unknown, SyncStatus.unsynced]:
                logger.debug(
                    f"Skipping tutorial callback  for send test, because {self.refs.qt_wallet.wallet.id} sync_status={ self.refs.qt_wallet.sync_status}"
                )
                return
            logger.debug(f"tutorial callback")

            # compare how many tx were already done , to the current test_number
            def should_offer_skip() -> bool:
                if not spend_txos:
                    return False
                return len(spend_txos) >= self.test_number + 1

            # offer to skip this step if it was spend from this wallet
            txos = self.refs.qt_wallet.wallet.get_all_txos_dict(include_not_mine=False).values()
            spend_txos = [txo for txo in txos if txo.is_spent_by_txid]

            if should_offer_skip():
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
            VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=bool(self.refs.qt_wallet))
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(
                self.refs.floating_button_box, on_focus_set_visible=True, on_unfocus_set_visible=False
            )
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(tutorial_widget.button_box, on_focus_set_visible=False)
        )
        if self.refs.qt_wallet:
            tutorial_widget.synchronize_visiblity(
                VisibilityOption(self.refs.qt_wallet.uitx_creator.button_box, on_focus_set_visible=False)
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


class WalletSteps(WalletStepsBase):
    signal_create_wallet = pyqtSignal()

    def __init__(
        self,
        qtwalletbase: QtWalletBase,
        wallet_tabs: QTabWidget,
        max_test_fund=1_000_000,
        qt_wallet: QTWallet | None = None,
    ) -> None:
        super().__init__(
            step_labels=[""] * 3,
            signals_min=qtwalletbase.signals,
            threading_parent=qt_wallet if qt_wallet else qtwalletbase,
        )  # initialize with 3 steps (doesnt matter)
        self.qtwalletbase = qtwalletbase
        self.qt_wallet = qt_wallet
        m, n = self.qtwalletbase.get_mn_tuple()

        # floating_button_box
        self.floating_button_box = FloatingButtonBar(
            self.fill_tx,
            (
                self.qt_wallet.uitx_creator.create_tx
                if self.qt_wallet
                else lambda: Message(self.tr("You must have an initilized wallet first"))
            ),
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
            TutorialStep.sticker: StickerTheHardware(refs=refs),
            TutorialStep.generate: GenerateSeed(refs=refs),
            TutorialStep.import_xpub: ImportXpubs(refs=refs),
            TutorialStep.backup_seed: BackupSeed(refs=refs),
        }
        if n > 1:
            self.tab_generators[TutorialStep.register] = RegisterMultisig(refs=refs)

        self.tab_generators[TutorialStep.receive] = ReceiveTest(refs=refs)

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

        def save(widget):
            if self.qt_wallet:
                self.qt_wallet.save()

        self.signal_set_current_widget.connect(save)

        self.updateUi()
        self.set_visibilities()

        self.qtwalletbase.signals.language_switch.connect(self.updateUi)
        if self.qt_wallet:
            self.qtwalletbase.signals.wallet_signals[self.qt_wallet.wallet.id].updated.connect(
                self.on_utxo_update
            )

    def get_latest_send_test_in_tx_history(
        self, steps: List[TutorialStep], wallet: Wallet
    ) -> Optional[TutorialStep]:
        latest_step = None
        for test_number, tutoral_step in enumerate(steps):
            tx_text = self.tx_text(test_number)
            for txo in wallet.get_all_txos_dict().values():
                if wallet.labels.get_label(txo.address) == tx_text:
                    latest_step = tutoral_step
        return latest_step

    def on_utxo_update(self, update_filter: UpdateFilter) -> None:
        if not self.qt_wallet or not self.should_be_visible:
            return

        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.outpoints:
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")

        steps = self.get_send_tests_steps()
        latest_step = self.get_latest_send_test_in_tx_history(steps, self.qt_wallet.wallet)
        if latest_step is None:
            return
        latest_test_number = steps.index(latest_step)

        steps = self.get_send_tests_steps()
        tx_text = self.tx_text(latest_test_number)
        if latest_test_number >= len(steps) - 1:
            Message(self.tr("All Send tests done successfully."), type=MessageType.Info)
        else:
            Message(
                self.tr(
                    "The test transaction \n'{tx_text}'\n was done successfully. Please proceed to do the send test: \n'{next_text}'"
                ).format(tx_text=tx_text, next_text=self.tx_text(latest_test_number + 1)),
                type=MessageType.Info,
            )

        # only increase the index, if the index is not ahead already
        if self.current_index() < self.index_of_step(latest_step) + 1:
            self.set_current_index(self.index_of_step(latest_step) + 1)

    def current_step(self) -> TutorialStep:
        return self.get_step_of_index(self.current_index())

    def index_of_step(self, step: TutorialStep) -> int:
        return [step for step in TutorialStep if step in self.tab_generators].index(step)

    def get_step_of_index(self, index: int) -> TutorialStep:
        members = list(self.tab_generators.keys())
        if index < 0:
            index = 0
        if index >= len(members):
            index = len(members) - 1
        return members[index]

    def get_wallet_tutorial_index(self) -> Optional[int]:
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

    @property
    def should_be_visible(self) -> bool:
        return self.get_wallet_tutorial_index() != None

    def set_visibilities(self) -> None:
        self.setVisible(self.should_be_visible)

        if self.should_be_visible:
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

        start_index = list(TutorialStep).index(TutorialStep.send)

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

        utxos = [txo for txo in self.qt_wallet.wallet.get_all_utxos()]
        if not utxos:
            Message(self.tr("The wallet is not funded. Please fund the wallet."))
            return
        # select only the last utxo
        utxos = [utxos[0]]
        # get the category
        funded_category = self.qt_wallet.wallet.labels.get_category(utxos[0].address)

        txinfos = TxUiInfos()
        # if I wanted to use all utxos of this category
        # ToolsTxUiInfo.fill_utxo_dict_from_categories(txinfos, [funded_category], [self.qt_wallet.wallet])
        # but it is probbaly better just to use 1 of the utxos
        # since the recipient is set to receive max
        txinfos.utxo_dict = {utxo.outpoint: utxo for utxo in utxos}
        txinfos.global_xpubs = self.qt_wallet.uitx_creator.get_global_xpub_dict(
            wallets=[self.qt_wallet.wallet]
        )
        txinfos.main_wallet_id = self.qt_wallet.wallet.id
        # inputs

        recipient_address = self.qt_wallet.wallet.get_unused_category_address(
            category=funded_category
        ).address.as_string()
        self.qt_wallet.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=set([recipient_address]), reason=UpdateFilterReason.GetUnusedCategoryAddress
            )
        )

        # outputs
        txinfos.recipients.append(
            Recipient(
                recipient_address,
                0,
                checked_max_amount=True,
                label=label,
            )
        )

        # visual elements
        txinfos.hide_UTXO_selection = True
        txinfos.recipient_read_only = True

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
            if tab_widget:
                tab_widget.setHidden(tab_widget != self.qt_wallet.send_tab)
        self.open_tx(test_number)

    def updateUi(self) -> None:
        # step_bar
        labels: Dict[TutorialStep, str] = {
            TutorialStep.buy: self.tr("Buy hardware signers"),
            TutorialStep.sticker: self.tr("Label the hardware signers"),
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

        self.set_labels([labels[key] for key in self.tab_generators if key in labels])

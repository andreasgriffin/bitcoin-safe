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

import enum
import logging
import xml.etree.ElementTree as ET
from abc import abstractmethod
from collections.abc import Callable
from functools import partial
from math import ceil
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_usb.address_types import AddressTypes
from bitcoin_usb.usb_gui import USBGui
from PyQt6.QtCore import QLocale, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.execute_config import DEFAULT_LANG_CODE
from bitcoin_safe.gui.qt.bitcoin_quick_receive import BitcoinQuickReceive
from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget
from bitcoin_safe.gui.qt.descriptor_ui import KeyStoreUIs
from bitcoin_safe.gui.qt.keystore_ui import (
    HardwareSignerInteractionWidget,
    icon_for_label,
)
from bitcoin_safe.gui.qt.qt_wallet import QTWallet, QtWalletBase, SyncStatus
from bitcoin_safe.gui.qt.register_multisig import RegisterMultisigInteractionWidget
from bitcoin_safe.gui.qt.tutorial_screenshots import (
    ScreenshotsGenerateSeed,
    ScreenshotsViewSeed,
)
from bitcoin_safe.gui.qt.wizard_base import WizardBase
from bitcoin_safe.html_utils import html_f, link
from bitcoin_safe.i18n import translate
from bitcoin_safe.plugin_framework.plugins.chat_sync.client import SyncClient
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason
from bitcoin_safe.wallet import Wallet
from bitcoin_safe.wallet_util import signer_name

from ...pdf_labels import make_and_open_labels_pdf
from ...pdfrecovery import TEXT_24_WORDS, make_and_open_pdf
from ...pythonbdk_types import PythonUtxo, Recipient
from ...signals import Signals
from ...tx import TxUiInfos
from .cbf_progress_bar import CBFProgressBar
from .step_progress_bar import StepProgressContainer, TutorialWidget, VisibilityOption
from .util import (
    AspectRatioSvgWidget,
    Message,
    MessageType,
    add_centered_icons,
    caught_exception_message,
    center_in_widget,
    create_button_box,
    generate_help_button,
    one_time_signal_connection,
    open_website,
    set_no_margins,
    svg_tools,
    svg_widget_hardware_signer,
)

logger = logging.getLogger(__name__)


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
    sync = enum.auto()


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
        """Initialize instance."""
        super().__init__()
        self.status: FloatingButtonBar.TxSendStatus | None = None
        self._fill_tx = fill_tx
        self._create_tx = create_tx
        self._go_to_next_index = go_to_next_index
        self._go_to_previous_index = go_to_previous_index
        self.signals = signals

        self.signals.language_switch.connect(self.updateUi)

    def set_visibilities(self) -> None:
        """Set visibilities."""
        self.tutorial_button_prefill.setVisible(self.status in [self.TxSendStatus.not_filled])
        self.button_create_tx.setVisible(self.status in [self.TxSendStatus.filled])
        self.tutorial_button_prev_step.setVisible(True)
        self.button_yes_it_is_in_hist.setVisible(
            self.status in [self.TxSendStatus.finalized, self.TxSendStatus.sent]
        )
        self.button_prefill_again.setVisible(
            self.status in [self.TxSendStatus.finalized, self.TxSendStatus.sent]
        )

    def set_status(self, status: TxSendStatus) -> None:
        """Set status."""
        if self.status == status:
            return
        self.status = status
        self.set_visibilities()

    def fill_tx(self) -> None:
        """Fill tx."""
        self._fill_tx()
        self.set_status(self.TxSendStatus.filled)

    def _catch_tx(self, tx: bdk.Transaction) -> None:
        """Catch tx."""
        self.set_status(self.TxSendStatus.finalized)
        logger.info(f"tx {str(tx.compute_txid())[:4]=} is assumed to be the send test")

    def create_tx(self) -> None:
        # before do _create_tx, setup a 1 time connection
        # so I can catch the tx and ensure that TxSendStatus == finalized
        # just in case the user clicked "go back"
        """Create tx."""
        one_time_signal_connection(self.signals.signal_broadcast_tx, self._catch_tx)

        self._create_tx()
        self.set_status(self.TxSendStatus.finalized)

    def go_to_next_index(self) -> None:
        """Go to next index."""
        self._go_to_next_index()
        self.set_status(self.TxSendStatus.not_filled)

    def go_to_previous_index(self) -> None:
        """Go to previous index."""
        self._go_to_previous_index()
        self.set_status(self.TxSendStatus.not_filled)

    def _next_step_and_prefill(self):
        """Next step and prefill."""
        self.go_to_next_index()
        self.fill_tx()

    def fill(self) -> None:
        """Fill."""
        self.setVisible(False)

        self.tutorial_button_prefill = QPushButton()
        self.tutorial_button_prefill.clicked.connect(self.fill_tx)
        self.addButton(self.tutorial_button_prefill, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_create_tx = QPushButton()
        self.button_create_tx.clicked.connect(self.create_tx)
        self.addButton(self.button_create_tx, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_yes_it_is_in_hist = QPushButton()
        self.button_yes_it_is_in_hist.setVisible(False)

        self.button_yes_it_is_in_hist.clicked.connect(self._next_step_and_prefill)
        self.addButton(self.button_yes_it_is_in_hist, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_prefill_again = QPushButton()
        self.button_prefill_again.setVisible(False)
        self.button_prefill_again.clicked.connect(self.fill_tx)
        self.addButton(self.button_prefill_again, QDialogButtonBox.ButtonRole.AcceptRole)

        self.tutorial_button_prev_step = QPushButton()
        self.tutorial_button_prev_step.clicked.connect(self.go_to_previous_index)
        self.addButton(self.tutorial_button_prev_step, QDialogButtonBox.ButtonRole.RejectRole)

        self.set_status(self.TxSendStatus.not_filled)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.tutorial_button_prefill.setText(self.tr("Prefill transaction fields"))
        self.button_create_tx.setText(self.tr("Create Transaction"))
        self.button_prefill_again.setText(self.tr("Retry"))
        self.button_yes_it_is_in_hist.setText(self.tr("Yes, I see the transaction in the history"))
        self.tutorial_button_prev_step.setText(self.tr("Previous Step"))


class WizardTabInfo:
    def __init__(
        self,
        container: StepProgressContainer,
        qtwalletbase: QtWalletBase,
        go_to_next_index: Callable,
        go_to_previous_index: Callable,
        floating_button_box: FloatingButtonBar,
        signal_create_wallet: SignalProtocol[str],
        max_test_fund: int,
        qt_wallet: QTWallet | None = None,
    ) -> None:
        """Initialize instance."""
        self.container = container
        self.wallet_tabs = qtwalletbase.tabs
        self.qtwalletbase = qtwalletbase
        self.go_to_next_index = go_to_next_index
        self.go_to_previous_index = go_to_previous_index
        self.floating_button_box = floating_button_box
        self.signal_create_wallet = signal_create_wallet
        self.qt_wallet = qt_wallet
        self.max_test_fund = max_test_fund


class BaseTab(QObject):
    def __init__(self, refs: WizardTabInfo, loop_in_thread: LoopInThread) -> None:
        """Initialize instance."""
        self.refs = refs
        super().__init__(parent=refs.container)

        self.previous_step_enabled = True

        self.loop_in_thread = loop_in_thread
        self.signal_tracker = SignalTracker()
        self.buttonbox, self.buttonbox_buttons = create_button_box(
            self.refs.go_to_next_index,
            self.refs.go_to_previous_index,
            ok_text="",
            cancel_text="",
        )
        self.signal_tracker.connect(
            cast(SignalProtocol[[]], self.refs.qtwalletbase.signals.language_switch), self.updateUi
        )

    @property
    def button_next(self) -> QPushButton:
        """Button next."""
        return self.buttonbox_buttons[0]

    @property
    def button_previous(self) -> QPushButton:
        """Button previous."""
        return self.buttonbox_buttons[1]

    @abstractmethod
    def create(self) -> TutorialWidget:
        """Create."""
        pass

    def updateUi(self) -> None:
        """UpdateUi."""
        self.button_next.setText(translate("basetab", "Next step"))
        self.button_previous.setText(translate("basetab", "Previous Step"))
        self.button_previous.setEnabled(self.previous_step_enabled)
        self.refs.floating_button_box.updateUi()

    def num_keystores(self) -> int:
        """Num keystores."""
        return self.refs.qtwalletbase.get_mn_tuple()[1]

    def get_never_label_text(self) -> str:
        """Get never label text."""
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

    def set_visibilities(self, should_be_visible: bool):
        """Set visibilities."""
        pass

    def close(self):
        """Close."""
        self.signal_tracker.disconnect_all()
        self.setParent(None)
        del self.refs


class BuyHardware(BaseTab):
    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        svg_widgets = [
            svg_widget_hardware_signer(index=i, parent=widget, max_height=100, max_width=100)
            for i in range(self.num_keystores())
        ]
        for svg_widget in svg_widgets:
            widget_layout.addWidget(svg_widget)

        right_widget = QWidget()
        right_widget_layout = QVBoxLayout(right_widget)
        right_widget_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        widget_layout.addWidget(right_widget)

        self.label_buy = QLabel(widget)
        self.label_buy.setOpenExternalLinks(True)  # This makes the link clickable
        self.label_buy.setWordWrap(True)
        right_widget_layout.addWidget(self.label_buy)

        # self.button_buy_q = QPushButton()
        # self.button_buy_q.setIcon(svg_tools_generated_hardware_signer.get_QIcon("coldcard.svg"))
        # self.button_buy_q.clicked.connect(self.website_open_coinkite)
        # # if HardwareSigners.q in ScreenshotsTutorial.enabled_hardware_signers:
        # #     right_widget_layout.addWidget(self.button_buy_q)
        # self.button_buy_q.setIconSize(QSize(32, 32))  # Set the icon size to 64x64 pixels

        # self.button_buycoldcard = QPushButton()
        # self.button_buycoldcard.setIcon(svg_tools_generated_hardware_signer.get_QIcon("coldcard.svg"))
        # self.button_buycoldcard.clicked.connect(self.website_open_coinkite)
        # # if HardwareSigners.coldcard in ScreenshotsTutorial.enabled_hardware_signers:
        # #     right_widget_layout.addWidget(self.button_buycoldcard)
        # self.button_buycoldcard.setIconSize(QSize(32, 32))  # Set the icon size to 64x64 pixels

        # self.button_buybitbox = QPushButton()
        # self.button_buybitbox.setIcon(svg_tools_generated_hardware_signer.get_QIcon("bitbox02.svg"))
        # self.button_buybitbox.clicked.connect(self.website_open_bitbox)
        # self.button_buybitbox.setIconSize(QSize(45, 32))  # Set the icon size to 64x64 pixels
        # # if HardwareSigners.bitbox02 in ScreenshotsTutorial.enabled_hardware_signers:
        # #     right_widget_layout.addWidget(self.button_buybitbox)

        # self.button_buyjade = QPushButton()
        # self.button_buyjade.setIcon(svg_tools_generated_hardware_signer.get_QIcon("jade.svg"))
        # self.button_buyjade.clicked.connect(self.website_open_jade)
        # self.button_buyjade.setIconSize(QSize(45, 32))  # Set the icon size to 64x64 pixels
        # # if HardwareSigners.jade in ScreenshotsTutorial.enabled_hardware_signers:
        # #     right_widget_layout.addWidget(self.button_buyjade)

        right_widget_layout.addItem(QSpacerItem(1, 40))

        # self.label_turn_on = QLabel(widget)
        # self.label_turn_on.setWordWrap(True)
        # right_widget_layout.addWidget(self.label_turn_on)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )

        self.updateUi()
        return tutorial_widget

    def website_open_coinkite(self):
        """Website open coinkite."""
        open_website("https://store.coinkite.com/promo/8BFF877000C34A86F410")

    def website_open_bitbox(self):
        """Website open bitbox."""
        open_website("https://shop.bitbox.swiss/?ref=MOB4dk7gpm")

    def website_open_jade(self):
        """Website open jade."""
        open_website("https://store.blockstream.com/?code=XEocg5boS77D")

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.label_buy.setText(
            html_f(
                self.tr(
                    """Buy {number} hardware signers                         
    <ul>
        {different_hint} 
        <li>Bitcoin Safe supports all major hardware signers: <a href="{url}">See full list</a></li>
    </ul>
        """
                ).format(
                    number=self.num_keystores(),
                    different_hint=(
                        "<li>Most secure is to buy from different reputable vendors</li>"
                        if self.num_keystores() > 1
                        else ""
                    ),
                    url="https://bitcoin-safe.org/en/knowledge/supported-hardware-signers",
                ),
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )

        # self.button_buybitbox.setText(self.tr("Buy a {name}").format(name="Bitbox02\nBitcoin Only Edition"))
        # self.button_buycoldcard.setText(self.tr("Buy a Coldcard Mk4"))
        # self.button_buy_q.setText(self.tr("Buy a Coldcard Q"))
        # self.button_buyjade.setText(self.tr("Buy a Blockstream Jade"))
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
        """Modify svg text."""
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
        """Create."""
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)

        self.label = QLabel()
        widget_layout.addWidget(self.label)

        self.button_print_labels = QPushButton()
        self.button_print_labels.setIcon(svg_tools.get_QIcon("print.svg"))
        self.button_print_labels.clicked.connect(self._print_labels)
        self.buttonbox.addButton(self.button_print_labels, QDialogButtonBox.ButtonRole.ActionRole)

        svg_widgets = [
            svg_widget_hardware_signer(
                index=i,
                parent=widget,
                sticker=True,
                replace_tuples=[("Label", self.refs.qtwalletbase.get_editable_protowallet().sticker_name(i))],
                size_hint_height=200,
                size_hint_width=200,
            )
            for i in range(self.num_keystores())
        ]

        widget1 = QWidget(parent=widget)
        widget_layout.addWidget(widget1)
        inner_layout = center_in_widget(
            svg_widgets, widget1, direction="h", alignment=Qt.AlignmentFlag.AlignCenter
        )
        inner_layout.setContentsMargins(1, 0, 1, 0)  # left, top, right, bottom

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )

        self.updateUi()
        return tutorial_widget

    def device_name(self, i: int) -> str:
        """Device name."""
        protowallet = self.refs.qtwalletbase.get_editable_protowallet()
        threshold, n = protowallet.get_mn_tuple()
        return signer_name(threshold=threshold, i=i)

    def _print_labels(self) -> None:
        """Print labels."""
        protowallet = self.refs.qtwalletbase.get_editable_protowallet()
        label_pairs = [
            (
                protowallet.sticker_name(i),
                self.device_name(i),
            )
            for i in range(self.num_keystores())
        ]

        make_and_open_labels_pdf(
            wallet_id=protowallet.id,
            label_pairs=label_pairs,
            lang_code=QLocale().name() or DEFAULT_LANG_CODE,
        )

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.label.setText(
            html_f(
                self.tr("Put the following stickers on your hardware:")
                + "<ul>"
                + "".join(
                    [
                        f"""<li>{
                            self.tr('"{sticker}" on {device_name}').format(
                                sticker=self.refs.qtwalletbase.get_editable_protowallet().sticker_name(i),
                                device_name=html_f(self.device_name(i), bf=True),
                            )
                        }</li>"""
                        for i in range(self.num_keystores())
                    ]
                )
                + "</ul>",
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )
        self.button_print_labels.setText(self.tr("Print labels"))


class GenerateSeed(BaseTab):
    def create(self) -> TutorialWidget:
        """Create."""
        self.usb_gui = USBGui(self.refs.qtwalletbase.config.network, loop_in_thread=self.loop_in_thread)

        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.screenshot = ScreenshotsGenerateSeed()
        widget_layout.addWidget(self.screenshot)

        self.hardware_signer_interactions: dict[str, HardwareSignerInteractionWidget] = {}
        usb_device_names = [
            enabled_hardware_signer.name
            for enabled_hardware_signer in self.screenshot.enabled_hardware_signers
            if enabled_hardware_signer.usb_preferred
        ]
        for usb_device_name in usb_device_names:
            if usb_device_name in self.screenshot.tabs:
                hardware_signer_interaction = HardwareSignerInteractionWidget()
                self.hardware_signer_interactions[usb_device_name] = hardware_signer_interaction
                button_hwi = hardware_signer_interaction.add_hwi_button(
                    signal_end_hwi_blocker=self.usb_gui.signal_end_hwi_blocker
                )
                button_hwi.clicked.connect(self.on_hwi_click)

                tab = self.screenshot.tabs[usb_device_name]
                tab.layout().addWidget(hardware_signer_interaction)  # type: ignore

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.screenshot.updateUi()

        for hardware_signer_interaction in self.hardware_signer_interactions.values():
            hardware_signer_interaction.updateUi()

    def on_hwi_click(self, initalization_label="") -> None:
        """On hwi click."""
        initalization_label, ok = QInputDialog.getText(
            None,
            self.tr("Sticker Label"),
            self.tr("Please enter the name (sticker label) of the hardware signer"),
            text=self.refs.qtwalletbase.get_editable_protowallet().sticker_name(""),
        )
        if not ok:
            Message("Aborted setup.", parent=self.refs.container)
            return

        self.usb_gui.set_initalization_label(initalization_label)
        address_type = AddressTypes.p2wpkh  # any address type is OK, since we wont use it
        key_origin = address_type.key_origin(self.refs.qtwalletbase.config.network)
        try:
            result = self.usb_gui.get_fingerprint_and_xpub(key_origin=key_origin, slow_hwi_listing=True)
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(
                str(e)
                + "\n\n"
                + self.tr("Please ensure that there are no other programs accessing the Hardware signer"),
                type=MessageType.Error,
                parent=self.refs.container,
            )
            return
        if not result:
            Message(
                self.tr("The setup didnt complete. Please repeat."),
                type=MessageType.Error,
                parent=self.refs.container,
            )
            return

        Message(
            self.tr("Success! Please complete this step with all hardware signers and then click Next."),
            type=MessageType.Info,
            parent=self.refs.container,
        )


class ValidateBackup(BaseTab):
    def create(self) -> TutorialWidget:
        """Create."""
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
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.custom_yes_button.setText(
            self.tr("Yes, I am sure all {number} words are correct").format(number=TEXT_24_WORDS)
        )
        self.custom_cancel_button.setText(self.tr("Previous Step"))
        self.screenshot.updateUi()
        self.never_label.setText(self.get_never_label_text())


class ImportXpubs(BaseTab):
    def _callback(self, tutorial_widget: TutorialWidget) -> None:
        """Callback."""
        self.widget_layout.addWidget(self.keystore_uis)
        # self.refs.wallet_tabs.setCurrentWidget(self.refs.qtwalletbase.wallet_descriptor_ui)
        # tutorial_widget.synchronize_visiblity(
        #     VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=bool(self.refs.qt_wallet))
        # )

    def _create_wallet(self) -> None:
        """Create wallet."""
        if not self.keystore_uis:
            return

        if not self.ask_if_can_proceed():
            return

        try:
            self.keystore_uis.set_protowallet_from_keystore_ui()
            self.refs.qtwalletbase.tutorial_index = self.refs.container.current_index() + 1
            self.refs.signal_create_wallet.emit(self.keystore_uis.protowallet.id)
        except Exception as e:
            caught_exception_message(e, parent=self.refs.container)

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        self.widget_layout = QVBoxLayout(widget)
        self.widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

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
                get_address_type=self.get_address_type,
                signals_min=self.refs.qtwalletbase.signals,
                slow_hwi_listing=True,
                loop_in_thread=self.loop_in_thread,
            )
            self.set_current_signer(0)
            self.keystore_uis.setMovable(False)

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
            self.button_create_wallet.clicked.connect(self._create_wallet)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )

        tutorial_widget.set_callback(partial(self._callback, tutorial_widget))
        # tutorial_widget.synchronize_visiblity(
        #     VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=bool(self.refs.qt_wallet))
        # )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def get_address_type(self):
        """Get address type."""
        return self.refs.qtwalletbase.get_editable_protowallet().address_type

    def set_current_signer(self, value: int):
        """Set current signer."""
        if not self.keystore_uis:
            return
        self.keystore_uis.setCurrentIndex(value)
        for i in range(self.keystore_uis.count()):
            self.keystore_uis.setTabEnabled(i, value == i)
        self.keystore_uis.setMovable(value >= self.keystore_uis.count() - 1)
        self.updateUi()

    def ask_if_can_proceed(self) -> bool:
        """Ask if can proceed."""
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
        """Next signer."""
        if not self.keystore_uis:
            return

        if not self.ask_if_can_proceed():
            return

        if self.keystore_uis.currentIndex() + 1 < self.keystore_uis.count():
            self.set_current_signer(self.keystore_uis.currentIndex() + 1)

    def previous_signer(self):
        """Previous signer."""
        if not self.keystore_uis:
            return
        if self.keystore_uis.currentIndex() - 1 >= 0:
            self.set_current_signer(self.keystore_uis.currentIndex() - 1)

    def updateUi(self) -> None:
        """UpdateUi."""
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

    def close(self):
        """Close."""
        super().close()
        if self.keystore_uis:
            self.keystore_uis.close()


class BackupSeed(BaseTab):
    def __init__(self, refs: WizardTabInfo, loop_in_thread: LoopInThread) -> None:
        super().__init__(refs, loop_in_thread)

        self.previous_step_enabled = False

    def _do_pdf(self) -> None:
        """Do pdf."""
        if not self.refs.qt_wallet:
            Message(self.tr("Please complete the previous steps."), parent=self.refs.container)
            return
        make_and_open_pdf(
            self.refs.qt_wallet.wallet,
            lang_code=QLocale().name() or DEFAULT_LANG_CODE,
        )

    def create(self) -> TutorialWidget:
        """Create."""
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

        screenshots = ScreenshotsViewSeed()
        self.button_help = generate_help_button(screenshots, title="View seed words")

        buttonbox = QDialogButtonBox()
        self.custom_yes_button = QPushButton()
        self.custom_yes_button.setIcon(svg_tools.get_QIcon("print.svg"))
        self.custom_yes_button.clicked.connect(self._do_pdf)
        self.custom_yes_button.clicked.connect(self.refs.go_to_next_index)
        buttonbox.addButton(self.custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.custom_cancel_button = QPushButton()
        self.custom_cancel_button.clicked.connect(self.refs.go_to_previous_index)
        buttonbox.addButton(self.custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttonbox.addButton(self.button_help, QDialogButtonBox.ButtonRole.HelpRole)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, buttonbox, buttonbox_always_visible=False
        )
        # tutorial_widget.synchronize_visiblity(
        #     VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=False)
        # )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()

        self.custom_yes_button.setText(self.tr("Print recovery sheet"))
        self.custom_cancel_button.setText(self.tr("Previous Step"))
        self.custom_cancel_button.setEnabled(self.previous_step_enabled)

        glue_statement = (
            self.tr("Glue the {number} word seed onto the matching printed pdf.").format(number=TEXT_24_WORDS)
            if self.num_keystores() > 1
            else self.tr("Glue the {number} word seed onto the printed pdf.").format(number=TEXT_24_WORDS)
        )
        self.label_print_instructions.setText(
            html_f(
                f"""<ol>
        <li>{self.tr("Print the pdf (it also contains the wallet descriptor)")}</li>
        <li>{glue_statement}</li>""",
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )


class ReceiveTest(BaseTab):
    def _on_sync_done(self, sync_status: SyncStatus) -> None:
        """On sync done."""
        self.check_wallet_for_utxos()

    def check_wallet_for_utxos(self) -> list[PythonUtxo]:
        """Check wallet for utxos."""
        if not self.refs.qt_wallet:
            return []
        utxos = self.refs.qt_wallet.wallet.get_all_utxos(include_not_mine=False)
        self.check_button.setHidden(bool(utxos))
        self.next_button.setHidden(not bool(utxos))
        if utxos:
            Message(
                self.tr("Balance = {amount}").format(
                    amount=Satoshis(utxos[0].txout.value, self.refs.qt_wallet.wallet.network).str_with_unit(
                        btc_symbol=self.refs.qtwalletbase.config.bitcoin_symbol.value
                    )
                ),
                parent=self.refs.container,
            )
        return utxos

    def _start_sync(
        self,
    ) -> None:
        """Start sync."""
        if not self.refs.qt_wallet:
            Message(self.tr("No wallet setup yet"), type=MessageType.Error, parent=self.refs.container)
            return

        # before I do a sync, I should check if the tx is alreasy there.
        if self.check_wallet_for_utxos():
            return

        self.check_button.set_enable_signal(self.refs.qtwalletbase.signal_after_sync)
        one_time_signal_connection(self.refs.qtwalletbase.signal_after_sync, self._on_sync_done)
        self.refs.qt_wallet.sync()

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(10, 0, 0, 0)  # Left, Top, Right, Bottom margins
        widget_layout.setSpacing(20)
        self.quick_receive: BitcoinQuickReceive | None = None

        left_widget_layout = QVBoxLayout()
        set_no_margins(left_widget_layout)
        widget_layout.addLayout(left_widget_layout)

        self.cbf_progress_bar: CBFProgressBar | None = None

        if self.refs.qt_wallet:
            self.quick_receive = BitcoinQuickReceive(
                wallet_signals=self.refs.qt_wallet.wallet_signals,
                wallet=self.refs.qt_wallet.wallet,
                parent=widget,
                signals_min=self.refs.qt_wallet.signals,
            )
            self.quick_receive.signal_manage_categories_requested.connect(
                self.refs.qt_wallet.category_manager.show
            )
            self.quick_receive.signal_add_category_requested.connect(
                self.refs.qt_wallet.category_manager.add_category
            )
            self.quick_receive.set_manage_categories_enabled(True)
            self.quick_receive.setMaximumWidth(250)
            self.quick_receive.setMaximumHeight(300)
            left_widget_layout.addWidget(self.quick_receive)

            self.cbf_progress_bar = CBFProgressBar(config=self.refs.qt_wallet.config, parent=widget)
            left_widget_layout.addWidget(self.cbf_progress_bar)
            self.signal_tracker.connect(
                self.refs.qt_wallet.signal_progress_info, self.cbf_progress_bar._set_progress_info
            )

        else:
            add_centered_icons(["ic--baseline-call-received.svg"], widget_layout, max_sizes=[(50, 80)])
            if (_layout_item := widget_layout.itemAt(0)) and (_widget := _layout_item.widget()):
                _widget.setMaximumWidth(150)

        right_widget = QWidget()
        right_widget_layout = QVBoxLayout(right_widget)
        set_no_margins(right_widget_layout)
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
        self.check_button = SpinningButton("", timeout=20, svg_tools=svg_tools)
        buttonbox.addButton(self.check_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.refs.go_to_previous_index)
        buttonbox.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        self.next_button.setHidden(True)

        self.check_button.clicked.connect(self._start_sync)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        if self.quick_receive:
            self.quick_receive.update_content(UpdateFilter(refresh_all=True))
        return tutorial_widget

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        test_amount = Satoshis(self.refs.max_test_fund, self.refs.qtwalletbase.config.network).str_with_unit(
            btc_symbol=self.refs.qtwalletbase.config.bitcoin_symbol.value
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
                    <b>Do NOT send large funds into the wallet, yet. Please complete all send tests first!</b>   
                    """  # noqa: E501
                ).format(test_amount=test_amount),
                add_html_and_body=True,
                p=True,
                size=12,
            )
        )
        self.next_button.setText(self.tr("Next step"))
        self.check_button.setText(self.tr("Check if received"))
        self.cancel_button.setText(self.tr("Previous Step"))
        if self.quick_receive:
            self.quick_receive.updateUi()


class RegisterMultisig(BaseTab):
    def _callback(self, tutorial_widget: TutorialWidget) -> None:
        """Callback."""
        self.updateUi()

    def create(self) -> TutorialWidget:
        """Create."""
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

        # ui hardware_signer_interactions
        self.hardware_signer_tabs = DataTabWidget[HardwareSignerInteractionWidget]()
        widget_layout.addWidget(self.hardware_signer_tabs)
        for label in self.refs.qtwalletbase.get_keystore_labels():
            hardware_signer_interaction = RegisterMultisigInteractionWidget(
                wallet=self.refs.qt_wallet.wallet if self.refs.qt_wallet else None,
                loop_in_thread=self.loop_in_thread,
                parent=widget,
                wallet_functions=self.refs.qt_wallet.wallet_functions if self.refs.qt_wallet else None,
                wallet_name=self.refs.qt_wallet.wallet.id if self.refs.qt_wallet else "Multisig",
            )
            self.hardware_signer_tabs.addTab(
                hardware_signer_interaction,
                icon=icon_for_label(label),
                description=label,
                data=hardware_signer_interaction,
            )

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

        tutorial_widget.set_callback(partial(self._callback, tutorial_widget))
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        self.set_current_signer(0)
        return tutorial_widget

    def set_current_signer(self, value: int) -> None:
        """Set current signer."""
        if value >= self.hardware_signer_tabs.count():
            return
        self.hardware_signer_tabs.setCurrentIndex(value)
        for i in range(self.hardware_signer_tabs.count()):
            self.hardware_signer_tabs.setTabEnabled(i, value == i)
        self.updateUi()

    def next_signer(self) -> None:
        """Next signer."""
        if self.hardware_signer_tabs.currentIndex() + 1 < self.hardware_signer_tabs.count():
            self.set_current_signer(self.hardware_signer_tabs.currentIndex() + 1)

    def previous_signer(self) -> None:
        """Previous signer."""
        if self.hardware_signer_tabs.currentIndex() - 1 >= 0:
            self.set_current_signer(self.hardware_signer_tabs.currentIndex() - 1)

    def updateUi(self) -> None:
        """UpdateUi."""
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
        """Create."""
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

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()

        if self.num_keystores() > 1:
            self.label_main.setText(
                html_f(
                    f"""<ul>
  <li>{self.tr("Place each seed backup and hardware signer in a secure location, such:")}</li>
   <ul>
   {"".join([f"<li>{self.tr('Seed backup {j} and hardware signer {j} should be in location {j}').format(j=i + 1)}</li>" for i in range(self.num_keystores())]) if self.num_keystores() > 1 else ""}
   </ul>   
   <li>{self.tr("Choose the secure places carefully, considering that you need to go to {m} of the {n}, to spend from your multisig-wallet.").format(m=self.refs.qtwalletbase.get_mn_tuple()[0], n=self.num_keystores())}</li>
</ul> """,  # noqa: E501
                    add_html_and_body=True,
                    p=True,
                    size=12,
                )
            )
        else:
            self.label_main.setText(
                html_f(
                    f"""<ul>
  <li>{self.tr("Store the  seed backup   in a <b>very</b> secure location (like a vault).")}</li>
   <ul>
      <li>{self.tr("The seed backup (24 words) give total control over the funds.")}</li>
   </ul>     
  <li>{self.tr("Store the   hardware signer   in secure location.")}</li>
   </ul>  
</ul>""",
                    add_html_and_body=True,
                    p=True,
                    size=12,
                )
            )


class LabelBackup(BaseTab):
    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        widget_layout = QHBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.checkbox = QCheckBox()
        self.checkbox.setEnabled(bool(self.refs.qt_wallet))
        if (
            self.refs.qt_wallet
            and self.refs.qt_wallet.plugin_manager
            and (sync_client := self.refs.qt_wallet.plugin_manager.get_instance(SyncClient))
        ):
            sync_client.nostr_sync.ui.signal_reset_keys.connect(self.updateUi)
            sync_client.nostr_sync.ui.signal_set_keys.connect(self.updateUi)
        self.checkbox.stateChanged.connect(self.on_checkbox_stateChanged)

        left_widget = QWidget()
        left_widget_layout = QVBoxLayout(left_widget)
        left_widget_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        widget_layout.addWidget(left_widget)

        self.icon = AspectRatioSvgWidget(
            svg_content=svg_tools.get_svg_content("bi--cloud-slash.svg"), size_hint_height=300
        )
        self.icon.setMaximumWidth(300)
        self.icon.setMaximumHeight(300)
        left_widget_layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignCenter)
        left_widget_layout.addWidget(self.checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        right_widget = QWidget()
        right_widget_layout = QVBoxLayout(right_widget)
        right_widget_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        widget_layout.addWidget(right_widget)

        self.label_main = QLabel(widget)
        self.label_main.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.label_main.setOpenExternalLinks(True)  # Allows opening links externally
        self.label_main.setWordWrap(True)
        right_widget_layout.addWidget(self.label_main)

        # right_widget_layout.addItem(QSpacerItem(1, 40))

        self.button_next.setIcon(svg_tools.get_QIcon("checkmark.svg"))

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def on_checkbox_stateChanged(self):
        """On checkbox stateChanged."""
        if (
            self.refs.qt_wallet
            and self.refs.qt_wallet.plugin_manager
            and (sync_client := self.refs.qt_wallet.plugin_manager.get_instance(SyncClient))
        ):
            sync_client.signal_request_enabled.emit(self.checkbox.isChecked())

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()

        if (
            self.refs.qt_wallet
            and self.refs.qt_wallet.plugin_manager
            and (sync_client := self.refs.qt_wallet.plugin_manager.get_instance(SyncClient))
        ):
            nsec = (
                html_f(
                    sync_client.nostr_sync.group_chat.dm_connection.async_dm_connection.keys.secret_key().to_bech32(),
                    bf=True,
                )
                if self.refs.qt_wallet
                else ""
            )
            label_sync_video = link(
                "https://bitcoin-safe.org/en/features/label-sync/", self.tr("Synchronization video")
            )
            collaboration_video = link(
                "https://bitcoin-safe.org/en/features/collaboration/", self.tr("Collaboration video")
            )
            self.label_main.setText(
                html_f(
                    f"""                
<ul>
<li>{self.tr("Encrypted cloud backup of the address labels and categories")}</li>
    <ul>
    <li>{self.tr("Backup secret sync key:") + "<br>" + nsec}</li> 
    </ul>   
<li>{self.tr("Multi-computer synchronization and chat")}</li> 
    <ul>
    <li>{self.tr("Choose trusted computers in Sync & Chat tab on each computer.") + " " + label_sync_video + ",  " + collaboration_video}</li> 
    </ul>
</ul>   
 """,  # noqa: E501
                    add_html_and_body=True,
                    p=True,
                    size=12,
                )
            )
        else:
            self.label_main.setText("")
        self.button_next.setText(self.tr("Finish"))
        self.checkbox.setText(self.tr("Enable"))

        sync_client = (
            self.refs.qt_wallet.plugin_manager.get_instance(SyncClient)
            if self.refs.qt_wallet and (self.refs.qt_wallet.plugin_manager)
            else None
        )
        self.icon.setSvgContent(svg_content=svg_tools.get_svg_content(icon_basename="bi--cloud.svg"))
        self.checkbox.setChecked(sync_client.enabled if sync_client else False)


class SendTest(BaseTab):
    def __init__(
        self,
        test_label: str,
        test_number: int,
        tx_text: str,
        refs: WizardTabInfo,
        loop_in_thread: LoopInThread,
    ) -> None:
        """Initialize instance."""
        super().__init__(refs, loop_in_thread=loop_in_thread)
        self.test_label = test_label
        self.test_number = test_number
        self.tx_text = tx_text

    def set_visibilities(self, should_be_visible: bool):
        """Set visibilities."""
        if self.refs.qt_wallet:
            if should_be_visible:
                uitx = self.refs.qt_wallet.uitx_creator
                # ensure the widget is reparented away from whatever layout currently holds it
                uitx.setParent(None)
                self.widget_layout.addWidget(uitx)
                uitx.setHidden(False)
            else:
                # Only move the shared widget back if this tab currently owns it;
                # otherwise another SendTest tab will steal it away from the active step.
                if self.widget_layout.indexOf(self.refs.qt_wallet.uitx_creator) != -1:
                    self.refs.qt_wallet.send_node.setWidget(self.refs.qt_wallet.uitx_creator)
                    self.refs.qt_wallet.uitx_creator.clear_ui()

    def _callback(self) -> None:
        """Callback."""
        if not self.refs.qt_wallet:
            return

        self.set_visibilities(True)
        if self.refs.qt_wallet.wallet.client and self.refs.qt_wallet.wallet.client.sync_status in [
            SyncStatus.unknown,
            SyncStatus.unsynced,
        ]:
            logger.debug(
                f"Skipping tutorial callback  for send test, "
                f"because {self.refs.qt_wallet.wallet.id} sync_status={self.refs.qt_wallet.wallet.client.sync_status}"
            )
            return
        logger.debug("tutorial callback")

        # compare how many tx were already done , to the current test_number
        def should_offer_skip() -> bool:
            """Should offer skip."""
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
                true_button=QMessageBox.StandardButton.Yes,
                false_button=QMessageBox.StandardButton.No,
            ):
                self.refs.go_to_next_index()
                return

        self.refs.floating_button_box.fill_tx()

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        self.widget_layout = QVBoxLayout(widget)
        set_no_margins(self.widget_layout)

        upper_widget = QWidget()
        self.widget_layout.addWidget(upper_widget)
        upper_widget_layout = QHBoxLayout(upper_widget)
        set_no_margins(upper_widget_layout)

        add_centered_icons(["bi--send.svg"], upper_widget_layout, max_sizes=[(50, 80)])
        if (layout_item := upper_widget_layout.itemAt(0)) and (sub_widget := layout_item.widget()):
            sub_widget.setMaximumWidth(150)

        inner_widget = QWidget()
        inner_widget_layout = QVBoxLayout(inner_widget)
        self.label = QLabel()
        inner_widget_layout.addWidget(self.label)

        upper_widget_layout.addWidget(inner_widget)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.setMinimumHeight(50)  # otherwise self.label isnt visible

        tutorial_widget.set_callback(self._callback)
        # tutorial_widget.synchronize_visiblity(
        #     VisibilityOption(self.refs.wallet_tabs, on_focus_set_visible=bool(self.refs.qt_wallet))
        # )
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
        """UpdateUi."""
        super().updateUi()

        if self.num_keystores() == 1:
            text = html_f(
                self.tr("Complete the send test to ensure the hardware signer works!"),
                add_html_and_body=True,
                p=True,
                size=12,
            )
        else:
            text = html_f(self.tx_text, add_html_and_body=True, p=True, size=12)

        self.label.setText(text)


class Wizard(WizardBase):
    signal_create_wallet = cast(SignalProtocol[[str]], pyqtSignal(str))  # protowallet_id
    signal_step_change = cast(SignalProtocol[[int]], pyqtSignal(int))

    def __init__(
        self,
        qtwalletbase: QtWalletBase,
        max_test_fund=1_000_000,
        qt_wallet: QTWallet | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            step_labels=[""] * 3,
            signals_min=qtwalletbase.signals,
            loop_in_thread=qt_wallet.loop_in_thread if qt_wallet else qtwalletbase.loop_in_thread,
            clickable=False,
        )  # initialize with 3 steps (doesnt matter)
        logger.debug(f"__init__ {self.__class__.__name__}")
        self.qtwalletbase = qtwalletbase
        self.qt_wallet = qt_wallet
        if qt_wallet and qt_wallet.tutorial_index is not None:
            qt_wallet.tutorial_index = max(qt_wallet.tutorial_index, TutorialStep.import_xpub.value)

        self.qtwalletbase.tabs.addChildNode(self.node)
        self.node.setHidable(bool(self.qt_wallet))

        m, n = self.qtwalletbase.get_mn_tuple()

        # floating_button_box
        self.floating_button_box = FloatingButtonBar(
            self.fill_tx,
            (self.qt_wallet.uitx_creator.create_tx if self.qt_wallet else self.show_warning_not_initialized),
            self.go_to_next_index,
            self.go_to_previous_index,
            self.qtwalletbase.signals,
        )
        self.floating_button_box.fill()
        self._layout.addWidget(self.floating_button_box)

        refs = WizardTabInfo(
            container=self.step_container,
            qtwalletbase=qtwalletbase,
            go_to_next_index=self.go_to_next_index,
            go_to_previous_index=self.go_to_previous_index,
            floating_button_box=self.floating_button_box,
            signal_create_wallet=self.signal_create_wallet,
            qt_wallet=self.qt_wallet,
            max_test_fund=max_test_fund,
        )

        self.tab_generators: dict[TutorialStep, BaseTab] = {
            TutorialStep.buy: BuyHardware(refs=refs, loop_in_thread=self.loop_in_thread),
            TutorialStep.sticker: StickerTheHardware(refs=refs, loop_in_thread=self.loop_in_thread),
            TutorialStep.generate: GenerateSeed(refs=refs, loop_in_thread=self.loop_in_thread),
            TutorialStep.import_xpub: ImportXpubs(refs=refs, loop_in_thread=self.loop_in_thread),
            TutorialStep.backup_seed: BackupSeed(refs=refs, loop_in_thread=self.loop_in_thread),
        }
        if n > 1:
            self.tab_generators[TutorialStep.register] = RegisterMultisig(
                refs=refs, loop_in_thread=self.loop_in_thread
            )

        self.tab_generators[TutorialStep.receive] = ReceiveTest(refs=refs, loop_in_thread=self.loop_in_thread)

        for test_number, tutoral_step in enumerate(self.get_send_tests_steps()):
            self.tab_generators[tutoral_step] = SendTest(
                self.get_send_test_labels()[test_number],
                test_number=test_number,
                tx_text=self.tx_text(test_number),
                refs=refs,
                loop_in_thread=self.loop_in_thread,
            )

        self.tab_generators[TutorialStep.distribute] = DistributeSeeds(
            refs=refs, loop_in_thread=self.loop_in_thread
        )
        self.tab_generators[TutorialStep.sync] = LabelBackup(refs=refs, loop_in_thread=self.loop_in_thread)

        self.max_test_fund = max_test_fund

        # self.qtwalletbase.outer_layout.insertWidget(0, self)

        self.widgets: dict[TutorialStep, TutorialWidget] = {
            key: generator.create() for key, generator in self.tab_generators.items()
        }

        # set_custom_widget  from StepProgressContainer
        for i, widget in enumerate(self.widgets.values()):
            self.step_container.set_custom_widget(i, widget)

        if self.qtwalletbase.tutorial_index is not None:
            self.set_current_index(self.qtwalletbase.tutorial_index)
            # save after every step

        self.step_container.signal_set_current_widget.connect(self._save)
        self.signal_step_change.connect(self.qtwalletbase.set_tutorial_index)
        self.node.hideClicked.connect(self.on_hide_clicked)

        self.updateUi()
        self.set_visibilities()

        self.qtwalletbase.signals.language_switch.connect(self.updateUi)
        if self.qt_wallet:
            self.qtwalletbase.wallet_functions.wallet_signals[self.qt_wallet.wallet.id].updated.connect(
                self.on_utxo_update
            )

    def on_hide_clicked(self, obj: object):
        """On hide clicked."""
        self.toggle_tutorial()

    def _save(self, widget):
        """Save."""
        if self.qt_wallet:
            self.qt_wallet.save()

    def show_warning_not_initialized(self):
        """Show warning not initialized."""
        Message(self.tr("You must have an initilized wallet first"), type=MessageType.Warning, parent=self)

    def toggle_tutorial(self) -> None:
        """Toggle tutorial."""
        if self.get_wallet_tutorial_index() is None:
            self.qtwalletbase.tutorial_index = self.index_of_step(self.guess_current_step())
            self.set_current_index(self.qtwalletbase.tutorial_index)

        else:
            self.qtwalletbase.tutorial_index = None

        self.set_visibilities()
        if self.should_be_visible:
            self.node.select()

    def guess_current_step(self) -> TutorialStep:
        """Guess current step."""
        step = TutorialStep.buy
        if self.qt_wallet:
            step = TutorialStep.backup_seed

            if self.qt_wallet.wallet.get_balance().total > 0:
                step = TutorialStep.send

            if (
                self.qt_wallet.plugin_manager
                and (sync_cient := self.qt_wallet.plugin_manager.get_instance(SyncClient))
                and sync_cient.enabled
            ):
                step = TutorialStep.sync

        return step

    def get_latest_send_test_in_tx_history(
        self, steps: list[TutorialStep], wallet: Wallet
    ) -> TutorialStep | None:
        """Get latest send test in tx history."""
        latest_step = None
        for test_number, tutoral_step in enumerate(steps):
            tx_text = self.tx_text(test_number)
            for txo in wallet.get_all_txos_dict().values():
                if wallet.labels.get_label(txo.address) == tx_text:
                    latest_step = tutoral_step
        return latest_step

    def on_utxo_update(self, update_filter: UpdateFilter) -> None:
        """On utxo update."""
        if not self.qt_wallet or not self.should_be_visible:
            return

        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.outpoints:
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter")

        steps = self.get_send_tests_steps()
        latest_step = self.get_latest_send_test_in_tx_history(steps, self.qt_wallet.wallet)
        if latest_step is None:
            return
        latest_test_number = steps.index(latest_step)

        steps = self.get_send_tests_steps()
        tx_text = self.tx_text(latest_test_number)
        if latest_test_number >= len(steps) - 1:
            Message(self.tr("All Send tests done successfully."), type=MessageType.Info, parent=self)
        else:
            Message(
                self.tr(
                    "The test transaction \n'{tx_text}'\n was done successfully. "
                    "Please proceed to do the send test: \n'{next_text}'"
                ).format(tx_text=tx_text, next_text=self.tx_text(latest_test_number + 1)),
                type=MessageType.Info,
                parent=self,
            )

        # only increase the index, if the index is not ahead already
        if self.step_container.current_index() < self.index_of_step(latest_step) + 1:
            self.set_current_index(self.index_of_step(latest_step) + 1)
            self.node.select()

    def current_step(self) -> TutorialStep:
        """Current step."""
        return self.get_step_of_index(self.step_container.current_index())

    def index_of_step(self, step: TutorialStep) -> int:
        """Index of step."""
        return [step for step in TutorialStep if step in self.tab_generators].index(step)

    def get_step_of_index(self, index: int) -> TutorialStep:
        """Get step of index."""
        members = list(self.tab_generators.keys())
        if index < 0:
            index = 0
        if index >= len(members):
            index = len(members) - 1
        return members[index]

    def get_wallet_tutorial_index(self) -> int | None:
        """Get wallet tutorial index."""
        return (self.qt_wallet.tutorial_index) if self.qt_wallet else self.qtwalletbase.tutorial_index

    def set_wallet_tutorial_index(self, value: int | None) -> None:
        """Set wallet tutorial index."""
        if self.qt_wallet:
            self.qt_wallet.tutorial_index = value
        else:
            self.qtwalletbase.tutorial_index = value

    @property
    def should_be_visible(self) -> bool:
        """Should be visible."""
        return self.get_wallet_tutorial_index() is not None

    def set_visibilities(self) -> None:
        """Set visibilities."""
        self.node.setVisible(self.should_be_visible)
        if self.node.parent_node:
            for child in self.node.parent_node.child_nodes:
                if child == self.node:
                    continue
                #  only non_wizard nodes
                always_visible = (
                    [self.qt_wallet.hist_node, self.qt_wallet.settings_node] if self.qt_wallet else []
                )
                if child in always_visible:
                    child.setVisible(True)
                else:
                    child.setVisible(not self.should_be_visible)

        if self.should_be_visible:
            self.step_container.signal_widget_focus.emit(self.widgets[self.current_step()])
        else:
            self.floating_button_box.setVisible(False)
            if self.qt_wallet:
                self.qt_wallet.uitx_creator.button_box.setVisible(True)

        active_step = self.current_step()
        for step, tab in self.tab_generators.items():
            tab.set_visibilities(step == active_step)

    def num_keystores(self) -> int:
        """Num keystores."""
        return self.qtwalletbase.get_mn_tuple()[1]

    def set_current_index(self, index: int) -> None:
        """Set current index."""
        self.step_container.set_current_index(index)
        self.signal_step_change.emit(index)

    def go_to_previous_index(self) -> None:
        """Go to previous index."""
        logger.info(
            f"go_to_previous_index: Old index {self.step_container.current_index()} = {self.current_step()}"
        )
        self.set_current_index(max(self.step_container.current_index() - 1, 0))
        logger.info(
            f"go_to_previous_index: Switched index "
            f"{self.step_container.current_index()} = {self.current_step()}"
        )

    def go_to_next_index(self) -> None:
        """Go to next index."""
        if self.step_container.step_bar.current_index + 1 >= self.step_container.step_bar.number_of_steps:
            self.set_wallet_tutorial_index(None)
            self.set_visibilities()
            if self.qt_wallet:
                self.qt_wallet.tabs.select()

            return
        logger.info(
            f"go_to_next_index: Old index {self.step_container.current_index()} = {self.current_step()}"
        )
        self.set_current_index(
            min(
                self.step_container.step_bar.current_index + 1,
                self.step_container.step_bar.number_of_steps - 1,
            )
        )
        logger.info(
            f"go_to_next_index: Switched index {self.step_container.current_index()} = {self.current_step()}"
        )

    def get_send_tests_steps(self) -> list[TutorialStep]:
        """Get send tests steps."""
        m, n = self.qtwalletbase.get_mn_tuple()

        number = ceil(n / m)

        start_index = list(TutorialStep).index(TutorialStep.send)

        return list(TutorialStep)[start_index : start_index + number]

    def get_send_test_labels(self) -> list[str]:
        """Get send test labels."""
        m, n = self.qtwalletbase.get_mn_tuple()
        keystore_labels = self.qtwalletbase.get_keystore_labels()

        send_test_labels = []
        for i_send_tests, _tutorial_step in enumerate(self.get_send_tests_steps()):
            start_signer = m * i_send_tests
            end_signer = min(m * i_send_tests + m, n)

            missing_signers = m - (end_signer - start_signer)
            start_signer -= missing_signers

            labels = [keystore_labels[j] for j in range(start_signer, end_signer)]
            send_test_labels.append(self.tr(" and ").join([f'"{label}"' for label in labels]))

        return send_test_labels

    def tx_text(self, test_number: int) -> str:
        """Tx text."""
        if self.num_keystores() == 1:
            return self.tr("Send Test")
        else:
            return self.tr("Sign with {label}").format(label=self.get_send_test_labels()[test_number])

    def open_tx(self, test_number: int) -> None:
        """Open tx."""
        if not self.qt_wallet:
            return

        label = self.tx_text(test_number)

        utxos = [txo for txo in self.qt_wallet.wallet.get_all_utxos()]
        if not utxos:
            Message(self.tr("The wallet is not funded. Please fund the wallet."), parent=self)
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
        txinfos.main_wallet_id = self.qt_wallet.wallet.id
        # inputs

        recipient_address = str(
            self.qt_wallet.wallet.get_unused_category_address(category=funded_category).address
        )
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
        txinfos.hide_entire_input_column = True
        txinfos.recipient_read_only = True

        self.qt_wallet.uitx_creator.initial_tx_ui_infos = txinfos
        self.qt_wallet.uitx_creator.set_ui(txinfos)

    def fill_tx(self) -> None:
        """Fill tx."""
        if not self.qt_wallet:
            return

        # use the current_step, but if I highlighted another signing
        if self.current_step() in self.get_send_tests_steps():
            test_number = self.get_send_tests_steps().index(self.current_step())
        else:
            hightligted_step = self.get_step_of_index(self.step_container.current_highlighted_index())
            if hightligted_step in self.get_send_tests_steps():
                test_number = self.get_send_tests_steps().index(hightligted_step)
            else:
                # don't know what tx to fill
                return

        # set all tabs except the send as hidden
        # for tab in self.qt_wallet.tabs.child_nodes:
        #     if tab.widget:
        #         tab.widget.setHidden(tab.widget != self.qt_wallet.uitx_creator)
        self.open_tx(test_number)

    def updateUi(self) -> None:
        # step_bar
        """UpdateUi."""
        labels: dict[TutorialStep, str] = {
            TutorialStep.buy: self.tr("Buy hardware signers"),
            TutorialStep.sticker: self.tr("Label the hardware signers"),
            TutorialStep.generate: self.tr("Generate Seed"),
            TutorialStep.import_xpub: self.tr("Import signer info"),
            TutorialStep.backup_seed: self.tr("Backup Seed"),
            TutorialStep.validate_backup: self.tr("Validate Backup"),
            TutorialStep.receive: self.tr("Receive Test"),
            TutorialStep.distribute: self.tr("Put in secure locations"),
            TutorialStep.register: self.tr("Register multisig on signers"),
            TutorialStep.sync: self.tr("Sync & Chat"),
        }
        for i, tutoral_step in enumerate(self.get_send_tests_steps()):
            labels[tutoral_step] = (
                self.tr("Send test {j}").format(j=i + 1)
                if len(self.get_send_tests_steps()) > 1
                else self.tr("Send test")
            )

        self.step_container.set_labels([labels[key] for key in self.tab_generators if key in labels])

    def _clear_widgets_and_tab_generators(self) -> None:
        """Clear widgets and tab generators."""
        while self.widgets:
            k, widget = self.widgets.popitem()
            widget.close()

        while self.tab_generators:
            k, g = self.tab_generators.popitem()
            g.close()

    def close(self) -> bool:
        """Close."""
        self.step_container.close()
        self.step_container.clear_widgets()
        self.qtwalletbase.outer_layout.removeWidget(self.floating_button_box)
        self.qtwalletbase.outer_layout.removeWidget(self)
        self.floating_button_box.setParent(None)
        self.floating_button_box.close()
        self._clear_widgets_and_tab_generators()
        self.setParent(None)
        return super().close()

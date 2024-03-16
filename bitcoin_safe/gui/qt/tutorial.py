import logging

from bitcoin_safe.signals import Signals

logger = logging.getLogger(__name__)

import enum
from math import ceil
from typing import Any, Callable, Dict, List, Optional

import bdkpython as bdk
import numpy as np
from PyQt6.QtCore import QSize, Qt, pyqtSignal
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
    ScreenshotsResetSigner,
    ScreenshotsRestoreSigner,
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
    add_centered,
    add_centered_icons,
    caught_exception_message,
    create_button,
    create_button_box,
    icon_path,
    one_time_signal_connection,
    open_website,
)


def create_buy_coldcard_button(parent):
    button = create_button("Buy a Coldcard\n5% off", icon_path("coldcard-only.svg"), parent)
    button.clicked.connect(lambda: open_website("https://store.coinkite.com/promo/8BFF877000C34A86F410"))
    return button


def create_buy_bitbox_button(parent):
    button = create_button("Buy a Bitbox02\nBitcoin Only Edition", icon_path("usb-stick.svg"), parent)
    button.clicked.connect(lambda: open_website("https://shiftcrypto.ch/bitbox02/?ref=MOB4dk7gpm"))
    return button


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

    def set_visibilities(self):
        self.tutorial_button_prefill.setVisible(self.status in [self.TxSendStatus.not_filled])
        self.button_create_tx.setVisible(self.status in [self.TxSendStatus.filled])
        self.tutorial_button_prev_step.setVisible(True)
        self.button_yes_it_is_in_hist.setVisible(
            self.status in [self.TxSendStatus.finalized, self.TxSendStatus.sent]
        )

    def set_status(self, status=TxSendStatus):
        if self.status == status:
            return
        self.status = status
        self.set_visibilities()

    def fill_tx(self):
        self._fill_tx()
        self.set_status(self.TxSendStatus.filled)

    def create_tx(self):
        # before do _create_tx, setup a 1 time connection
        # so I can catch the tx and ensure that TxSendStatus == finalized
        # just in case the suer clicked "go back"
        def catch_txid(tx: bdk.Transaction):
            self.set_status(self.TxSendStatus.finalized)

        one_time_signal_connection(self.signals.signal_broadcast_tx, catch_txid)

        self._create_tx()
        self.set_status(self.TxSendStatus.finalized)

    def go_to_next_index(self):
        self._go_to_next_index()
        self.set_status(self.TxSendStatus.not_filled)

    def go_to_previous_index(self):
        self._go_to_previous_index()
        self.set_status(self.TxSendStatus.not_filled)

    def fill(self) -> QDialogButtonBox:
        self.setVisible(False)

        self.tutorial_button_prefill = QPushButton(f"Fill the transaction fields")
        self.tutorial_button_prefill.clicked.connect(self.fill_tx)
        self.addButton(self.tutorial_button_prefill, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_create_tx = QPushButton(f"Create Transaction")
        self.button_create_tx.clicked.connect(self.create_tx)
        self.addButton(self.button_create_tx, QDialogButtonBox.ButtonRole.AcceptRole)

        self.button_yes_it_is_in_hist = QPushButton("Yes, I see the transaction in the history")
        self.button_yes_it_is_in_hist.setVisible(False)
        self.button_yes_it_is_in_hist.clicked.connect(self.go_to_next_index)
        self.addButton(self.button_yes_it_is_in_hist, QDialogButtonBox.ButtonRole.AcceptRole)

        self.tutorial_button_prev_step = QPushButton("Previous Step")
        self.tutorial_button_prev_step.clicked.connect(self.go_to_previous_index)
        self.addButton(self.tutorial_button_prev_step, QDialogButtonBox.ButtonRole.RejectRole)

        self.set_status(self.TxSendStatus.not_filled)


class WalletSteps(StepProgressContainer):
    signal_create_wallet = pyqtSignal()

    def __init__(
        self,
        qtwalletbase: QtWalletBase,
        wallet_tabs: QTabWidget,
        max_test_fund=1_000_000,
        qt_wallet: QTWallet = None,
    ) -> None:
        self.qtwalletbase = qtwalletbase
        self.qt_wallet = qt_wallet
        m, n = self.qtwalletbase.get_mn_tuple()

        self.tab_infos: Dict[TutorialStep, Dict[str, Any]] = {
            TutorialStep.buy: {"label": "Turn on hardware signer", "create_tab": self.create_buy_hardware},
            TutorialStep.generate: {"label": "Generate Seed", "create_tab": self.create_generate_seed},
            TutorialStep.import_xpub: {
                "label": "Import signer info",
                "create_tab": self.create_import_xpubs,
            },
            TutorialStep.backup_seed: {"label": "Backup Seed", "create_tab": self.create_backup_seed},
            TutorialStep.validate_backup: {
                "label": "Validate Backup",
                "create_tab": self.create_validate_backup,
            },
            TutorialStep.receive: {"label": "Receive Test", "create_tab": self.create_receive_test},
            # TutorialStep.reset: {"label": "Reset hardware signer", "create_tab": self.create_reset_signer},
        }
        if n > 1:
            self.tab_infos[TutorialStep.register] = {
                "label": "Register multisig on signers",
                "create_tab": self.create_register_multisig_on_signers,
            }
        for i, tutoral_step in enumerate(self.get_send_tests_steps()):

            def factory_create_send_test(test_number: int):
                return lambda: self.create_send_test(test_number=test_number)

            self.tab_infos[tutoral_step] = {
                "label": f"Send test {i+1}" if len(self.get_send_tests_steps()) > 1 else f"Send test",
                "create_tab": factory_create_send_test(i),
            }

        self.tab_infos[TutorialStep.distribute] = {
            "label": "Put in secure locations",
            "create_tab": self.create_distribute_seeds,
        }

        self.wallet_tabs = wallet_tabs
        self.max_test_fund = max_test_fund

        super().__init__(step_labels=[d["label"] for d in self.tab_infos.values()])
        self.qtwalletbase.outer_layout.insertWidget(0, self)

        self.floating_button_box = FloatingButtonBar(
            self.fill_tx,
            self.qt_wallet.uitx_creator.create_tx
            if self.qt_wallet
            else lambda: Message("You must have an initilized wallet first"),
            self.go_to_next_index,
            self.go_to_previous_index,
            self.qtwalletbase.signals,
        )
        self.floating_button_box.fill()
        self.qtwalletbase.outer_layout.addWidget(self.floating_button_box)
        self.widgets: List[TutorialWidget] = [d["create_tab"]() for d in self.tab_infos.values()]

        # set_custom_widget  from StepProgressContainer
        for i, widget in enumerate(self.widgets):
            self.set_custom_widget(i, widget)

        if self.qt_wallet:
            step = (
                self.count() - 1
                if self.qt_wallet.wallet.tutorial_index is None
                else self.qt_wallet.wallet.tutorial_index
            )
            self.set_current_index(step)

        self.set_visibilities()

    def current_step(self) -> TutorialStep:
        return self.get_step_of_index(self.current_index())

    def index_of_step(self, step: TutorialStep) -> int:
        return list(TutorialStep).index(step)

    def get_step_of_index(self, index: int) -> TutorialStep:
        members = list(self.tab_infos.keys())
        if index < 0:
            index = 0
        if index >= len(members):
            index = len(members) - 1
        return members[index]

    def get_step_title_number_of(self, step: TutorialStep) -> int:
        return list(self.tab_infos.keys()).index(step) + 1

    def get_wallet_tutorial_index(self):
        return (
            (self.qt_wallet.wallet.tutorial_index)
            if self.qt_wallet
            else self.qtwalletbase.get_editable_protowallet().tutorial_index
        )

    def set_wallet_tutorial_index(self, value: Optional[int]):
        if self.qt_wallet:
            self.qt_wallet.wallet.tutorial_index = value
        else:
            self.qtwalletbase.get_editable_protowallet().tutorial_index = value

    def set_visibilities(self):
        should_be_visible = self.get_wallet_tutorial_index() != None
        self.setVisible(should_be_visible)

        if should_be_visible:
            self.signal_widget_focus.emit(self.widgets[self.current_index()])
        else:
            self.wallet_tabs.setVisible(True)
            self.floating_button_box.setVisible(False)
            if self.qt_wallet:
                self.qt_wallet.uitx_creator.button_box.setVisible(True)

    def num_keystores(self) -> int:
        return self.qtwalletbase.get_mn_tuple()[1]

    def create_buy_hardware(self):

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

        label_buy = QLabel(widget)
        label_buy.setWordWrap(True)
        label_buy.setText(
            f'<html><head/><body><p><span style="font-size: 12pt;">Do you need to buy a hardware signer? </span></p></body></html>',
        )
        right_widget.layout().addWidget(label_buy)

        pushButton_buycoldcard = QPushButton()
        pushButton_buycoldcard.setText("Buy a Coldcard\n5% off")
        pushButton_buycoldcard.setIcon(QIcon(icon_path("coldcard-only.svg")))
        pushButton_buycoldcard.clicked.connect(
            lambda: open_website("https://store.coinkite.com/promo/8BFF877000C34A86F410")
        )
        right_widget.layout().addWidget(pushButton_buycoldcard)
        pushButton_buycoldcard.setIconSize(QSize(32, 32))  # Set the icon size to 64x64 pixels

        pushButton_buybitbox = QPushButton()
        pushButton_buybitbox.setText("Buy a Bitbox02\nBitcoin Only Edition")
        pushButton_buybitbox.setIcon(QIcon(icon_path("usb-stick.svg")))
        pushButton_buybitbox.clicked.connect(
            lambda: open_website("https://shiftcrypto.ch/bitbox02/?ref=MOB4dk7gpm")
        )
        pushButton_buybitbox.setIconSize(QSize(32, 32))  # Set the icon size to 64x64 pixels
        right_widget.layout().addWidget(pushButton_buybitbox)

        right_widget.layout().addItem(QSpacerItem(1, 40))

        label_2 = QLabel(widget)
        label_2.setWordWrap(True)
        label_2.setText(
            f'<html><head/><body><p><span style="font-size: 12pt;">Turn on your {self.num_keystores()} hardware signer{"s" if self.num_keystores()>1 else ""}</span></p></body></html>',
        )
        right_widget.layout().addWidget(label_2)

        # pushButton_buycoldcard.clicked.connect(lambda: open_website("https://store.coinkite.com/promo/8BFF877000C34A86F410"))

        # pushButton_buycoldcard = create_buy_coldcard_button(widget)
        # pushButton_buycoldcard.setMaximumWidth(150)

        # pushButton_buybitbox = create_buy_bitbox_button(widget)
        # pushButton_buybitbox.setMaximumWidth(150)

        buttonbox = create_button_box(
            self.go_to_next_index,
            self.go_to_previous_index,
            ok_text="Next step",
            cancel_text="Previous Step",
        )

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)

        return tutorial_widget

    def change_index(self, index: int):
        self.set_current_index(index)

    def go_to_previous_index(self):
        self.change_index(max(self.current_index() - 1, 0))

    def go_to_next_index(self):
        if self.step_bar.current_index + 1 >= self.step_bar.number_of_steps:
            self.set_wallet_tutorial_index(None)
            self.set_visibilities()

            # Message(
            #     f'Your wallet is now setup. \nPut the {self.num_keystores()} Seed-backup{"s" if  self.num_keystores()> 1 else ""} in {self.num_keystores()} different secure places. ',
            #     icon=QIcon(icon_path("checkmark.png")).pixmap(QSize(64, 64)),
            # )

            return
        self.change_index(min(self.step_bar.current_index + 1, self.step_bar.number_of_steps - 1))

    def get_never_share_label(self) -> QLabel:

        label_never_share_seed = QLabel()
        label_never_share_seed.setWordWrap(True)
        label_never_share_seed.setText(
            '<html><head/><body><p><span style="color: red; font-size: 12pt;">Never share the 24 secret words with anyone! </span></p><p><span style="color: red; font-size: 12pt;">Never type them into any computer or cellphone! </span></p><p><span style="color: red; font-size: 12pt;">Never make a picture of them!</span></p></body></html>',
        )
        label_never_share_seed.setMinimumWidth(300)
        return label_never_share_seed

    def create_generate_seed(self) -> QWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        screenshot = ScreenshotsGenerateSeed()
        widget.layout().addWidget(screenshot)

        widget.layout().addWidget(self.get_never_share_label())

        buttonbox = create_button_box(
            self.go_to_next_index,
            self.go_to_previous_index,
            ok_text="Next step",
            cancel_text="Previous Step",
        )

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=False)
        return tutorial_widget

    def create_import_xpubs(self) -> QWidget:

        widget = QWidget()
        widget.setLayout(QVBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        screenshot = ScreenshotsExportXpub()
        widget.layout().addWidget(screenshot)

        # handle protowallet and qt_wallet differently:
        if self.qt_wallet:
            # show the full walet descriptor tab below

            buttonbox = create_button_box(
                self.go_to_next_index,
                self.go_to_previous_index,
                ok_text="Skip step",
                cancel_text="Previous Step",
            )

        else:
            # integrater the KeyStoreUIs into the tutorials, hide wallet_tabs

            label2 = QLabel("2. Import wallet information into Bitcoin Safe")
            label2.setFont(screenshot.title.font())
            widget.layout().addWidget(label2)

            # this is used in TutorialStep.import_xpub
            self.keystore_uis = KeyStoreUIs(
                get_editable_protowallet=self.qtwalletbase.get_editable_protowallet,
                get_address_type=lambda: self.qtwalletbase.get_editable_protowallet().address_type,
            )
            self.keystore_uis.setCurrentIndex(0)
            widget.layout().addWidget(self.keystore_uis)

            def create_wallet():
                try:
                    self.keystore_uis.set_protowallet_from_keystore_ui()
                    self.qtwalletbase.get_editable_protowallet().tutorial_index = self.current_index() + 1
                    self.signal_create_wallet.emit()
                except Exception as e:
                    caught_exception_message(e)

            buttonbox = create_button_box(
                create_wallet,
                self.go_to_previous_index,
                ok_text="Next step",
                cancel_text="Previous Step",
            )

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)

        def callback():
            self.wallet_tabs.setCurrentWidget(self.qtwalletbase.wallet_descriptor_tab)
            tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=bool(self.qt_wallet))

        tutorial_widget.set_callback(callback)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=bool(self.qt_wallet))
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=False)

        return tutorial_widget

    def create_backup_seed(self) -> QWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["descriptor-backup.svg"],
            widget,
            max_sizes=[(100 * self.num_keystores(), 120)],
        )

        label_10 = QLabel(widget)
        label_10.setWordWrap(True)
        label_10.setText(
            f"""<html><head/><body><p><span style="font-size: 12pt;">
             <ol>
        <li>Print the pdf (it also contains the wallet descriptor)</li>
        <li>Write {"each" if self.num_keystores()>1 else "the"} 24-word seed onto the printed pdf.</li> </body></html>"""
        )
        widget.layout().addWidget(label_10)

        def do_pdf():
            if not self.qt_wallet:
                Message("Please complete the previous steps.")
                return
            make_and_open_pdf(self.qt_wallet.wallet)

        # button = create_button(
        #     "Print the descriptor", icon_path("pdf-file.svg"), widget, layout
        # )
        # button.setMaximumWidth(150)
        # button.clicked.connect(do_pdf)

        buttonbox = QDialogButtonBox()
        custom_yes_button = QPushButton("Print recovery sheet")
        custom_yes_button.setIcon(QIcon(icon_path("print.svg")))
        custom_yes_button.clicked.connect(do_pdf)
        custom_yes_button.clicked.connect(self.go_to_next_index)
        buttonbox.addButton(custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        custom_cancel_button = QPushButton("Previous Step")
        custom_cancel_button.clicked.connect(self.go_to_previous_index)
        buttonbox.addButton(custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=False)
        return tutorial_widget

    def create_validate_backup(self) -> QWidget:

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # width = 300
        # svg_widgets = add_centered_icons(["reset-signer.svg"], widget, max_sizes=[(width, 120)])
        # widget.layout().itemAt(0).widget().setMaximumWidth(width)

        screenshot = ScreenshotsViewSeed()
        widget.layout().addWidget(screenshot)
        widget.layout().addWidget(self.get_never_share_label())

        buttonbox = QDialogButtonBox()
        custom_yes_button = QPushButton(f"Yes, I am sure all 24 words are correct")
        custom_yes_button.clicked.connect(self.go_to_next_index)
        buttonbox.addButton(custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        custom_cancel_button = QPushButton("Previous Step")
        custom_cancel_button.clicked.connect(self.go_to_previous_index)
        buttonbox.addButton(custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=False)

        return tutorial_widget

    def create_receive_test(self) -> QWidget:
        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(10, 0, 0, 0)  # Left, Top, Right, Bottom margins
        widget.layout().setSpacing(20)

        if self.qt_wallet:
            category = self.qt_wallet.wallet.labels.get_default_category()
            address_info = self.qt_wallet.wallet.get_unused_category_address(category)
            quick_receive = ReceiveGroup(
                category,
                hash_color(category).name(),
                address_info.address.as_string(),
                address_info.address.to_qr_uri(),
            )
            quick_receive.setMaximumHeight(300)
            widget.layout().addWidget(quick_receive)
        else:
            add_centered_icons(["receive.svg"], widget, max_sizes=[(50, 80)])
            widget.layout().itemAt(0).widget().setMaximumWidth(150)

        label_10 = QLabel(widget)
        label_10.setWordWrap(True)
        test_amount = (
            f"(less than {Satoshis( self.max_test_fund, self.qt_wallet.wallet.network).str_with_unit()}) "
            if self.qt_wallet
            else ""
        )
        label_10.setText(
            f'<html><head/><body><p><span style="font-size: 12pt;">Receive a small amount {test_amount}to an address of this wallet</span></p></body></html>'
        )
        widget.layout().addWidget(label_10)

        buttonbox = QDialogButtonBox()
        next_button = QPushButton("Next step")
        next_button.clicked.connect(self.go_to_next_index)
        buttonbox.addButton(next_button, QDialogButtonBox.ButtonRole.AcceptRole)
        check_button = SpinningButton("Check if received")
        buttonbox.addButton(check_button, QDialogButtonBox.ButtonRole.AcceptRole)
        custom_cancel_button = QPushButton("Previous Step")
        custom_cancel_button.clicked.connect(self.go_to_previous_index)
        buttonbox.addButton(custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        next_button.setHidden(True)

        def on_utxo_update(sync_status):
            if not self.qt_wallet:
                return
            txos = self.qt_wallet.wallet.get_all_txos(include_not_mine=False)
            check_button.setHidden(bool(txos))
            next_button.setHidden(not bool(txos))
            if txos:
                Message(
                    f"Received {Satoshis(txos[0].txout.value, self.qt_wallet.wallet.network).str_with_unit()}"
                )

        def start_sync():
            if not self.qt_wallet:
                Message("No wallet setup yet", type=MessageType.Error)
                return

            self.qt_wallet.sync()
            check_button.set_enable_signal(self.qtwalletbase.signals.utxos_updated)
            one_time_signal_connection(self.qtwalletbase.signals.utxos_updated, on_utxo_update)

        check_button.clicked.connect(start_sync)

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=False)
        return tutorial_widget

    def create_reset_signer(self) -> QWidget:

        outer_widget = QWidget()
        outer_widget.setLayout(QVBoxLayout())
        outer_widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # width = 300
        # svg_widgets = add_centered_icons(["reset-signer.svg"], widget, max_sizes=[(width, 120)])
        # widget.layout().itemAt(0).widget().setMaximumWidth(width)

        screenshot = ScreenshotsResetSigner(
            title=f"""1. Reset {"each" if self.num_keystores()>1 else "the"} hardware signer."""
        )
        widget.layout().addWidget(screenshot)

        screenshot = ScreenshotsRestoreSigner(
            title=f"""2. Restore {"each" if self.num_keystores()>1 else "the"} hardware signer from the seed backup"""
        )
        widget.layout().addWidget(screenshot)

        buttonbox = QDialogButtonBox()
        custom_yes_button = QPushButton(
            f"Yes, I reset and restored the {self.num_keystores()} hardware signer"
        )
        custom_yes_button.clicked.connect(self.go_to_next_index)
        buttonbox.addButton(custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        custom_cancel_button = QPushButton("Previous Step")
        custom_cancel_button.clicked.connect(self.go_to_previous_index)
        buttonbox.addButton(custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        tutorial_widget = TutorialWidget(self, outer_widget, buttonbox, buttonbox_always_visible=False)

        def callback():
            if not self.qt_wallet:
                return
            balance = self.qt_wallet.wallet.bdkwallet.get_balance().total
            if balance > self.max_test_fund:
                Message(
                    f"Your balance {Satoshis(balance, self.qt_wallet.wallet.network).str_with_unit( )} is greater than a maximally allowed test amount of {Satoshis(self.max_test_fund, self.qt_wallet.wallet.network).str_with_unit()}!\nPlease do the hardware signer reset only  with a lower balance!  (Send some funds out before)",
                    type=MessageType.Warning,
                )

        tutorial_widget.set_callback(callback)

        label = QLabel(
            f"""<html><head/><body>
                  Why? 
                    <ul>
                    <li>The Reset + Send Test  in step { self.get_step_title_number_of(TutorialStep.send)}, together ensure that the seed backup (24 words) are correct. </li>
                    </ul>
                 </body></html>                    
                """.replace(
                "    ", ""
            )
        )
        label.setFont(screenshot.title.font())
        label.setWordWrap(True)
        outer_widget.layout().addWidget(label)
        outer_widget.layout().addItem(QSpacerItem(10, 30))
        outer_widget.layout().addWidget(widget)

        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=False)
        return tutorial_widget

    def create_register_multisig_on_signers(self) -> QWidget:
        def create_register_coldcard_button() -> QPushButton:
            button_register_coldcard_quorum = QPushButton(
                f"""Export file to register the multisig on Coldcard"""
            )
            # button_style = """
            # QPushButton {
            #     padding: 20px 10px; /* Adjust the padding values as needed */
            # }
            # """
            # button_register_quorum.setStyleSheet(button_style)

            def export_wallet_for_coldcard():
                if self.qt_wallet:
                    self.qt_wallet.export_wallet_for_coldcard()

            button_register_coldcard_quorum.clicked.connect(export_wallet_for_coldcard)
            return button_register_coldcard_quorum

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # width = 300
        # svg_widgets = add_centered_icons(["reset-signer.svg"], widget, max_sizes=[(width, 120)])
        # widget.layout().itemAt(0).widget().setMaximumWidth(width)

        groupbox1 = ScreenshotsTutorial()
        groupbox1.title.setText("1. Export wallet descriptor")
        tab = QWidget()
        tab.setLayout(QVBoxLayout())
        add_centered([create_register_coldcard_button()], tab, direction="v")
        groupbox1.sync_tab.addTab(tab, "Coldcard")
        widget.layout().addWidget(groupbox1)

        screenshot = ScreenshotsRegisterMultisig(
            title=f"""2. Import in {"each" if self.num_keystores()>1 else "the"} hardware signer"""
        )
        widget.layout().addWidget(screenshot)

        buttonbox = QDialogButtonBox()
        custom_yes_button = QPushButton(
            f"Yes, I registered the multisig on the {self.num_keystores()} hardware signer"
        )
        custom_yes_button.clicked.connect(self.go_to_next_index)
        buttonbox.addButton(custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        custom_cancel_button = QPushButton("Previous Step")
        custom_cancel_button.clicked.connect(self.go_to_previous_index)
        buttonbox.addButton(custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)

        def callback():
            if not self.qt_wallet:
                return
            balance = self.qt_wallet.wallet.bdkwallet.get_balance().total
            if balance > self.max_test_fund:
                Message(
                    f"Your balance {Satoshis(balance, self.qt_wallet.wallet.network).str_with_unit( )} is greater than a maximally allowed test amount of {Satoshis(self.max_test_fund, self.qt_wallet.wallet.network).str_with_unit()}!\nPlease do the hardware signer reset only  with a lower balance!  (Send some funds out before)",
                    type=MessageType.Warning,
                )

        tutorial_widget.set_callback(callback)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=False)
        return tutorial_widget

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
            send_test_labels.append(" and ".join([f'"{label}"' for label in labels]))

        return send_test_labels

    def tx_text(self, test_number: int) -> str:
        if self.num_keystores() == 1:
            return f"""Send Test"""
        else:

            return f"""Sign with {self.get_send_test_labels()[test_number]}"""

    def fill_tx(self):
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

    def create_send_test(self, test_number=0):

        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(["send.svg"], widget, max_sizes=[(50, 80)])
        widget.layout().itemAt(0).widget().setMaximumWidth(150)

        inner_widget = QWidget()
        inner_widget_layout = QVBoxLayout(inner_widget)
        if self.num_keystores() == 1:

            label = QLabel(
                f"""<html><head/><body><p><span style="font-size: 12pt;">Complete the send test to ensure the hardware signer works!
                    </span></p></body></html>                    
                    """.replace(
                    "    ", ""
                )
            )
            # label.setWordWrap(True)
            inner_widget_layout.addWidget(label)

            # label2 = QLabel(
            #     f"""<html><head/><body><p><span style="font-size: 12pt;">If the transaction confirmed, then the hardware signer and wallet are correctly set up and ready to use for larger amounts. Place the printed seed+descriptor backup in a secure place, where only you have access.</span></p></body></html>
            #         """.replace(
            #         "    ", ""
            #     )
            # )
            # inner_widget_layout.addWidget(label2)
            # label2.setWordWrap(True)
        else:

            label = QLabel(
                f"""<html><head/><body><p><span style="font-size: 12pt;">{self.tx_text(test_number)}</span></p></body></html>""".replace(
                    "    ", ""
                )
            )
            # label.setWordWrap(True)
            inner_widget_layout.addWidget(label)

            # label2 = QLabel(
            #     f"""<html><head/><body><p><span style="font-size: 12pt;">If all transactions confirmed, then the hardware signers and wallet are correctly set up and ready to use for larger amounts. Place each printed seed+descriptor backup in a different secure place, where only you have access.</span></p></body></html>
            #         """.replace(
            #         "    ", ""
            #     )
            # )
            # inner_widget_layout.addWidget(label2)
            # label2.setWordWrap(True)

        widget.layout().addWidget(inner_widget)

        buttonbox = create_button_box(
            self.go_to_next_index,
            self.go_to_previous_index,
            ok_text=f"Next Step",
            cancel_text="Previous Step",
        )

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)
        tutorial_widget.setMinimumHeight(30)

        def callback():
            if not self.qt_wallet:
                return
            logger.debug(f"tutorial callback")

            # compare how many tx were already done , to the current test_number
            def should_offer_skip() -> bool:
                if not spend_txos:
                    return False
                return len(spend_txos) >= test_number + 1

            # offer to skip this step if it was spend from this wallet
            txos = self.qt_wallet.wallet.get_all_txos(include_not_mine=False)
            spend_txos = [txo for txo in txos if txo.is_spent_by_txid]

            if not should_offer_skip():
                return

            if question_dialog(
                text=f"You made {len(spend_txos) } outgoing transactions already. Would you like to skip this spend test?",
                title="Skip spend test?",
                buttons=QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
            ):
                self.go_to_next_index()
                return

            self.fill_tx()

        tutorial_widget.set_callback(callback)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=bool(self.qt_wallet))
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=True)
        tutorial_widget.synchronize_visiblity(tutorial_widget.button_box, set_also_visible=False)
        if self.qt_wallet:
            tutorial_widget.synchronize_visiblity(
                self.qt_wallet.uitx_creator.button_box, set_also_visible=False
            )
        return tutorial_widget

    def open_tx(self, test_number):
        if not self.qt_wallet:
            return

        label = self.tx_text(test_number)

        utxos = self.qt_wallet.wallet.bdkwallet.list_unspent()
        if not utxos:
            Message(
                f"The wallet is not funded. Please go to step {self.get_step_title_number_of(TutorialStep.receive)} and fund the wallet."
            )
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

    def create_distribute_seeds(self):

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

        label_2 = QLabel(widget)
        label_2.setWordWrap(True)

        if self.num_keystores() > 1:
            label_2.setText(
                f"""<html><head/><body><p><span style="font-size: 12pt;">
             <ul>
  <li>Place each seed backup and hardware signer in a secure location, such:</li>
   <ul>
   {''.join([f"<li>Seed backup {i+1} and hardware signer {i+1} should be in location {i+1}  </li>" for i in  range(self.num_keystores())]) if self.num_keystores()>1 else ""}
   </ul>   
   <li>Choose the secure places carefully, considering that you need to go to {self.qtwalletbase.get_mn_tuple()[0]} of the {self.num_keystores()}, to spend from your multisig-wallet.</li>
</ul> 
</span></p></body></html>""",
            )
        else:
            label_2.setText(
                f"""<html><head/><body><p><span style="font-size: 12pt;">
             <ul>
  <li>Store the  seed backup   in a <b>very</b> secure location (like a vault).</li>
   <ul>
      <li>The seed backup (24 words) give total control over the funds.</li>
   </ul>     
  <li>Store the   hardware signer   in secure location.</li>
   </ul>  
</ul> 
</span></p></body></html>""",
            )

        right_widget.layout().addWidget(label_2)

        right_widget.layout().addItem(QSpacerItem(1, 40))

        buttonbox = create_button_box(
            self.go_to_next_index,
            self.go_to_previous_index,
            ok_text="Finish",
            cancel_text="Previous Step",
        )
        buttonbox.buttons()[0].setIcon(QIcon(icon_path("checkmark.png")))

        tutorial_widget = TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)
        tutorial_widget.synchronize_visiblity(self.wallet_tabs, set_also_visible=False)
        tutorial_widget.synchronize_visiblity(self.floating_button_box, set_also_visible=False)

        return tutorial_widget

import enum
import logging
from typing import List

from bitcoin_safe.gui.qt.qt_wallet import QTWallet, QtWalletBase

from ...pdfrecovery import make_and_open_pdf
from ...pythonbdk_types import Recipient
from ...tx import TxUiInfos
from .qr_components.quick_receive import ReceiveGroup
from .spinning_button import SpinningButton
from .step_progress_bar import StepProgressContainer
from .taglist.main import hash_color

logger = logging.getLogger(__name__)

import numpy as np
from PySide2.QtCore import QCoreApplication, QSize, Signal
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...util import Satoshis
from .util import (
    QWIDGETSIZE_MAX,
    Message,
    MessageType,
    add_centered,
    add_centered_icons,
    create_button,
    create_button_box,
    icon_path,
    one_time_signal_connection,
    open_website,
)


def create_buy_coldcard_button(layout):
    button = create_button("Buy a Coldcard\n5% off", icon_path("coldcard-only.svg"), None, layout)
    button.clicked.connect(lambda: open_website("https://store.coinkite.com/promo/8BFF877000C34A86F410"))
    return button


def create_buy_bitbox_button(layout):
    button = create_button("Buy a Bitbox02\nBitcoin Only Edition", icon_path("usb-stick.svg"), None, layout)
    button.clicked.connect(lambda: open_website("https://shiftcrypto.ch/bitbox02/?ref=MOB4dk7gpm"))
    return button


class TutorialSteps(enum.Enum):
    buy = 0
    generate = 1
    import_xpub = 2
    backup_seed = 3
    receive = 4
    reset = 5
    send = 6
    send2 = 7


class WalletSteps(StepProgressContainer):
    signal_on_set_step = Signal(int)  # step

    def __init__(
        self,
        qtwalletbase: QtWalletBase,
        wallet_tabs: QTabWidget,
        max_test_fund=1_000_000,
        qt_wallet: QTWallet = None,
        signal_create_wallet: Signal = None,
    ) -> None:
        self.qtwalletbase = qtwalletbase
        self.qt_wallet = qt_wallet

        labels = [
            "Buy hardware signer",
            "Generate Seed",
            "Import public signer keys",
            "Backup Seed",
            "Receive Test",
            "Reset hardware signer",
        ]
        if self.show_2_send_tests():
            labels += [
                "Send test 1",
                "Send test 2",
            ]
        elif self.num_keystores() == 1:
            labels += ["Send test"]
        else:
            labels += ["Send tests"]

        super().__init__(steps=len(labels))

        self.wallet_tabs = wallet_tabs
        self.max_test_fund = max_test_fund
        self.step_bar.set_labels(labels)
        # self.step_bar.set_step_tooltips(
        #     [
        #         "<font color='red'>This is an important step.</font><br><br><u>Payment information is required.</u><br><br><b>Confirm your submission.</b>",
        #         "<i>Remember to check your details.</i>",
        #         "<u>Payment information is required.</u>",
        #         "<b>Confirm your submission.</b>",
        #     ]
        # )

        self.widgets = [
            self.create_buy_hardware(),
            self.create_generate_seed(),
            self.create_import_xpubs(),
            self.create_backup_seed(),
            self.create_receive_test(),
            self.create_reset_signer(),
            self.create_send_test(),
        ]
        if self.show_2_send_tests():
            self.widgets.append(self.create_send_test(test_number=1))

        # set_custom_widget  from StepProgressContainer
        for i, widget in enumerate(self.widgets):
            self.set_custom_widget(i, widget)

        def next_step_on_apply_changes():
            if not self.isVisible():
                return
            self.go_to_next_step()

        if signal_create_wallet:
            signal_create_wallet.connect(next_step_on_apply_changes)

        if self.qt_wallet:
            if self.qt_wallet.wallet.tutorial_step is None:
                self.setVisible(False)
            else:
                self.set_current_step(self.qt_wallet.wallet.tutorial_step)

    def set_current_step(self, step):
        super().set_current_step(step)
        self.set_visibilities()

    def set_visibilities(self):
        if self.isVisible():
            if self.step_bar.current_step == TutorialSteps.generate.value:
                self.wallet_tabs.setVisible(False)
            elif self.step_bar.current_step == TutorialSteps.backup_seed.value:
                self.wallet_tabs.setVisible(False)
            elif self.step_bar.current_step == TutorialSteps.receive.value:
                self.wallet_tabs.setVisible(False)

    def show_2_send_tests(self) -> bool:
        return self.num_keystores() == 3 and self.qtwalletbase.get_mn_tuple()[0] == 2

    def num_keystores(self):
        return self.qtwalletbase.get_mn_tuple()[1]

    def create_buy_hardware(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(5, 0, 5, 5)  # Left, Top, Right, Bottom margins

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["coldcard-only.svg"] * int(np.ceil(self.num_keystores() / 2))
            + ["usb-stick.svg"] * int(np.floor(self.num_keystores() / 2)),
            widget,
            layout,
            max_sizes=[(60, 80)] * self.num_keystores(),
        )

        label_2 = QLabel(widget)
        label_2.setWordWrap(True)
        label_2.setText(
            f'<html><head/><body><p><span style=" font-size:12pt;">Buy {self.num_keystores()} hardware signer{"s" if self.num_keystores()>1 else ""}</span></p></body></html>',
        )
        layout.addWidget(label_2)

        pushButton_buycoldcard = create_buy_coldcard_button(layout)
        pushButton_buycoldcard.setMaximumWidth(150)

        pushButton_buybitbox = create_buy_bitbox_button(layout)
        pushButton_buybitbox.setMaximumWidth(150)

        outer_layout.addWidget(widget)

        outer_layout.addWidget(
            create_button_box(
                self.go_to_next_step,
                self.go_to_previous_step,
                ok_text="Done",
                cancel_text="Go to Previous Step",
            )
        )

        return outer_widget

    def change_step(self, step):
        self.stacked_widget.setMaximumHeight(QWIDGETSIZE_MAX)
        self.set_current_step(step)
        self.signal_on_set_step.emit(step)

    def go_to_previous_step(self):
        self.change_step(max(self.step_bar.current_step - 1, 0))

    def go_to_next_step(self):
        if self.step_bar.current_step + 1 >= self.step_bar.steps:
            self.setVisible(False)
            # if self.qt_wallet:
            #     for i in range(self.qt_wallet.tabs.count()):
            #         self.qt_wallet.tabs.widget(i).setVisible(True)
            #         self.qt_wallet.tabs.widget(i).update()
            self.wallet_tabs.setVisible(True)

            Message(
                f'Your wallet is now setup. \nPut the {self.num_keystores()} Seed-backup{"s" if  self.num_keystores()> 1 else ""} in {self.num_keystores()} different secure places. ',
                icon=QIcon(icon_path("checkmark.png")).pixmap(QSize(64, 64)),
            )

            return
        self.change_step(min(self.step_bar.current_step + 1, self.step_bar.steps - 1))

    def create_generate_seed(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(5, 0, 5, 5)  # Left, Top, Right, Bottom margins

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["coldcard-dice.svg"] * int(np.ceil(self.num_keystores() / 2))
            + ["usb-stick-dice.svg"] * int(np.floor(self.num_keystores() / 2)),
            widget,
            layout,
            max_sizes=[(60, 80)] * self.num_keystores(),
        )

        label_8 = QLabel(widget)
        label_8.setWordWrap(True)
        label_8.setText(
            QCoreApplication.translate(
                "Form",
                f'<html><head/><body><p><span style=" font-size:12pt;">Generate 24 secret words on {"each" if self.num_keystores()>1 else "the"} hardware signer</span></p></body></html>',
                None,
            )
        )
        layout.addWidget(label_8)

        label_never_share_seed = QLabel(widget)
        label_never_share_seed.setWordWrap(True)
        label_never_share_seed.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Never share the 24 secret words with anyone! </span></p><p><span style=" font-size:12pt;">Never type them into any computer! </span></p><p><span style=" font-size:12pt;">Never make a picture of them!</span></p></body></html>',
                None,
            )
        )
        layout.addWidget(label_never_share_seed)

        outer_layout.addWidget(widget)

        outer_layout.addWidget(
            create_button_box(
                self.go_to_next_step,
                self.go_to_previous_step,
                ok_text="Done",
                cancel_text="Go to Previous Step",
            )
        )

        return outer_widget

    def create_import_xpubs(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(5, 0, 5, 5)  # Left, Top, Right, Bottom margins

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["usb.svg", "camera.svg", "sd-card.svg"],
            widget,
            layout,
            max_sizes=[(50, 50)],
        )
        layout.itemAt(0).widget().setMaximumWidth(250)

        label = QLabel(
            '<html><head/><body><p><span style=" font-size:12pt;">Import the signer information (xPubs)\nto create the wallet descriptor.<br><br>Then you can receive Bitcoin, send Bitcoin, and watch your balances :-)</span></p></body></html>'
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        outer_layout.addWidget(widget)

        # outer_layout.addWidget(
        #     create_button_box(
        #         self.go_to_next_step,
        #         self.go_to_previous_step,
        #         ok_text="Done",
        #         cancel_text="Go to Previous Step",
        #     )
        # )

        def on_step(step):
            if step == TutorialSteps.import_xpub.value:
                self.stacked_widget.setMaximumHeight(80)
                self.wallet_tabs.setVisible(True)

                self.wallet_tabs.setCurrentWidget(self.qtwalletbase.wallet_descriptor_tab)

        self.signal_on_set_step.connect(on_step)

        return outer_widget

    def create_backup_seed(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(5, 0, 5, 5)  # Left, Top, Right, Bottom margins

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["descriptor-backup.svg"],
            widget,
            layout,
            max_sizes=[(100 * self.num_keystores(), 120)],
        )

        label_10 = QLabel(widget)
        label_10.setWordWrap(True)
        label_10.setText(
            f"""<html><head/><body><p><span style=" font-size:12pt;">Write {"each" if self.num_keystores()>1 else "the"} 24-word seed onto the printed pdf. <br><br>
                Do not skip this step!<br><br>This backup is the only way to recover your funds.</p></body></html>"""
        )
        layout.addWidget(label_10)

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

        outer_layout.addWidget(widget)

        button_box = QDialogButtonBox()
        custom_yes_button = QPushButton("Print recovery sheet")
        custom_yes_button.setIcon(QIcon(icon_path("print.svg")))
        custom_yes_button.clicked.connect(do_pdf)
        custom_yes_button.clicked.connect(self.go_to_next_step)
        button_box.addButton(custom_yes_button, QDialogButtonBox.AcceptRole)
        custom_cancel_button = QPushButton("Go to Previous Step")
        custom_cancel_button.clicked.connect(self.go_to_previous_step)
        button_box.addButton(custom_cancel_button, QDialogButtonBox.RejectRole)

        outer_layout.addWidget(button_box)

        return outer_widget

    def create_receive_test(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(5, 0, 5, 5)  # Left, Top, Right, Bottom margins

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 0, 0, 0)  # Left, Top, Right, Bottom margins
        layout.setSpacing(20)

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
            layout.addWidget(quick_receive)
        else:
            add_centered_icons(["receive.svg"], widget, layout, max_sizes=[(50, 80)])
            layout.itemAt(0).widget().setMaximumWidth(150)

        label_10 = QLabel(widget)
        label_10.setWordWrap(True)
        test_amount = (
            f"(less than {Satoshis( self.max_test_fund, self.qt_wallet.wallet.network).str_with_unit()}) "
            if self.qt_wallet
            else ""
        )
        label_10.setText(
            f'<html><head/><body><p><span style=" font-size:12pt;">Receive a small amount {test_amount}to an address of this wallet</span></p></body></html>'
        )
        layout.addWidget(label_10)

        outer_layout.addWidget(widget)

        button_box = QDialogButtonBox()
        next_button = QPushButton("Go to next step")
        next_button.clicked.connect(self.go_to_next_step)
        button_box.addButton(next_button, QDialogButtonBox.AcceptRole)
        check_button = SpinningButton("Check if received")
        button_box.addButton(check_button, QDialogButtonBox.AcceptRole)
        custom_cancel_button = QPushButton("Go to Previous Step")
        custom_cancel_button.clicked.connect(self.go_to_previous_step)
        button_box.addButton(custom_cancel_button, QDialogButtonBox.RejectRole)

        outer_layout.addWidget(button_box)

        next_button.setHidden(True)

        def on_utxo_update(sync_status):
            if not self.qt_wallet:
                return
            balance = self.qt_wallet.wallet.bdkwallet.get_balance().total
            check_button.setHidden(bool(balance))
            next_button.setHidden(not bool(balance))
            if balance:
                Message(f"Received {Satoshis(balance, self.qt_wallet.wallet.network).str_with_unit()}")

        def start_sync():
            if not self.qt_wallet:
                Message("No wallet setup yet", type=MessageType.Error)
                return

            self.qt_wallet.sync()
            check_button.set_enable_signal(self.qtwalletbase.signals.utxos_updated)
            one_time_signal_connection(self.qtwalletbase.signals.utxos_updated, on_utxo_update)

        check_button.clicked.connect(start_sync)

        return outer_widget

    def create_reset_signer(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(5, 0, 5, 5)  # Left, Top, Right, Bottom margins

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        width = 300
        svg_widgets = add_centered_icons(["reset-signer.svg"], widget, layout, max_sizes=[(width, 120)])
        layout.itemAt(0).widget().setMaximumWidth(width)

        label = QLabel(
            f"""<html><head/><body><p><span style=" font-size:12pt;">To make sure the seed backup{"s" if self.num_keystores()>1 else ""} of   step {TutorialSteps.backup_seed.value+1} was correct:
                        <ol>
                            <li>Reset {"each" if self.num_keystores()>1 else "the"} hardware signer, which deletes the seed from it. The wallet should contain only a small amount of Bitcoin.</li>
                            <li>Initialize {"each" if self.num_keystores()>1 else "the"} hardware signer from your seed backup{"s" if self.num_keystores()>1 else ""}  (NEVER type a seed into a computer)</li>
                        </ol>  </span></p></body></html>"""
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        outer_layout.addWidget(widget)

        button_box = QDialogButtonBox()
        custom_yes_button = QPushButton(f"Yes, I reset the {self.num_keystores()} hardware signer")
        custom_yes_button.clicked.connect(self.go_to_next_step)
        button_box.addButton(custom_yes_button, QDialogButtonBox.AcceptRole)
        custom_cancel_button = QPushButton("Go to Previous Step")
        custom_cancel_button.clicked.connect(self.go_to_previous_step)
        button_box.addButton(custom_cancel_button, QDialogButtonBox.RejectRole)
        outer_layout.addWidget(button_box)

        def on_step(step):
            if not self.qt_wallet:
                return
            if step == TutorialSteps.reset.value:
                balance = self.qt_wallet.wallet.bdkwallet.get_balance().total
                if balance > self.max_test_fund:
                    Message(
                        f"Your balance {Satoshis(balance, self.qt_wallet.wallet.network).str_with_unit( )} is greater than a maximally allowed test amount of {Satoshis(self.max_test_fund, self.qt_wallet.wallet.network).str_with_unit()}!\nPlease do the hardware signer reset only  with a lower balance!  (Send some funds out before)",
                        type=MessageType.Warning,
                    )

        self.signal_on_set_step.connect(on_step)

        return outer_widget

    def get_keystore_labels_for_test_tx(self, test_number) -> List[str]:
        m, n = self.qtwalletbase.get_mn_tuple()
        keystore_labels = self.qtwalletbase.get_keystore_labels()
        return [
            keystore_labels[j]
            for j in range(test_number, test_number + m)
            if test_number + m <= len(keystore_labels)
        ]

    def tx_text(self, test_number):
        keystore_labels_for_test_tx = self.get_keystore_labels_for_test_tx(test_number)

        if self.num_keystores() == 1:
            return f"""Send Test"""
        else:
            return f"""Send Test {test_number+1}: Sign with {' and '.join([f'"{label}"' for label in keystore_labels_for_test_tx])}""".replace(
                "    ", ""
            )

    def create_send_test(self, test_number=0):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(5, 0, 5, 5)  # Left, Top, Right, Bottom margins

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(["send.svg"], widget, layout, max_sizes=[(50, 80)])
        layout.itemAt(0).widget().setMaximumWidth(150)

        inner_widget = QWidget()
        inner_widget_layout = QVBoxLayout(inner_widget)
        if self.num_keystores() == 1:

            label = QLabel(
                f"""<html><head/><body><p><span style=" font-size:12pt;">Complete the send test to ensure the hardware signer works!
                    </span></p></body></html>                    
                    """.replace(
                    "    ", ""
                )
            )
            label.setWordWrap(True)
            inner_widget_layout.addWidget(label)

            label2 = QLabel(
                f"""<html><head/><body><p><span style=" font-size:12pt;">If the transaction confirmed, then the hardware signer and wallet are correctly set up and ready to use for larger amounts. Place the printed seed+descriptor backup in a secure place, where only you have access.</span></p></body></html>                    
                    """.replace(
                    "    ", ""
                )
            )
            inner_widget_layout.addWidget(label2)
            label2.setWordWrap(True)
        elif self.show_2_send_tests():
            label = QLabel(self.tx_text(test_number))
            label.setWordWrap(True)
            inner_widget_layout.addWidget(label)
        else:
            label = QLabel(
                f"""<html><head/><body><p><span style=" font-size:12pt;">Complete <font color='red'>all</font> steps to ensure all hardware signers work!
                    </span></p></body></html>                    
                    """.replace(
                    "    ", ""
                )
            )
            label.setWordWrap(True)
            inner_widget_layout.addWidget(label)

            m, n = self.qtwalletbase.get_mn_tuple()

            buttons = []

            # register wallet button
            if n > 1:
                button_register_quorum = QPushButton(f"""Register the multisig on the hardware wallet""")
                button_style = """
                QPushButton {
                    padding: 10px 20px; /* Adjust the padding values as needed */
                }
                """
                button_register_quorum.setStyleSheet(button_style)

                def export_wallet_for_coldcard():
                    if self.qt_wallet:
                        self.qt_wallet.export_wallet_for_coldcard()

                button_register_quorum.clicked.connect(export_wallet_for_coldcard)
                buttons.append(button_register_quorum)

            # send test buttons

            for i in range(n - m + 1):
                keystore_labels_for_test_tx = self.get_keystore_labels_for_test_tx(i)
                button_tx1 = QPushButton(
                    f"""Send Test {i+1}: Send a test amount  to a receive address and sign with   {' and '.join([f'"{label}"' for label in keystore_labels_for_test_tx])}"""
                )
                button_style = """
                QPushButton {
                    padding: 10px 20px; /* Adjust the padding values as needed */
                }
                """
                button_tx1.setStyleSheet(button_style)

                def function_generator(label):
                    def f():
                        self.send_a_tx(label)

                    return f

                button_tx1.clicked.connect(function_generator(self.tx_text(i)))
                buttons.append(button_tx1)

            add_centered(buttons, inner_widget, inner_widget_layout, direction="v")

            label2 = QLabel(
                f"""<html><head/><body><p><span style=" font-size:12pt;">If all transactions confirmed, then the hardware signers and wallet are correctly set up and ready to use for larger amounts. Place each printed seed+descriptor backup in a different secure place, where only you have access.</span></p></body></html>                    
                    """.replace(
                    "    ", ""
                )
            )
            inner_widget_layout.addWidget(label2)
            label2.setWordWrap(True)

        layout.addWidget(inner_widget)
        outer_layout.addWidget(widget)

        def on_utxo_update(*args):
            if not self.isVisible():
                return
            self.go_to_next_step()

        def on_step(step):
            if not self.qt_wallet:
                return
            # I call create_send_test multiple times with different testnumber.
            # Here i have to make sure only the step corresponding to the testnumber is executed
            if step == TutorialSteps.send.value + test_number:
                self.wallet_tabs.setVisible(True)
                self.wallet_tabs.setCurrentWidget(self.qt_wallet.send_tab)

                # set all tabs except the send as hidden
                for i in range(self.qt_wallet.tabs.count()):
                    tab_widget = self.qt_wallet.tabs.widget(i)
                    tab_widget.setHidden(tab_widget != self.qt_wallet.send_tab)
                self.send_a_tx(self.tx_text(test_number))

                # once the tx is broadcasted, then start listening to the sync status update
                one_time_signal_connection(self.qtwalletbase.signals.utxos_updated, on_utxo_update)

        self.signal_on_set_step.connect(on_step)

        return outer_widget

    def send_a_tx(self, label):
        if not self.qt_wallet:
            return

        utxos = self.qt_wallet.wallet.bdkwallet.list_unspent()
        if not utxos:
            Message(
                f'The wallet is not funded. Please go to step {1+self.step_bar.step_labels.index("Receive Test")} and fund the wallet.'
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

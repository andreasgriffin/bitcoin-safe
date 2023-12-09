import logging

from bitcoin_safe.gui.qt.step_progress_bar import StepProgressContainer
from bitcoin_safe.pdfrecovery import make_and_open_pdf

logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from PySide2.QtSvg import QSvgWidget
from .util import (
    add_centered_icons,
    create_button,
    create_button_box,
    icon_path,
)
from PySide2.QtCore import Signal
from ...util import call_call_functions
from .util import create_buy_bitbox_button, create_buy_coldcard_button
import numpy as np

from .util import Message


class Ui_Form(QObject):
    signal_onclick_proceed = Signal()

    def __init__(self, main_tabs) -> None:
        super().__init__()
        self.tab = QWidget()
        self.main_tabs = main_tabs

    def setupUi(self):
        Form = self.tab
        Form.resize(821, 507)
        Form.setMinimumSize(QSize(821, 507))
        self.verticalLayout = QVBoxLayout(Form)

        self.label = self.create_main_label(Form)
        self.verticalLayout.addWidget(self.label)

        self.groupBox_2 = QGroupBox()
        self.horizontalLayout = QHBoxLayout(self.groupBox_2)

        self.groupBox_buy_hardware = self.create_groupbox_buy_hardware()
        self.groupBox_generate_seed = self.create_groupbox_generate_seed()
        self.groupBox_backup_seed = self.create_groupbox_backup_seed()
        self.groupBox_setup_wallet = self.create_groupbox_setup_wallet()

        self.horizontalLayout.addWidget(self.groupBox_buy_hardware)
        self.add_separator_label(self.groupBox_2)
        self.horizontalLayout.addWidget(self.groupBox_generate_seed)
        self.add_separator_label(self.groupBox_2)
        self.horizontalLayout.addWidget(self.groupBox_backup_seed)
        self.add_separator_label(self.groupBox_2)
        self.horizontalLayout.addWidget(self.groupBox_setup_wallet)

        self.verticalLayout.addWidget(self.groupBox_2)

    def create_main_label(self, parent):
        label = QLabel(parent)
        label.setMaximumSize(QSize(16777215, 150))
        label.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><h1 align="center" style=" margin-top:18px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-size:xx-large; font-weight:600;">Storing your bitcoin in a</span></h1><h1 align="center" style=" margin-top:18px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-size:xx-large; font-weight:600;">2 of 3 Multisig</span></h1></body></html>',
                None,
            )
        )
        return label

    def create_groupbox_buy_hardware(self):
        groupBox = QGroupBox()
        groupBox.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        verticalLayout = QVBoxLayout(groupBox)

        label_2 = QLabel(groupBox)
        label_2.setWordWrap(True)
        label_2.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Buy 3 hardware signers</span></p></body></html>',
                None,
            )
        )
        verticalLayout.addWidget(label_2)

        # Assuming add_centered_icons is a predefined function
        add_centered_icons(
            ["coldcard-only.svg"] * 2 + ["usb-stick.svg"],
            groupBox,
            verticalLayout,
            max_sizes=[(60, 80), (60, 80), (60, 50)],
        )

        verticalSpacer = QSpacerItem(20, 83, QSizePolicy.Minimum, QSizePolicy.Expanding)
        verticalLayout.addItem(verticalSpacer)

        pushButton_buybitbox = create_buy_bitbox_button(verticalLayout)

        label_3 = QLabel(groupBox)
        label_3.setWordWrap(True)
        label_3.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p align="center"><span style=" font-size:12pt;">or</span></p></body></html>',
                None,
            )
        )
        verticalLayout.addWidget(label_3)

        pushButton_buycoldcard = create_buy_coldcard_button(verticalLayout)

        verticalSpacer_3 = QSpacerItem(
            20, 84, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        verticalLayout.addItem(verticalSpacer_3)

        return groupBox

    def create_groupbox_generate_seed(self):
        groupBox = QGroupBox()

        groupBox.setTitle(QCoreApplication.translate("Form", "2)", None))
        groupBox.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        verticalLayout = QVBoxLayout(groupBox)

        label_8 = QLabel(groupBox)
        label_8.setWordWrap(True)
        label_8.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Generate 24 secret words on each hardware signer</span></p></body></html>',
                None,
            )
        )
        verticalLayout.addWidget(label_8)

        add_centered_icons(
            ["coldcard-dice.svg"] * 2 + ["usb-stick-dice.svg"],
            groupBox,
            verticalLayout,
            max_sizes=[(60, 80), (60, 80), (60, 50)],
        )

        verticalSpacer_2 = QSpacerItem(
            20, 36, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        verticalLayout.addItem(verticalSpacer_2)

        label_never_share_seed = QLabel(groupBox)
        label_never_share_seed.setWordWrap(True)
        label_never_share_seed.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Never share the 24 secret words with anyone! </span></p><p><span style=" font-size:12pt;">Never type them into any computer! </span></p><p><span style=" font-size:12pt;">Never make a picture of them!</span></p></body></html>',
                None,
            )
        )
        verticalLayout.addWidget(label_never_share_seed)

        verticalSpacer_6 = QSpacerItem(
            20, 38, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        verticalLayout.addItem(verticalSpacer_6)

        return groupBox

    def create_groupbox_backup_seed(self):
        groupBox = QGroupBox()
        groupBox.setTitle(QCoreApplication.translate("Form", "3)", None))

        groupBox.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        verticalLayout = QVBoxLayout(groupBox)

        label_10 = QLabel(groupBox)
        label_10.setWordWrap(True)
        label_10.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Backup each 24 secret words (paper or steel) + the wallet descriptor in a secure location.</span></p></body></html>',
                None,
            )
        )
        verticalLayout.addWidget(label_10)

        add_centered_icons(
            ["2of3backup.svg"], groupBox, verticalLayout, max_sizes=[(160, 150)]
        )

        verticalSpacer_4 = QSpacerItem(
            20, 18, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        verticalLayout.addItem(verticalSpacer_4)

        label_11 = QLabel(groupBox)
        label_11.setWordWrap(True)
        label_11.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Do not skip this step!</span></p><p><span style=" font-size:12pt;">This backup is the only way to recover your funds.</span></p></body></html>',
                None,
            )
        )
        verticalLayout.addWidget(label_11)

        verticalSpacer_7 = QSpacerItem(
            20, 18, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        verticalLayout.addItem(verticalSpacer_7)

        return groupBox

    def create_groupbox_setup_wallet(self):
        groupBox = QGroupBox()
        groupBox.setTitle(QCoreApplication.translate("Form", "4)", None))

        groupBox.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        verticalLayout = QVBoxLayout(groupBox)

        pushButton_proceed = create_button(
            "Create 'Bitcoin Safe' Wallet\nand import all \nhardware signers\n as signers",
            ("usb.svg", "qr-code.svg", "sd-card.svg"),
            groupBox,
            verticalLayout,
            max_sizes=[(40, 40)] * 3,
            button_max_height=None,
        )
        pushButton_proceed.clicked.connect(
            lambda: call_call_functions(
                [self.remove_tab, self.signal_onclick_proceed.emit]
            )
        )  # Assuming call_call_functions is a predefined function
        verticalLayout.addWidget(pushButton_proceed)

        verticalSpacer_5 = QSpacerItem(20, 58, QSizePolicy.Minimum, QSizePolicy.Fixed)
        verticalLayout.addItem(verticalSpacer_5)

        label_14 = QLabel(groupBox)
        label_14.setWordWrap(True)
        label_14.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Then you can receive Bitcoin, send Bitcoin, and watch your balances :-)</span></p></body></html>',
                None,
            )
        )

        verticalLayout.addWidget(label_14)

        verticalSpacer_8 = QSpacerItem(
            20, 57, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        verticalLayout.addItem(verticalSpacer_8)

        return groupBox

    def add_separator_label(self, parent):
        label = QLabel(parent)

        label.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:18pt; font-weight:600;">\u2192</span></p></body></html>',
                None,
            )
        )

        label.setMaximumSize(QSize(20, 16777215))
        self.horizontalLayout.addWidget(label)

    def remove_tab(self):
        index = self.main_tabs.indexOf(self.tab)
        if index >= 0:
            self.main_tabs.removeTab(index)


class WalletSteps(StepProgressContainer):
    signal_done = Signal(int)  # step

    def __init__(
        self, protowallet: "ProtoWallet" = None, wallet: "Wallet" = None
    ) -> None:
        labels = [
            "Buy hardware signer",
            "Generate Seed",
            "Import public signer keys",
            "Backup Seed",
            "Receive Test",
            "Reset hardware signer",
            "Send Test",
        ]

        super().__init__(steps=len(labels))
        self.wallet = wallet
        self.protowallet = protowallet
        self.step_bar.set_step_labels(labels)
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
        for i, widget in enumerate(self.widgets):
            self.set_custom_widget(i + 1, widget)

    def num_keystores(self):
        if self.wallet:
            return len(self.wallet.keystores)
        if self.protowallet:
            return len(self.protowallet.keystores)

        return 0

    def create_buy_hardware(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["coldcard-only.svg"]
            + list(
                np.random.choice(
                    ["coldcard-only.svg", "usb-stick.svg"], self.num_keystores() - 1
                )
            ),
            widget,
            layout,
            max_sizes=[(60, 80), (60, 80), (60, 50)],
        )

        label_2 = QLabel(widget)
        label_2.setWordWrap(True)
        label_2.setText(
            QCoreApplication.translate(
                "Form",
                f'<html><head/><body><p><span style=" font-size:12pt;">Buy {self.num_keystores()} hardware signer{"s" if self.num_keystores()>1 else ""}</span></p></body></html>',
                None,
            )
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

    def go_to_previous_step(self):
        self.set_current_step(max(self.step_bar.current_step - 1, 1))

    def go_to_next_step(self):
        self.signal_done.emit(self.step_bar.current_step)
        self.set_current_step(min(self.step_bar.current_step + 1, self.step_bar.steps))

    def create_generate_seed(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["coldcard-dice.svg"]
            + list(
                np.random.choice(
                    ["coldcard-dice.svg", "usb-stick-dice.svg"],
                    self.num_keystores() - 1,
                )
            ),
            widget,
            layout,
            max_sizes=[(60, 80), (60, 80), (60, 50)],
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

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(
            ["usb.svg", "qr-code.svg", "sd-card.svg"],
            widget,
            layout,
            max_sizes=[(50, 80)],
        )

        label = QLabel(
            '<html><head/><body><p><span style=" font-size:12pt;">Import the signer information (xPubs)\nto create the wallet descriptor.</span></p></body></html>'
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        label_14 = QLabel(
            '<html><head/><body><p><span style=" font-size:12pt;">Then you can receive Bitcoin, send Bitcoin, and watch your balances :-)</span></p></body></html>'
        )
        label_14.setWordWrap(True)
        layout.addWidget(label_14)

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

    def create_backup_seed(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        if self.num_keystores() > 1:
            add_centered_icons(
                ["2of3backup.svg"], widget, layout, max_sizes=[(200, 120)]
            )
        else:
            add_centered_icons(
                ["seed-plate.svg"], widget, layout, max_sizes=[(100, 120)]
            )

        label_10 = QLabel(widget)
        label_10.setWordWrap(True)
        label_10.setText(
            QCoreApplication.translate(
                "Form",
                f'<html><head/><body><p><span style=" font-size:12pt;">Backup {"each" if self.num_keystores()>1 else "the"} 24-word seed onto paper or steel + the wallet descriptor in a secure location.</span></p></body></html>',
                None,
            )
        )
        layout.addWidget(label_10)

        def do_pdf():
            if not self.wallet:
                Message("Please complete the previous steps.").show_message()
                return
            make_and_open_pdf(self.wallet)

        button = create_button(
            "Print the descriptor", icon_path("pdf-file.svg"), widget, layout
        )
        button.setMaximumWidth(150)
        button.clicked.connect(do_pdf)

        label_11 = QLabel(widget)
        label_11.setWordWrap(True)
        label_11.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Do not skip this step!</span></p><p><span style=" font-size:12pt;">This backup is the only way to recover your funds.</span></p></body></html>',
                None,
            )
        )
        layout.addWidget(label_11)

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

    def create_receive_test(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(["receive.svg"], widget, layout, max_sizes=[(50, 80)])
        layout.itemAt(0).widget().setMaximumWidth(150)

        label_10 = QLabel(widget)
        label_10.setWordWrap(True)
        label_10.setText(
            QCoreApplication.translate(
                "Form",
                f'<html><head/><body><p><span style=" font-size:12pt;">Receive a small amount to an address of this wallet</span></p></body></html>',
                None,
            )
        )
        layout.addWidget(label_10)

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

    def create_reset_signer(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        svg_widgets = add_centered_icons(
            ["seed-plate.svg"], widget, layout, max_sizes=[(50, 80)]
        )
        layout.itemAt(0).widget().setMaximumWidth(150)

        label = QLabel(
            """<html><head/><body><p><span style=" font-size:12pt;">To make sure the seed backup of the previous step was correct, go to you hardware wallet 
                        <ol>
                            <li>Reset the hardware signer, which deletes the seed from it. </li>
                            <li>Initialize the hardware signer from your seed backup  (NEVER type a seed into a computer)</li>
                        </ol>  </span></p></body></html>"""
        )
        label.setWordWrap(True)
        layout.addWidget(label)

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

    def create_send_test(self):
        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        add_centered_icons(["send.svg"], widget, layout, max_sizes=[(50, 80)])
        layout.itemAt(0).widget().setMaximumWidth(150)

        label = QLabel(
            '<html><head/><body><p><span style=" font-size:12pt;">Send the test amount of the wallet from to another addres in the wallet. If this new transaction is confirmed then the hardware signer and wallet are correctly set up and ready to use for larger amounts.</span></p></body></html>'
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        outer_layout.addWidget(widget)

        def on_done():
            self.signal_done.emit(self.step_bar.current_step)
            self.setVisible(False)

        outer_layout.addWidget(
            create_button_box(
                on_done,
                self.go_to_previous_step,
                ok_text="Done! Close Tutorial",
                cancel_text="Go to Previous Step",
            )
        )

        return outer_widget

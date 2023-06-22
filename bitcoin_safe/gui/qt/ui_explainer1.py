import logging

logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from PySide2.QtSvg import QSvgWidget
from .util import (
    icon_path,
    center_in_widget,
    qresize,
    add_tab_to_tabs,
    read_QIcon,
    add_centered,
    add_centered_icons,
    create_button,
)
from PySide2.QtCore import Signal
from ...util import call_call_functions


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
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QLabel(Form)
        self.label.setObjectName("label")
        self.label.setMaximumSize(QSize(16777215, 150))

        self.verticalLayout.addWidget(self.label)

        self.groupBox_2 = QGroupBox(Form)
        self.groupBox_2.setObjectName("groupBox_2")
        self.horizontalLayout = QHBoxLayout(self.groupBox_2)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.groupBox_3 = QGroupBox(self.groupBox_2)
        self.groupBox_3.setObjectName("groupBox_3")
        sizePolicy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.groupBox_3.sizePolicy().hasHeightForWidth())
        self.groupBox_3.setSizePolicy(sizePolicy)
        self.verticalLayout_2 = QVBoxLayout(self.groupBox_3)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.label_2 = QLabel(self.groupBox_3)
        self.label_2.setObjectName("label_2")
        self.label_2.setWordWrap(True)

        # add_centered_icons(["coldcard-only.svg"]*3, self.groupBox_3, self.verticalLayout_2)
        add_centered_icons(
            ["coldcard-only.svg"] * 2 + ["usb-stick.svg"],
            self.groupBox_3,
            self.verticalLayout_2,
            max_sizes=[(60, 80), (60, 80), (60, 50)],
        )

        self.verticalLayout_2.addWidget(self.label_2)

        self.verticalSpacer = QSpacerItem(
            20, 83, QSizePolicy.Minimum, QSizePolicy.Expanding
        )

        self.verticalLayout_2.addItem(self.verticalSpacer)

        self.pushButton_buybitbox = QPushButton(self.groupBox_3)
        self.pushButton_buybitbox.setObjectName("pushButton_buybitbox")

        self.verticalLayout_2.addWidget(self.pushButton_buybitbox)

        self.label_3 = QLabel(self.groupBox_3)
        self.label_3.setObjectName("label_3")
        self.label_3.setWordWrap(True)

        self.verticalLayout_2.addWidget(self.label_3)

        self.pushButton_buycoldcard = QPushButton(self.groupBox_3)
        self.pushButton_buycoldcard.setObjectName("pushButton_buycoldcard")

        self.verticalLayout_2.addWidget(self.pushButton_buycoldcard)

        self.verticalSpacer_3 = QSpacerItem(
            20, 84, QSizePolicy.Minimum, QSizePolicy.Expanding
        )

        self.verticalLayout_2.addItem(self.verticalSpacer_3)

        self.horizontalLayout.addWidget(self.groupBox_3)

        self.label_6 = QLabel(self.groupBox_2)
        self.label_6.setObjectName("label_6")
        self.label_6.setMaximumSize(QSize(20, 16777215))

        self.horizontalLayout.addWidget(self.label_6)

        self.groupBox_4 = QGroupBox(self.groupBox_2)
        self.groupBox_4.setObjectName("groupBox_4")
        sizePolicy.setHeightForWidth(self.groupBox_4.sizePolicy().hasHeightForWidth())
        self.groupBox_4.setSizePolicy(sizePolicy)
        self.verticalLayout_3 = QVBoxLayout(self.groupBox_4)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.label_8 = QLabel(self.groupBox_4)
        self.label_8.setObjectName("label_8")
        self.label_8.setWordWrap(True)

        add_centered_icons(
            ["coldcard-dice.svg"] * 2 + ["usb-stick-dice.svg"],
            self.groupBox_4,
            self.verticalLayout_3,
            max_sizes=[(60, 80), (60, 80), (60, 50)],
        )
        # add_centered_icons(["coldcard-dice.svg"]*3, self.groupBox_4, self.verticalLayout_3)

        self.verticalLayout_3.addWidget(self.label_8)

        self.verticalSpacer_2 = QSpacerItem(
            20, 36, QSizePolicy.Minimum, QSizePolicy.Expanding
        )

        self.verticalLayout_3.addItem(self.verticalSpacer_2)

        self.label_9 = QLabel(self.groupBox_4)
        self.label_9.setObjectName("label_9")
        self.label_9.setWordWrap(True)

        self.verticalLayout_3.addWidget(self.label_9)

        self.verticalSpacer_6 = QSpacerItem(
            20, 38, QSizePolicy.Minimum, QSizePolicy.Expanding
        )

        self.verticalLayout_3.addItem(self.verticalSpacer_6)

        self.horizontalLayout.addWidget(self.groupBox_4)

        self.label_12 = QLabel(self.groupBox_2)
        self.label_12.setObjectName("label_12")
        self.label_12.setMaximumSize(QSize(20, 16777215))

        self.horizontalLayout.addWidget(self.label_12)

        self.groupBox_5 = QGroupBox(self.groupBox_2)
        self.groupBox_5.setObjectName("groupBox_5")
        sizePolicy.setHeightForWidth(self.groupBox_5.sizePolicy().hasHeightForWidth())
        self.groupBox_5.setSizePolicy(sizePolicy)
        self.verticalLayout_4 = QVBoxLayout(self.groupBox_5)
        self.verticalLayout_4.setObjectName("verticalLayout_4")
        self.label_10 = QLabel(self.groupBox_5)
        self.label_10.setObjectName("label_10")
        self.label_10.setWordWrap(True)

        add_centered_icons(
            ["seed-plate.svg"] * 3,
            self.groupBox_5,
            self.verticalLayout_4,
            max_sizes=[(50, 80)],
        )
        add_centered_icons(
            ["descriptor3.svg"],
            self.groupBox_5,
            self.verticalLayout_4,
            max_sizes=(200, 65),
        )

        self.verticalLayout_4.addWidget(self.label_10)

        self.verticalSpacer_4 = QSpacerItem(
            20, 18, QSizePolicy.Minimum, QSizePolicy.Expanding
        )

        self.verticalLayout_4.addItem(self.verticalSpacer_4)

        self.label_11 = QLabel(self.groupBox_5)
        self.label_11.setObjectName("label_11")
        self.label_11.setWordWrap(True)

        self.verticalLayout_4.addWidget(self.label_11)

        self.verticalSpacer_7 = QSpacerItem(
            20, 18, QSizePolicy.Minimum, QSizePolicy.Expanding
        )

        self.verticalLayout_4.addItem(self.verticalSpacer_7)

        self.horizontalLayout.addWidget(self.groupBox_5)

        self.label_15 = QLabel(self.groupBox_2)
        self.label_15.setObjectName("label_15")
        self.label_15.setMaximumSize(QSize(20, 16777215))

        self.horizontalLayout.addWidget(self.label_15)

        self.groupBox_6 = QGroupBox(self.groupBox_2)
        self.groupBox_6.setObjectName("groupBox_6")
        sizePolicy.setHeightForWidth(self.groupBox_6.sizePolicy().hasHeightForWidth())
        self.groupBox_6.setSizePolicy(sizePolicy)
        self.verticalLayout_5 = QVBoxLayout(self.groupBox_6)
        self.verticalLayout_5.setObjectName("verticalLayout_5")

        self.pushButton_proceed = create_button(
            "Create 'Bitcoin Safe' Wallet\nand import all \nhardware wallets\n as signers",
            ("usb.svg", "qr-code.svg", "sd-card.svg"),
            self.groupBox_6,
            self.verticalLayout_5,
            max_sizes=[(40, 40)] * 3,
            button_max_height=None,
        )
        self.verticalSpacer_5 = QSpacerItem(
            20, 58, QSizePolicy.Minimum, QSizePolicy.Fixed
        )

        self.verticalLayout_5.addItem(self.verticalSpacer_5)

        self.label_14 = QLabel(self.groupBox_6)
        self.label_14.setObjectName("label_14")
        self.label_14.setWordWrap(True)

        self.verticalLayout_5.addWidget(self.label_14)

        self.verticalSpacer_8 = QSpacerItem(
            20, 57, QSizePolicy.Minimum, QSizePolicy.Expanding
        )

        self.verticalLayout_5.addItem(self.verticalSpacer_8)

        self.horizontalLayout.addWidget(self.groupBox_6)

        self.verticalLayout.addWidget(self.groupBox_2)

        # connect signals
        self.pushButton_proceed.clicked.connect(
            lambda: call_call_functions(
                [self.remove_tab, self.signal_onclick_proceed.emit]
            )
        )

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)

    # setupUi

    def remove_tab(self):
        index = self.main_tabs.indexOf(self.tab)
        if index >= 0:
            self.main_tabs.removeTab(index)

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", "Form", None))
        self.label.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><h1 align="center" style=" margin-top:18px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-size:xx-large; font-weight:600;">Storing your bitcoin in a</span></h1><h1 align="center" style=" margin-top:18px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-size:xx-large; font-weight:600;">2 of 3 Multisig</span></h1></body></html>',
                None,
            )
        )
        self.groupBox_2.setTitle("")
        self.groupBox_3.setTitle(QCoreApplication.translate("Form", "1)", None))
        self.label_2.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Buy 3 hardware wallets</span></p></body></html>',
                None,
            )
        )
        self.pushButton_buybitbox.setText(
            QCoreApplication.translate("Form", "Buy a Bitbox02", None)
        )
        self.label_3.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p align="center"><span style=" font-size:12pt;">or</span></p></body></html>',
                None,
            )
        )
        self.pushButton_buycoldcard.setText(
            QCoreApplication.translate("Form", "Buy a Coldcard", None)
        )
        self.label_6.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:18pt; font-weight:600;">\u2192</span></p></body></html>',
                None,
            )
        )
        self.groupBox_4.setTitle(QCoreApplication.translate("Form", "2)", None))
        self.label_8.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Generate 24 secret words on each hardware wallet</span></p></body></html>',
                None,
            )
        )
        self.label_9.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Never share the 24 secret words with anyone! </span></p><p><span style=" font-size:12pt;">Never type them into any computer! </span></p><p><span style=" font-size:12pt;">Never make a picture of them!</span></p></body></html>',
                None,
            )
        )
        self.label_12.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:18pt; font-weight:600;">\u2192</span></p></body></html>',
                None,
            )
        )
        self.groupBox_5.setTitle(QCoreApplication.translate("Form", "3)", None))
        self.label_10.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Backup each 24 secret words (paper or steel) + the wallet descriptor in a secure location.</span></p></body></html>',
                None,
            )
        )
        self.label_11.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Do not skip this step!</span></p><p><span style=" font-size:12pt;">This backup is the only way to recover your funds.</span></p></body></html>',
                None,
            )
        )
        self.label_15.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:18pt; font-weight:600;">\u2192</span></p></body></html>',
                None,
            )
        )
        self.groupBox_6.setTitle(QCoreApplication.translate("Form", "4)", None))

        self.label_14.setText(
            QCoreApplication.translate(
                "Form",
                '<html><head/><body><p><span style=" font-size:12pt;">Then you can receive Bitcoin, send Bitcoin, and watch your balances :-)</span></p></body></html>',
                None,
            )
        )

    # retranslateUi

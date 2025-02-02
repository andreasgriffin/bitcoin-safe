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

from bdkpython import Network
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget
from bitcoin_safe.gui.qt.wallet_list import RecentlyOpenedWalletsGroup
from bitcoin_safe.html_utils import html_f
from bitcoin_safe.signals import Signals
from bitcoin_safe.typestubs import TypedPyQtSignal, TypedPyQtSignalNo

from .util import read_QIcon, svg_widgets_hardware_signers

logger = logging.getLogger(__name__)


class NewWalletWelcomeScreen(QWidget):
    signal_onclick_multisig_signature: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_onclick_single_signature: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_onclick_custom_signature: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_remove_me: TypedPyQtSignal[QWidget] = pyqtSignal(QWidget)  # type: ignore

    def __init__(
        self,
        network: Network,
        signals: Signals,
        signal_recently_open_wallet_changed: TypedPyQtSignal,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setVisible(False)
        self.signals = signals
        self.signal_recently_open_wallet_changed = signal_recently_open_wallet_changed

        self.name = "New wallet tab"
        self.network = network

        self.create_ui()

        self.pushButton_multisig.clicked.connect(self.on_pushButton_multisig)
        self.pushButton_singlesig.clicked.connect(self.on_pushButton_singlesig)
        self.pushButton_custom_wallet.clicked.connect(self.on_pushButton_custom_wallet)
        logger.debug(f"initialized welcome_screen = {self.__class__.__name__}")

    def remove_me(self):
        self.signal_remove_me.emit(self)

    def on_pushButton_multisig(self):
        self.signal_onclick_multisig_signature.emit()
        self.signal_remove_me.emit(self)

    def on_pushButton_singlesig(self):
        self.signal_onclick_single_signature.emit()
        self.signal_remove_me.emit(self)

    def on_pushButton_custom_wallet(self):
        self.signal_onclick_custom_signature.emit()
        self.signal_remove_me.emit(self)

    def add_new_wallet_welcome_tab(self, main_tabs: DataTabWidget[object]) -> None:
        main_tabs.add_tab(
            tab=self,
            icon=read_QIcon("file.png"),
            description=self.tr("Create new wallet"),
            focus=True,
            data=self,
        )

    def create_ui(self) -> None:
        svg_max_height = 70
        svg_max_width = 60
        self._layout = QHBoxLayout(self)

        self.groupbox_recently_opened_wallets = RecentlyOpenedWalletsGroup(
            signal_open_wallet=self.signals.open_wallet,
            signal_recently_open_wallet_changed=self.signal_recently_open_wallet_changed,
        )
        self._layout.addWidget(self.groupbox_recently_opened_wallets)

        self.groupBox_singlesig = QGroupBox(self)
        self.verticalLayout = QVBoxLayout(self.groupBox_singlesig)
        self.label_singlesig = QLabel(self.groupBox_singlesig)
        # font = QFont()
        # font.setPointSize(11)
        # self.label_singlesig.setFont(font)
        self.label_singlesig.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_singlesig)

        self.groupBox_1signingdevice = QGroupBox(self.groupBox_singlesig)
        self.groupBox_1signingdevice.setEnabled(True)
        self.horizontalLayout_4 = QHBoxLayout(self.groupBox_1signingdevice)

        svg_widgets = svg_widgets_hardware_signers(
            1, parent=self.groupBox_1signingdevice, max_height=svg_max_height, max_width=svg_max_width
        )
        for svg_widget in svg_widgets:
            self.horizontalLayout_4.addWidget(svg_widget)

        # set size of groupbox according to svg
        self.groupBox_1signingdevice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.verticalLayout.addWidget(self.groupBox_1signingdevice)

        self.pushButton_singlesig = QPushButton(self.groupBox_singlesig)

        self.verticalLayout.addWidget(self.pushButton_singlesig)

        self._layout.addWidget(self.groupBox_singlesig)

        self.groupBox_multisig = QGroupBox(self)
        self.verticalLayout_multisig = QVBoxLayout(self.groupBox_multisig)
        self.label_multisig = QLabel(self.groupBox_multisig)
        # font1 = QFont()
        # font1.setFamily(u"Noto Sans")
        # # font1.setPointSize(11)
        # font1.setBold(False)
        # font1.setItalic(False)
        # font1.setWeight(50)
        # self.label_multisig.setFont(font1)
        self.label_multisig.setWordWrap(True)

        self.verticalLayout_multisig.addWidget(self.label_multisig)

        self.groupBox_3signingdevices = QGroupBox(self.groupBox_multisig)
        self.groupBox_3signingdevices.setEnabled(True)
        self.groupBox_3signingdevices_layout = QHBoxLayout(self.groupBox_3signingdevices)

        svg_widgets = svg_widgets_hardware_signers(
            3, parent=self.groupBox_3signingdevices, max_height=svg_max_height, max_width=svg_max_width
        )
        for i, svg_widget in enumerate(svg_widgets):
            self.groupBox_3signingdevices_layout.addWidget(svg_widget)

        self.verticalLayout_multisig.addWidget(self.groupBox_3signingdevices)
        # set size of groupbox according to svg
        self.groupBox_3signingdevices.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.pushButton_multisig = QPushButton(self.groupBox_multisig)

        self.verticalLayout_multisig.addWidget(self.pushButton_multisig)

        self._layout.addWidget(self.groupBox_multisig)

        self.groupBox_3 = QGroupBox(self)
        self.verticalLayout_2 = QVBoxLayout(self.groupBox_3)
        self.label_custom = QLabel(self.groupBox_3)
        # self.label_custom.setFont(font)
        self.label_custom.setWordWrap(True)

        self.verticalLayout_2.addWidget(self.label_custom)

        self.pushButton_custom_wallet = QPushButton(self.groupBox_3)

        self.verticalLayout_2.addWidget(self.pushButton_custom_wallet)

        self._layout.addWidget(self.groupBox_3)

        self.label_singlesig.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.label_multisig.setAlignment(Qt.AlignmentFlag.AlignTop)
        # self.groupBox_3.setTitle(QCoreApplication.translate("Form", u"Custom", None))
        self.label_custom.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.updateUi()
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        self.label_singlesig.setText(
            f"""<h1>{self.tr('Single Signature Wallet')}</h1>
<ul>
<li>{self.tr('Best for medium-sized funds')}</li>
</ul>             
<p><b>{self.tr('Pros:')}</b></p>
<ul>
<li>{self.tr('1 seed (24 secret words) is all you need to access your funds')}</li>
<li>{self.tr('1 secure location to store the seed backup (on paper or steel) is needed')}</li>
</ul>
<p><b>{self.tr('Cons:')}</b></p>
<ul>
<li>{self.tr('If you get tricked into giving hackers your seed, your Bitcoin will be stolen immediately')}</li>
</ul>""",
        )
        self.groupBox_1signingdevice.setTitle(self.tr("1 signing devices"))
        self.pushButton_singlesig.setText(self.tr("Choose Single Signature"))
        self.label_multisig.setText(
            f"""<h1>{self.tr('2 of 3 Multi-Signature Wal')}let</h1>
<ul>
<li>{self.tr('Best for large funds')}</li>
</ul>             
<p><b>{self.tr('Pros:')}</b></p>
<ul>
<li>{self.tr('If 1 seed was lost or stolen, all the funds can be transferred to a new wallet with the 2 remaining seeds + wallet descriptor (QR-code)')}</li>
</ul>
<p><b>{self.tr('Cons:')}</b></p>
<ul>
<li>{self.tr('3 secure locations (each with 1 seed backup   + wallet descriptor   are needed)')}</li>
<li>{self.tr('The wallet descriptor (QR-code) is necessary to recover the wallet')}</li>
</ul>
""",
        )
        self.groupBox_3signingdevices.setTitle(self.tr("3 signing devices"))
        self.pushButton_multisig.setText(self.tr("Choose Multi-Signature"))
        self.label_custom.setText(
            html_f(
                f"""<h1>{self.tr('Custom or restore existing Wallet')}</h1>
                <p><b>{self.tr('Pros:')}</b></p><p>{self.tr('Customize the wallet to your needs')}</p>
                <p><b>{self.tr('Cons:')}</b></p><p>{self.tr('Less support material online in case of recovery')}</p>""",
                add_html_and_body=True,
            )
        )
        self.pushButton_custom_wallet.setText(self.tr("Create custom wallet"))

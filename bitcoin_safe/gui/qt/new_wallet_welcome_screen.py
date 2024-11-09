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

from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget
from bitcoin_safe.html_utils import html_f
from bitcoin_safe.signals import Signals

logger = logging.getLogger(__name__)

from bdkpython import Network
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...util import call_call_functions
from .util import add_centered_icons, icon_path, qresize, read_QIcon


class NewWalletWelcomeScreen(QObject):
    signal_onclick_multisig_signature = pyqtSignal()
    signal_onclick_single_signature = pyqtSignal()
    signal_onclick_custom_signature = pyqtSignal()

    def __init__(self, main_tabs: DataTabWidget[object], network: Network, signals: Signals) -> None:
        super().__init__()
        self.main_tabs = main_tabs
        self.signals = signals

        self.name = "New wallet tab"
        self.network = network

        self.create_ui()

        self.pushButton_multisig.clicked.connect(
            lambda: call_call_functions([self.signal_onclick_multisig_signature.emit, self.remove_tab])
        )
        self.pushButton_singlesig.clicked.connect(
            lambda: call_call_functions([self.signal_onclick_single_signature.emit, self.remove_tab])
        )
        self.pushButton_custom_wallet.clicked.connect(
            lambda: call_call_functions([self.signal_onclick_custom_signature.emit, self.remove_tab])
        )
        logger.debug(f"initialized welcome_screen = {self}")

    def add_new_wallet_welcome_tab(self) -> None:
        self.main_tabs.add_tab(
            tab=self.tab,
            icon=read_QIcon("file.png"),
            description=self.tr("Create new wallet"),
            focus=True,
            data=self,
        )

    def create_ui(self) -> None:
        self.tab = QWidget()
        self.horizontalLayout_2 = QHBoxLayout(self.tab)
        self.groupBox_singlesig = QGroupBox(self.tab)
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

        self.svg_widget = QSvgWidget(icon_path("coldcard-only.svg"))
        self.svg_widget.setMinimumSize(qresize(self.svg_widget.sizeHint(), (60, 80)))
        self.svg_widget.setMaximumSize(qresize(self.svg_widget.sizeHint(), (60, 80)))
        self.horizontalLayout_4.addWidget(self.svg_widget)

        # set size of groupbox according to svg
        self.groupBox_1signingdevice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.verticalLayout.addWidget(self.groupBox_1signingdevice)

        self.pushButton_singlesig = QPushButton(self.groupBox_singlesig)

        self.verticalLayout.addWidget(self.pushButton_singlesig)

        self.horizontalLayout_2.addWidget(self.groupBox_singlesig)

        self.groupBox_multisig = QGroupBox(self.tab)
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

        add_centered_icons(
            ["coldcard-only.svg"] * 2 + ["bitbox02.svg"],
            self.groupBox_3signingdevices_layout,
            max_sizes=[(60, 80), (60, 80), (60, 50)],
        )

        self.verticalLayout_multisig.addWidget(self.groupBox_3signingdevices)
        # set size of groupbox according to svg
        self.groupBox_3signingdevices.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.pushButton_multisig = QPushButton(self.groupBox_multisig)

        self.verticalLayout_multisig.addWidget(self.pushButton_multisig)

        self.horizontalLayout_2.addWidget(self.groupBox_multisig)

        self.groupBox_3 = QGroupBox(self.tab)
        self.verticalLayout_2 = QVBoxLayout(self.groupBox_3)
        self.label_custom = QLabel(self.groupBox_3)
        # self.label_custom.setFont(font)
        self.label_custom.setWordWrap(True)

        self.verticalLayout_2.addWidget(self.label_custom)

        self.pushButton_custom_wallet = QPushButton(self.groupBox_3)

        self.verticalLayout_2.addWidget(self.pushButton_custom_wallet)

        self.horizontalLayout_2.addWidget(self.groupBox_3)

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

    def remove_tab(self) -> None:
        index = self.main_tabs.indexOf(self.tab)
        if index >= 0 and self.main_tabs.count() > 1:
            self.main_tabs.removeTab(index)

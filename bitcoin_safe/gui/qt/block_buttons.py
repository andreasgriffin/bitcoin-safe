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

logger = logging.getLogger(__name__)

import enum
from typing import Callable, List

import bdkpython as bdk
from PyQt6.QtCore import QLocale, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout

from bitcoin_safe.config import UserConfig
from bitcoin_safe.util import block_explorer_URL_of_projected_block, unit_fee_str

from ...html_utils import html_f
from ...mempool import MempoolData, fee_to_color, mempoolFeeColors
from .invisible_scroll_area import InvisibleScrollArea
from .util import center_in_widget, open_website


def format_block_number(block_number) -> str:
    return QLocale().toString(int(block_number))


class BlockType(enum.Enum):
    projected = enum.auto()
    confirmed = enum.auto()
    unconfirmed = enum.auto()


class BaseBlockLabel(QLabel):
    def __init__(self, network: bdk.Network, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.network = network

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setHidden(not text)

    def setText(self, s: str | None) -> None:
        self.setHidden(not s)
        return super().setText(s)


class LabelTitle(BaseBlockLabel):
    def set(self, text: str, block_type: BlockType) -> None:
        self.setText(html_f(text, color="white" if block_type else "black", size="16px"))


class LabelApproximateMedianFee(BaseBlockLabel):
    def set(self, median_fee: float, block_type: BlockType) -> None:
        s = f"~{int(median_fee)} {unit_fee_str(self.network)}"

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelExactMedianFee(BaseBlockLabel):
    def set(self, median_fee: float, block_type: BlockType) -> None:
        s = f"{round(median_fee, 1)} {unit_fee_str(self.network)}"

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelNumberConfirmations(BaseBlockLabel):
    def set(self, i: int, block_type: BlockType) -> None:
        s = f"{i} Confirmation{'s' if i>1 else ''}"

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelBlockHeight(BaseBlockLabel):
    def set(self, i: int, block_type: BlockType) -> None:
        s = f"{round(i)}. Block"

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelFeeRange(BaseBlockLabel):
    def set(self, min_fee: float, max_fee: float) -> None:
        s = f"{int(min_fee)} - {int(max_fee)} {unit_fee_str(self.network)}"

        self.setText(html_f(s, color="#eee002", size="10px"))


class LabelTimeEstimation(BaseBlockLabel):
    def set(self, block_number: int, block_type: BlockType) -> None:
        if block_number < 6:
            s = self.tr("~in {t} min").format(t=(block_number) * 10)
        else:
            s = self.tr("~in {t} hours").format(t=round((block_number) / 6))

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelExplorer(BaseBlockLabel):
    def set(self, block_type: BlockType) -> None:
        s = "visit<br>mempool.space"
        self.setText(html_f(s, color="white" if block_type else "black", size="10px"))


class BlockButton(QPushButton):
    def __init__(self, network: bdk.Network, size=100, parent=None) -> None:
        super().__init__(parent=parent)

        # Create labels for each text line

        self.label_approximate_median_fee = LabelApproximateMedianFee(network)
        self.label_exact_median_fee = LabelExactMedianFee(network)
        self.label_number_confirmations = LabelNumberConfirmations(network)
        self.label_block_height = LabelBlockHeight(network)
        self.label_fee_range = LabelFeeRange(network)
        self.label_title = LabelTitle(network)
        self.label_time_estimation = LabelTimeEstimation(network)
        self.label_explorer = LabelExplorer(network)

        # define the order:
        self.labels = [
            self.label_approximate_median_fee,
            self.label_exact_median_fee,
            self.label_number_confirmations,
            self.label_block_height,
            self.label_fee_range,
            self.label_title,
            self.label_time_estimation,
            self.label_explorer,
        ]

        layout = center_in_widget(self.labels, self, direction="v")
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # Ensure buttons are square
        self.setMinimumHeight(size)
        self.setMinimumWidth(size)

    def clear_labels(self) -> None:
        for label in self.labels:
            label.setText("")

    def _set_background_gradient(self, color_top: str, color_bottom: str) -> None:
        # Set the stylesheet for the QPushButton
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {color_bottom},
                                    stop:1 {color_top});
                color: white; /* Change this to set the text color */
            }}
        """
        )

    def set_background_gradient(self, min_fee: float, max_fee: float, block_type: BlockType) -> None:
        self.block_type = block_type
        if self.block_type == BlockType.confirmed:
            self._set_background_gradient("#115fb0", "#9239f3")
        else:
            self._set_background_gradient(
                fee_to_color(min_fee, mempoolFeeColors),
                fee_to_color(max_fee, mempoolFeeColors),
            )


class VerticalButtonGroup(InvisibleScrollArea):
    signal_button_click = pyqtSignal(int)

    def __init__(self, network: bdk.Network, button_count=3, parent=None, size=100) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self.content_widget)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(size + 30)
        # if button_count > 1:
        #     self.setMinimumHeight(size + 20)

        self.setWidgetResizable(True)
        self.buttons: List[BlockButton] = []

        # Create buttons
        for i in range(button_count):
            button = BlockButton(network=network, size=size)

            def create_signal_handler(index) -> Callable:
                def send_signal() -> None:
                    return self.signal_button_click.emit(index)

                return send_signal

            button.clicked.connect(create_signal_handler(i))

            self.buttons.append(button)
            layout.addWidget(button)
            layout.setAlignment(button, Qt.AlignmentFlag.AlignCenter)


class ObjectRequiringMempool(QObject):
    def __init__(self, mempool_data: MempoolData, parent=None) -> None:
        super().__init__(parent=parent)

        self.mempool_data = mempool_data

        self.timer = QTimer()
        self.timer.timeout.connect(self.mempool_data.set_data_from_mempoolspace)
        self.timer.start(10 * 60 * 1000)  # 10 minutes in milliseconds

    def set_mempool_block_unknown_fee_rate(self, i, confirmation_time: bdk.BlockTime | None = None) -> None:
        logger.error("This should not be called")


class BaseBlock(QObject):
    signal_click = pyqtSignal(float)

    def __init__(
        self,
        mempool_data: MempoolData,
        button_group: VerticalButtonGroup,
        confirmation_time: bdk.BlockTime | None = None,
        parent=None,
    ) -> None:
        QObject.__init__(self, parent=parent)
        self.confirmation_time = confirmation_time
        self.mempool_data = mempool_data
        self.button_group = button_group

        # signals
        self.button_group.signal_button_click.connect(self._on_button_click)
        self.mempool_data.signal_data_updated.connect(self.refresh)

    def refresh(self, **kwargs) -> None:
        pass

    def set_url(self, url: str) -> None:
        pass

    def _on_button_click(self, i: int) -> None:
        pass


class MempoolButtons(BaseBlock, ObjectRequiringMempool):
    "Showing multiple buttons of the next, the 2. and the 3. block templates according to the mempool"

    def __init__(self, mempool_data: MempoolData, max_button_count=3, parent=None) -> None:
        button_group = VerticalButtonGroup(
            network=mempool_data.network_config.network, button_count=max_button_count, parent=parent
        )
        BaseBlock.__init__(
            self, mempool_data=mempool_data, button_group=button_group, confirmation_time=None, parent=parent
        )
        ObjectRequiringMempool.__init__(self, mempool_data=mempool_data, parent=parent)

        self.refresh()

    def refresh(self, **kwargs) -> None:
        for i, button in enumerate(self.button_group.buttons):
            block_number = i + 1
            button.setVisible(i < max(1, self.mempool_data.num_mempool_blocks()))
            button.label_title.set(
                (
                    self.tr("Next Block")
                    if block_number == 1
                    else self.tr("{n}. Block").format(n=format_block_number(block_number))
                ),
                block_type=BlockType.projected,
            )
            button.label_time_estimation.set(block_number, block_type=BlockType.projected)
            button.label_approximate_median_fee.set(
                self.mempool_data.median_block_fee_rate(i), block_type=BlockType.projected
            )
            button.label_fee_range.set(*self.mempool_data.fee_rates_min_max(i))
            button.set_background_gradient(*self.mempool_data.fee_rates_min_max(i), BlockType.projected)

    def _on_button_click(self, i: int) -> None:
        logger.debug(f"Clicked button {i}: {self.mempool_data.median_block_fee_rate(i)}")
        self.signal_click.emit(self.mempool_data.median_block_fee_rate(i))


class MempoolProjectedBlock(BaseBlock, ObjectRequiringMempool):
    "The Button showing the block in which the fee_rate fits"

    def __init__(
        self,
        mempool_data: MempoolData,
        config: UserConfig,
        fee_rate: float = 1,
        parent=None,
    ) -> None:
        button_group = VerticalButtonGroup(
            network=mempool_data.network_config.network, size=100, button_count=1, parent=parent
        )

        BaseBlock.__init__(
            self, mempool_data=mempool_data, button_group=button_group, confirmation_time=None, parent=parent
        )
        ObjectRequiringMempool.__init__(self, mempool_data=mempool_data, parent=parent)

        self.config = config
        self.fee_rate = fee_rate
        self.url = ""

        self.refresh()

    def set_url(self, url: str) -> None:
        self.url = url

    def set_unknown_fee_rate(self) -> None:
        for button in self.button_group.buttons:
            button.clear_labels()
            button.label_title.set(self.tr("Unconfirmed"), BlockType.projected)
            button.label_explorer.set(BlockType.projected)
            button.set_background_gradient(0, 1, BlockType.projected)

    def refresh(self, fee_rate=None, **kwargs) -> None:
        self.fee_rate = fee_rate if fee_rate is not None else self.fee_rate
        # if self.fee_rate is None:
        #     self.set_unknown_fee_rate()
        #     return

        block_index = self.mempool_data.fee_rate_to_projected_block_index(self.fee_rate)

        for button in self.button_group.buttons:

            button.label_title.set(
                self.tr("~{n}. Block").format(n=format_block_number(block_index + 1)), BlockType.projected
            )
            button.label_approximate_median_fee.set(
                self.mempool_data.median_block_fee_rate(block_index), block_type=BlockType.projected
            )
            button.label_fee_range.set(*self.mempool_data.fee_rates_min_max(block_index))
            button.label_time_estimation.set(block_index + 1, BlockType.projected)
            button.set_background_gradient(
                *self.mempool_data.fee_rates_min_max(block_index), BlockType.projected
            )

    def _on_button_click(self, i: int) -> None:
        block_index = self.mempool_data.fee_rate_to_projected_block_index(self.fee_rate)
        url = (
            self.url
            if self.url
            else block_explorer_URL_of_projected_block(self.config.network_config.mempool_url, block_index)
        )
        if url:
            open_website(url)


class ConfirmedBlock(BaseBlock):
    "Showing a confirmed block"

    def __init__(
        self,
        mempool_data: MempoolData,
        url: str | None = None,
        confirmation_time: bdk.BlockTime | None = None,
        fee_rate: float | None = None,
        parent=None,
    ) -> None:
        button_group = VerticalButtonGroup(
            network=mempool_data.network_config.network, button_count=1, parent=parent, size=120
        )

        super().__init__(
            parent=parent,
            mempool_data=mempool_data,
            button_group=button_group,
            confirmation_time=confirmation_time,
        )

        self.fee_rate = fee_rate
        self.url = url

    def set_url(self, url: str) -> None:
        self.url = url

    def refresh(
        self, fee_rate=None, confirmation_time=None, chain_height: int | None = None, **kwargs
    ) -> None:
        self.fee_rate = fee_rate if fee_rate is not None else self.fee_rate
        self.confirmation_time = confirmation_time if confirmation_time else self.confirmation_time
        if not self.confirmation_time:
            return

        for i, button in enumerate(self.button_group.buttons):
            button.label_title.set(
                self.tr("Block {n}").format(n=format_block_number(self.confirmation_time.height)),
                BlockType.confirmed,
            )
            if chain_height is None:
                button.label_number_confirmations.setText("")
                button.label_block_height.set(self.confirmation_time.height, BlockType.confirmed)
            else:
                button.label_number_confirmations.set(
                    chain_height - self.confirmation_time.height + 1,
                    BlockType.confirmed,
                )
                button.label_block_height.setText("")

            button.label_explorer.set(BlockType.confirmed)
            if self.fee_rate:
                button.set_background_gradient(self.fee_rate, self.fee_rate, BlockType.confirmed)
                button.label_exact_median_fee.set(self.fee_rate, BlockType.confirmed)
            else:
                button.set_background_gradient(0, 1, BlockType.confirmed)
                button.label_exact_median_fee.setText("")

    def _on_button_click(self, i: int) -> None:
        if self.url:
            open_website(self.url)
        self.signal_click.emit(self.fee_rate)


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    widget = VerticalButtonGroup(network=bdk.Network.REGTEST)
    widget.show()

    sys.exit(app.exec())

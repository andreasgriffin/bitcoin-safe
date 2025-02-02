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


import enum
import logging
from functools import partial
from typing import Dict, List
from urllib.parse import urlparse

import bdkpython as bdk
from PyQt6.QtCore import QDateTime, QLocale, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from bitcoin_safe.config import MIN_RELAY_FEE, UserConfig
from bitcoin_safe.execute_config import ENABLE_TIMERS, MEMPOOL_SCHEDULE_TIMER
from bitcoin_safe.network_config import ProxyInfo
from bitcoin_safe.util import block_explorer_URL_of_projected_block, unit_fee_str

from ...html_utils import html_f
from ...mempool import MempoolData, fee_to_color, mempoolFeeColors
from ...signals import TypedPyQtSignal
from .invisible_scroll_area import InvisibleScrollArea
from .util import AspectRatioSvgWidget, center_in_widget, icon_path, open_website

logger = logging.getLogger(__name__)


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


class LabelConfirmationTime(BaseBlockLabel):
    def set(self, timestamp: int, block_type: BlockType) -> None:
        s = QLocale().toString(QDateTime.fromSecsSinceEpoch(timestamp), QLocale.FormatType.ShortFormat)

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelExplorer(BaseBlockLabel):

    @staticmethod
    def _extract_domain(url: str):
        """
        Extract the domain from a given URL.

        Args:
            url (str): The URL to extract the domain from.

        Returns:
            str: The domain without 'www.' if present.
        """
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.split(":")[0]  # Handles potential ports
        return domain.lstrip("www.")  # Removes 'www.' if present

    def set(self, mempool_url: str, block_type: BlockType) -> None:
        s = f"visit<br>{self._extract_domain(mempool_url)}"
        self.setText(html_f(s, color="white" if block_type else "black", size="10px"))


class ButtonExplorerIcon(AspectRatioSvgWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(svg_path=icon_path("block-explorer.svg"), max_height=20, max_width=20, parent=parent)
        self.setVisible(False)


class BlockButton(QPushButton):
    def __init__(self, network: bdk.Network, size=100, glow_color="#fab30d", parent=None) -> None:
        super().__init__(parent=parent)
        self.active = False
        self.min_fee: float = MIN_RELAY_FEE
        self.max_fee: float = MIN_RELAY_FEE
        self.block_type: BlockType = BlockType.confirmed
        self.glow_color = glow_color

        # Create labels for each text line

        self.label_approximate_median_fee = LabelApproximateMedianFee(network)
        self.label_exact_median_fee = LabelExactMedianFee(network)
        self.label_number_confirmations = LabelNumberConfirmations(network)
        self.label_block_height = LabelBlockHeight(network)
        self.label_fee_range = LabelFeeRange(network)
        self.label_title = LabelTitle(network)
        self.label_time_estimation = LabelTimeEstimation(network)
        self.label_confirmation_time = LabelConfirmationTime(network)
        self.explorer_explorer_icon = ButtonExplorerIcon()

        # define the order:
        self.labels: List[BaseBlockLabel] = [
            self.label_approximate_median_fee,
            self.label_exact_median_fee,
            self.label_number_confirmations,
            self.label_block_height,
            self.label_fee_range,
            self.label_title,
            self.label_time_estimation,
            self.label_confirmation_time,
        ]

        layout = center_in_widget(self.labels, self, direction="v")
        layout.addWidget(self.explorer_explorer_icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # Ensure buttons are square
        self.setMinimumHeight(size)
        self.setMinimumWidth(size)

    def set_active(self, value: bool):
        self.active = value
        self.set_background_gradient(
            active=value, min_fee=self.min_fee, max_fee=self.max_fee, block_type=self.block_type
        )

    def _set_glow(self, value: bool):
        if value:
            glow_effect = QGraphicsDropShadowEffect()
            glow_effect.setOffset(0)
            glow_effect.setBlurRadius(30)  # Increased blur radius
            glow_effect.setColor(QColor(self.glow_color))  # Bright orange color
            self.setGraphicsEffect(glow_effect)
        else:
            self.setGraphicsEffect(None)

    def clear_labels(self) -> None:
        for label in self.labels:
            label.setText("")

    def _get_css(self, active: bool, color_top: str, color_bottom: str) -> str:
        css = f"""
            QPushButton {{
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {color_bottom},
                                    stop:1 {color_top});
                color: white; /* Change this to set the text color */
            }}
        """
        if active:
            css += f""" 
                QPushButton:active {{
                    border: 2px solid {self.glow_color};  
                }}            
            """
        return css

    def set_background_gradient(
        self, active: bool, min_fee: float, max_fee: float, block_type: BlockType
    ) -> None:
        self.active = active
        self.min_fee = min_fee
        self.max_fee = max_fee
        self.block_type = block_type

        if self.block_type == BlockType.confirmed:
            css = self._get_css(active=active, color_top="#115fb0", color_bottom="#9239f3")
        else:
            css = self._get_css(
                active=active,
                color_top=fee_to_color(min_fee, mempoolFeeColors),
                color_bottom=fee_to_color(max_fee, mempoolFeeColors),
            )
        self.setStyleSheet(css)
        self._set_glow(active)


class VerticalButtonGroup(InvisibleScrollArea):
    signal_button_click: TypedPyQtSignal[int] = pyqtSignal(int)  # type: ignore

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
            button.clicked.connect(partial(self.signal_button_click.emit, i))

            self.buttons.append(button)
            layout.addWidget(button)
            layout.setAlignment(button, Qt.AlignmentFlag.AlignCenter)

    def set_active(self, index: int, exclusive=True):
        for i, button in enumerate(self.buttons):
            if i == index or exclusive:
                button.set_active(i == index)


class MempoolScheduler(QObject):
    def __init__(self, proxies: Dict | None, mempool_data: MempoolData, parent=None) -> None:
        super().__init__(parent=parent)
        self.proxies = proxies

        self.mempool_data = mempool_data

        self.timer = QTimer()
        self.timer.timeout.connect(self.set_data_from_mempoolspace)
        if ENABLE_TIMERS:
            self.timer.start(MEMPOOL_SCHEDULE_TIMER)

    def set_mempool_block_unknown_fee_rate(self, i, confirmation_time: bdk.BlockTime | None = None) -> None:
        logger.error("This should not be called")

    def set_data_from_mempoolspace(self):
        self.mempool_data.set_data_from_mempoolspace(proxies=self.proxies)


class BaseBlock(VerticalButtonGroup):
    signal_click: TypedPyQtSignal[float] = pyqtSignal(float)  # type: ignore

    def __init__(
        self,
        mempool_data: MempoolData,
        network: bdk.Network,
        confirmation_time: bdk.BlockTime | None = None,
        button_count=3,
        parent=None,
        size=100,
    ) -> None:
        super().__init__(network=network, button_count=button_count, parent=parent, size=size)
        self.confirmation_time = confirmation_time
        self.mempool_data = mempool_data

        # signals
        self.signal_button_click.connect(self._on_button_click)
        self.mempool_data.signal_data_updated.connect(self.refresh)

    def refresh(self, **kwargs) -> None:
        pass

    def set_url(self, url: str) -> None:
        pass

    def _on_button_click(self, i: int) -> None:
        pass


class MempoolButtons(BaseBlock):
    "Showing multiple buttons of the next, the 2. and the 3. block templates according to the mempool"

    def __init__(
        self,
        mempool_data: MempoolData,
        proxies: Dict | None,
        fee_rate: float = 1,
        max_button_count=3,
        parent=None,
    ) -> None:
        super().__init__(
            mempool_data=mempool_data,
            confirmation_time=None,
            network=mempool_data.network_config.network,
            button_count=max_button_count,
            parent=parent,
        )
        self.mempool_scheduler = MempoolScheduler(
            proxies=proxies,
            mempool_data=mempool_data,
            parent=parent,
        )
        self.fee_rate = fee_rate

        self.refresh()

    def refresh(self, fee_rate=None, **kwargs) -> None:
        self.fee_rate = fee_rate if fee_rate is not None else self.fee_rate
        # if self.fee_rate is None:
        #     self.set_unknown_fee_rate()
        #     return

        block_index = self.mempool_data.fee_rate_to_projected_block_index(self.fee_rate)

        for i, button in enumerate(self.buttons):
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
            min_fee, max_fee = self.mempool_data.fee_rates_min_max(i)
            button.set_background_gradient(
                active=i == block_index, min_fee=min_fee, max_fee=max_fee, block_type=BlockType.projected
            )

    def _on_button_click(self, i: int) -> None:
        logger.debug(f"Clicked button {i}: {self.mempool_data.median_block_fee_rate(i)}")
        self.set_active(i)
        self.signal_click.emit(self.mempool_data.median_block_fee_rate(i))


class MempoolProjectedBlock(BaseBlock):
    "The Button showing the block in which the fee_rate fits"

    def __init__(
        self,
        mempool_data: MempoolData,
        config: UserConfig,
        fee_rate: float = 1,
        parent=None,
    ) -> None:
        super().__init__(
            mempool_data=mempool_data,
            confirmation_time=None,
            network=mempool_data.network_config.network,
            button_count=1,
            parent=parent,
            size=100,
        )
        self.mempool_scheduler = MempoolScheduler(
            (
                ProxyInfo.parse(config.network_config.proxy_url).get_requests_proxy_dict()
                if config.network_config.proxy_url
                else None
            ),
            mempool_data,
            parent=parent,
        )

        self.config = config
        self.fee_rate = fee_rate
        self.url = ""

        self.refresh()

    def set_url(self, url: str) -> None:
        self.url = url

    def set_unknown_fee_rate(self) -> None:
        for button in self.buttons:
            button.clear_labels()
            button.label_title.set(self.tr("Unconfirmed"), BlockType.projected)
            button.explorer_explorer_icon.setVisible(True)
            button.set_background_gradient(
                active=False, min_fee=MIN_RELAY_FEE, max_fee=MIN_RELAY_FEE, block_type=BlockType.projected
            )

    def refresh(self, fee_rate=None, **kwargs) -> None:
        self.fee_rate = fee_rate if fee_rate is not None else self.fee_rate
        # if self.fee_rate is None:
        #     self.set_unknown_fee_rate()
        #     return

        block_index = self.mempool_data.fee_rate_to_projected_block_index(self.fee_rate)

        for button in self.buttons:

            button.label_title.set(
                self.tr("~{n}. Block").format(n=format_block_number(block_index + 1)), BlockType.projected
            )
            button.label_approximate_median_fee.set(
                self.mempool_data.median_block_fee_rate(block_index), block_type=BlockType.projected
            )
            button.label_fee_range.set(*self.mempool_data.fee_rates_min_max(block_index))
            button.label_time_estimation.set(block_index + 1, BlockType.projected)
            min_fee, max_fee = self.mempool_data.fee_rates_min_max(block_index)
            button.set_background_gradient(
                active=True, min_fee=min_fee, max_fee=max_fee, block_type=BlockType.projected
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
        super().__init__(
            mempool_data=mempool_data,
            confirmation_time=confirmation_time,
            network=mempool_data.network_config.network,
            button_count=1,
            parent=parent,
            size=120,
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

        for i, button in enumerate(self.buttons):
            button.label_title.set(
                self.tr("Block {n}").format(n=format_block_number(self.confirmation_time.height)),
                BlockType.confirmed,
            )
            if chain_height is None:
                button.label_number_confirmations.setText("")
            else:
                button.label_number_confirmations.set(
                    chain_height - self.confirmation_time.height + 1,
                    BlockType.confirmed,
                )
            button.label_block_height.setText("")
            button.label_confirmation_time.set(
                self.confirmation_time.timestamp, block_type=BlockType.confirmed
            )

            button.explorer_explorer_icon.setVisible(True)
            if self.fee_rate:
                button.set_background_gradient(
                    active=True, min_fee=self.fee_rate, max_fee=self.fee_rate, block_type=BlockType.confirmed
                )
                button.label_exact_median_fee.set(median_fee=self.fee_rate, block_type=BlockType.confirmed)
            else:
                button.set_background_gradient(
                    active=True, min_fee=MIN_RELAY_FEE, max_fee=MIN_RELAY_FEE, block_type=BlockType.confirmed
                )
                button.label_exact_median_fee.setText("")

    def _on_button_click(self, i: int) -> None:
        if self.url:
            open_website(self.url)

        # do not set fee_rate, because it is a confirmed block.
        # self.signal_click.emit(self.fee_rate)


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    widget = VerticalButtonGroup(network=bdk.Network.REGTEST)
    widget.show()

    sys.exit(app.exec())

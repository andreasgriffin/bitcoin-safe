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

import logging
from typing import cast
from urllib.parse import urlparse

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import unit_fee_str
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.util import age
from PyQt6.QtCore import QDateTime, QLocale, QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.execute_config import ENABLE_TIMERS, MEMPOOL_SCHEDULE_TIMER
from bitcoin_safe.gui.qt.qr_components.square_buttons import FlatSquareButton
from bitcoin_safe.gui.qt.tx_tools import TxTools
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.wallet import TxConfirmationStatus, TxStatus

from ....html_utils import html_f
from ....mempool_manager import (
    BlockInfo,
    BlockType,
    MempoolManager,
    fee_to_color,
    mempoolFeeColors,
)
from ....signals import WalletFunctions
from ....util import required_precision
from ..invisible_scroll_area import InvisibleScrollArea
from ..util import (
    ButtonInfoType,
    button_info,
    center_in_widget,
    set_no_margins,
)

logger = logging.getLogger(__name__)
SIZE_MEMPOOL_BLOCK = 100
SIZE_CONFIRMED_BLOCK = 120


_DEFAULT_ICON_SIZE = QSize(24, 24)


def format_block_number(block_number) -> str:
    """Format block number."""
    return QLocale().toString(int(block_number))


class SmallTitleLabel(QLabel):
    def __init__(self, text: str = "", parent=None) -> None:
        """Initialize instance."""
        super().__init__(text, parent)

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Set opacity
        opacity_effect = QGraphicsOpacityEffect()
        opacity_effect.setOpacity(0.75)  # value from 0.0 (transparent) to 1.0 (fully opaque)
        self.setGraphicsEffect(opacity_effect)

        # Get default font and scale it down
        font = self.font()
        default_size = font.pointSizeF()
        if default_size <= 0:  # fallback in case it's -1 or invalid
            default_size = QApplication.font().pointSizeF()
        font.setPointSizeF(default_size * 0.85)  # 20% smaller
        self.setFont(font)


class SmallTextLabel(QLabel):
    def __init__(self, text: str = "", parent=None) -> None:
        """Initialize instance."""
        super().__init__(text, parent)

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        font = self.font()
        font.setBold(True)
        self.setFont(font)


class BetweenBlockInfoBox(QWidget):
    def __init__(self, parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setVisible(False)

        self.title = SmallTitleLabel()
        self.text = SmallTextLabel()
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.title)
        self._layout.addWidget(self.text)

        self._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)


class BaseBlockLabel(QLabel):
    def __init__(self, network: bdk.Network, text: str = "", parent=None) -> None:
        """Initialize instance."""
        super().__init__(text, parent)
        self.network = network

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setHidden(not text)

    def setText(self, a0: str | None) -> None:
        """SetText."""
        self.setHidden(not a0)
        return super().setText(a0)

    def format_fee(self, fee: float, decimal_precision: int = 0) -> str:
        """Format fee."""
        return f"{fee:.{decimal_precision}f}"


class LabelTitle(BaseBlockLabel):
    def set(self, text: str, block_type: BlockType) -> None:
        """Set."""
        self.setText(html_f(text, color="white" if block_type else "black", size="16px"))


class LabelApproximateMedianFee(BaseBlockLabel):
    def set(
        self,
        block_info: BlockInfo,
    ) -> None:
        """Set."""
        decimal_precision = required_precision(block_info.min_fee, block_info.max_fee)
        median_fee_str = self.format_fee(block_info.median_fee, decimal_precision=decimal_precision)
        s = f"~{median_fee_str} {unit_fee_str(self.network)}"

        self.setText(html_f(s, color="white" if block_info.block_type else "black", size="12px"))


class LabelExactMedianFee(BaseBlockLabel):
    def set(self, median_fee: float, block_type: BlockType) -> None:
        """Set."""
        s = f"{round(median_fee, 1)} {unit_fee_str(self.network)}"

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelNumberConfirmations(BaseBlockLabel):
    def set(self, i: int, block_type: BlockType) -> None:
        """Set."""
        s = f"{i} Confirmation{'s' if i > 1 else ''}"

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelBlockHeight(BaseBlockLabel):
    def set(self, i: int, block_type: BlockType) -> None:
        """Set."""
        s = f"{round(i)}. Block"

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelFeeRange(BaseBlockLabel):
    def set(self, min_fee: float, max_fee: float) -> None:
        """Set."""
        decimal_precision = required_precision(min_fee, max_fee)
        min_fee_str = self.format_fee(min_fee, decimal_precision=decimal_precision)
        max_fee_str = self.format_fee(max_fee, decimal_precision=decimal_precision)
        s = f"{min_fee_str} - {max_fee_str} {unit_fee_str(self.network)}"

        self.setText(html_f(s, color="#eee002", size="10px"))


class LabelTimeEstimation(BaseBlockLabel):
    def set(self, block_number: int, block_type: BlockType) -> None:
        """Set."""
        if block_number < 6:
            s = self.tr("~in {t} min").format(t=(block_number) * 10)
        else:
            s = self.tr("~in {t} hours").format(t=round((block_number) / 6))

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelConfirmationTime(BaseBlockLabel):
    def set(self, timestamp: int, block_type: BlockType) -> None:
        """Set."""
        s = QLocale().toString(QDateTime.fromSecsSinceEpoch(timestamp), QLocale.FormatType.ShortFormat)

        self.setText(html_f(s, color="white" if block_type else "black", size="12px"))


class LabelExplorer(BaseBlockLabel):
    @staticmethod
    def _extract_domain(url: str):
        """Extract the domain from a given URL.

        Args:
            url (str): The URL to extract the domain from.

        Returns:
            str: The domain without 'www.' if present.
        """
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.split(":")[0]  # Handles potential ports
        return domain.removeprefix("www.")  # Removes 'www.' if present

    def set(self, mempool_url: str, block_type: BlockType) -> None:
        """Set."""
        s = f"visit<br>{self._extract_domain(mempool_url)}"
        self.setText(html_f(s, color="white" if block_type else "black", size="10px"))


class ButtonExplorerIcon(FlatSquareButton):
    def __init__(self, size=_DEFAULT_ICON_SIZE, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(
            qicon=svg_tools.get_QIcon(
                "block-explorer.svg", auto_theme=False, replace_tuples=(("currentColor", "#ffffff"),)
            ),
            size=size,
            parent=parent,
        )
        self.setVisible(False)
        self.setToolTip(self.tr("Open in the block explorer"))


class RBFIcon(FlatSquareButton):
    def __init__(self, size=_DEFAULT_ICON_SIZE, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(
            qicon=svg_tools.get_QIcon(
                button_info(ButtonInfoType.rbf).icon_name,
                auto_theme=False,
                replace_tuples=(("currentColor", "#ffffff"),),
            ),
            size=size,
            parent=parent,
        )
        self.setVisible(False)
        self.setToolTip(
            self.tr(
                "Use this fee to build a replacement (RBF) transaction at the shown target speed."
                "\nOutputs stay the same; only the fee changes."
            )
        )


class CPFPIcon(FlatSquareButton):
    def __init__(self, size=_DEFAULT_ICON_SIZE, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(
            qicon=svg_tools.get_QIcon(
                button_info(ButtonInfoType.cpfp).icon_name,
                auto_theme=False,
                replace_tuples=(("currentColor", "#ffffff"),),
            ),
            size=size,
            parent=parent,
        )
        self.setVisible(False)
        self.setToolTip(
            self.tr(
                "Spend your change with this fee to pull the parent in (CPFP)."
                "\nThe combined parent+child fee rate should meet the target block."
            )
        )


class EditWithFeeIcon(FlatSquareButton):
    def __init__(self, size=_DEFAULT_ICON_SIZE, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(
            qicon=svg_tools.get_QIcon(
                button_info(ButtonInfoType.edit).icon_name,
                auto_theme=False,
                replace_tuples=(("currentColor", "#ffffff"),),
            ),
            size=size,
            parent=parent,
        )
        self.setVisible(False)
        self.setToolTip(self.tr("Edit with this fee rate"))


class BlockButton(QPushButton):
    signal_click = cast(SignalProtocol[[int]], pyqtSignal(int))

    signal_rbf_icon = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_cpfp_icon = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_edit_with_fee_icon = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_explorer_explorer_icon = cast(SignalProtocol[[int]], pyqtSignal(int))

    def __init__(
        self,
        network: bdk.Network,
        size=SIZE_MEMPOOL_BLOCK,
        non_active_opacity=0.7,
        active_border_width=0,
        border_radius=5,
        clickable=True,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.active = False
        self.block_info = BlockInfo(block_type=BlockType.confirmed)
        self.non_active_opacity = non_active_opacity
        self.active_border_width = active_border_width
        self.border_radius = border_radius
        self.index = 0
        self.clickable = clickable

        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

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
        self.rbf_icon = RBFIcon()
        self.cpfp_icon = CPFPIcon()
        self.edit_with_fee_icon = EditWithFeeIcon()

        # define the order:
        self.labels: list[BaseBlockLabel] = [
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
        widget_icons = QWidget(self)
        widget_icons.setMinimumHeight(0)
        widget_icons_layout = QHBoxLayout(widget_icons)
        set_no_margins(widget_icons_layout)
        for icon in [self.explorer_explorer_icon, self.edit_with_fee_icon, self.rbf_icon, self.cpfp_icon]:
            widget_icons_layout.addWidget(icon)
        layout.addWidget(widget_icons, alignment=Qt.AlignmentFlag.AlignHCenter)
        set_no_margins(layout)

        self.set_size(size=size)

        self.clicked.connect(self._on_click)
        self.explorer_explorer_icon.clicked.connect(self._on_explorer_explorer_icon)
        self.rbf_icon.clicked.connect(self._on_rbf_icon)
        self.cpfp_icon.clicked.connect(self._on_cpfp_icon)
        self.edit_with_fee_icon.clicked.connect(
            self._on_edit_with_fee_icon,
        )

    def set_size(self, size=SIZE_MEMPOOL_BLOCK):
        # Ensure buttons are square
        """Set size."""
        self.setMinimumHeight(size)
        self.setMinimumWidth(size)

    def _on_click(self) -> None:
        """On click."""
        if self.clickable:
            self.signal_click.emit(self.index)

    def _on_rbf_icon(self) -> None:
        """On rbf icon."""
        self.signal_rbf_icon.emit(self.index)

    def _on_cpfp_icon(self) -> None:
        """On cpfp icon."""
        self.signal_cpfp_icon.emit(self.index)

    def _on_edit_with_fee_icon(self) -> None:
        """On edit with fee icon."""
        self.signal_edit_with_fee_icon.emit(self.index)

    def _on_explorer_explorer_icon(self) -> None:
        """On explorer explorer icon."""
        self.signal_explorer_explorer_icon.emit(self.index)

    def set_index(self, index: int):
        """Set index."""
        self.index = index

    def set_active(self, value: bool):
        """Set active."""
        self.active = value
        self.set_background_gradient(
            active=value,
        )

    def clear_labels(self) -> None:
        """Clear labels."""
        for label in self.labels:
            label.setText("")

    def set_opacity(self, active: bool):
        # remove any existing effect first
        """Set opacity."""
        self.setGraphicsEffect(None)

        if not active:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(self.non_active_opacity)
            self.setGraphicsEffect(effect)

    def _get_css(
        self,
        color_top: str,
        color_bottom: str,
        median_color: str | None = None,
    ) -> str:
        """Get css."""
        self.setObjectName(f"{id(self)}")

        colors = (
            [color_bottom, color_top] if median_color is None else [color_bottom, median_color, color_top]
        )
        stops = ",".join([f"stop:{i / len(colors)} {c}" for i, c in enumerate(colors)])

        css = f"""
            #{self.objectName()} {{
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1,{stops});
                border: none;
                color: white;
                border-radius: {self.border_radius}px;
            }}
            #{self.objectName()}:pressed {{
                border: none;
            }}
            #{self.objectName()}:focus {{
                border: none;
                outline: none;
            }}
        """
        return css

    def set_background_gradient(self, active: bool, block_info: BlockInfo | None = None) -> None:
        """Set background gradient."""
        self.active = active
        block_info = block_info if block_info else self.block_info
        self.block_info = block_info

        if block_info.block_type == BlockType.confirmed:
            css = self._get_css(color_top="#115fb0", color_bottom="#9239f3")
        else:
            css = self._get_css(
                color_top=fee_to_color(block_info.min_fee, mempoolFeeColors),
                color_bottom=fee_to_color(block_info.max_fee, mempoolFeeColors),
                median_color=fee_to_color(block_info.median_fee, mempoolFeeColors),
            )
        self.setStyleSheet(css)
        self.set_opacity(active=active)


class VerticalButtonGroup(InvisibleScrollArea):
    def __init__(
        self,
        network: bdk.Network,
        button_count=3,
        parent=None,
        size=SIZE_MEMPOOL_BLOCK,
        non_active_opacity=0.6,
        border_radius=5,
        clickable=True,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self._layout = QVBoxLayout(self.content_widget)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # if button_count > 1:
        #     self.setMinimumHeight(size + 20)

        self.setWidgetResizable(True)
        self.buttons: list[BlockButton] = []

        # Create buttons
        for _i in range(button_count):
            button = BlockButton(
                network=network,
                size=size,
                non_active_opacity=non_active_opacity,
                border_radius=border_radius,
                clickable=clickable,
            )

            self.buttons.append(button)
            self._layout.addWidget(button)
            self._layout.setAlignment(button, Qt.AlignmentFlag.AlignCenter)

        self.set_size(size=size)

    def set_size(self, size: int):
        """Set size."""
        self.setMinimumWidth(size + 30)
        for button in self.buttons:
            button.set_size(size=size)

    def set_active(self, index: int, exclusive=True):
        """Set active."""
        for i, button in enumerate(self.buttons):
            if i == index or exclusive:
                button.set_active(i == index)


class MempoolScheduler(QObject):
    def __init__(self, mempool_manager: MempoolManager, parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)

        self.mempool_manager = mempool_manager

        self.timer = QTimer()
        self.timer.timeout.connect(self.set_data_from_mempoolspace)
        if ENABLE_TIMERS:
            self.timer.start(MEMPOOL_SCHEDULE_TIMER)

    def set_mempool_block_unknown_fee_rate(
        self, i, confirmation_time: bdk.ConfirmationBlockTime | None = None
    ) -> None:
        """Set mempool block unknown fee rate."""
        logger.error("This should not be called")

    def set_data_from_mempoolspace(self):
        """Set data from mempoolspace."""
        self.mempool_manager.set_data_from_mempoolspace()


class MempoolButtons(VerticalButtonGroup):
    "Showing multiple buttons of the next, the 2. and the 3. block templates according to the mempool"

    signal_click_median_fee = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_rbf_icon = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_cpfp_icon = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_edit_with_fee_icon = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_explorer_explorer_icon = cast(SignalProtocol[[int]], pyqtSignal(int))

    def __init__(
        self,
        mempool_manager: MempoolManager,
        decimal_precision: int,
        tx_status: TxStatus,
        wallet_functions: WalletFunctions,
        fee_rate: float = 1,
        max_button_count=4,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            network=mempool_manager.network_config.network,
            button_count=max_button_count,
            size=self._tx_status_to_size(tx_status=tx_status),
            parent=parent,
            border_radius=int(5 / 100 * self._tx_status_to_size(tx_status=tx_status)),
            clickable=tx_status.confirmation_status in [TxConfirmationStatus.DRAFT],
        )
        self.tx_status = tx_status
        self.mempool_manager = mempool_manager
        self.wallet_functions = wallet_functions
        self.can_rbf_safely = False

        self.info_past_days = BetweenBlockInfoBox()
        self._layout.insertWidget(0, self.info_past_days)

        self.info_confirmations = BetweenBlockInfoBox()
        self._layout.addWidget(self.info_confirmations)

        self._layout.addStretch()  # makes the buttons stack on top

        self.mempool_scheduler = MempoolScheduler(
            mempool_manager=mempool_manager,
            parent=parent,
        )
        self.decimal_precision = decimal_precision
        self.fee_rate = fee_rate

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_context_menu)

        self.refresh()

        # signals
        for button in self.buttons:
            button.signal_click.connect(self._on_button_click)
            button.signal_rbf_icon.connect(self.signal_rbf_icon)
            button.signal_cpfp_icon.connect(self.signal_cpfp_icon)
            button.signal_edit_with_fee_icon.connect(self.signal_edit_with_fee_icon)
            button.signal_explorer_explorer_icon.connect(self.signal_explorer_explorer_icon)
        self.mempool_manager.signal_data_updated.connect(self.refresh)

    @staticmethod
    def _tx_status_to_size(tx_status: TxStatus) -> int:
        """Tx status to size."""
        return SIZE_CONFIRMED_BLOCK if tx_status.is_confirmed() else SIZE_MEMPOOL_BLOCK

    def calculate_button_indices(self, include_index: int):
        """Calculate button indices."""
        button_indices = {include_index}

        default_indices = list(range(len(self.buttons)))
        while len(button_indices) < len(self.buttons):
            button_indices.add(default_indices.pop(0))

        return sorted(list(button_indices))

    def open_context_menu(self, pos):
        """Open context menu."""
        menu = QMenu(self)
        action_refresh = menu.addAction(self.tr("Fetch new mempool data"))
        if action_refresh:
            action_refresh.setIcon(svg_tools.get_QIcon("bi--arrow-clockwise.svg"))

        # Convert the local position to global coordinates.
        global_pos = self.mapToGlobal(pos)
        action = menu.exec(global_pos)

        if action == action_refresh:
            self.mempool_manager.set_data_from_mempoolspace(force=True)

    def refresh_confirmed(
        self,
        fee_rate=None,
    ) -> None:
        """Refresh confirmed."""
        self.fee_rate = fee_rate if fee_rate is not None else self.fee_rate
        if not self.tx_status.chain_position or not isinstance(
            self.tx_status.chain_position, bdk.ChainPosition.CONFIRMED
        ):
            return

        block_index = self.tx_status.chain_position.confirmation_block_time.block_id.height

        self.info_past_days.title.setText(self.tr("First confirmation"))
        self.info_past_days.text.setText(
            age(from_date=self.tx_status.chain_position.confirmation_block_time.confirmation_time)
        )
        self.info_past_days.setVisible(True)

        self.info_confirmations.title.setText(self.tr("Confirmations"))
        self.info_confirmations.text.setText(f"{self.tx_status.confirmations()}")
        self.info_confirmations.setVisible(True)

        for button in self.buttons[:1]:
            button.set_index(block_index)
            button.set_active(True)
            button.label_title.set(
                self.tr("Block {n}").format(n=format_block_number(block_index)),
                BlockType.confirmed,
            )
            # button.label_number_confirmations.set(
            #     self.tx_status.confirmations(),
            #     BlockType.confirmed,
            # )
            button.label_number_confirmations.setVisible(False)
            button.label_block_height.setText("")
            button.label_confirmation_time.set(
                self.tx_status.chain_position.confirmation_block_time.confirmation_time,
                block_type=BlockType.confirmed,
            )

            if self.fee_rate:
                button.set_background_gradient(
                    active=True, block_info=BlockInfo(block_type=BlockType.confirmed)
                )
            else:
                button.set_background_gradient(
                    active=True, block_info=BlockInfo(block_type=BlockType.confirmed)
                )
            button.label_exact_median_fee.setText("")

        for button in self.buttons[1:]:
            button.set_index(-1)

        self.set_visibilities(block_index=block_index)

    def refresh(
        self,
        can_rbf_safely: bool | None = None,
        tx_status: TxStatus | None = None,
        fee_rate=None,
    ) -> None:
        """Refresh."""
        self.tx_status = tx_status if tx_status else self.tx_status
        self.can_rbf_safely = can_rbf_safely if can_rbf_safely is not None else self.can_rbf_safely
        self.set_size(size=self._tx_status_to_size(self.tx_status))

        if self.tx_status.chain_position and isinstance(
            self.tx_status.chain_position, bdk.ChainPosition.CONFIRMED
        ):
            self.refresh_confirmed(fee_rate=fee_rate)
            return

        logger.debug(f"{self.__class__.__name__} refresh  {fee_rate=}")
        self.fee_rate = fee_rate if fee_rate is not None else self.fee_rate
        # if self.fee_rate is None:
        #     self.set_unknown_fee_rate()
        #     return

        block_index = self.mempool_manager.fee_rate_to_projected_block_index(self.fee_rate)
        self.set_active(block_index)
        button_indices = self.calculate_button_indices(block_index)

        for index, button in zip(button_indices, self.buttons, strict=False):
            button.set_index(index)
            block_number = index + 1
            button.label_title.set(
                (
                    self.tr("Next Block")
                    if block_number == 1
                    else self.tr("{n}. Block").format(n=format_block_number(block_number))
                ),
                block_type=BlockType.mempool,
            )
            button.label_time_estimation.set(block_number, block_type=BlockType.mempool)
            block_info = self.mempool_manager.block_info(index, decimal_precision=self.decimal_precision)
            button.label_approximate_median_fee.set(block_info)
            button.label_fee_range.set(min_fee=block_info.min_fee, max_fee=block_info.max_fee)
            button.set_background_gradient(
                active=index == block_index, block_info=self.mempool_manager.block_info(index)
            )
        self.set_visibilities(block_index=block_index)

    def set_visibilities(self, block_index: int):
        """Set visibilities."""
        for button in self.buttons:
            # set visibilities
            button.setVisible(button.index < max(1, self.mempool_manager.num_mempool_blocks()))
            button.label_fee_range.setHidden(True)
            button.rbf_icon.setHidden(True)
            button.cpfp_icon.setHidden(True)
            button.edit_with_fee_icon.setHidden(True)
            button.explorer_explorer_icon.setHidden(True)
            button.label_time_estimation.setHidden(self.tx_status.is_confirmed())
            button.label_approximate_median_fee.setHidden(self.tx_status.is_confirmed())
            self.info_past_days.setVisible(self.tx_status.is_confirmed())
            if button.index == block_index:
                self.ensureWidgetVisible(button)

            if self.tx_status.confirmation_status == TxConfirmationStatus.DRAFT:
                button.label_fee_range.setVisible(True)
            elif self.tx_status.confirmation_status in [
                TxConfirmationStatus.PSBT,
                TxConfirmationStatus.LOCAL,
            ]:
                button.setVisible(button.index <= block_index)
                button.edit_with_fee_icon.setVisible(
                    (button.index < block_index) and TxTools.can_edit_safely(tx_status=self.tx_status)
                )
                button.label_fee_range.setVisible(button.index == block_index)
            elif self.tx_status.confirmation_status == TxConfirmationStatus.UNCONFIRMED:
                button.setVisible(button.index <= block_index)
                button.rbf_icon.setVisible((button.index < block_index) and self.can_rbf_safely)
                button.cpfp_icon.setVisible(
                    (button.index < block_index)
                    and TxTools.can_cpfp(tx_status=self.tx_status, wallet_functions=self.wallet_functions)
                )
                button.label_fee_range.setVisible(button.index == block_index)
            elif self.tx_status.confirmation_status == TxConfirmationStatus.CONFIRMED:
                button.setVisible(button.index == block_index)
                button.explorer_explorer_icon.setVisible(True)

    def _on_button_click(self, i: int) -> None:
        """On button click."""
        if self.tx_status.confirmation_status != TxConfirmationStatus.DRAFT:
            return
        fee_rate = self.mempool_manager.median_block_fee_rate(i, decimal_precision=self.decimal_precision)
        logger.debug(f"Clicked button {i}: {fee_rate}")
        self.set_active(i)
        self.signal_click_median_fee.emit(i)


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    widget = VerticalButtonGroup(network=bdk.Network.REGTEST)
    widget.show()

    sys.exit(app.exec())

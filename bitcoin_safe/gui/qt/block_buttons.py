from asyncio.log import logger
from PySide2.QtWidgets import QPushButton, QLabel, QVBoxLayout, QWidget, QApplication
from PySide2.QtCore import Qt
import numpy as np
from ...mempool import (
    MempoolData,
    fee_to_color,
    get_block_min_fees,
    chartColors,
    bin_data,
    feeLevels,
    index_of_sum_until_including,
    mempoolFeeColors,
    fee_to_blocknumber,
    fees_of_depths,
)
from .util import QColorLerp, center_in_widget, open_website
from PySide2.QtCore import Signal, QObject
from typing import List, Dict
from PySide2.QtWidgets import QSizePolicy, QScrollArea
import bdkpython as bdk
from PySide2.QtCore import QObject, QEvent
from PySide2.QtGui import QBrush, QColor, QPainter
import enum
from PyQt5.QtCore import QTimer


class BlockType(enum.Enum):
    projected = enum.auto()
    confirmed = enum.auto()
    unconfirmed = enum.auto()


class BaseBlockLabel(QLabel):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)

        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setHidden(not text)

    def setText(self, arg__1: str) -> None:
        self.setHidden(not arg__1)
        return super().setText(arg__1)


class LabelTitle(BaseBlockLabel):
    def set(self, text: str, block_type: BlockType):
        self.setText(
            f"<span style='color: {'white' if block_type else 'black'}; font-size: 16px;'>{text}</span>"
        )


class LabelApproximateMedianFee(BaseBlockLabel):
    def set(self, median_fee: float, block_type: BlockType):
        s = f"~{int(median_fee)} Sat/vB"

        self.setText(
            f"<span style='color: {'white' if block_type else 'black'}; font-size: 12px;'>{s}</span>"
        )


class LabelExactMedianFee(BaseBlockLabel):
    def set(self, median_fee: float, block_type: BlockType):
        s = f"{round(median_fee, 1)} Sat/vB"

        self.setText(
            f"<span style='color: {'white' if block_type else 'black'}; font-size: 12px;'>{s}</span>"
        )


class LabelNumberConfirmations(BaseBlockLabel):
    def set(self, i: int, block_type: BlockType):
        s = f"{i} Confirmation{'s' if i>1 else ''}"

        self.setText(
            f"<span style='color: {'white' if block_type else 'black'}; font-size: 12px;'>{s}</span>"
        )


class LabelBlockHeight(BaseBlockLabel):
    def set(self, i: int, block_type: BlockType):
        s = f"{round(i)}. Block"

        self.setText(
            f"<span style='color: {'white' if block_type else 'black'}; font-size: 12px;'>{s}</span>"
        )


class LabelFeeRange(BaseBlockLabel):
    def set(self, min_fee: float, max_fee: float):
        s = f"{int(min_fee)} - {int(max_fee)} Sat/vB"

        self.setText(f"<span style='color: #eee002; font-size: 10px;'>{s}</span>")


class LabelTimeEstimation(BaseBlockLabel):
    def set(self, blocknumber: int, block_type: BlockType):
        if blocknumber < 6:
            s = f"~in {(blocknumber)*10} min</span>"
        else:
            s = f"~in {round(blocknumber/6)} hours"

        self.setText(
            f"<span style='color: {'white' if block_type else 'black'}; font-size: 12px;'>{s}</span>"
        )


class LabelExplorer(BaseBlockLabel):
    def set(self, block_type: BlockType):
        s = "visit<br>mempool.space"
        self.setText(
            f"<span style='color: {'white' if block_type else 'black'}; font-size: 10px;'>{s}</span>"
        )


class BlockButton(QPushButton):
    def __init__(self, size=100, parent=None):
        super().__init__(parent=parent)

        # Create labels for each text line

        self.label_approximate_median_fee = LabelApproximateMedianFee()
        self.label_exact_median_fee = LabelExactMedianFee()
        self.label_number_confirmations = LabelNumberConfirmations()
        self.label_block_height = LabelBlockHeight()
        self.label_fee_range = LabelFeeRange()
        self.label_title = LabelTitle()
        self.label_time_estimation = LabelTimeEstimation()
        self.label_explorer = LabelExplorer()

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

    def clear_labels(self):
        for label in self.labels:
            label.setText("")

    def _set_background_gradient(self, color_top: QColor, color_bottom: QColor):
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

    def set_background_gradient(
        self, min_fee: float, max_fee: float, block_type: BlockType
    ):
        self.block_type = block_type
        if self.block_type == BlockType.confirmed:
            self._set_background_gradient("#115fb0", "#9239f3")
        else:
            self._set_background_gradient(
                fee_to_color(min_fee, mempoolFeeColors),
                fee_to_color(max_fee, mempoolFeeColors),
            )


class VerticalButtonGroup(QScrollArea):
    signal_button_click = Signal(int)

    def __init__(self, button_count=3, parent=None, size=100):
        super().__init__(parent)
        content_widget = QWidget()
        self.setWidget(content_widget)
        layout = QVBoxLayout(content_widget)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(size + 50)
        if button_count > 1:
            self.setMinimumHeight(size + 20)

        self.setWidgetResizable(True)
        self.buttons: List[BlockButton] = []

        # Create buttons
        for i in range(button_count):
            button = BlockButton(size=size)

            def create_signal_handler(index):
                def send_signal():
                    return self.signal_button_click.emit(index)

                return send_signal

            button.clicked.connect(create_signal_handler(i))

            self.buttons.append(button)
            layout.addWidget(button)
            layout.setAlignment(button, Qt.AlignCenter)


class ObjectRequiringMempool(QObject):
    def __init__(self, mempool_data: MempoolData, parent=None) -> None:
        super().__init__(parent=parent)

        self.count_signal_data_updated = 0
        self.mempool_data = mempool_data

        def refresh_if_visible():
            # make sure that the inital data from mempoolspace refreshes the button, even if it is not visible.
            if self.count_signal_data_updated == 0 or self.button_group.isVisible():
                if "button_group" in dir(self):
                    self.refresh()
            self.count_signal_data_updated += 1

        self.mempool_data.signal_data_updated.connect(refresh_if_visible)

        self.timer = QTimer()
        self.timer.timeout.connect(self.mempool_data.set_data_from_mempoolspace)
        self.timer.start(10 * 60 * 1000)  # 10 minutes in milliseconds

    def refresh(self, **kwargs):
        raise NotImplementedError()

    def set_mempool_block_unknown_fee_rate(
        self, i, confirmation_time: bdk.BlockTime = None
    ):
        logger.error("This should not be called")


class MempoolButtons(ObjectRequiringMempool):
    "Showing multiple buttons of the next, the 2. and the 3. block templates according to the mempool"
    signal_click = Signal(float)

    def __init__(self, mempool_data: MempoolData, button_count=3, parent=None) -> None:
        super().__init__(mempool_data=mempool_data, parent=parent)

        self.button_group = VerticalButtonGroup(
            button_count=button_count, parent=parent
        )

        self.button_group.signal_button_click.connect(self._on_button_click)
        self.refresh()

    def refresh(self, **kwargs):
        if self.mempool_data is None:
            return

        depths = np.arange(len(self.button_group.buttons) + 1) * 1e6
        block_fee_borders = fees_of_depths(self.mempool_data.data, depths)
        self.median_block_fee_borders = fees_of_depths(
            self.mempool_data.data, depths + 0.5e6
        )

        for i, button in enumerate(self.button_group.buttons):
            button.label_approximate_median_fee.set(
                self.median_block_fee_borders[i], block_type=BlockType.projected
            )
            button.label_fee_range.set(block_fee_borders[i + 1], block_fee_borders[i])
            button.set_background_gradient(
                block_fee_borders[i + 1], block_fee_borders[i], BlockType.projected
            )

    def _on_button_click(self, i: int):
        print(i, self.median_block_fee_borders[i])
        self.signal_click.emit(self.median_block_fee_borders[i])


class MempoolProjectedBlock(ObjectRequiringMempool):
    "The Button showing the block in which the fee_rate fits"
    signal_click = Signal(float)

    def __init__(
        self, mempool_data: MempoolData, url: str = None, fee_rate=1, parent=None
    ) -> None:
        super().__init__(mempool_data=mempool_data, parent=parent)

        self.url = url
        self.fee_rate = fee_rate

        self.button_group = VerticalButtonGroup(size=100, button_count=1, parent=parent)
        self.refresh()

        self.button_group.signal_button_click.connect(self._on_button_click)

    def set_unknown_fee_rate(self):
        for button in self.button_group.buttons:
            button.clear_labels()
            button.label_title.set("Unconfirmed", BlockType.projected)
            button.label_explorer.set(BlockType.projected)
            button.set_background_gradient(0, 1, BlockType.projected)

    def refresh(self, fee_rate=None, **kwargs):
        self.fee_rate = fee_rate if fee_rate else self.fee_rate
        if self.mempool_data is None:
            return

        if self.fee_rate is None:
            self.set_unknown_fee_rate()
            return

        block_number = fee_to_blocknumber(self.mempool_data.data, self.fee_rate)
        depths = np.array([block_number - 1, block_number]) * 1e6
        block_fee_borders = fees_of_depths(self.mempool_data.data, depths)
        self.median_block_fee_borders = fees_of_depths(
            self.mempool_data.data, depths + 0.5e6
        )

        for i, button in enumerate(self.button_group.buttons):
            button.label_title.set(f"~{block_number}. Block", BlockType.projected)
            button.label_approximate_median_fee.set(
                self.median_block_fee_borders[i], block_type=BlockType.projected
            )
            button.label_fee_range.set(block_fee_borders[i + 1], block_fee_borders[i])
            button.label_time_estimation.set(block_number, BlockType.projected)
            button.set_background_gradient(
                block_fee_borders[i + 1], block_fee_borders[i], BlockType.projected
            )

    def _on_button_click(self, i: int):
        open_website(self.url)
        self.signal_click.emit(self.median_block_fee_borders[i])


class ConfirmedBlock(ObjectRequiringMempool):
    "Showing a confirmed block"
    signal_click = Signal(str)  # txid

    def __init__(
        self,
        mempool_data,
        url: str = None,
        confirmation_time: bdk.BlockTime = None,
        fee_rate=None,
        parent=None,
    ) -> None:
        super().__init__(mempool_data=mempool_data, parent=parent)

        self.button_group = VerticalButtonGroup(button_count=1, parent=parent, size=120)
        self.fee_rate = fee_rate
        self.confirmation_time = confirmation_time
        self.url = url

        # self.mempool_data.signal_data_updated.connect(self.refresh)
        self.button_group.signal_button_click.connect(self._on_button_click)

    def refresh(
        self, fee_rate=None, confirmation_time=None, chain_height=None, **kwargs
    ):
        self.fee_rate = fee_rate if fee_rate else self.fee_rate
        self.confirmation_time = (
            confirmation_time if confirmation_time else self.confirmation_time
        )
        if not self.confirmation_time:
            return

        for i, button in enumerate(self.button_group.buttons):
            button.label_title.set(
                f"Block {self.confirmation_time.height}", BlockType.confirmed
            )
            if chain_height is None:
                button.label_number_confirmations.setText("")
                button.label_block_height.set(
                    self.confirmation_time.height, BlockType.confirmed
                )
            else:
                button.label_number_confirmations.set(
                    chain_height - self.confirmation_time.height + 1,
                    BlockType.confirmed,
                )
                button.label_block_height.setText("")

            button.label_explorer.set(BlockType.confirmed)
            if self.fee_rate:
                button.set_background_gradient(
                    self.fee_rate, self.fee_rate, BlockType.confirmed
                )
                button.label_exact_median_fee.set(fee_rate, BlockType.confirmed)
            else:
                button.set_background_gradient(0, 1, BlockType.confirmed)
                button.label_exact_median_fee.setText("")

    def _on_button_click(self, i: int):
        open_website(self.url)
        self.signal_click.emit(self.fee_rate)


if __name__ == "__main__":
    from PySide2.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)

    widget = VerticalButtonGroup(3)
    widget.show()

    sys.exit(app.exec_())

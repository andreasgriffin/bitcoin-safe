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
    fee_to_depth,
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


class BlockButton(QPushButton):
    def __init__(self, size=100, block_type=BlockType.projected, parent=None):
        super().__init__(parent=parent)
        self.block_type = block_type

        # Create labels for each text line
        self.labels = [QLabel() for _ in range(4)]
        for label in self.labels:
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(True)
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            # label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = center_in_widget(self.labels, self, direction="v")

        # Ensure buttons are square
        self.setMinimumHeight(size)
        self.setMinimumWidth(size)
        # self.setMaximumWidth(size)
        # self.setMinimumSize(size, 10)
        # self.setMaximumSize(size, size)

    def update_title(self, title: str):
        self.labels[2].setText(
            f"<span style='color: {'white' if self.block_type else 'black'}; font-size: 16px;'>{title}</span>"
        )

    def set_background_gradient(self, color_top: QColor, color_bottom: QColor):
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

    def update_median_fee(self, median_fee: float, is_exact=False):
        if isinstance(median_fee, str):
            s = median_fee
        else:
            if is_exact:
                s = f"{round(median_fee, 1)} Sat/vB"
            else:
                s = f"~{int(median_fee)} Sat/vB"

        self.labels[0].setText(
            f"<span style='color: {'white' if self.block_type else 'black'}; font-size: 12px;'>{s}</span>"
        )

    def update_fee_range(self, min_fee, max_fee):
        if max_fee is None:
            s = f"{round(min_fee, 1 )} Sat/vB"
        else:
            s = f"{int(min_fee)} - {int(max_fee)} Sat/vB"

        self.labels[1].setText(
            f"<span style='color: #eee002; font-size: 10px;'>{s}</span>"
        )
        if self.block_type == BlockType.confirmed:
            self.set_background_gradient("#115fb0", "#9239f3")
        else:
            self.set_background_gradient(
                fee_to_color(min_fee, mempoolFeeColors),
                fee_to_color(max_fee, mempoolFeeColors),
            )

    def update_bottom_text(self, blocknumber):
        if isinstance(blocknumber, str):
            s = blocknumber
        elif blocknumber < 6:
            s = f"~in {(blocknumber)*10} min</span>"
        else:
            s = f"~in {round(blocknumber/6)} hours"

        if self.block_type == BlockType.confirmed:
            s += "visit\nmempool.space"

        self.labels[3].setText(
            f"<span style='color: {'white' if self.block_type else 'black'}; font-size: 12px;'>{s}</span>"
        )


class VerticalButtonGroup(QScrollArea):
    signal_button_click = Signal(int)

    def __init__(
        self, button_count=3, block_type=BlockType.projected, parent=None, size=100
    ):
        super().__init__(parent)
        self.setMinimumWidth(size + 30)
        self.setMinimumHeight(size + 20)
        content_widget = QWidget()
        self.setWidget(content_widget)
        layout = QVBoxLayout(content_widget)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # layout.setContentsMargins(20, 5, 20, 5)  # Left, Top, Right, Bottom margins
        self.installEventFilter(self)

        self.setWidgetResizable(True)
        self.buttons: List[BlockButton] = []

        # Create buttons
        for i in range(button_count):
            button = BlockButton(size=size, block_type=block_type, parent=self)
            button.update_title("Next Block" if i == 0 else f"{i+1}. Block")
            button.update_median_fee(37)
            button.update_fee_range(32, 336)
            button.update_bottom_text(i + 1)

            def create_signal_handler(index):
                def send_signal():
                    return self.signal_button_click.emit(index)

                return send_signal

            button.clicked.connect(create_signal_handler(i))

            self.buttons.append(button)
            layout.addWidget(button)
            layout.setAlignment(button, Qt.AlignCenter)

    def showEvent(self, event):
        self.set_horizontal_scroll()
        super().showEvent(event)

    def set_horizontal_scroll(self):
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().maximum() / 2)

    def eventFilter(self, obj, event):
        if obj == self and event.type() == QEvent.Resize:
            self.set_horizontal_scroll()
        return super().eventFilter(obj, event)


class ObjectRequiringMempool(QObject):
    def __init__(self, mempool_data: MempoolData, parent=None) -> None:
        super().__init__(parent=parent)

        self.count_signal_data_updated = 0
        self.mempool_data = mempool_data

        def refresh_if_visible():
            # make sure that the inital data from mempoolspace refreshes the button, even if it is not visible.
            if self.count_signal_data_updated == 0 or self.button_group.isVisible():
                self.refresh()
            self.count_signal_data_updated += 1

        self.mempool_data.signal_data_updated.connect(refresh_if_visible)

        self.timer = QTimer()
        self.timer.timeout.connect(self.mempool_data.set_data_from_mempoolspace)
        self.timer.start(10 * 60 * 1000)  # 10 minutes in milliseconds

    def refresh(self):
        raise NotImplementedError()


class MempoolButtons(ObjectRequiringMempool):
    signal_click = Signal(float)

    def __init__(
        self, mempool_data: MempoolData, button_count=3, fee_rate=1, parent=None
    ) -> None:
        super().__init__(mempool_data=mempool_data, parent=parent)

        self.fee_rate = fee_rate
        self.button_group = VerticalButtonGroup(
            button_count=button_count, block_type=BlockType.projected, parent=parent
        )

        self.button_group.signal_button_click.connect(self._on_button_click)
        self.refresh()

    def refresh(self):
        if self.mempool_data is None:
            return

        depths = np.arange(len(self.button_group.buttons) + 1) * 1e6
        block_fee_borders = fees_of_depths(self.mempool_data.data, depths)
        self.median_block_fee_borders = fees_of_depths(
            self.mempool_data.data, depths + 0.5e6
        )

        for i, button in enumerate(self.button_group.buttons):
            button.update_median_fee(self.median_block_fee_borders[i])
            button.update_fee_range(block_fee_borders[i + 1], block_fee_borders[i])

    def _on_button_click(self, i: int):
        print(i, self.median_block_fee_borders[i])
        self.signal_click.emit(self.median_block_fee_borders[i])

    def set_fee_rate(self, fee_rate, **kwargs):
        self.fee_rate = fee_rate


class MempoolProjectedBlock(ObjectRequiringMempool):
    signal_click = Signal(float)

    def __init__(
        self, mempool_data: MempoolData, url: str = None, fee_rate=1, parent=None
    ) -> None:
        super().__init__(mempool_data=mempool_data, parent=parent)

        self.fee_rate = fee_rate
        self.url = url

        self.button_group = VerticalButtonGroup(
            button_count=1, block_type=BlockType.unconfirmed, parent=parent
        )
        self.refresh()

        self.button_group.signal_button_click.connect(self._on_button_click)

    def set_fee_rate(self, fee_rate, **kwargs):
        self.fee_rate = fee_rate
        self.refresh()

    def refresh(self):
        if self.mempool_data is None:
            return
        block_number = fee_to_blocknumber(self.mempool_data.data, self.fee_rate)
        depths = np.array([block_number - 1, block_number]) * 1e6
        block_fee_borders = fees_of_depths(self.mempool_data.data, depths)
        self.median_block_fee_borders = fees_of_depths(
            self.mempool_data.data, depths + 0.5e6
        )

        for i, button in enumerate(self.button_group.buttons):
            button.update_title(f"~{block_number}. Block")
            button.update_median_fee(self.median_block_fee_borders[i])
            button.update_fee_range(block_fee_borders[i + 1], block_fee_borders[i])
            button.update_bottom_text(block_number)

    def _on_button_click(self, i: int):
        open_website(self.url)
        self.signal_click.emit(self.median_block_fee_borders[i])


class ConfirmedBlock(ObjectRequiringMempool):
    signal_click = Signal(str)  # txid

    def __init__(
        self,
        mempool_data,
        url: str = None,
        confirmation_time: bdk.BlockTime = None,
        fee_rate=1,
        parent=None,
    ) -> None:
        super().__init__(mempool_data=mempool_data, parent=parent)

        self.button_group = VerticalButtonGroup(
            button_count=1, block_type=BlockType.confirmed, parent=parent, size=130
        )
        self.set_fee_rate(confirmation_time, fee_rate)
        self.url = url

        # self.mempool_data.signal_data_updated.connect(self.refresh)
        self.button_group.signal_button_click.connect(self._on_button_click)

    def set_fee_rate(self, confirmation_time: bdk.BlockTime, fee_rate):
        self.fee_rate = fee_rate
        self.confirmation_time = confirmation_time
        self.refresh()

    def refresh(self):
        if not self.confirmation_time:
            return
        for i, button in enumerate(self.button_group.buttons):
            button.update_title(f"Block {self.confirmation_time.height}")
            button.update_median_fee("Confirmed")
            button.update_fee_range(self.fee_rate, None)
            button.update_bottom_text("")

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

from PySide2.QtWidgets import QPushButton, QLabel, QVBoxLayout, QWidget, QApplication
from PySide2.QtCore import Qt
import numpy as np
from ...mempool import (
    MempoolData,
    get_block_min_fees,
    chartColors,
    bin_data,
    feeLevels,
    fetch_mempool_histogram,
    index_of_sum_until_including,
    fee_to_depth,
    fee_to_blocknumber,
    fees_of_depths,
)
from .util import center_in_widget
from PySide2.QtCore import Signal, QObject
from typing import List, Dict
from PySide2.QtWidgets import QSizePolicy


class BlockButton(QPushButton):
    def __init__(self, size=100, parent=None):
        super().__init__(parent)

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
        self.labels[0].setText(
            f"<span style='color: black; font-size: 16px;'>{title}</span>"
        )

    def update_median_fee(self, median_fee: float):
        self.labels[1].setText(
            f"<span style='color: black; font-size: 12px;'>~{int(median_fee)} sat/vB</span>"
        )

    def update_fee_range(self, min_fee, max_fee):
        self.labels[2].setText(
            f"<span style='color: darkorange; font-size: 10px;'>{int(min_fee)} - {int(max_fee)} sat/vB</span>"
        )

    def update_bottom_text(self, blocknumber):
        if blocknumber < 6:
            self.labels[3].setText(
                f"<span style='color: black; font-size: 12px;'>~in {(blocknumber)*10} min</span>"
            )
        else:
            self.labels[3].setText(
                f"<span style='color: black; font-size: 12px;'>~in {round(blocknumber/6)} hours</span>"
            )


class VerticalButtonGroup(QWidget):
    signal_button_click = Signal(int)

    def __init__(self, button_count=3, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.buttons: List[BlockButton] = []

        # Create buttons
        for i in range(button_count):
            button = BlockButton()
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


class MempoolButtons(QObject):
    signal_click = Signal(float)

    def __init__(
        self, mempool_data: MempoolData, button_count=3, fee_rate=1, parent=None
    ) -> None:
        super().__init__()

        self.mempool_data = mempool_data
        self.fee_rate = fee_rate

        self.button_group = VerticalButtonGroup(
            button_count=button_count, parent=parent
        )
        self._fill_buttton_text()

        # self.mempool_data.signal_current_data_updated.connect(self._fill_buttton_text)
        self.button_group.signal_button_click.connect(self._on_button_click)

    def _fill_buttton_text(self):
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

    def set_fee_rate(self, fee_rate):
        self.fee_rate = fee_rate


class MempoolProjectedBlock(QObject):
    signal_click = Signal(float)

    def __init__(self, mempool_data: MempoolData, fee_rate=1, parent=None) -> None:
        super().__init__()

        self.mempool_data = mempool_data
        self.fee_rate = fee_rate

        self.button_group = VerticalButtonGroup(button_count=1, parent=parent)
        self._fill_buttton_text()

        # self.mempool_data.signal_current_data_updated.connect(self._fill_buttton_text)
        self.button_group.signal_button_click.connect(self._on_button_click)

    def set_fee_rate(self, fee_rate):
        self.fee_rate = fee_rate
        self._fill_buttton_text()

    def _fill_buttton_text(self):
        if self.mempool_data is None:
            return

        def fees_of_depths(depths):
            fee_borders_indizes = [
                index_of_sum_until_including(self.mempool_data.data[:, 1], depth)
                for depth in depths
            ]
            return [self.mempool_data.data[i, 0] for i in fee_borders_indizes]

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
        print(i, self.median_block_fee_borders[i])
        self.signal_click.emit(self.median_block_fee_borders[i])


if __name__ == "__main__":
    from PySide2.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)

    widget = VerticalButtonGroup(3)
    widget.show()

    sys.exit(app.exec_())

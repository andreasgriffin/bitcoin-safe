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

from bitcoin_safe.signals import SignalsMin

logger = logging.getLogger(__name__)

import sys
from typing import Callable, List, Optional

from PyQt6.QtCore import QEvent, QModelIndex, QObject, QPoint, Qt
from PyQt6.QtGui import (
    QKeyEvent,
    QPainter,
    QStandardItem,
    QStandardItemModel,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.my_treeview import MyTreeView, SearchableTab
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.ui_tx import UITx_Creator

from ...i18n import translate


class HTMLDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        logger.debug("HTMLDelegate.paint")
        text = index.model().data(index, Qt.ItemDataRole.DisplayRole)
        option.state & QStyle.StateFlag.State_Selected

        # Use QStyle to draw the item. This respects the native theme.
        self.parent().style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, self.parent()
        )

        painter.save()

        # Set up the QTextDocument for HTML rendering
        document = QTextDocument()
        document.setHtml(text)

        # Calculate the vertical alignment to center the text
        text_height = document.size().height()
        center_y = option.rect.center().y() - (text_height / 2)

        painter.translate(option.rect.left(), center_y)
        document.drawContents(painter)

        painter.restore()


class ResultItem:
    def __init__(self, text: str, parent: "ResultItem" = None, obj=None, obj_key=None) -> None:
        self.text = text
        self.obj = obj
        self.obj_key = obj_key
        self.children: List["ResultItem"] = []

        self.set_parent(parent)

    def set_parent(self, parent: "ResultItem" = None):
        self.parent = parent
        if self.parent:
            if self not in self.parent.children:
                self.parent.children.append(self)


def demo_do_search(search_text: str):
    # Demo search function. Replace with actual search logic
    # Returns data in the format expected by CustomTreeView.set_data
    root = ResultItem("")

    if not search_text:
        return root

    search_text = search_text.strip()

    wallet = ResultItem("test", parent=root)
    addresses = ResultItem("addresses", parent=wallet)
    utxo = ResultItem("utxo", parent=wallet)
    history = ResultItem("history", parent=wallet)

    for l in [addresses, utxo, history]:
        for txt in ["aaaa", "bbbb"]:
            text = txt + search_text + txt
            ResultItem(text, parent=l)

    return root


def demo_on_click(item: ResultItem):
    print("Item Clicked:", item.text)


class CustomTreeView(QTreeView):
    def __init__(self, parent=None, on_click=None):
        super().__init__(parent)
        self.on_click = on_click
        self.setModel(QStandardItemModel())

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)  # Vertical scrollbar
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)  # Horizontal scrollbar

        self.setHeaderHidden(True)

        # Set the selection behavior to select full rows

        self.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )  # Allow selecting, but not editing
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # Disable editing

        # Make the last column stretch to fill the view
        # self.header().setStretchLastSection(True)
        # self.header().setSectionResizeMode(QHeaderView.ResizeToContents)

        # Connect the clicked signal to the callback function
        self.clicked.connect(self.handle_item_clicked)

    def model(self) -> QStandardItemModel:
        return super().model()

    def set_data(self, data: ResultItem):
        self.model().clear()  # Clear existing items
        self._populate_model(data)
        self.expandAll()  # Expand all items after setting data
        self.resizeColumnToContents(0)  # Resize the first column

    def _populate_model(self, result_item: ResultItem, model_parent=None):
        def add_child(child: ResultItem):
            model_item = QStandardItem(child.text)
            model_item.setEditable(False)
            model_item.result_item = child
            model_parent.appendRow(model_item)
            return model_item

        model_parent = self.model().invisibleRootItem() if model_parent is None else add_child(result_item)

        for child in result_item.children:
            # Recursively process the value
            self._populate_model(child, model_parent=model_parent)

    def handle_item_clicked(self, index: QModelIndex):
        if self.on_click and index.isValid():
            # Retrieve the item from the model
            item = self.model().itemFromIndex(index)
            # Perform the action you want based on the clicked item
            # For example, call a custom method of the item (if your item class has one)
            self.on_click(item.result_item)


class CustomPopup(QFrame):
    def __init__(self, parent=None):
        super(CustomPopup, self).__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 1, 0, 0)  # Left, Top, Right, Bottom margins

        # self.setFrameShape(QFrame.Panel)

        self.hide()  # Start hidden

    # Override keyPressEvent method
    def keyPressEvent(self, event: QKeyEvent):
        # Check if the pressed key is 'Esc'
        if event.key() == Qt.Key.Key_Escape:
            # Close the widget
            self.hide()


class SearchTreeView(QWidget):
    prev_main_window_pos = None

    def __init__(
        self,
        do_search: Callable[[str], ResultItem],
        parent=None,
        results_in_popup=True,
        on_click: Optional[Callable] = None,
        result_width=None,
        result_height=300,
    ):
        super().__init__(parent)
        self.on_click = on_click
        self.do_search = do_search
        self.result_width = result_width
        self.result_height = result_height
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.search_field = QLineEdit(self)
        self.search_field.setClearButtonEnabled(True)
        self.layout().addWidget(self.search_field)

        self.popup = CustomPopup(self)

        self.tree_view = CustomTreeView(self, on_click=on_click)
        self.tree_view.setVisible(False)
        if results_in_popup:
            self.popup.layout().addWidget(self.tree_view)
        else:
            self.layout().addWidget(self.tree_view)

        self.search_field.textChanged.connect(self.on_search)

        self.highlight_delegate = HTMLDelegate(self.tree_view)
        self.tree_view.setItemDelegate(self.highlight_delegate)

        self.updateUi()
        # Install event filter on the main window
        self.window().installEventFilter(self)

    def updateUi(self):
        self.search_field.setPlaceholderText(translate("mytreeview", "Type to search..."))

    def on_search(self, text: str):
        search_results = self.do_search(text)
        self.tree_view.set_data(search_results)
        self.tree_view.update()  # Update the view to redraw with highlights
        self.tree_view.setVisible(bool(search_results))

        if text:
            self.position_popup()
            self.popup.show()
        else:
            self.popup.hide()

    def position_popup(self):
        self.popup.setFixedSize(
            self.search_field.width() if self.result_width is None else self.result_width, self.result_height
        )  # Set a fixed size or adjust as needed

        # Calculate the global position for the popup
        global_pos = self.search_field.mapToGlobal(
            QPoint(int(self.search_field.width() - self.popup.width()), int(self.search_field.height()))
        )
        self.popup.move(global_pos)

    # Override keyPressEvent method
    def keyPressEvent(self, event: QKeyEvent):
        # Check if the pressed key is 'Esc'
        if event.key() == Qt.Key.Key_Escape:
            # Close the widget
            self.popup.hide()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj in [self, self.window()]:
            if event.type() == QEvent.Type.Move or event.type() == QEvent.Type.Resize:
                self.position_popup()
        return super().eventFilter(obj, event)


class SearchWallets(SearchTreeView):
    def __init__(
        self,
        get_qt_wallets: Callable[[], List[QTWallet]],
        signal_min: SignalsMin,
        parent=None,
        result_height=300,
        result_width=500,
    ):
        super().__init__(
            self.do_search,
            parent=parent,
            results_in_popup=True,
            on_click=self.search_result_on_click,
            result_height=result_height,
            result_width=result_width,
        )
        self.signal_min = signal_min

        self.get_qt_wallets = get_qt_wallets
        self.signal_min.language_switch.connect(self.updateUi)

    def search_result_on_click(self, result_item: ResultItem):
        # call the parent action first
        if result_item.parent is not None:
            self.search_result_on_click(result_item.parent)

        if isinstance(result_item.obj, MyTreeView):
            result_item.obj.select_row(result_item.obj_key, result_item.obj.key_column)
        elif isinstance(result_item.obj, SearchableTab):
            tabs: QTabWidget = result_item.obj.parent().parent()
            if isinstance(tabs, QTabWidget):
                tabs.setCurrentWidget(result_item.obj)
        elif isinstance(result_item.obj, UITx_Creator):
            tabs = result_item.obj.main_widget.parent().parent()
            if isinstance(tabs, QTabWidget):
                tabs.setCurrentWidget(result_item.obj.main_widget)
            result_item.obj.tabs_inputs.setCurrentWidget(result_item.obj.tab_inputs_utxos)
        elif isinstance(result_item.obj, QTWallet):
            wallet_tabs: QTabWidget = result_item.obj.tab.parent().parent()
            wallet_tabs.setCurrentWidget(result_item.obj.tab)

    def do_search(self, search_text: str) -> ResultItem:
        def format_result_text(matching_string: str) -> str:
            return matching_string.replace(
                search_text, f"<span style='background-color: #ADD8E6;'>{search_text}</span>"
            )

        search_text = search_text.strip()
        root = ResultItem("")
        for qt_wallet in self.get_qt_wallets():
            wallet_item = ResultItem(
                f"<span style='font-weight:bold;'>{qt_wallet.wallet.id}</span>", obj=qt_wallet
            )

            wallet_addresses = ResultItem(
                f"<span style='font-weight:bold;'>Addresses</span>", obj=qt_wallet.addresses_tab
            )
            for address in qt_wallet.wallet.get_addresses():
                if search_text in address:
                    ResultItem(
                        format_result_text(address),
                        parent=wallet_addresses,
                        obj=qt_wallet.address_list,
                        obj_key=address,
                    )
                    # connect also the higher parents, so the results appear at all
                    wallet_addresses.set_parent(wallet_item)
                    wallet_item.set_parent(root)
                label = qt_wallet.wallet.get_label_for_address(address, autofill_from_txs=False)
                if label and (search_text.lower() in label.lower()):
                    ResultItem(
                        format_result_text(label),
                        parent=wallet_addresses,
                        obj=qt_wallet.address_list,
                        obj_key=address,
                    )
                    # connect also the higher parents, so the results appear at all
                    wallet_addresses.set_parent(wallet_item)
                    wallet_item.set_parent(root)

            wallet_tx_ids = ResultItem(
                f"<span style='font-weight:bold;'>Transaction Ids</span>", obj=qt_wallet.history_tab
            )
            for txid, fulltxdetail in qt_wallet.wallet.get_dict_fulltxdetail().items():
                if search_text in txid:
                    ResultItem(
                        format_result_text(txid),
                        parent=wallet_tx_ids,
                        obj=qt_wallet.history_list,
                        obj_key=txid,
                    )
                    # connect also the higher parents, so the results appear at all
                    wallet_tx_ids.set_parent(wallet_item)
                    wallet_item.set_parent(root)
                label = qt_wallet.wallet.get_label_for_txid(txid, autofill_from_addresses=False)
                if label and (search_text.lower() in label.lower()):
                    ResultItem(
                        format_result_text(label),
                        parent=wallet_tx_ids,
                        obj=qt_wallet.history_list,
                        obj_key=txid,
                    )
                    # connect also the higher parents, so the results appear at all
                    wallet_tx_ids.set_parent(wallet_item)
                    wallet_item.set_parent(root)

            wallet_utxos = ResultItem(
                f"<span style='font-weight:bold;'>UTXOs</span>", obj=qt_wallet.uitx_creator
            )
            wallet_txos = ResultItem(
                f"<span style='font-weight:bold;'>Spent Outputs</span>", obj=qt_wallet.history_tab
            )
            for pythonutxo in qt_wallet.wallet.get_all_txos():
                outpoint_str = str(pythonutxo.outpoint)
                if search_text in outpoint_str:
                    if pythonutxo.is_spent_by_txid:
                        ResultItem(
                            format_result_text(outpoint_str),
                            parent=wallet_txos,
                            obj=qt_wallet.history_list,
                            obj_key=pythonutxo.is_spent_by_txid,
                        )
                        # connect also the higher parents, so the results appear at all
                        wallet_txos.set_parent(wallet_item)
                        wallet_item.set_parent(root)
                    else:
                        ResultItem(
                            format_result_text(outpoint_str),
                            parent=wallet_utxos,
                            obj=qt_wallet.uitx_creator.utxo_list,
                            obj_key=outpoint_str,
                        )
                        # connect also the higher parents, so the results appear at all
                        wallet_utxos.set_parent(wallet_item)
                        wallet_item.set_parent(root)

        return root


if __name__ == "__main__":

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()

            self.central_widget = QWidget()
            self.setCentralWidget(self.central_widget)

            self.layout = QVBoxLayout(self.central_widget)

            self.search_tree_view = SearchTreeView(demo_do_search, on_click=demo_on_click)
            self.layout.addWidget(self.search_tree_view)
            self.layout.addWidget(QPushButton())

    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())

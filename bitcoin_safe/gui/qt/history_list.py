#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2015 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
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

import os
import sys
import time
import datetime
from datetime import date
from typing import TYPE_CHECKING, Tuple, Dict
import threading
import enum
from decimal import Decimal
from ...util import TX_HEIGHT_FUTURE, TX_HEIGHT_INF, TX_HEIGHT_LOCAL, TX_HEIGHT_UNCONF_PARENT, TX_HEIGHT_UNCONFIRMED, TX_STATUS, THOUSANDS_SEP

from PySide2.QtGui import QBrush, QColor, QPainterPath, QMouseEvent
from PySide2.QtCore import (Qt, QPersistentModelIndex, QModelIndex, QAbstractItemModel,
                          QSortFilterProxyModel, QItemSelectionModel, QDate, QPoint)
from PySide2.QtWidgets import (QMenu, QHeaderView, QLabel, QMessageBox, 
                             QPushButton, QComboBox, QVBoxLayout, QCalendarWidget,
                             QGridLayout)

from ...i18n import _
from ...util import (block_explorer_URL, profiler, TxMinedInfo,
                           OrderedDictWithIndex, timestamp_to_datetime,
                           Satoshis, Fiat, format_time)
from ...logging import get_logger, Logger

from .custom_model import CustomNode, CustomModel
from .util import (read_QIcon, MONOSPACE_FONT, Buttons, CancelButton, OkButton,
                   filename_field, AcceptFileDragDrop, WindowModalDialog,
                   CloseButton, webopen, WWLabel, format_amount, MessageBoxMixin)
from .my_treeview import MyTreeView
from ...wallet import Wallet    


_logger = get_logger(__name__)


# note: this list needs to be kept in sync with another in kivy
TX_ICONS = [
    "unconfirmed.png",
    "warning.png",
    "offline_tx.png",
    "offline_tx.png",
    "clock1.png",
    "clock2.png",
    "clock3.png",
    "clock4.png",
    "clock5.png",
    "confirmed.png",
]


ROLE_SORT_ORDER = Qt.UserRole + 1000


class HistorySortModel(QSortFilterProxyModel):
    def lessThan(self, source_left: QModelIndex, source_right: QModelIndex):
        item1 = self.sourceModel().data(source_left, ROLE_SORT_ORDER)
        item2 = self.sourceModel().data(source_right, ROLE_SORT_ORDER)
        if item1 is None or item2 is None:
            raise Exception(f'UserRole not set for column {source_left.column()}')
        v1 = item1 
        v2 = item2 
        if v1 is None or isinstance(v1, Decimal) and v1.is_nan(): v1 = -float("inf")
        if v2 is None or isinstance(v2, Decimal) and v2.is_nan(): v2 = -float("inf")
        try:
            return v1 < v2
        except:
            return False

def get_item_key(tx_item):
    return tx_item.get('txid') or tx_item['payment_hash']



        
        
class HistoryNode(CustomNode):

    model: 'HistoryModel'
    
    
    def set_label(self, value=''):
        return value

    def get_data_for_role(self, index: QModelIndex, role: Qt.ItemDataRole):
        # note: this method is performance-critical.
        # it is called a lot, and so must run extremely fast.
        assert index.isValid()
        col = index.column()
        tx_item = self.get_data()
        is_lightning = tx_item.get('lightning', False)
        timestamp = tx_item['timestamp']
        short_id = None
        if is_lightning:
            status = 0
            if timestamp is None:
                status_str = 'unconfirmed'
            else:
                status_str = format_time(int(timestamp))
        else:
            txid = tx_item['txid']
            txpos_in_block = tx_item.get('txpos_in_block')
            if txpos_in_block is not None and txpos_in_block >= 0:
                short_id = f"{tx_item['height']}x{txpos_in_block}"
            conf = tx_item['confirmations']
            try:
                status, status_str = self.model.tx_status_cache[txid]
            except KeyError:
                tx_mined_info = self.model.tx_mined_info_from_tx_item(tx_item)
                status, status_str = self.model.wallet.get_tx_status(txid, tx_mined_info)

        if role == ROLE_SORT_ORDER:
            d = {
                HistoryColumns.STATUS:
                    # respect sort order of self.transactions (wallet.get_full_history)
                    -index.row(),
                HistoryColumns.DESCRIPTION:
                    tx_item['label'] if 'label' in tx_item else None,
                HistoryColumns.AMOUNT:
                    (tx_item['bc_value'].value if 'bc_value' in tx_item else 0)\
                    + (tx_item['ln_value'].value if 'ln_value' in tx_item else 0),
                HistoryColumns.BALANCE:
                    (tx_item['balance'].value if 'balance' in tx_item else 0),
                HistoryColumns.FIAT_VALUE:
                    tx_item['fiat_value'].value if 'fiat_value' in tx_item else None,
                HistoryColumns.FIAT_ACQ_PRICE:
                    tx_item['acquisition_price'].value if 'acquisition_price' in tx_item else None,
                HistoryColumns.FIAT_CAP_GAINS:
                    tx_item['capital_gain'].value if 'capital_gain' in tx_item else None,
                HistoryColumns.TXID: txid if not is_lightning else None,
                HistoryColumns.SHORT_ID: short_id,
            }
            return self.set_label(d[col])
        if role == MyTreeView.ROLE_EDIT_KEY:
            return self.set_label(get_item_key(tx_item))
        if role not in (Qt.DisplayRole, Qt.EditRole):
            if col == HistoryColumns.STATUS and role == Qt.DecorationRole:
                icon = "lightning" if is_lightning else TX_ICONS[status]
                return self.set_label(read_QIcon(icon))
            elif col == HistoryColumns.STATUS and role == Qt.ToolTipRole:
                if is_lightning:
                    msg = 'lightning transaction'
                else:  # on-chain
                    if tx_item['height'] == TX_HEIGHT_LOCAL:
                        # note: should we also explain double-spends?
                        msg = _("This transaction is only available on your local machine.\n"
                                "The currently connected server does not know about it.\n"
                                "You can either broadcast it now, or simply remove it.")
                    else:
                        msg = str(conf) + _(" confirmation" + ("s" if conf != 1 else ""))
                return self.set_label(msg)
            elif col > HistoryColumns.DESCRIPTION and role == Qt.TextAlignmentRole:
                return self.set_label(int(Qt.AlignRight | Qt.AlignVCenter))
            elif col > HistoryColumns.DESCRIPTION and role == Qt.FontRole:
                monospace_font = self.set_label(MONOSPACE_FONT)
                return self.set_label(monospace_font)
            #elif col == HistoryColumns.DESCRIPTION and role == Qt.DecorationRole and not is_lightning\
            #        and self.parent.wallet.invoices.paid.get(txid):
            #    return QVariant(read_QIcon("seal"))
            elif col in (HistoryColumns.DESCRIPTION, HistoryColumns.AMOUNT) \
                    and role == Qt.ForegroundRole and tx_item['value'].value < 0:
                red_brush = QBrush(QColor("#BC1E1E"))
                return red_brush
            elif col == HistoryColumns.FIAT_VALUE and role == Qt.ForegroundRole \
                    and not tx_item.get('fiat_default') and tx_item.get('fiat_value') is not None:
                blue_brush = QBrush(QColor("#1E1EFF"))
                return blue_brush
            return 
            
        if col == HistoryColumns.STATUS:
            return self.set_label(status_str)
        elif col == HistoryColumns.DESCRIPTION and 'label' in tx_item:
            return self.set_label(tx_item['label'])
        elif col == HistoryColumns.AMOUNT:
            bc_value = tx_item['bc_value'].value if 'bc_value' in tx_item else 0
            ln_value = tx_item['ln_value'].value if 'ln_value' in tx_item else 0
            value = bc_value + ln_value
            v_str = format_amount(value, is_diff=True, whitespaces=True)
            return self.set_label(v_str)
        elif col == HistoryColumns.BALANCE:
            balance = tx_item['balance'].value
            balance_str = format_amount(balance, whitespaces=True)
            return self.set_label(balance_str)
        elif col == HistoryColumns.FIAT_VALUE and 'fiat_value' in tx_item:
            value_str = self.model.fx.format_fiat(tx_item['fiat_value'].value)
            return self.set_label(value_str)
        elif col == HistoryColumns.FIAT_ACQ_PRICE and \
                tx_item['value'].value < 0 and 'acquisition_price' in tx_item:
            # fixme: should use is_mine
            acq = tx_item['acquisition_price'].value
            return self.set_label(self.model.fx.format_fiat(acq))
        elif col == HistoryColumns.FIAT_CAP_GAINS and 'capital_gain' in tx_item:
            cg = tx_item['capital_gain'].value
            return self.set_label(self.model.fx.format_fiat(cg))
        elif col == HistoryColumns.TXID:
            return self.set_label(txid) if not is_lightning else self.set_label('')
        elif col == HistoryColumns.SHORT_ID:
            return self.set_label(short_id or "")
        return  



from ...signals import Signals, Listener
class HistoryModel(CustomModel, Logger):

    def __init__(self, parent, fx, config, wallet:Wallet, signals:Signals):
        CustomModel.__init__(self, parent, len(HistoryColumns))
        Logger.__init__(self)
        self.fx = fx
        self.config = config
        self.wallet = wallet
        self.signals = signals
        self.view = None  # type: HistoryList
        self.transactions = OrderedDictWithIndex()
        self.tx_status_cache = {}  # type: Dict[str, Tuple[int, str]]
        
        self.listener_are_in_coincontrol = Listener(self.refresh, connect_to_signals=[signals.addresses_updated]) 

    def set_view(self, history_list: 'HistoryList'):
        # FIXME HistoryModel and HistoryList mutually depend on each other.
        # After constructing both, this method needs to be called.
        self.view = history_list  # type: HistoryList
        self.set_visibility_of_columns()

    def update_label(self, index):
        tx_item = index.internalPointer().get_data()
        tx_item['label'] = self.wallet.get_label_for_txid(get_item_key(tx_item))
        topLeft = bottomRight = self.createIndex(index.row(), HistoryColumns.DESCRIPTION)
        self.dataChanged.emit(topLeft, bottomRight, [Qt.DisplayRole])
        self.signals.utxos_updated.emit()
        # self.qt_wallet.utxo_list.update()

    def get_domain(self):
        """Overridden in address_dialog.py"""
        return self.wallet.get_addresses()

    def should_include_lightning_payments(self) -> bool:
        """Overridden in address_dialog.py"""
        return True

    def should_show_fiat(self):
        if not self.config.get('history_rates', False):
            return False
        fx = self.fx
        if not fx or not fx.is_enabled():
            return False
        return fx.has_history()

    def should_show_capital_gains(self):
        return self.should_show_fiat() and self.config.get('history_rates_capital_gains', False)

    @profiler
    def refresh(self, reason: str):
        self.logger.info(f"refreshing... reason: {reason}")
        # assert self.qt_wallet.main_window.loop == threading.current_thread(), 'must be called from GUI thread'
        assert self.view, 'view not set'
        if self.view.maybe_defer_update():
            return
        selected = self.view.selectionModel().currentIndex()
        selected_row = None
        if selected:
            selected_row = selected.row()
        fx = self.fx
        if fx: fx.history_used_spot = False
        wallet = self.wallet
        self.set_visibility_of_columns()
        
        transactions = wallet.get_full_history()
        
        if transactions == self.transactions:
            return
        old_length = self._root.childCount()
        if old_length != 0:
            self.beginRemoveRows(QModelIndex(), 0, old_length)
            self.transactions.clear()
            self._root = HistoryNode(self, None)
            self.endRemoveRows()
        parents = {}
        for tx_item in transactions:
            node = HistoryNode(self, tx_item)
            group_id = tx_item.get('group_id')
            if group_id is None:
                self._root.addChild(node)
            else:
                parent = parents.get(group_id)
                if parent is None:
                    # create parent if it does not exist
                    self._root.addChild(node)
                    parents[group_id] = node
                else:
                    # if parent has no children, create two children
                    if parent.childCount() == 0:
                        child_data = dict(parent.get_data())
                        node1 = HistoryNode(self, child_data)
                        parent.addChild(node1)
                        parent._data['label'] = child_data.get('group_label')
                        parent._data['bc_value'] = child_data.get('bc_value', Satoshis(0))
                    # add child to parent
                    parent.addChild(node)
                    # update parent data
                    parent._data['balance'] = tx_item['balance']
                    parent._data['value'] += tx_item['value']
                    if 'group_label' in tx_item:
                        parent._data['label'] = tx_item['group_label']
                    if 'bc_value' in tx_item:
                        parent._data['bc_value'] += tx_item['bc_value']
                    if 'fiat_value' in tx_item:
                        parent._data['fiat_value'] += tx_item['fiat_value']
                    if tx_item.get('txid') == group_id:
                        parent._data['txid'] = tx_item['txid']
                        parent._data['timestamp'] = tx_item['timestamp']
                        parent._data['height'] = tx_item['height']
                        parent._data['confirmations'] = tx_item['confirmations']

        new_length = self._root.childCount()
        self.beginInsertRows(QModelIndex(), 0, new_length-1)
        self.transactions = transactions        
        self.endInsertRows()
        
        
    

        if selected_row:
            self.view.selectionModel().select(self.createIndex(selected_row, 0), QItemSelectionModel.Rows | QItemSelectionModel.SelectCurrent)
        self.view.filter()
        # update time filter
        if not self.view.years and self.transactions:
            start_date = date.today()
            end_date = date.today()
            if len(self.transactions) > 0:
                start_date = self.transactions[0].get('date') or start_date
                end_date = self.transactions[len(self.transactions) - 1].get('date') or end_date
            self.view.years = [str(i) for i in range(start_date.year, end_date.year + 1)]
            self.view.period_combo.insertItems(1, self.view.years)
        # update tx_status_cache
        self.tx_status_cache.clear()
        for tx_item in self.transactions:
            tx_mined_info = self.tx_mined_info_from_tx_item(tx_item)
            self.tx_status_cache[tx_item['txid']] = self.wallet.get_tx_status(tx_item['txid'], tx_mined_info)
        # update counter
        num_tx = len(self.transactions)
        if self.view:
            self.view.num_tx_label.setText(_("{} transactions").format(num_tx))

    def set_visibility_of_columns(self):
        def set_visible(col: int, b: bool):
            self.view.showColumn(col) if b else self.view.hideColumn(col)
        # txid
        set_visible(HistoryColumns.TXID, False)
        set_visible(HistoryColumns.SHORT_ID, False)
        # fiat
        history = self.should_show_fiat()
        cap_gains = self.should_show_capital_gains()
        set_visible(HistoryColumns.FIAT_VALUE, history)
        set_visible(HistoryColumns.FIAT_ACQ_PRICE, history and cap_gains)
        set_visible(HistoryColumns.FIAT_CAP_GAINS, history and cap_gains)

    def update_fiat(self, idx):
        tx_item = idx.internalPointer().get_data()
        txid = tx_item['txid']
        fee = tx_item.get('fee')
        value = tx_item['value'].value
        fiat_fields = self.wallet.get_tx_item_fiat(
            txid=txid, amount_sat=value, fx=self.fx, tx_fee=fee.value if fee else None)
        tx_item.update(fiat_fields)
        self.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.ForegroundRole])

    def update_tx_mined_status(self, txid: str, tx_mined_info: TxMinedInfo):
        try:
            row = self.transactions.pos_from_key(txid)
            tx_item = self.transactions[txid]
        except KeyError:
            return
        self.tx_status_cache[txid] = self.wallet.get_tx_status(txid, tx_mined_info)
        tx_item.update({
            'confirmations':  tx_mined_info.conf,
            'timestamp':      tx_mined_info.timestamp,
            'txpos_in_block': tx_mined_info.txpos,
            'date':           timestamp_to_datetime(tx_mined_info.timestamp),
        })
        topLeft = self.createIndex(row, 0)
        bottomRight = self.createIndex(row, len(HistoryColumns) - 1)
        self.dataChanged.emit(topLeft, bottomRight)

    def on_fee_histogram(self):
        for txid, tx_item in list(self.transactions.items()):
            if tx_item.get('lightning'):
                continue
            tx_mined_info = self.tx_mined_info_from_tx_item(tx_item)
            if tx_mined_info.conf > 0:
                # note: we could actually break here if we wanted to rely on the order of txns in self.transactions
                continue
            self.update_tx_mined_status(txid, tx_mined_info)

    def headerData(self, section: int, orientation: Qt.Orientation, role: Qt.ItemDataRole):
        assert orientation == Qt.Horizontal
        if role != Qt.DisplayRole:
            return None
        fx = self.fx
        fiat_title = 'n/a fiat value'
        fiat_acq_title = 'n/a fiat acquisition price'
        fiat_cg_title = 'n/a fiat capital gains'
        if self.should_show_fiat():
            fiat_title = '%s '%fx.ccy + _('Value')
            fiat_acq_title = '%s '%fx.ccy + _('Acquisition price')
            fiat_cg_title =  '%s '%fx.ccy + _('Capital Gains')
        return {
            HistoryColumns.STATUS: _('Date'),
            HistoryColumns.DESCRIPTION: _('Description'),
            HistoryColumns.AMOUNT: _('Amount'),
            HistoryColumns.BALANCE: _('Balance'),
            HistoryColumns.FIAT_VALUE: fiat_title,
            HistoryColumns.FIAT_ACQ_PRICE: fiat_acq_title,
            HistoryColumns.FIAT_CAP_GAINS: fiat_cg_title,
            HistoryColumns.TXID: 'TXID',
            HistoryColumns.SHORT_ID: 'Short ID',
        }[section]

    def flags(self, idx: QModelIndex) -> int:
        extra_flags = Qt.NoItemFlags  # type: Qt.ItemFlag
        if idx.column() in self.view.editable_columns:
            extra_flags |= Qt.ItemIsEditable
        return super().flags(idx) | int(extra_flags)

    @staticmethod
    def tx_mined_info_from_tx_item(tx_item):
        # FIXME a bit hackish to have to reconstruct the TxMinedInfo...
        tx_mined_info = TxMinedInfo(
            height=tx_item['height'],
            conf=tx_item['confirmations'],
            timestamp=tx_item['timestamp'],
            wanted_height=tx_item.get('wanted_height', None),
        )
        return tx_mined_info


class HistoryList(MyTreeView, AcceptFileDragDrop, MessageBoxMixin):

    class Columns(MyTreeView.BaseColumnsEnum):
        STATUS = enum.auto()
        DESCRIPTION = enum.auto()
        AMOUNT = enum.auto()
        BALANCE = enum.auto()
        FIAT_VALUE = enum.auto()
        FIAT_ACQ_PRICE = enum.auto()
        FIAT_CAP_GAINS = enum.auto()
        TXID = enum.auto()
        SHORT_ID = enum.auto()  # ~SCID

    filter_columns = [
        Columns.STATUS,
        Columns.DESCRIPTION,
        Columns.AMOUNT,
        Columns.TXID,
        Columns.SHORT_ID,
    ]

    def tx_item_from_proxy_row(self, proxy_row):
        hm_idx = self.model().mapToSource(self.model().index(proxy_row, 0))
        return hm_idx.internalPointer().get_data()

    def should_hide(self, proxy_row):
        if self.start_date and self.end_date:
            tx_item = self.tx_item_from_proxy_row(proxy_row)
            date = tx_item['date']
            if date:
                in_interval = self.start_date <= date <= self.end_date
                if not in_interval:
                    return True
            return False

    def __init__(self, fx, config, signals:Signals, wallet:Wallet, model: HistoryModel):
        super().__init__(
            config=config,
            stretch_column=HistoryColumns.DESCRIPTION,
            editable_columns=[HistoryColumns.DESCRIPTION, HistoryColumns.FIAT_VALUE],
        )
        self.hm = model
        self.fx = fx
        self.signals = signals
        self.proxy = HistorySortModel(self)
        self.proxy.setSourceModel(model)
        self.setModel(self.proxy)
        AcceptFileDragDrop.__init__(self, ".txn")
        self.setSortingEnabled(True)
        self.start_date = None
        self.end_date = None
        self.years = []
        self.period_combo = QComboBox()
        self.start_button = QPushButton('-')
        self.start_button.pressed.connect(self.select_start_date)
        self.start_button.setEnabled(False)
        self.end_button = QPushButton('-')
        self.end_button.pressed.connect(self.select_end_date)
        self.end_button.setEnabled(False)
        self.period_combo.addItems([_('All'), _('Custom')])
        self.period_combo.activated.connect(self.on_combo)
        self.wallet = wallet 
        self.sortByColumn(HistoryColumns.STATUS, Qt.AscendingOrder)
        self.setRootIsDecorated(True)
        self.header().setStretchLastSection(False)
        for col in HistoryColumns:
            sm = QHeaderView.Stretch if col == self.stretch_column else QHeaderView.ResizeToContents
            self.header().setSectionResizeMode(col, sm)

    def update(self):
        self.hm.refresh('HistoryList.update()')
                



    def format_date(self, d):
        return str(datetime.date(d.year, d.month, d.day)) if d else _('None')

    def on_combo(self, x):
        s = self.period_combo.itemText(x)
        x = s == _('Custom')
        self.start_button.setEnabled(x)
        self.end_button.setEnabled(x)
        if s == _('All'):
            self.start_date = None
            self.end_date = None
            self.start_button.setText("-")
            self.end_button.setText("-")
        else:
            try:
                year = int(s)
            except:
                return
            self.start_date = datetime.datetime(year, 1, 1)
            self.end_date = datetime.datetime(year+1, 1, 1)
            self.start_button.setText(_('From') + ' ' + self.format_date(self.start_date))
            self.end_button.setText(_('To') + ' ' + self.format_date(self.end_date))
        self.hide_rows()

    def create_toolbar(self, config):
        toolbar, menu = self.create_toolbar_with_menu('')
        self.num_tx_label = toolbar.itemAt(0).widget()
        menu.addToggle(_("Filter by Date"), lambda: self.toggle_toolbar(config))
        # self.menu_fiat = menu.addConfig(_('Show Fiat Values'), 'history_rates', False, callback=self.main_window.app.update_fiat_signal.emit)
        # self.menu_capgains = menu.addConfig(_('Show Capital Gains'), 'history_rates_capital_gains', False, callback=self.main_window.app.update_fiat_signal.emit)
        self.menu_summary = menu.addAction(_("&Summary"), self.show_summary)
        menu.addAction(_("&Plot"), self.plot_history_dialog)
        menu.addAction(_("&Export"), self.export_history_dialog)
        hbox = self.create_toolbar_buttons()
        toolbar.insertLayout(1, hbox)
        self.update_toolbar_menu()
        return toolbar

    def update_toolbar_menu(self):
        fx = self.fx
        # self.menu_fiat.setEnabled(fx and fx.can_have_history())
        # setChecked because has_history can be modified through settings dialog
        # self.menu_fiat.setChecked(fx and fx.has_history())
        # self.menu_capgains.setEnabled(fx and fx.has_history())
        self.menu_summary.setEnabled(bool(fx and fx.has_history()))


    def get_toolbar_buttons(self):
        return self.period_combo, self.start_button, self.end_button

    def on_hide_toolbar(self):
        self.start_date = None
        self.end_date = None
        self.hide_rows()

    def select_start_date(self):
        self.start_date = self.select_date(self.start_button)
        self.hide_rows()

    def select_end_date(self):
        self.end_date = self.select_date(self.end_button)
        self.hide_rows()

    def select_date(self, button):
        d = WindowModalDialog(self, _("Select date"))
        d.setMinimumSize(600, 150)
        d.date = None
        vbox = QVBoxLayout()
        def on_date(date):
            d.date = date
        cal = QCalendarWidget()
        cal.setGridVisible(True)
        cal.clicked[QDate].connect(on_date)
        vbox.addWidget(cal)
        vbox.addLayout(Buttons(OkButton(d), CancelButton(d)))
        d.setLayout(vbox)
        if d.exec_():
            if d.date is None:
                return None
            date = d.date.toPyDate()
            button.setText(self.format_date(date))
            return datetime.datetime(date.year, date.month, date.day)

    def show_summary(self):
        if not self.hm.should_show_fiat():
            self.show_message(_("Enable fiat exchange rate with history."))
            return
        fx = self.fx
        h = self.wallet.get_detailed_history(
            from_timestamp = time.mktime(self.start_date.timetuple()) if self.start_date else None,
            to_timestamp = time.mktime(self.end_date.timetuple()) if self.end_date else None,
            fx=fx)
        summary = h['summary']
        if not summary:
            self.show_message(_("Nothing to summarize."))
            return
        start = summary['begin']
        end = summary['end']
        flow = summary['flow']
        start_date = start.get('date')
        end_date = end.get('date')
        format_amount_value = lambda x: format_amount(x.value) + ' ' + self.config.get_base_unit()
        format_fiat = lambda x: str(x) + ' ' + self.fx.ccy

        d = WindowModalDialog(self, _("Summary"))
        d.setMinimumSize(600, 150)
        vbox = QVBoxLayout()
        msg = 'CAPITAL_GAINS'
        vbox.addWidget(WWLabel(msg))
        grid = QGridLayout()
        grid.addWidget(QLabel(_("Begin")), 0, 1)
        grid.addWidget(QLabel(_("End")), 0, 2)
        #
        grid.addWidget(QLabel(_("Date")), 1, 0)
        grid.addWidget(QLabel(self.format_date(start_date)), 1, 1)
        grid.addWidget(QLabel(self.format_date(end_date)), 1, 2)
        #
        grid.addWidget(QLabel(_("BTC balance")), 2, 0)
        grid.addWidget(QLabel(format_amount_value(start['BTC_balance'])), 2, 1)
        grid.addWidget(QLabel(format_amount_value(end['BTC_balance'])), 2, 2)
        #
        grid.addWidget(QLabel(_("BTC Fiat price")), 3, 0)
        grid.addWidget(QLabel(format_fiat(start.get('BTC_fiat_price'))), 3, 1)
        grid.addWidget(QLabel(format_fiat(end.get('BTC_fiat_price'))), 3, 2)
        #
        grid.addWidget(QLabel(_("Fiat balance")), 4, 0)
        grid.addWidget(QLabel(format_fiat(start.get('fiat_balance'))), 4, 1)
        grid.addWidget(QLabel(format_fiat(end.get('fiat_balance'))), 4, 2)
        #
        grid.addWidget(QLabel(_("Acquisition price")), 5, 0)
        grid.addWidget(QLabel(format_fiat(start.get('acquisition_price', ''))), 5, 1)
        grid.addWidget(QLabel(format_fiat(end.get('acquisition_price', ''))), 5, 2)
        #
        grid.addWidget(QLabel(_("Unrealized capital gains")), 6, 0)
        grid.addWidget(QLabel(format_fiat(start.get('unrealized_gains', ''))), 6, 1)
        grid.addWidget(QLabel(format_fiat(end.get('unrealized_gains', ''))), 6, 2)
        #
        grid2 = QGridLayout()
        grid2.addWidget(QLabel(_("BTC incoming")), 0, 0)
        grid2.addWidget(QLabel(format_amount_value(flow['BTC_incoming'])), 0, 1)
        grid2.addWidget(QLabel(_("Fiat incoming")), 1, 0)
        grid2.addWidget(QLabel(format_fiat(flow.get('fiat_incoming'))), 1, 1)
        grid2.addWidget(QLabel(_("BTC outgoing")), 2, 0)
        grid2.addWidget(QLabel(format_amount_value(flow['BTC_outgoing'])), 2, 1)
        grid2.addWidget(QLabel(_("Fiat outgoing")), 3, 0)
        grid2.addWidget(QLabel(format_fiat(flow.get('fiat_outgoing'))), 3, 1)
        #
        grid2.addWidget(QLabel(_("Realized capital gains")), 4, 0)
        grid2.addWidget(QLabel(format_fiat(flow.get('realized_capital_gains'))), 4, 1)
        vbox.addLayout(grid)
        vbox.addWidget(QLabel(_('Cash flow')))
        vbox.addLayout(grid2)
        vbox.addLayout(Buttons(CloseButton(d)))
        d.setLayout(vbox)
        d.exec_()

    def plot_history_dialog(self):
        try:
            from electrum.plot import plot_history, NothingToPlotException
        except Exception as e:
            _logger.error(f"could not import electrum.plot. This feature needs matplotlib to be installed. exc={e!r}")
            self.show_message(
                _("Can't plot history.") + '\n' +
                _("Perhaps some dependencies are missing...") + " (matplotlib?)" + '\n' +
                f"Error: {e!r}"
            )
            return
        try:
            plt = plot_history(list(self.hm.transactions.values()))
            plt.show()
        except NothingToPlotException as e:
            self.show_message(str(e))

    def on_edited(self, idx, edit_key, *, text):
        index = self.model().mapToSource(idx)
        tx_item = index.internalPointer().get_data()
        column = index.column()
        key = get_item_key(tx_item)
        if column == HistoryColumns.DESCRIPTION:
            if self.wallet.set_label(key, text): #changed
                self.hm.update_label(index)
                # self.main_window.update_completions()
        elif column == HistoryColumns.FIAT_VALUE:
            self.wallet.set_fiat_value(key, self.fx.ccy, text, self.fx, tx_item['value'].value)
            value = tx_item['value'].value
            if value is not None:
                self.hm.update_fiat(index)
        else:
            assert False


    def mouseDoubleClickEvent(self, event: QMouseEvent):
        org_idx: QModelIndex = self.indexAt(event.pos())
        idx = self.proxy.mapToSource(org_idx)
        if not idx.isValid():
            # can happen e.g. before list is populated for the first time
            return
        tx_item = idx.internalPointer().get_data()
        if self.hm.flags(idx) & Qt.ItemIsEditable:
            super().mouseDoubleClickEvent(event)
        else:
            tx_hash = tx_item['txid']
            tx = self.wallet.get_bdk_tx(tx_hash)
            if not tx:
                return
            self.signals.show_transaction(tx)


    # def on_double_click(self, idx):
    #     tx_item = idx.internalPointer().get_data()
    #     txid = tx_item['txid']
    #     tx = self.wallet.get_bdk_tx(txid)
    #     if not tx:
    #         return
    #     self.signals.show_transaction(tx)

    def add_copy_menu(self, menu, idx):
        cc = menu.addMenu(_("Copy"))
        for column in HistoryColumns:
            if self.isColumnHidden(column):
                continue
            column_title = self.hm.headerData(column, Qt.Horizontal, Qt.DisplayRole)
            idx2 = idx.sibling(idx.row(), column)
            column_data = (self.hm.data(idx2, Qt.DisplayRole) or '').strip()
            cc.addAction(
                column_title,
                lambda text=column_data, title=column_title:
                self.place_text_on_clipboard(text, title=title))
        return cc

    def create_menu(self, position: QPoint):
        org_idx: QModelIndex = self.indexAt(position)
        idx = self.proxy.mapToSource(org_idx)
        if not idx.isValid():
            # can happen e.g. before list is populated for the first time
            return
        tx_item = idx.internalPointer().get_data()

        txid = tx_item['txid']
        tx = self.wallet.get_bdk_tx(txid)
        if not tx:
            return
        tx_URL = block_explorer_URL(self.config, 'tx', txid)
        tx_details = self.wallet.get_tx_info(tx)
        is_unconfirmed = tx_details.tx_mined_status.height <= 0
        menu = QMenu()
        menu.addAction(_("Details"), lambda: self.signals.show_transaction(tx))
        if tx_details.can_remove:
            menu.addAction(_("Remove"), lambda: self.remove_local_tx(txid))
        copy_menu = self.add_copy_menu(menu, idx)
        copy_menu.addAction(_("Transaction ID"), lambda: self.place_text_on_clipboard(txid, title="TXID"))
        menu_edit = menu.addMenu(_("Edit"))
        for c in self.editable_columns:
            if self.isColumnHidden(c): continue
            label = self.hm.headerData(c, Qt.Horizontal, Qt.DisplayRole)
            # TODO use siblingAtColumn when min Qt version is >=5.11
            persistent = QPersistentModelIndex(org_idx.sibling(org_idx.row(), c))
            menu_edit.addAction(_("{}").format(label), lambda p=persistent: self.edit(QModelIndex(p)))

        if is_unconfirmed and tx:
            if tx_details.can_bump:
                menu.addAction(_("Increase fee"), lambda: self.signals.bump_fee_dialog(tx))
            else:
                if tx_details.can_cpfp:
                    menu.addAction(_("Child pays for parent"), lambda: self.signals.cpfp_dialog(tx))
            if tx_details.can_dscancel:
                menu.addAction(_("Cancel (double-spend)"), lambda: self.signals.dscancel_dialog(tx))
        invoices = self.wallet.get_relevant_invoices_for_tx(txid)
        if len(invoices) == 1:
            menu.addAction(_("View invoice"), lambda inv=invoices[0]: self.signals.show_onchain_invoice(inv))
        elif len(invoices) > 1:
            menu_invs = menu.addMenu(_("Related invoices"))
            for inv in invoices:
                menu_invs.addAction(_("View invoice"), lambda inv=inv: self.signals.show_onchain_invoice(inv))
        if tx_URL:
            menu.addAction(_("View on block explorer"), lambda: webopen(tx_URL))
        menu.exec_(self.viewport().mapToGlobal(position))

    def remove_local_tx(self, txid: str):
        num_child_txs = len(self.wallet.get_depending_transactions(txid))
        question = _("Are you sure you want to remove this transaction?")
        if num_child_txs > 0:
            question = (_("Are you sure you want to remove this transaction and {} child transactions?")
                        .format(num_child_txs))
        if not self.question(msg=question,
                                    title=_("Please confirm")):
            return
        self.wallet.adb.remove_transaction(txid)
        self.wallet.save_db()
        # need to update at least: history_list, utxo_list, address_list
        self.signals.update_all_in_qt_wallet()

    def onFileAdded(self, fn):
        try:
            with open(fn) as f:
                tx = self.signals.tx_from_text(f.read())
        except IOError as e:
            self.show_error(e)
            return
        if not tx:
            return
        self.signals.save_transaction_into_wallet(tx)

    def export_history_dialog(self):
        d = WindowModalDialog(self, _('Export History'))
        d.setMinimumSize(400, 200)
        vbox = QVBoxLayout(d)
        defaultname = f'electrum-history-{self.wallet.basename()}.csv'
        select_msg = _('Select file to export your wallet transactions to')
        hbox, filename_e, csv_button = filename_field(self, self.config, defaultname, select_msg)
        vbox.addLayout(hbox)
        vbox.addStretch(1)
        hbox = Buttons(CancelButton(d), OkButton(d, _('Export')))
        vbox.addLayout(hbox)
        #run_hook('export_history_dialog', self, hbox)
        self.update()
        if not d.exec_():
            return
        filename = filename_e.text()
        if not filename:
            return
        try:
            self.do_export_history(filename, csv_button.isChecked())
        except (IOError, os.error) as reason:
            export_error_label = _("Electrum was unable to produce a transaction export.")
            self.show_critical(export_error_label + "\n" + str(reason), title=_("Unable to export history"))
            return
        self.show_message(_("Your wallet history has been successfully exported."))

    def do_export_history(self, file_name, is_csv):
        hist = self.wallet.get_detailed_history(fx=self.fx)
        txns = hist['transactions']
        lines = []
        if is_csv:
            for item in txns:
                lines.append([item['txid'],
                              item.get('label', ''),
                              item['confirmations'],
                              item['bc_value'],
                              item.get('fiat_value', ''),
                              item.get('fee', ''),
                              item.get('fiat_fee', ''),
                              item['date']])
        with open(file_name, "w+", encoding='utf-8') as f:
            if is_csv:
                import csv
                transaction = csv.writer(f, lineterminator='\n')
                transaction.writerow(["transaction_hash",
                                      "label",
                                      "confirmations",
                                      "value",
                                      "fiat_value",
                                      "fee",
                                      "fiat_fee",
                                      "timestamp"])
                for line in lines:
                    transaction.writerow(line)
            else:
                from electrum.util import json_encode
                f.write(json_encode(txns))

    def get_text_from_coordinate(self, row, col):
        return self.get_role_data_from_coordinate(row, col, role=Qt.DisplayRole)

    def get_role_data_from_coordinate(self, row, col, *, role):
        idx = self.model().mapToSource(self.model().index(row, col))
        return self.hm.data(idx, role) 


HistoryColumns = HistoryList.Columns

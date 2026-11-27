#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
#

from __future__ import annotations

import asyncio
import inspect
import json
from collections import Counter
from datetime import datetime
from threading import Event
from unittest.mock import AsyncMock, MagicMock

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from PyQt6.QtCore import QItemSelectionModel, QSignalBlocker
from pytestqt.qtbot import QtBot

from bitcoin_safe.foreign_utxo import ForeignUtxo
from bitcoin_safe.foreign_utxo_resolver import resolve_foreign_outpoints
from bitcoin_safe.gui.qt.category_manager.category_list import CategoryList
from bitcoin_safe.gui.qt.main import MainWindow
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole
from bitcoin_safe.gui.qt.ui_tx.ui_tx_creator import UITx_Creator
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.util import ColorScheme
from bitcoin_safe.gui.qt.utxo_list import UTXOList, UtxoListWithToolbar
from bitcoin_safe.psbt_util import FeeInfo, InputWeight, TxWeight, read_psbt, weight_to_vsize
from bitcoin_safe.pythonbdk_types import OutPoint, PythonUtxo, Recipient, TxOut
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason
from bitcoin_safe.tx import TxUiInfos
from tests.gui.qt.helpers import Shutter, main_window_context, setup_single_sig_wallet
from tests.helpers import TestConfig as ConfigForTest
from tests.non_gui.test_foreign_utxo import make_wallet, transaction
from tests.non_gui.test_psbt_util import p2wsh_psbt_0_2of3
from tests.non_gui.test_signers import test_seeds


def creator_class_kwargs(creator: UITx_Creator) -> dict:
    return {
        UITx_Creator.__name__: UITx_Creator.cls_kwargs(
            wallet_functions=creator.wallet_functions,
            config=creator.config,
            mempool_manager=creator.mempool_manager,
            fx=creator.fx,
        ),
        UTXOList.__name__: UTXOList.cls_kwargs(
            wallet_functions=creator.wallet_functions,
            config=creator.config,
            fx=creator.fx,
        ),
        UtxoListWithToolbar.__name__: UtxoListWithToolbar.cls_kwargs(config=creator.config),
        CategoryList.__name__: CategoryList.cls_kwargs(
            signals=creator.signals,
            config=creator.config,
            fx=creator.fx,
        ),
    }


@pytest.mark.marker_qt_2
def test_unsigned_size_fee_bound_warnings(qtbot: QtBot) -> None:
    from bitcoin_safe.gui.qt.ui_tx.fee_group import FeeGroup, FeeRateWarningBar, FeeWarningBar
    from bitcoin_safe.psbt_util import FeeInfo
    from bitcoin_safe.wallet import TxConfirmationStatus, TxStatus

    network = bdk.Network.REGTEST
    info = FeeInfo(400_000, 100, False, True, vsize_is_lower_bound=True)
    status = TxStatus(None, None, lambda: 0, TxConfirmationStatus.PSBT)
    ratio_bar = FeeWarningBar(network, "BTC")
    rate_bar = FeeRateWarningBar(network)
    qtbot.addWidget(ratio_bar)
    qtbot.addWidget(rate_bar)
    ratio_bar.set_fee_to_send_ratio(info, 1, network, status)
    assert not ratio_bar.isHidden()
    ratio_bar.set_fee_to_send_ratio(info, 100_000_000, network, status)
    assert ratio_bar.isHidden()
    rate_bar.update_fee_rate_warning(
        info.fee_rate(), 10, status.confirmation_status, fee_rate_is_upper_bound=True
    )
    assert not rate_bar.isHidden()
    rate_bar.update_fee_rate_warning(
        info.fee_rate(), 10_000, status.confirmation_status, fee_rate_is_upper_bound=True
    )
    assert rate_bar.isHidden()

    viewer = MagicMock()
    UITx_Viewer.update_high_fee_warning_label(viewer, TxConfirmationStatus.PSBT)
    viewer._update_high_fee_warning_label.assert_called_once()

    # Updating the fee group must not project a confirmation time from a bound.
    group = MagicMock()
    group.tr.side_effect = lambda text: text
    group.fee_info = info
    FeeGroup.updateUi(group)
    group.fee_rate_label.setText.assert_called_once_with("Fee rate at most 4000 sat/vB")
    group.mempool_buttons.setVisible.assert_called_once_with(False)
    group.mempool_buttons.refresh.assert_not_called()
    group.set_fee_amount_label.assert_called_once()


@pytest.mark.marker_qt_2
@pytest.mark.parametrize("custom_category", [False, True])
def test_unconfirmed_receiving_output_keeps_owning_wallet_category(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: ConfigForTest,
    monkeypatch: pytest.MonkeyPatch,
    custom_category: bool,
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_unconfirmed_category_{custom_category}")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name=f"unconfirmed_category_{custom_category}",
            seed=test_seeds[0],
        )
        wallet = qt_wallet.wallet
        creator = qt_wallet.uitx_creator
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        address = wallet.bdkwallet.peek_address(bdk.KeychainKind.EXTERNAL, 0).address
        category = "Savings" if custom_category else wallet.labels.get_default_category()
        if custom_category:
            wallet.labels.set_addr_category(ref=str(address), category=category)
        tx = transaction([bytes(address.script_pubkey().to_bytes())])
        wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=tx, last_seen=1)])
        wallet.clear_cache()
        outpoint = OutPoint(txid=tx.compute_txid(), vout=0)
        utxo = wallet.get_all_txos_dict()[str(outpoint)]
        assert utxo.address == str(address)

        # The sending wallet also knows this output, but does not own its address.
        other = make_wallet(test_seeds[1], "other_wallet")
        other.get_all_txos_dict.return_value = {str(outpoint): utxo}
        other.is_my_address.return_value = False
        other.get_tx.return_value = None
        other.get_label_for_txid.return_value = ""

        def get_other() -> MagicMock:
            return other

        creator.wallet_functions.get_wallets.connect(get_other, slot_name=other.id)
        try:
            creator.column_inputs.checkBox_manual_coin_select.setChecked(True)
            creator.refresh_inputs()
            view = creator.utxo_list
            row = view.find_row_by_key(outpoint)
            assert row is not None
            model = view._source_model
            view.set_filter_categories({category})
            index = view.proxy.mapFromSource(model.index(row, UTXOList.Columns.OUTPOINT))
            assert model.item(row, UTXOList.Columns.CATEGORY).text() == category
            assert model.item(row, UTXOList.Columns.WALLET_ID).text() == wallet.id
            assert not view.isRowHidden(index.row(), index.parent())
            view.set_filter_categories({"Other"})
            assert view.isRowHidden(index.row(), index.parent())
            view.set_filter_categories(None)
            assert not view.isRowHidden(index.row(), index.parent())

            # Ownership must win regardless of the order in which wallets are visited.
            monkeypatch.setattr("bitcoin_safe.gui.qt.utxo_list.get_wallets", lambda _: [other, wallet])
            view.update_content()
            row = view.find_row_by_key(outpoint)
            assert row is not None
            assert model.item(row, UTXOList.Columns.CATEGORY).text() == category
            assert model.item(row, UTXOList.Columns.WALLET_ID).text() == wallet.id
        finally:
            creator.wallet_functions.get_wallets.disconnect(get_other)


@pytest.mark.marker_qt_2
def test_spent_selection_stays_visible_and_can_be_deselected(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: ConfigForTest,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_spent_selection_{backend}")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="spent_selection",
            seed=test_seeds[0],
        )
        wallet = qt_wallet.wallet
        creator = qt_wallet.uitx_creator
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        address = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        tx = transaction([bytes(address.script_pubkey().to_bytes())] * 2)
        wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=tx, last_seen=1)])
        first, spent = (OutPoint(txid=tx.compute_txid(), vout=i) for i in range(2))
        utxos = {
            op: PythonUtxo(str(address), op, TxOut.from_bdk(tx.output()[op.vout])) for op in (first, spent)
        }
        available = [utxos[first], utxos[spent]]
        txos = {str(op): utxo for op, utxo in utxos.items()}
        monkeypatch.setattr(wallet, "get_all_utxos", lambda *args, **kwargs: available)
        monkeypatch.setattr(wallet, "get_all_txos_dict", lambda *args, **kwargs: txos)
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.question_dialog", lambda *args, **kwargs: False
        )
        messages: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: messages.append(text)
        )
        creator.column_inputs.checkBox_manual_coin_select.setChecked(True)
        creator.refresh_inputs()
        creator.set_selected_outpoints({first, spent})
        qtbot.waitUntil(
            lambda: set(creator.utxo_list.get_selected_outpoints()) == {first, spent}, timeout=5_000
        )
        qtbot.waitUntil(lambda: not creator._input_change_timer.isActive(), timeout=5_000)
        total_before = creator.column_inputs.totals.c2.l2.text()

        available[:] = [utxos[first]]
        txos[str(spent)] = PythonUtxo(str(address), spent, utxos[spent].txout, is_spent_by_txid="ab" * 32)
        with monkeypatch.context() as patch:
            refresh = MagicMock()
            patch.setattr(creator, "refresh_inputs", refresh)
            creator.on_wallet_updated(UpdateFilter(reason=UpdateFilterReason.TransactionChange))
            refresh.assert_not_called()
        creator.update_with_filter(
            UpdateFilter(refresh_all=True, reason=UpdateFilterReason.TransactionChange)
        )
        qtbot.waitUntil(lambda: creator.column_inputs.totals.c2.l2.text() != total_before, timeout=5_000)
        expected, _ = Satoshis(100_000, network=wallet.network).format_splitted(
            btc_symbol=creator.fx.config.bitcoin_symbol.value
        )
        assert creator.column_inputs.totals.c2.l2.text() == expected
        assert spent not in creator.get_outpoints()
        assert set(creator.utxo_list.get_selected_outpoints()) == creator.selected_outpoints == {first, spent}
        row = creator.utxo_list.find_row_by_key(spent)
        assert row is not None
        model = creator.utxo_list._source_model
        assert model.item(row, UTXOList.Columns.STATUS).text() == "Spent"
        assert model.item(row, UTXOList.Columns.STATUS).foreground().color() == ColorScheme.RED.as_color()
        assert model.item(row, UTXOList.Columns.ADDRESS).text() == str(address)
        assert model.item(row, UTXOList.Columns.AMOUNT).data(MyItemDataRole.ROLE_CLIPBOARD_DATA) == 100_000
        assert set(creator.get_tx_ui_infos().inputs) == {first}
        assert creator.utxo_list.get_selected_values() == [100_000]
        with qtbot.assertNotEmitted(creator.signal_create_tx):
            creator.create_tx()
        assert any("unavailable" in message for message in messages)

        creator.utxo_list.set_filter_categories({"a different category"})
        proxy_index = creator.utxo_list.proxy.mapFromSource(model.index(row, UTXOList.Columns.OUTPOINT))
        assert not creator.utxo_list.isRowHidden(proxy_index.row(), proxy_index.parent())
        creator.category_list.update_content()
        creator.utxo_list.update_content()
        assert set(creator.utxo_list.get_selected_outpoints()) == creator.selected_outpoints == {first, spent}
        creator.utxo_list.set_filter_categories(None)

        creator.category_list.force_full_ui_creation()
        category_model = creator.category_list._source_model
        assert category_model.rowCount()
        category = category_model.item(0, creator.category_list.key_column).data(
            MyItemDataRole.ROLE_CLIPBOARD_DATA
        )
        creator.category_list.select_rows(
            [category], creator.category_list.key_column, role=MyItemDataRole.ROLE_CLIPBOARD_DATA
        )
        with QSignalBlocker(creator.column_inputs.checkBox_auto_opportunistic_coin_select):
            creator.column_inputs.checkBox_auto_opportunistic_coin_select.setChecked(True)
        with monkeypatch.context() as patch:
            recalculate = MagicMock()
            patch.setattr(creator, "coin_selection_checkbox_state_change", recalculate)
            creator.category_list.force_full_ui_creation()
            recalculate.assert_not_called()
        assert set(creator.utxo_list.get_selected_outpoints()) == creator.selected_outpoints == {first, spent}
        with QSignalBlocker(creator.column_inputs.checkBox_auto_opportunistic_coin_select):
            creator.column_inputs.checkBox_auto_opportunistic_coin_select.setChecked(False)

        saved = creator.dumps()
        restored = UITx_Creator._from_dumps(saved, class_kwargs=creator_class_kwargs(creator))
        restored.set_category_core(qt_wallet.category_core)
        restored.show()
        try:
            qtbot.wait(300)
            assert set(restored.utxo_list.get_selected_outpoints()) == {first, spent}, (
                restored.selected_outpoints,
                restored.utxo_list.outpoints,
                restored.utxo_list.get_selected_outpoints(),
                restored.column_inputs.checkBox_manual_coin_select.isChecked(),
                messages,
            )
            assert spent not in restored.get_outpoints()
            assert spent in restored.utxo_list.outpoints
            assert spent not in restored.dump()["tx_ui_infos"].inputs
            # A selected local input remains visible even when wallet history no longer has its TXO.
            del txos[str(spent)]
            restored.refresh_inputs()
            row = restored.utxo_list.find_row_by_key(spent)
            assert row is not None
            model = restored.utxo_list._source_model
            assert not model.item(row, UTXOList.Columns.ADDRESS).text()
            assert model.item(row, UTXOList.Columns.AMOUNT).data(MyItemDataRole.ROLE_CLIPBOARD_DATA) is None
            with qtbot.assertNotEmitted(restored.signal_create_tx):
                restored.create_tx()
            row = restored.utxo_list.find_row_by_key(spent)
            assert row is not None
            index = restored.utxo_list.proxy.mapFromSource(
                restored.utxo_list._source_model.index(row, UTXOList.Columns.OUTPOINT)
            )
            selection_model = restored.utxo_list.selectionModel()
            assert selection_model is not None
            selection_model.select(
                index, QItemSelectionModel.SelectionFlag.Deselect | QItemSelectionModel.SelectionFlag.Rows
            )
            qtbot.waitUntil(lambda: spent not in restored.utxo_list.outpoints, timeout=5_000)
            assert set(restored.utxo_list.get_selected_outpoints()) == restored.selected_outpoints == {first}
            with qtbot.waitSignal(restored.signal_create_tx, timeout=5_000) as emitted:
                restored.create_tx()
            assert set(emitted.args[0].inputs) == {first}
        finally:
            restored.close()

        available.append(utxos[spent])
        txos[str(spent)] = utxos[spent]
        creator.update_with_filter(
            UpdateFilter(refresh_all=True, reason=UpdateFilterReason.TransactionChange)
        )
        assert set(creator.utxo_list.get_selected_outpoints()) == creator.selected_outpoints == {first, spent}
        row = creator.utxo_list.find_row_by_key(spent)
        assert row is not None
        assert creator.utxo_list._source_model.item(row, UTXOList.Columns.STATUS).text() == ""


@pytest.fixture
def psbt_without_input_utxos() -> bdk.Psbt:
    native = read_psbt(p2wsh_psbt_0_2of3)
    for inp in native.inputs:
        inp.witness_utxo = None
        inp.non_witness_utxo = None
    psbt = bdk.Psbt(native.b64encode(check_validity=False))
    assert FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt) is None
    with pytest.raises(bdk.ExtractTxError.MissingInputValue):
        psbt.extract_tx()
    return psbt


@pytest.mark.marker_qt_2
def test_open_incomplete_psbt_reports_error_without_creating_tab(
    psbt_without_input_utxos: bdk.Psbt, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = MagicMock()
    window.config.network = bdk.Network.REGTEST
    window.tr.side_effect = lambda text: text
    message = MagicMock()
    monkeypatch.setattr("bitcoin_safe.gui.qt.main.Message", message)
    create_viewer = MagicMock()
    monkeypatch.setattr("bitcoin_safe.gui.qt.main.create_tx_viewer", create_viewer)

    assert MainWindow.open_psbt_in_tab(window, psbt_without_input_utxos) is None
    message.assert_called_once()
    assert "lacks the input UTXOs" in message.call_args.args[0]
    window.get_tx_viewer.assert_not_called()
    create_viewer.assert_not_called()


@pytest.mark.marker_qt_2
def test_set_incomplete_psbt_preserves_viewer_state(
    psbt_without_input_utxos: bdk.Psbt, monkeypatch: pytest.MonkeyPatch
) -> None:
    viewer = MagicMock()
    viewer.tr.side_effect = lambda text: text
    viewer.network = bdk.Network.REGTEST
    original_data = viewer.data
    original_fee_info = viewer.fee_info
    message = MagicMock()
    monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.Message", message)

    UITx_Viewer.set_psbt(viewer, psbt_without_input_utxos)
    message.assert_called_once()
    assert viewer.data is original_data
    assert viewer.fee_info is original_fee_info
    viewer.get_tx_status.assert_not_called()


@pytest.mark.marker_qt_2
def test_edit_psbt_with_only_foreign_inputs_uses_open_wallet(
    qtbot: QtBot, mytest_start_time: datetime, test_config: ConfigForTest
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_edit_foreign_psbt")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="edit_foreign_psbt",
            seed=test_seeds[0],
        )
        wallet = qt_wallet.wallet
        foreign_tx = transaction([b"\x00\x14" + b"\x42" * 20])
        foreign_op = OutPoint(txid=foreign_tx.compute_txid(), vout=0)
        foreign = ForeignUtxo.from_outpoint(
            foreign_op, foreign_tx.output()[0], foreign_tx, [], wallet.network
        )
        destination = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        psbt = (
            bdk.TxBuilder()
            .add_foreign_utxo(foreign_op, foreign.psbt_input, foreign.satisfaction_weight)
            .manually_selected_only()
            .fee_rate(bdk.FeeRate.from_sat_per_vb(2))
            .add_recipient(destination.script_pubkey(), bdk.Amount.from_sat(50_000))
            .finish(wallet.bdkwallet)
        )
        main_window.open_tx_like_in_tab(psbt)
        viewer = main_window.tab_wallets.currentWidget()
        assert isinstance(viewer, UITx_Viewer)

        viewer.edit()

        creator = qt_wallet.uitx_creator
        qtbot.waitUntil(
            lambda: foreign_op in creator.foreign_inputs and not creator._import_busy, timeout=10_000
        )
        assert foreign_op in creator.selected_outpoints
        assert (str(destination), 50_000) in [(r.address, r.amount) for r in creator.recipients.recipients]


@pytest.mark.marker_qt_2
def test_import_outpoints_selects_local_and_resolved_foreign_inputs(
    qtbot: QtBot, mytest_start_time: datetime, test_config: ConfigForTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_import_outpoints")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="import_outpoints",
            seed=test_seeds[0],
        )
        wallet = qt_wallet.wallet
        creator = qt_wallet.uitx_creator
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        address = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        local_tx = transaction([bytes(address.script_pubkey().to_bytes())] * 2)
        wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=local_tx, last_seen=1)])
        local_points = [OutPoint(txid=local_tx.compute_txid(), vout=i) for i in range(2)]
        local_utxos = [
            PythonUtxo(str(address), op, TxOut.from_bdk(local_tx.output()[op.vout])) for op in local_points
        ]
        monkeypatch.setattr(wallet, "get_all_utxos", lambda *args, **kwargs: local_utxos)
        monkeypatch.setattr(
            wallet, "get_all_txos_dict", lambda *args, **kwargs: {str(u.outpoint): u for u in local_utxos}
        )
        foreign_tx = transaction([b"\x00\x14" + b"\x42" * 20])
        foreign_op = OutPoint(txid=foreign_tx.compute_txid(), vout=0)
        missing = OutPoint.from_str("ab" * 32 + ":0")

        async def fetch(txid: bdk.Txid) -> bdk.Transaction:
            if txid == foreign_tx.compute_txid():
                return foreign_tx
            raise ValueError("offline")

        monkeypatch.setattr(creator.mempool_manager, "fetch_transaction", fetch)
        errors: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: errors.append(text)
        )
        creator.import_outpoints([local_points[0]], select=True)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert creator.selected_outpoints == {local_points[0]}
        assert creator.column_inputs.checkBox_manual_coin_select.isChecked()
        assert set(creator.utxo_list.get_selected_outpoints()) == {local_points[0]}

        creator.import_outpoints([local_points[1], foreign_op, missing], select=True)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        expected = set(local_points) | {foreign_op}
        assert errors and "offline" in errors[0]
        assert creator.selected_outpoints == expected
        assert set(creator.utxo_list.get_selected_outpoints()) == expected


@pytest.mark.marker_qt_2
def test_import_mixed_psbt_resolves_and_rebuilds_outputs(
    qtbot: QtBot, mytest_start_time: datetime, test_config: ConfigForTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="mixed_import",
            seed=test_seeds[0],
        )
        wallet = qt_wallet.wallet
        creator = qt_wallet.uitx_creator
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        address = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        change = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.INTERNAL).address
        local_tx = transaction([bytes(address.script_pubkey().to_bytes())])
        wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=local_tx, last_seen=1)])
        local_op = OutPoint(txid=local_tx.compute_txid(), vout=0)
        local = PythonUtxo(str(address), local_op, TxOut.from_bdk(local_tx.output()[0]))
        monkeypatch.setattr(wallet, "get_all_utxos", lambda *args, **kwargs: [local])
        monkeypatch.setattr(wallet, "get_all_txos_dict", lambda *args, **kwargs: {str(local_op): local})
        foreign_tx = transaction([b"\x00\x14" + b"\x42" * 20])
        foreign_op = OutPoint(txid=foreign_tx.compute_txid(), vout=0)
        foreign = ForeignUtxo.from_outpoint(
            foreign_op, foreign_tx.output()[0], foreign_tx, [], wallet.network
        )
        raw_script = bdk.Script(bytes.fromhex("6a026869"))
        original = (
            bdk.TxBuilder()
            .add_utxo(local_op)
            .add_foreign_utxo(foreign_op, foreign.psbt_input, foreign.satisfaction_weight)
            .manually_selected_only()
            .fee_rate(bdk.FeeRate.from_sat_per_vb(2))
            .add_recipient(bdk.Script(b"\x00\x14" + b"\x43" * 20), bdk.Amount.from_sat(50_000))
            .add_recipient(raw_script, bdk.Amount.from_sat(1_000))
            .add_recipient(address.script_pubkey(), bdk.Amount.from_sat(12_000))
            .add_recipient(bdk.Script(b"\x00\x14" + b"\x44" * 20), bdk.Amount.from_sat(15_000))
            .drain_to(change.script_pubkey())
            .finish(wallet.bdkwallet)
        )
        original_tx = original.extract_tx_unchecked_fee_rate()
        # A valid PSBT without input UTXO maps forces independent previous-output resolution.
        imported = bdk.Psbt.from_unsigned_tx(original_tx)
        fetch = AsyncMock(return_value=foreign_tx)
        monkeypatch.setattr(creator.mempool_manager, "fetch_transaction", fetch)
        missing = OutPoint.from_str("ab" * 32 + ":0")
        edit_infos = TxUiInfos(hide_UTXO_selection=False)
        edit_infos.source_tx_inputs = {
            OutPoint.from_bdk(txin.previous_output): psbt_input
            for txin, psbt_input in zip(original_tx.input(), original.input(), strict=True)
        }
        edit_infos.source_tx_inputs[missing] = None
        edit_infos.recipients = [Recipient(str(address), 12_000)]
        edited = UITx_Creator(
            **UITx_Creator.cls_kwargs(
                creator.wallet_functions, creator.config, creator.mempool_manager, creator.fx
            ),
            category_core=qt_wallet.category_core,
            tx_ui_infos=edit_infos,
        )
        edited.show()
        try:
            qtbot.waitUntil(lambda: edited._ui_well_defined and not edited._import_busy, timeout=10_000)
            assert edited.selected_outpoints == {local_op, foreign_op, missing}
            assert foreign_op in edited.get_outpoints()
            assert missing not in edited.get_outpoints()
            assert edited.column_inputs.checkBox_manual_coin_select.isChecked()
            assert not edited.column_inputs.checkBox_auto_opportunistic_coin_select.isChecked()
            assert edited.column_inputs.upper_widget_category_selection.isHidden()
            assert edited.foreign_inputs[foreign_op].psbt_input.non_witness_utxo is not None
            assert [(r.address, r.amount) for r in edited.recipients.recipients] == [(str(address), 12_000)]
            fetch.assert_not_awaited()

            edited.set_selected_outpoints({foreign_op})
            row = edited.utxo_list.find_row_by_key(foreign_op)
            assert row is not None
            index = edited.utxo_list.proxy.mapFromSource(
                edited.utxo_list._source_model.index(row, UTXOList.Columns.OUTPOINT)
            )
            position = edited.utxo_list.visualRect(index).center()
            monkeypatch.setattr("bitcoin_safe.gui.qt.utxo_list.Menu.exec", lambda *args: None)
            menu = edited.utxo_list.create_menu(position)
            assert any(action.text() == "Remove foreign inputs" for action in menu.actions())
            assert all(action.text() != "Open Address Details" for action in menu.actions())
            edited.foreign_inputs[foreign_op].wallet_id = "Closed wallet"
            edited.refresh_inputs()
            menu = edited.utxo_list.create_menu(position)
            assert any(action.text() == "Remove foreign inputs" for action in menu.actions())
            assert all(action.text() != "Open Address Details" for action in menu.actions())
        finally:
            edited.close()
        edit_infos.utxos_read_only = True
        readonly = UITx_Creator(
            **UITx_Creator.cls_kwargs(
                creator.wallet_functions, creator.config, creator.mempool_manager, creator.fx
            ),
            category_core=qt_wallet.category_core,
            tx_ui_infos=edit_infos,
        )
        readonly.show()
        try:
            qtbot.waitUntil(lambda: readonly._ui_well_defined and not readonly._import_busy, timeout=10_000)
            assert readonly.selected_outpoints == {local_op, foreign_op, missing}
            assert readonly.column_inputs.checkBox_manual_coin_select.isChecked()
            assert not readonly.column_inputs.checkBox_auto_opportunistic_coin_select.isChecked()
            assert readonly.column_inputs.upper_widget_category_selection.isHidden()
            assert not readonly.column_inputs.isEnabled()
            assert not readonly.utxo_list.allow_edit
        finally:
            readonly.close()
        errors: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: errors.append(text)
        )
        confirm_change = MagicMock(return_value=True)
        monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.question_dialog", confirm_change)
        creator.column_fee.fee_group.spin_fee_rate.setValue(2)
        creator.merge_psbt(imported)
        qtbot.waitUntil(
            lambda: bool(errors) or set(creator.utxo_list.get_selected_outpoints()) == {local_op, foreign_op},
            timeout=10_000,
        )
        assert not errors
        recipients = creator.recipients.recipients
        assert foreign_op not in creator.dump()["tx_ui_infos"].inputs
        with monkeypatch.context() as patch:
            spendable_inputs = MagicMock(wraps=creator._spendable_inputs)
            patch.setattr(creator, "_spendable_inputs", spendable_inputs)
            creator.on_input_changed()
            creator._input_change_timer.stop()
            creator._apply_input_changed()
            assert spendable_inputs.call_count == 1
        original_outputs = [
            (bytes(o.script_pubkey.to_bytes()), o.value.to_sat()) for o in original_tx.output()
        ]
        change_script = bytes(change.script_pubkey().to_bytes())
        payments = [output for output in original_outputs if output[0] != change_script]
        assert (bytes(raw_script.to_bytes()), 1_000) in payments
        assert [
            (bytes(r.script_pubkey(wallet.network).to_bytes()), r.amount) for r in recipients
        ] == original_outputs
        raw_box = next(
            box for box in creator.recipients.get_recipient_group_boxes() if box.address.startswith("script:")
        )
        assert raw_box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: hi"
        assert all(not r.checked_max_amount for r in recipients)
        confirm_change.assert_not_called()
        # Remove the imported change output manually so the rebuilt transaction can
        # regenerate change at a different fee rate.
        creator.recipients.recipients = [
            recipient
            for recipient in recipients
            if bytes(recipient.script_pubkey(wallet.network).to_bytes()) != change_script
        ]
        creation_errors: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.qt_wallet.caught_exception_message",
            lambda error, **kwargs: creation_errors.append(str(error)),
        )
        monkeypatch.setattr(wallet, "get_min_broadcast_fee_rate", lambda: None)
        with qtbot.assertNotEmitted(qt_wallet.signal_psbt_created):
            with qtbot.waitSignal(qt_wallet.wallet_signals.finished_psbt_creation, timeout=10_000):
                creator.create_tx()
        assert creation_errors == ["OP_RETURN outputs must have an amount of zero."]
        raw_box = next(
            box for box in creator.recipients.get_recipient_group_boxes() if box.address.startswith("script:")
        )
        assert raw_box.amount == 1_000
        assert raw_box.recipient_widget.amount_spin_box.isEnabled()
        raw_box.amount = 0
        payments = [
            (script, 0 if script == bytes(raw_script.to_bytes()) else value) for script, value in payments
        ]
        infos = creator.get_tx_ui_infos()
        expected_weight = TxWeight(
            [InputWeight(foreign.satisfaction_weight)] * 2,
            [bdk.Script(script) for script, _ in payments] + [bdk.Script(change_script)],
        ).estimate()
        fee_estimate = creator.estimate_fee_info(2)
        assert fee_estimate.vsize == weight_to_vsize(expected_weight)
        assert fee_estimate.fee_amount == 2 * fee_estimate.vsize

        # Editing only the script must refresh the displayed fee, including its CompactSize prefix.
        original_address = raw_box.address
        raw_box.address = "script:" + "6a" + "00" * 252
        qtbot.waitUntil(lambda: not creator._input_change_timer.isActive(), timeout=5_000)
        long_script_estimate = creator.estimate_fee_info(2)
        assert long_script_estimate.vsize - fee_estimate.vsize == 251
        assert creator.column_fee.fee_group.fee_info is not None
        assert creator.column_fee.fee_group.fee_info.vsize == long_script_estimate.vsize
        raw_box.address = "script:6a0"
        assert creator.estimate_fee_info(2).vsize - fee_estimate.vsize == 18
        raw_box.address = "incomplete address"
        assert creator.estimate_fee_info(2).vsize - fee_estimate.vsize == 18
        raw_box.address = original_address
        with monkeypatch.context() as patch:
            change_info = MagicMock()
            change_info.address.script_pubkey.return_value = bdk.Script(bytes(34))
            patch.setattr(wallet.bdkwallet, "peek_address", lambda *args: change_info)
            assert creator.estimate_fee_info(2).vsize - fee_estimate.vsize == 34 - len(change_script)

        raw_box.recipient_widget.send_max_checkbox.setChecked(True)
        assert creator.estimate_fee_info(2).vsize == fee_estimate.vsize - 8 - 1 - len(change_script)
        raw_box.recipient_widget.send_max_checkbox.setChecked(False)

        changes = []
        fees = []
        for fee_rate in (2, 5):
            infos.fee_rate = fee_rate
            rebuilt = wallet.create_psbt(infos).psbt.extract_tx_unchecked_fee_rate()
            assert {OutPoint.from_bdk(i.previous_output) for i in rebuilt.input()} == {local_op, foreign_op}
            outputs = [(bytes(o.script_pubkey.to_bytes()), o.value.to_sat()) for o in rebuilt.output()]
            change_outputs = [
                o
                for o in rebuilt.output()
                if (derivation := wallet.bdkwallet.derivation_of_spk(o.script_pubkey))
                and derivation.keychain == bdk.KeychainKind.INTERNAL
            ]
            assert len(change_outputs) == 1
            generated_change_script = bytes(change_outputs[0].script_pubkey.to_bytes())
            assert Counter(output for output in outputs if output[0] != generated_change_script) == Counter(
                payments
            )
            assert len(outputs) == len(payments) + 1
            changes.append(change_outputs[0].value.to_sat())
            fees.append(200_000 - sum(amount for _, amount in outputs))
        assert fees[1] > fees[0]
        assert changes[0] - changes[1] == fees[1] - fees[0]
        assert fetch.await_count == 1
        restored = UITx_Creator._from_dumps(creator.dumps(), class_kwargs=creator_class_kwargs(creator))
        restored.set_category_core(qt_wallet.category_core)
        restored.show()
        try:
            qtbot.waitUntil(lambda: foreign_op in restored.utxo_list.get_selected_outpoints(), timeout=10_000)
            assert set(restored.utxo_list.get_selected_outpoints()) == {local_op, foreign_op}
            assert restored.foreign_inputs[foreign_op].psbt_input.non_witness_utxo
            assert [
                (bytes(r.script_pubkey(wallet.network).to_bytes()), r.amount)
                for r in restored.recipients.recipients
            ] == payments
        finally:
            restored.close()

        # Create the imported transaction in the GUI, then reopen it for editing.
        creation_errors.clear()
        with qtbot.waitSignal(creator.signal_create_tx, timeout=2_000):
            creator.create_tx()
            assert not errors
            confirm_change.assert_not_called()
        qtbot.waitUntil(
            lambda: (
                bool(creation_errors or errors)
                or isinstance(main_window.tab_wallets.currentWidget(), UITx_Viewer)
            ),
            timeout=10_000,
        )
        assert not errors
        assert not creation_errors
        viewer = main_window.tab_wallets.currentWidget()
        assert isinstance(viewer, UITx_Viewer)
        raw_box = next(
            box for box in viewer.recipients.get_recipient_group_boxes() if box.address.startswith("script:")
        )
        assert raw_box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: hi"
        created_tx = viewer.extract_tx()
        assert (bytes(raw_script.to_bytes()), 0) in [
            (bytes(output.script_pubkey.to_bytes()), output.value.to_sat()) for output in created_tx.output()
        ]
        viewer.edit()
        qtbot.waitUntil(
            lambda: any(r.address == "script:6a026869" for r in creator.recipients.recipients),
            timeout=10_000,
        )
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert ("script:6a026869", 0) in [(r.address, r.amount) for r in creator.recipients.recipients]
        raw_box = next(
            box for box in creator.recipients.get_recipient_group_boxes() if box.address.startswith("script:")
        )
        assert raw_box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: hi"
        edited_psbt = wallet.create_psbt(creator.get_tx_ui_infos()).psbt
        assert (bytes(raw_script.to_bytes()), 0) in [
            (bytes(output.script_pubkey.to_bytes()), output.value.to_sat())
            for output in edited_psbt.extract_tx_unchecked_fee_rate().output()
        ]
        viewer.set_tx(created_tx)
        raw_box = next(
            box for box in viewer.recipients.get_recipient_group_boxes() if box.address.startswith("script:")
        )
        assert raw_box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: hi"

        # A single internal output with no other outputs could be an intentional self-payment.
        creator.clear_ui()
        self_payment = (
            bdk.TxBuilder()
            .add_utxo(local_op)
            .manually_selected_only()
            .drain_to(change.script_pubkey())
            .finish(wallet.bdkwallet)
        )
        self_output = self_payment.extract_tx_unchecked_fee_rate().output()[0]
        creator.merge_psbt(self_payment)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert [(r.address, r.amount) for r in creator.recipients.recipients] == [
            (str(change), self_output.value.to_sat())
        ]
        self_payment_with_data = (
            bdk.TxBuilder()
            .add_utxo(local_op)
            .manually_selected_only()
            .add_recipient(raw_script, bdk.Amount.from_sat(0))
            .drain_to(change.script_pubkey())
            .finish(wallet.bdkwallet)
        )
        creator.clear_ui()
        creator.merge_psbt(self_payment_with_data)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert [
            (bytes(r.script_pubkey(wallet.network).to_bytes()), r.amount)
            for r in creator.recipients.recipients
        ] == [
            (bytes(o.script_pubkey.to_bytes()), o.value.to_sat())
            for o in self_payment_with_data.extract_tx_unchecked_fee_rate().output()
        ]
        creator.clear_ui()
        creator.merge_psbt(original)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert [
            (bytes(r.script_pubkey(wallet.network).to_bytes()), r.amount)
            for r in creator.recipients.recipients
        ] == original_outputs
        confirm_change.assert_not_called()

        # An imported nonstandard output stays visible and blocks a new transaction.
        arbitrary = (
            bdk.TxBuilder()
            .add_utxo(local_op)
            .manually_selected_only()
            .add_recipient(bdk.Script(b"\x51"), bdk.Amount.from_sat(1_000))
            .drain_to(change.script_pubkey())
            .finish(wallet.bdkwallet)
        )
        creator.clear_ui()
        creator.merge_psbt(arbitrary)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert ("script:51", 1_000) in [(r.address, r.amount) for r in creator.recipients.recipients]
        with pytest.raises(ValueError, match="output script is not allowed"):
            wallet.create_psbt(creator.get_tx_ui_infos())
        creation_errors.clear()
        with qtbot.assertNotEmitted(qt_wallet.signal_psbt_created):
            with qtbot.waitSignal(qt_wallet.wallet_signals.finished_psbt_creation, timeout=10_000):
                creator.create_tx()
        assert creation_errors == ["This output script is not allowed when creating a transaction."]
        assert ("script:51", 1_000) in [(r.address, r.amount) for r in creator.recipients.recipients]
        viewer.set_psbt(arbitrary)
        assert any(r.address == "script:51" for r in viewer.recipients.recipients)

        malformed = (
            bdk.TxBuilder()
            .add_utxo(local_op)
            .manually_selected_only()
            .add_recipient(bdk.Script(bytes.fromhex("6a02ff")), bdk.Amount.from_sat(0))
            .drain_to(change.script_pubkey())
            .finish(wallet.bdkwallet)
        )
        viewer.set_tx(malformed.extract_tx_unchecked_fee_rate())
        raw_box = next(
            box for box in viewer.recipients.get_recipient_group_boxes() if box.address.startswith("script:")
        )
        assert raw_box.address == "script:6a02ff"
        assert raw_box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: 0x6a02ff"


@pytest.mark.marker_qt_2
@pytest.mark.parametrize("last_seen", [0, 2])
def test_import_unconfirmed_payment_from_another_wallet(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: ConfigForTest,
    monkeypatch: pytest.MonkeyPatch,
    last_seen: int,
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_unconfirmed_payment_{last_seen}")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        sender = setup_single_sig_wallet(
            main_window, qtbot, shutter, test_config, f"sender_{last_seen}", test_seeds[0]
        )
        receiver = setup_single_sig_wallet(
            main_window, qtbot, shutter, test_config, f"receiver_{last_seen}", test_seeds[1]
        )
        creator = sender.uitx_creator
        sender_address = sender.wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        receiver_address = receiver.wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        funding = transaction([bytes(sender_address.script_pubkey().to_bytes())])
        sender.wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
        payment = (
            bdk.TxBuilder()
            .add_utxo(OutPoint(txid=funding.compute_txid(), vout=0))
            .manually_selected_only()
            .drain_to(receiver_address.script_pubkey())
            .finish(sender.wallet.bdkwallet)
            .extract_tx()
        )
        for wallet in (sender.wallet, receiver.wallet):
            wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=payment, last_seen=last_seen)])
            wallet.clear_cache()
        point = OutPoint(txid=payment.compute_txid(), vout=0)
        assert point in {utxo.outpoint for utxo in receiver.wallet.get_all_utxos()}
        messages: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: messages.append(text)
        )
        sender.tabs.setCurrentWidget(creator)
        creator.import_wallet_utxos(receiver.wallet)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert not messages
        assert point in creator.foreign_inputs
        row = creator.utxo_list.find_row_by_key(point)
        assert row is not None
        index = creator.utxo_list.proxy.mapFromSource(
            creator.utxo_list._source_model.index(row, UTXOList.Columns.OUTPOINT)
        )
        assert not creator.utxo_list.isRowHidden(index.row(), index.parent())

        # The receiving wallet spends the unconfirmed payment and gets unconfirmed change.
        child = (
            bdk.TxBuilder()
            .add_utxo(point)
            .manually_selected_only()
            .add_recipient(sender_address.script_pubkey(), bdk.Amount.from_sat(10_000))
            .finish(receiver.wallet.bdkwallet)
            .extract_tx()
        )
        for wallet in (sender.wallet, receiver.wallet):
            wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=child, last_seen=last_seen)])
            wallet.clear_cache()
        change = {
            utxo.outpoint
            for utxo in receiver.wallet.get_all_utxos()
            if utxo.outpoint.txid == child.compute_txid()
        }
        assert change
        creator.import_wallet_utxos(receiver.wallet)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert not messages
        assert change <= creator.foreign_inputs.keys()
        assert change <= set(creator.get_outpoints())
        assert change <= creator.utxo_list.get_displayed_outpoints()
        qtbot.waitUntil(lambda: not creator._input_change_timer.isActive(), timeout=10_000)
        for outpoint in change:
            row = creator.utxo_list.find_row_by_key(outpoint)
            assert row is not None
            index = creator.utxo_list.proxy.mapFromSource(
                creator.utxo_list._source_model.index(row, UTXOList.Columns.OUTPOINT)
            )
            assert not creator.utxo_list.isRowHidden(index.row(), index.parent())


@pytest.mark.marker_qt_2
def test_import_utxos_from_all_open_wallets(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: ConfigForTest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_all_wallets")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="all_wallets",
            seed=test_seeds[0],
        )
        creator = qt_wallet.uitx_creator
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        other_wallets = [make_wallet(test_seeds[i], f"other_{i}") for i in (1, 2)]
        outpoints = set()
        for wallet in other_wallets:
            wallet.labels = qt_wallet.wallet.labels
            wallet.is_my_address.return_value = True
            wallet.get_label_for_txid.return_value = ""
            wallet.is_change.return_value = False
            address = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
            tx = transaction([bytes(address.script_pubkey().to_bytes())])
            wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=tx, last_seen=1)])
            outpoint = OutPoint(txid=tx.compute_txid(), vout=0)
            utxo = PythonUtxo(str(address), outpoint, TxOut.from_bdk(tx.output()[0]))
            wallet.get_all_utxos.return_value = [utxo]
            wallet.get_all_txos_dict.return_value = {str(outpoint): utxo}
            outpoints.add(outpoint)

        def get_first() -> MagicMock:
            return other_wallets[0]

        def get_second() -> MagicMock:
            return other_wallets[1]

        creator.wallet_functions.get_wallets.connect(get_first, slot_name=other_wallets[0].id)
        creator.wallet_functions.get_wallets.connect(get_second, slot_name=other_wallets[1].id)
        messages: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: messages.append(text)
        )
        try:
            creator.update_add_source_menu()
            menu = next(
                action.menu()
                for action in creator.menu_add_source.actions()
                if action.text() == "Import UTXOs from wallet"
            )
            assert menu
            assert menu.actions()[0].text() == "Add UTXOs from all open wallets"
            menu.actions()[0].trigger()
            qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
            assert not messages
            assert set(creator.foreign_inputs) == outpoints
            assert not creator.selected_outpoints
        finally:
            creator.wallet_functions.get_wallets.disconnect(get_first)
            creator.wallet_functions.get_wallets.disconnect(get_second)


@pytest.mark.marker_qt_2
def test_wallet_import_skips_outputs_spent_by_unconfirmed_transaction(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: ConfigForTest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_unconfirmed_wallet_import")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="unconfirmed_wallet_import",
            seed=test_seeds[0],
        )
        creator = qt_wallet.uitx_creator
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        other = make_wallet(test_seeds[1], "other_wallet")
        other.labels = qt_wallet.wallet.labels
        other.is_my_address.return_value = True
        other.get_label_for_txid.return_value = ""
        other.get_label_for_address.return_value = ""
        other.is_change.return_value = False
        address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        funding = transaction([bytes(address.script_pubkey().to_bytes())] * 2)
        other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
        spent, remaining = [OutPoint(txid=funding.compute_txid(), vout=i) for i in range(2)]
        utxos = [
            PythonUtxo(str(address), op, TxOut.from_bdk(funding.output()[op.vout]))
            for op in (spent, remaining)
        ]
        other.get_all_utxos.return_value = utxos
        other.get_all_txos_dict.return_value = {str(utxo.outpoint): utxo for utxo in utxos}

        # Only the active wallet has seen the transaction spending the first output.
        destination = qt_wallet.wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        child = (
            bdk.TxBuilder()
            .add_utxo(spent)
            .manually_selected_only()
            .drain_to(destination.script_pubkey())
            .finish(other.bdkwallet)
            .extract_tx()
        )
        qt_wallet.wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=child, last_seen=2)])
        qt_wallet.wallet.clear_cache()
        assert str(spent) in qt_wallet.wallet.get_dict_fulltxdetail()[str(child.compute_txid())].inputs
        messages: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: messages.append(text)
        )

        def get_other() -> MagicMock:
            return other

        creator.wallet_functions.get_wallets.connect(get_other, slot_name=other.id)
        try:
            creator.import_wallet_utxos(other)
            qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
            assert not messages
            assert set(creator.foreign_inputs) == {remaining}
            assert not creator.selected_outpoints
        finally:
            creator.wallet_functions.get_wallets.disconnect(get_other)


@pytest.mark.marker_qt_2
def test_wallet_import_is_a_persistent_snapshot(
    qtbot: QtBot, mytest_start_time: datetime, test_config: ConfigForTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_wallet_snapshot")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="wallet_snapshot",
            seed=test_seeds[0],
        )
        creator = qt_wallet.uitx_creator
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        other = make_wallet(test_seeds[1], "other_wallet")
        other.labels = qt_wallet.wallet.labels
        other.is_my_address.return_value = True
        other.get_label_for_txid.return_value = ""
        other.is_change.return_value = False
        address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        tx = transaction([bytes(address.script_pubkey().to_bytes())] * 2)
        other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=tx, last_seen=1)])
        first, second = [OutPoint(txid=tx.compute_txid(), vout=i) for i in range(2)]
        utxos = [PythonUtxo(str(address), op, TxOut.from_bdk(tx.output()[op.vout])) for op in (first, second)]
        other.get_all_utxos.return_value = utxos[:1]
        other.get_all_txos_dict.return_value = {str(first): utxos[0]}
        messages: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: messages.append(text)
        )
        fetch = AsyncMock()
        monkeypatch.setattr(creator.mempool_manager, "fetch_transaction", fetch)

        def get_other() -> MagicMock:
            return other

        creator.wallet_functions.get_wallets.connect(get_other, slot_name=other.id)
        try:
            creator.update_add_source_menu()
            menu = next(
                action.menu()
                for action in creator.menu_add_source.actions()
                if action.text() == "Import UTXOs from wallet"
            )
            assert menu and all(not action.isCheckable() for action in menu.actions())
            creator.import_wallet_utxos(other)
            qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
            assert not messages
            assert set(creator.foreign_inputs) == {first}
            assert not creator.selected_outpoints
            other.get_all_utxos.return_value = utxos
            other.get_all_txos_dict.return_value = {str(u.outpoint): u for u in utxos}
            creator.on_wallet_updated(UpdateFilter(reason=UpdateFilterReason.TransactionChange))
            assert set(creator.foreign_inputs) == {first}
            creator.import_wallet_utxos(other)
            qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
            assert not messages
            assert set(creator.foreign_inputs) == {first, second}
            creator.set_selected_outpoints({first})
            other.get_all_txos_dict.return_value[str(first)] = PythonUtxo(
                str(address), first, utxos[0].txout, is_spent_by_txid="ab" * 32
            )
            creator.on_wallet_updated(UpdateFilter(reason=UpdateFilterReason.TransactionChange))
            assert first not in creator.get_outpoints()
            assert creator.selected_outpoints == {first}
            with qtbot.assertNotEmitted(creator.signal_create_tx):
                creator.create_tx()
            assert any("unavailable" in message for message in messages)
        finally:
            creator.wallet_functions.get_wallets.disconnect(get_other)
        creator.on_wallet_updated(UpdateFilter(reason=UpdateFilterReason.WalletClosed))
        assert set(creator.foreign_inputs) == {first, second}
        assert first in creator.get_outpoints()
        saved = creator.dumps()
        restored = UITx_Creator._from_dumps(saved, class_kwargs=creator_class_kwargs(creator))
        restored.set_category_core(qt_wallet.category_core)
        restored.show()
        try:
            qtbot.waitUntil(lambda: set(restored.foreign_inputs) == {first, second}, timeout=10_000)
            assert restored.selected_outpoints == {first}
            restored.remove_foreign_inputs([first, second])
            assert not restored.foreign_inputs
            assert not restored.selected_outpoints
        finally:
            restored.close()
        saved_data = json.loads(saved)
        assert set(saved_data["foreign_inputs"]) == {str(first), str(second)}
        fetch.assert_not_awaited()


@pytest.mark.marker_qt_2
@pytest.mark.parametrize("replace_draft", [False, True])
def test_reset_discards_late_foreign_import(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: ConfigForTest,
    monkeypatch: pytest.MonkeyPatch,
    replace_draft: bool,
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_stale_import_{replace_draft}")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name=f"stale_import_{replace_draft}",
            seed=test_seeds[0],
        )
        creator = qt_wallet.uitx_creator
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        tx = transaction([b"\x00\x14" + b"\x42" * 20])
        op = OutPoint(txid=tx.compute_txid(), vout=0)
        started, release, completed = Event(), Event(), Event()
        requested: list[bdk.Txid] = []

        async def fetch(_txid: bdk.Txid) -> bdk.Transaction:
            requested.append(_txid)
            started.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return tx

        monkeypatch.setattr(creator.mempool_manager, "fetch_transaction", fetch)
        run_task = creator.loop_in_thread.run_task

        def track(coro, **kwargs):
            success = kwargs.pop("on_success")

            def on_success(result):
                try:
                    success(result)
                finally:
                    completed.set()

            return run_task(coro, on_success=on_success, **kwargs)

        monkeypatch.setattr(creator.loop_in_thread, "run_task", track)
        assert creator.wallet is not None
        foreign = ForeignUtxo.from_outpoint(op, tx.output()[0], tx, [], creator.wallet.network)
        destination = creator.wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        psbt = (
            bdk.TxBuilder()
            .add_foreign_utxo(op, foreign.psbt_input, foreign.satisfaction_weight)
            .manually_selected_only()
            .add_recipient(destination.script_pubkey(), bdk.Amount.from_sat(90_000))
            .finish(creator.wallet.bdkwallet)
        )
        psbt_without_metadata = bdk.Psbt.from_unsigned_tx(psbt.extract_tx_unchecked_fee_rate())
        creator.merge_psbt(psbt_without_metadata)
        try:
            qtbot.waitUntil(started.is_set, timeout=10_000)
            assert not creator.button_ok.isEnabled()
            assert not creator.column_inputs.isEnabled()
            with qtbot.assertNotEmitted(creator.signal_create_tx):
                creator.create_tx()
            if replace_draft:
                creator.set_ui(TxUiInfos())
            else:
                creator.clear_ui()
        finally:
            release.set()
        qtbot.waitUntil(completed.is_set, timeout=10_000)
        assert not creator.foreign_inputs
        assert not creator.selected_outpoints
        assert creator.button_ok.isEnabled()
        assert creator.column_inputs.isEnabled()
        edited = TxUiInfos(hide_UTXO_selection=False)
        edited.source_tx_inputs[op] = None
        creator.set_ui(edited)
        assert creator.selected_outpoints == {op}
        assert op in creator.utxo_list.outpoints
        assert op not in creator.get_outpoints()
        qtbot.wait(100)
        assert len(requested) == 1


@pytest.mark.marker_qt_2
def test_psbt_merge_is_atomic_when_an_input_cannot_be_resolved(
    qtbot: QtBot, mytest_start_time: datetime, test_config: ConfigForTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_atomic_psbt")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="atomic_psbt",
            seed=test_seeds[0],
        )
        creator = qt_wallet.uitx_creator
        wallet = qt_wallet.wallet
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        transactions = [transaction([b"\x00\x14" + bytes([n]) * 20]) for n in (0x42, 0x43)]
        points = [OutPoint(txid=tx.compute_txid(), vout=0) for tx in transactions]
        builder = bdk.TxBuilder()
        for op, tx in zip(points, transactions, strict=True):
            item = ForeignUtxo.from_outpoint(op, tx.output()[0], tx, [], wallet.network)
            builder = builder.add_foreign_utxo(op, item.psbt_input, item.satisfaction_weight)
        destination = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        original = (
            builder.manually_selected_only()
            .add_recipient(destination.script_pubkey(), bdk.Amount.from_sat(150_000))
            .finish(wallet.bdkwallet)
        )
        psbt = bdk.Psbt.from_unsigned_tx(original.extract_tx_unchecked_fee_rate())
        existing = Recipient(str(destination), 10_000)
        creator.recipients.recipients = [existing]

        async def fetch(txid: bdk.Txid) -> bdk.Transaction:
            if txid == transactions[0].compute_txid():
                return transactions[0]
            raise ValueError("offline")

        monkeypatch.setattr(creator.mempool_manager, "fetch_transaction", fetch)
        errors: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: errors.append(text)
        )
        creator.merge_psbt(psbt)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert errors and "offline" in errors[0]
        assert not creator.foreign_inputs
        assert not creator.selected_outpoints
        assert creator.recipients.recipients == [existing]

        async def fetch_all(txid: bdk.Txid) -> bdk.Transaction:
            return next(tx for tx in transactions if tx.compute_txid() == txid)

        monkeypatch.setattr(creator.mempool_manager, "fetch_transaction", fetch_all)
        errors.clear()
        output_count = len(original.extract_tx_unchecked_fee_rate().output())
        creator.merge_psbt(psbt)
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert not errors
        assert set(creator.foreign_inputs) == set(points)
        assert creator.selected_outpoints == set(points)
        assert len(creator.recipients.recipients) == 1 + output_count
        with pytest.raises(ValueError, match="already selected"):
            creator.merge_psbt(psbt)
        assert len(creator.recipients.recipients) == 1 + output_count


@pytest.mark.marker_qt_2
def test_psbt_merge_rejects_selected_inputs_and_allows_unselected_inputs(
    qtbot: QtBot, mytest_start_time: datetime, test_config: ConfigForTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_psbt_conflicts")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="psbt_conflicts",
            seed=test_seeds[0],
        )
        creator = qt_wallet.uitx_creator
        wallet = qt_wallet.wallet
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        destination = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        local_tx = transaction([bytes(destination.script_pubkey().to_bytes())])
        wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=local_tx, last_seen=1)])
        local = OutPoint(txid=local_tx.compute_txid(), vout=0)
        local_utxo = PythonUtxo(str(destination), local, TxOut.from_bdk(local_tx.output()[0]))
        monkeypatch.setattr(wallet, "get_all_utxos", lambda *args, **kwargs: [local_utxo])
        monkeypatch.setattr(wallet, "get_all_txos_dict", lambda *args, **kwargs: {str(local): local_utxo})
        foreign_txs = [transaction([b"\x00\x14" + bytes([n]) * 20]) for n in (0x42, 0x43)]
        foreign = [OutPoint(txid=tx.compute_txid(), vout=0) for tx in foreign_txs]
        foreign_items = {
            op: ForeignUtxo.from_outpoint(op, tx.output()[0], tx, [], wallet.network)
            for op, tx in zip(foreign, foreign_txs, strict=True)
        }

        def make_psbt(points: list[OutPoint]) -> bdk.Psbt:
            builder = bdk.TxBuilder()
            for op in points:
                if op == local:
                    builder = builder.add_utxo(op)
                else:
                    item = foreign_items[op]
                    builder = builder.add_foreign_utxo(op, item.psbt_input, item.satisfaction_weight)
            return (
                builder.manually_selected_only()
                .add_recipient(destination.script_pubkey(), bdk.Amount.from_sat(50_000))
                .finish(wallet.bdkwallet)
            )

        def merge(psbt: bdk.Psbt) -> None:
            creator.merge_psbt(psbt)
            qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)

        errors: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: errors.append(text)
        )
        local_psbt = make_psbt([local])
        foreign_psbt = make_psbt([foreign[0]])
        merge(local_psbt)
        merge(foreign_psbt)
        assert not errors
        assert creator.selected_outpoints == {local, foreign[0]}
        assert set(creator.foreign_inputs) == {foreign[0]}
        qtbot.waitUntil(lambda: not creator._input_change_timer.isActive(), timeout=10_000)
        before = creator.dumps()
        outputs_before = [
            (bytes(r.script_pubkey(wallet.network).to_bytes()), r.amount)
            for r in creator.recipients.recipients
        ]
        assert outputs_before == [
            (bytes(output.script_pubkey.to_bytes()), output.value.to_sat())
            for psbt in (local_psbt, foreign_psbt)
            for output in psbt.extract_tx_unchecked_fee_rate().output()
        ]
        for psbt, conflict in (
            (local_psbt, local),
            (foreign_psbt, foreign[0]),
            (make_psbt([local, foreign[1]]), local),
            (make_psbt(foreign), foreign[0]),
        ):
            with pytest.raises(ValueError, match="already selected") as exc:
                creator.merge_psbt(psbt)
            assert str(conflict) in str(exc.value)
            assert creator.dumps() == before
            assert [
                (bytes(r.script_pubkey(wallet.network).to_bytes()), r.amount)
                for r in creator.recipients.recipients
            ] == outputs_before

        # Individual outpoint imports remain idempotent even when already selected.
        for _ in range(2):
            creator.import_outpoints([local, foreign[0]], select=True)
            qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert not errors
        assert creator.selected_outpoints == {local, foreign[0]}
        assert set(creator.foreign_inputs) == {foreign[0]}
        assert len(creator.recipients.recipients) == len(outputs_before)

        creator.set_selected_outpoints({local})
        merge(foreign_psbt)
        assert not errors
        assert creator.selected_outpoints == {local, foreign[0]}
        assert set(creator.foreign_inputs) == {foreign[0]}
        assert len(creator.recipients.recipients) == len(outputs_before) + len(
            foreign_psbt.extract_tx_unchecked_fee_rate().output()
        )


@pytest.mark.marker_qt_2
def test_psbt_merge_rechecks_selection_after_resolution(
    qtbot: QtBot, mytest_start_time: datetime, test_config: ConfigForTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_late_psbt_conflict")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="late_psbt_conflict",
            seed=test_seeds[0],
        )
        creator = qt_wallet.uitx_creator
        wallet = qt_wallet.wallet
        qt_wallet.tabs.setCurrentWidget(creator)
        qtbot.waitUntil(creator.isVisible, timeout=10_000)
        tx = transaction([b"\x00\x14" + b"\x42" * 20])
        op = OutPoint(txid=tx.compute_txid(), vout=0)
        item = ForeignUtxo.from_outpoint(op, tx.output()[0], tx, [], wallet.network)
        destination = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        psbt = (
            bdk.TxBuilder()
            .add_foreign_utxo(op, item.psbt_input, item.satisfaction_weight)
            .manually_selected_only()
            .add_recipient(destination.script_pubkey(), bdk.Amount.from_sat(50_000))
            .finish(wallet.bdkwallet)
        )
        started, release = Event(), Event()

        async def delayed_resolve(*args, **kwargs):
            started.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return await resolve_foreign_outpoints(*args, **kwargs)

        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.resolve_foreign_outpoints", delayed_resolve
        )
        errors: list[str] = []
        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.Message", lambda text, **kwargs: errors.append(text)
        )
        creator.recipients.recipients = [Recipient(str(destination), 10_000)]
        creator.merge_psbt(psbt)
        try:
            qtbot.waitUntil(started.is_set, timeout=10_000)
            creator.set_selected_outpoints({op})
            qtbot.waitUntil(lambda: not creator._input_change_timer.isActive(), timeout=10_000)
            before = creator.dumps()
        finally:
            release.set()
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert errors and "already selected" in errors[0] and str(op) in errors[0]
        assert creator.dumps() == before
        assert creator.selected_outpoints == {op}
        assert not creator.foreign_inputs
        assert [(r.address, r.amount) for r in creator.recipients.recipients] == [(str(destination), 10_000)]

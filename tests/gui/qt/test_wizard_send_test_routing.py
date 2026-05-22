#
# Bitcoin Safe
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

from types import SimpleNamespace
from unittest.mock import Mock

import bdkpython as bdk
import pytest
from bitcoin_qr_tools.data import DataType
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QDialogButtonBox, QPushButton, QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.card_base import CardExpansionMode, CardList
from bitcoin_safe.gui.qt.send_test_schedule import (
    build_send_test_fingerprint_groups,
    build_send_test_signer_groups,
)
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer, ViewerPresentation
from bitcoin_safe.gui.qt.wizard.wizard import ReceiveTest, SendTest, TutorialStep, Wizard
from bitcoin_safe.gui.qt.wizard.wizard_step_cards import (
    TUTORIAL_TX_ICON_RECOGNIZED,
    TUTORIAL_TX_ICON_SEND,
    TutorialTxCard,
    completed_tx_subtitle,
    pending_tx_subtitle,
)
from bitcoin_safe.tx import HiddenTxUiInfos, PostBroadcastEnum, PostCreateEnum, TxBuilderInfos
from tests.helpers import TestConfig as WizardTestConfig
from tests.non_gui.test_psbt_util import tr_psbt_singlesig
from tests.non_gui.utils import create_test_seed_keystores


class DummyWizardSignals(QObject):
    language_switch = pyqtSignal()
    open_tx_like = pyqtSignal(object)


class DummyContainer(QWidget):
    signal_set_current_widget = pyqtSignal(QWidget)
    signal_widget_focus = pyqtSignal(QWidget)
    signal_widget_unfocus = pyqtSignal(QWidget)


def _make_receive_step() -> ReceiveTest:
    config = WizardTestConfig()
    config.network = bdk.Network.REGTEST
    refs = SimpleNamespace(
        container=DummyContainer(),
        qtwalletbase=SimpleNamespace(
            config=config,
            signals=DummyWizardSignals(),
        ),
        go_to_next_index=lambda: None,
        go_to_previous_index=lambda: None,
        floating_button_box=SimpleNamespace(updateUi=Mock()),
        signal_create_wallet=None,
        max_test_fund=int(1e6),
        qt_wallet=None,
    )
    return ReceiveTest(refs=refs, loop_in_thread=None, show_previous_step_button=False)


def _make_builder_infos(request_id: str, test_number: int) -> TxBuilderInfos:
    hidden = HiddenTxUiInfos(
        post_create_action=PostCreateEnum.no_action,
        wizard_request_id=request_id,
        wizard_send_test_index=test_number,
    )
    tx = SimpleNamespace(compute_txid=lambda: "txid", output=lambda: [])
    psbt = SimpleNamespace(extract_tx=lambda: tx)
    return TxBuilderInfos(recipients=[], utxos_for_input=[], psbt=psbt, hidden_tx_infos=hidden)


def test_on_signal_psbt_created_embeds_viewer() -> None:
    builder_infos = _make_builder_infos("request-1", 0)
    viewer = SimpleNamespace(post_broadcast_action=None)
    step = SimpleNamespace(
        viewer_container=object(),
        show_embedded_viewer=Mock(),
    )
    qt_wallet = SimpleNamespace(create_viewer_from_builder_infos=Mock(return_value=viewer))
    fake_self = SimpleNamespace(
        _is_closing=False,
        qt_wallet=qt_wallet,
        should_be_visible=True,
        active_request_id="request-1",
        active_send_test_index=0,
        pending_txid_by_send_test={},
        recognized_txids=set(),
        tr=lambda text: text,
    )

    def clear_active_send_test_request() -> None:
        fake_self.active_request_id = None
        fake_self.active_send_test_index = None

    fake_self._clear_active_send_test_request = clear_active_send_test_request
    fake_self._send_test_step = lambda test_number: step if test_number == 0 else None
    fake_self._detach_creator_from_send_test = Mock()
    fake_self._update_send_test_step_status = Mock()
    fake_self._refresh_all_send_test_cards = Mock()

    Wizard.on_signal_psbt_created(fake_self, builder_infos)

    assert fake_self.active_request_id is None
    assert fake_self.active_send_test_index is None
    assert fake_self.pending_txid_by_send_test == {0: "txid"}
    assert viewer.post_broadcast_action == PostBroadcastEnum.no_action
    qt_wallet.create_viewer_from_builder_infos.assert_called_once_with(
        builder_infos, parent=step.viewer_container
    )
    step.show_embedded_viewer.assert_called_once_with(viewer)
    fake_self._detach_creator_from_send_test.assert_called_once_with(step)
    fake_self._update_send_test_step_status.assert_called_once()
    fake_self._refresh_all_send_test_cards.assert_called_once_with()


def test_build_send_test_signer_groups_2_of_3() -> None:
    assert build_send_test_signer_groups(["A", "B", "C"], (2, 3)) == [["A", "B"], ["B", "C"]]


def test_build_send_test_signer_groups_3_of_5() -> None:
    assert build_send_test_signer_groups(["A", "B", "C", "D", "E"], (3, 5)) == [
        ["A", "B", "C"],
        ["C", "D", "E"],
    ]


def test_get_send_test_labels_uses_shared_grouping_helper() -> None:
    fake_self = SimpleNamespace(
        qtwalletbase=SimpleNamespace(
            get_mn_tuple=lambda: (2, 3),
            get_keystore_labels=lambda: ["Jade", "Passport", "Coldcard"],
        ),
        tr=lambda text: text,
    )

    labels = Wizard.get_send_test_labels(fake_self)

    assert labels == ['"Jade" and "Passport"', '"Passport" and "Coldcard"']


def test_get_send_test_labels_prefer_current_group_for_overlap_tests() -> None:
    fake_self = SimpleNamespace(
        qtwalletbase=SimpleNamespace(
            get_mn_tuple=lambda: (4, 6),
            get_keystore_labels=lambda: ["A", "B", "C", "D", "E", "F"],
        ),
        tr=lambda text: text,
    )

    labels = Wizard.get_send_test_labels(fake_self)

    assert labels == ['"A" and "B" and "C" and "D"', '"C" and "D" and "E" and "F"']


def test_build_send_test_fingerprint_groups_normalizes_and_groups() -> None:
    groups = build_send_test_fingerprint_groups(
        fingerprints=["aa11bb22", "cc33dd44", "", "EE55FF66"],
        mn_tuple=(2, 3),
    )

    assert groups == [["AA11BB22", "CC33DD44"], ["CC33DD44", "EE55FF66"]]


def test_open_tx_stores_send_test_signer_groups() -> None:
    keystores = create_test_seed_keystores(
        signers=3,
        key_origins=["m/48h/1h/0h/2h", "m/48h/1h/1h/2h", "m/48h/1h/2h/2h"],
        network=bdk.Network.REGTEST,
    )
    created_infos: list = []
    qt_wallet = SimpleNamespace(
        wallet=SimpleNamespace(
            id="wallet-id",
            keystores=keystores,
            labels=SimpleNamespace(get_category=lambda address: "funded"),
            get_all_utxos=lambda: [SimpleNamespace(outpoint="outpoint-1", address="addr-1")],
            get_unused_category_address=lambda category: SimpleNamespace(address="addr-2"),
        ),
        uitx_creator=SimpleNamespace(
            initial_tx_ui_infos=None,
            set_ui=lambda txinfos: created_infos.append(txinfos),
        ),
        wallet_signals=SimpleNamespace(updated=SimpleNamespace(emit=Mock())),
    )
    fake_self = SimpleNamespace(
        qt_wallet=qt_wallet,
        qtwalletbase=SimpleNamespace(get_mn_tuple=lambda: (2, 3)),
        active_request_id="request-1",
        tr=lambda text: text,
        tx_text=lambda test_number: f"Send test {test_number + 1}",
    )

    Wizard.open_tx(fake_self, 1)

    assert len(created_infos) == 1
    assert created_infos[0].hidden.wizard_send_test_index == 1
    assert created_infos[0].hidden.wizard_send_test_signer_groups == [
        [keystores[0].fingerprint, keystores[1].fingerprint],
        [keystores[1].fingerprint, keystores[2].fingerprint],
    ]


def test_show_embedded_viewer_makes_viewer_visible(qtbot) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    root_layout = QVBoxLayout(root)
    active_card = TutorialTxCard(root)
    root_layout.addWidget(active_card)
    viewer_container = QWidget(active_card.content_widget)
    viewer_layout = QVBoxLayout(viewer_container)
    active_card.content_layout.addWidget(viewer_container)
    viewer_container.hide()

    class DummyViewer(QWidget):
        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.presentation: ViewerPresentation | None = None

        def set_presentation(self, presentation: ViewerPresentation) -> None:
            self.presentation = presentation

    fake_self = SimpleNamespace(
        embedded_viewer=None,
        viewer_container=viewer_container,
        viewer_layout=viewer_layout,
        active_card=active_card,
        refresh_cards=Mock(),
    )
    fake_self.close_embedded_viewer = lambda refresh=True: SendTest.close_embedded_viewer(
        fake_self, refresh=refresh
    )

    root.show()
    viewer = DummyViewer(parent=viewer_container)

    SendTest.show_embedded_viewer(fake_self, viewer)

    qtbot.waitUntil(viewer_container.isVisible, timeout=1_000)
    qtbot.waitUntil(viewer.isVisible, timeout=1_000)
    assert viewer.presentation == ViewerPresentation.embedded_card
    fake_self.refresh_cards.assert_called_once_with()


def test_update_tx_progress_passes_wizard_signer_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, object] = {}

    class DummyTxSigningSteps(QWidget):
        def __init__(self, **kwargs) -> None:
            super().__init__()
            captured_kwargs.update(kwargs)

    monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.clear_layout", lambda layout: None)
    monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.TxSigningSteps", DummyTxSigningSteps)

    fake_self = SimpleNamespace(
        data=SimpleNamespace(data_type=DataType.PSBT, data=tr_psbt_singlesig),
        tx_singning_steps_container_layout=SimpleNamespace(addWidget=Mock()),
        hidden_tx_infos=HiddenTxUiInfos(
            wizard_send_test_index=1,
            wizard_send_test_signer_groups=[["A", "B"], ["B", "C"]],
        ),
        network=bdk.Network.REGTEST,
        wallet_functions=SimpleNamespace(),
        loop_in_thread=None,
        get_combined_signature_importers=lambda psbt: {"wallet.0": []},
    )

    result = UITx_Viewer.update_tx_progress(fake_self)

    assert isinstance(result, DummyTxSigningSteps)
    assert captured_kwargs["wizard_send_test_index"] == 1
    assert captured_kwargs["wizard_send_test_signer_groups"] == [["A", "B"], ["B", "C"]]


def test_viewer_set_presentation_disables_fee_notification_bars(qtbot) -> None:
    container_label = QWidget()
    header_button_group = QWidget()
    button_back = QPushButton()
    qtbot.addWidget(container_label)
    qtbot.addWidget(header_button_group)
    qtbot.addWidget(button_back)
    container_label.show()
    header_button_group.show()
    button_back.show()

    fake_self = SimpleNamespace(
        presentation=ViewerPresentation.standalone_tab,
        container_label=container_label,
        header_button_group=header_button_group,
        button_back=button_back,
        set_fee_notification_bars_enabled=Mock(),
    )

    UITx_Viewer.set_presentation(fake_self, ViewerPresentation.embedded_card)

    assert fake_self.presentation == ViewerPresentation.embedded_card
    fake_self.set_fee_notification_bars_enabled.assert_called_once_with(False)
    assert not container_label.isVisible()
    assert not header_button_group.isVisible()
    assert not button_back.isVisible()


def test_configure_creator_for_embedded_send_test_disables_fee_notification_bars() -> None:
    creator = SimpleNamespace(
        set_fee_notification_bars_enabled=Mock(),
        button_box=QDialogButtonBox(),
        button_back=QPushButton(),
        set_show_reset_button=Mock(),
    )
    send_test_previous_button = QPushButton()
    fake_self = SimpleNamespace(
        qt_wallet=SimpleNamespace(uitx_creator=creator),
        send_test_previous_button=send_test_previous_button,
    )

    Wizard._configure_creator_for_embedded_send_test(fake_self, True)

    creator.set_fee_notification_bars_enabled.assert_called_once_with(False)
    assert send_test_previous_button in creator.button_box.buttons()
    assert send_test_previous_button.isVisible()

    creator.set_fee_notification_bars_enabled.reset_mock()
    Wizard._configure_creator_for_embedded_send_test(fake_self, False)
    creator.set_fee_notification_bars_enabled.assert_called_once_with(True)


def test_on_signal_psbt_created_ignores_stale_requests() -> None:
    builder_infos = _make_builder_infos("request-2", 0)
    fake_self = SimpleNamespace(
        _is_closing=False,
        qt_wallet=SimpleNamespace(create_viewer_from_builder_infos=Mock()),
        should_be_visible=True,
        active_request_id="request-1",
        active_send_test_index=0,
        pending_txid_by_send_test={},
        recognized_txids=set(),
        floating_button_box=SimpleNamespace(set_status=Mock()),
        tr=lambda text: text,
        _clear_active_send_test_request=Mock(),
        _send_test_step=Mock(),
        _detach_creator_from_send_test=Mock(),
        _update_send_test_step_status=Mock(),
        _refresh_all_send_test_cards=Mock(),
    )

    Wizard.on_signal_psbt_created(fake_self, builder_infos)

    assert fake_self.pending_txid_by_send_test == {}
    fake_self._clear_active_send_test_request.assert_not_called()
    fake_self.qt_wallet.create_viewer_from_builder_infos.assert_not_called()


def test_on_utxo_update_marks_tx_recognized_without_advancing() -> None:
    step = SimpleNamespace(close_embedded_viewer=Mock())
    fake_self = SimpleNamespace(
        qt_wallet=SimpleNamespace(wallet=SimpleNamespace(get_tx=lambda txid: object())),
        should_be_visible=True,
        pending_txid_by_send_test={0: "txid"},
        recognized_txids=set(),
        current_step=lambda: TutorialStep.send,
        get_send_tests_steps=lambda: [TutorialStep.send],
        get_send_test_txid=lambda test_number: "txid" if test_number == 0 else None,
        _receive_step=lambda: None,
        _send_test_step=lambda test_number: step if test_number == 0 else None,
        _update_send_test_step_status=Mock(),
        _refresh_all_send_test_cards=Mock(),
        tr=lambda text: text,
    )
    update_filter = SimpleNamespace(
        refresh_all=True,
        outpoints=None,
        txids=None,
        reason=None,
    )

    Wizard.on_utxo_update(fake_self, update_filter)
    Wizard.on_utxo_update(fake_self, update_filter)

    assert fake_self.recognized_txids == {"txid"}
    step.close_embedded_viewer.assert_called_with(refresh=False)
    fake_self._update_send_test_step_status.assert_called_with(0, "Transaction recognized by the wallet.")
    fake_self._refresh_all_send_test_cards.assert_called()


def test_get_send_test_txid_restores_from_wallet_state() -> None:
    txo = SimpleNamespace(address="addr", outpoint=SimpleNamespace(txid_str="txid-1"))
    wallet = SimpleNamespace(
        get_all_txos_dict=lambda: {"outpoint": txo},
        labels=SimpleNamespace(get_label=lambda address: "Self-Send Test" if address == "addr" else None),
        get_tx=lambda txid: object() if txid == "txid-1" else None,
    )
    fake_self = SimpleNamespace(
        pending_txid_by_send_test={},
        recognized_txids=set(),
        qt_wallet=SimpleNamespace(wallet=wallet),
        tx_text=lambda test_number: "Self-Send Test",
    )

    txid = Wizard.get_send_test_txid(fake_self, 0)

    assert txid == "txid-1"
    assert fake_self.pending_txid_by_send_test == {0: "txid-1"}
    assert fake_self.recognized_txids == {"txid-1"}


def test_on_send_test_step_activated_recognized_step_stays_put() -> None:
    step = SimpleNamespace(close_embedded_viewer=Mock())
    fake_self = SimpleNamespace(
        _refresh_all_send_test_cards=Mock(),
        get_send_test_txid=lambda test_number: "txid-1" if test_number == 0 else None,
        recognized_txids={"txid-1"},
        _send_test_step=lambda test_number: step if test_number == 0 else None,
        _update_send_test_step_status=Mock(),
        tr=lambda text: text,
    )

    Wizard.on_send_test_step_activated(fake_self, 0)

    step.close_embedded_viewer.assert_called_once_with(refresh=False)
    fake_self._update_send_test_step_status.assert_called_once_with(
        0, "Transaction recognized by the wallet."
    )


def test_open_send_test_tx_falls_back_to_txid_when_wallet_tx_missing() -> None:
    open_tx_like = Mock()
    fake_self = SimpleNamespace(
        qt_wallet=SimpleNamespace(wallet=SimpleNamespace(get_tx=lambda txid: None)),
        qtwalletbase=SimpleNamespace(
            signals=SimpleNamespace(open_tx_like=SimpleNamespace(emit=open_tx_like))
        ),
        get_send_test_txid=lambda test_number: "txid-1" if test_number == 0 else None,
    )

    Wizard.open_send_test_tx(fake_self, 0)

    open_tx_like.assert_called_once_with("txid-1")


def test_get_previous_displayed_step_returns_register_before_receive() -> None:
    fake_self = SimpleNamespace(
        get_displayed_steps=lambda: [TutorialStep.register, TutorialStep.receive, TutorialStep.send]
    )

    previous = Wizard.get_previous_displayed_step(fake_self, TutorialStep.receive)

    assert previous == TutorialStep.register


def test_get_previous_displayed_step_returns_none_for_first_step() -> None:
    fake_self = SimpleNamespace(get_displayed_steps=lambda: [TutorialStep.receive, TutorialStep.send])

    previous = Wizard.get_previous_displayed_step(fake_self, TutorialStep.receive)

    assert previous is None


def test_send_test_callback_prefers_existing_tutorial_tx_over_skip_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_mock = Mock(return_value=False)
    monkeypatch.setattr("bitcoin_safe.gui.qt.wizard.wizard_step_send.question_dialog", question_mock)

    class DummyWizard(Wizard):
        def __init__(self) -> None:
            self.on_send_test_step_activated = Mock()
            self.get_send_test_txid = Mock(return_value="txid-1")

    wizard = DummyWizard()
    qt_wallet = SimpleNamespace(
        wallet=SimpleNamespace(client=None),
    )
    fake_self = SimpleNamespace(
        refs=SimpleNamespace(container=SimpleNamespace(parent=lambda: wizard), qt_wallet=qt_wallet),
        test_number=0,
        set_visibilities=Mock(),
        wizard_parent=lambda: wizard,
        tr=lambda text: text,
    )

    from bitcoin_safe.gui.qt.wizard.wizard import SendTest

    SendTest._callback(fake_self)

    wizard.on_send_test_step_activated.assert_called_once_with(0)
    question_mock.assert_not_called()


def test_configure_creator_for_embedded_send_test_swaps_reset_for_previous() -> None:
    button_box = SimpleNamespace(
        setVisible=Mock(),
        buttons=Mock(return_value=[]),
        addButton=Mock(),
        removeButton=Mock(),
    )
    creator = SimpleNamespace(
        button_box=button_box,
        button_back=SimpleNamespace(setVisible=Mock()),
        set_show_reset_button=Mock(),
        set_fee_notification_bars_enabled=Mock(),
    )
    previous_button = SimpleNamespace(setVisible=Mock())
    fake_self = SimpleNamespace(
        qt_wallet=SimpleNamespace(uitx_creator=creator),
        send_test_previous_button=previous_button,
    )

    Wizard._configure_creator_for_embedded_send_test(fake_self, True)

    button_box.setVisible.assert_called_once_with(True)
    creator.set_fee_notification_bars_enabled.assert_called_once_with(False)
    creator.button_back.setVisible.assert_called_once_with(False)
    creator.set_show_reset_button.assert_called_once_with(False)
    button_box.addButton.assert_called_once_with(previous_button, QDialogButtonBox.ButtonRole.RejectRole)


def test_configure_creator_for_standard_send_restores_reset_button() -> None:
    button_box = SimpleNamespace(
        setVisible=Mock(),
        removeButton=Mock(),
    )
    creator = SimpleNamespace(
        button_box=button_box,
        button_back=SimpleNamespace(setVisible=Mock()),
        set_show_reset_button=Mock(),
        set_fee_notification_bars_enabled=Mock(),
    )
    previous_button = SimpleNamespace(setVisible=Mock())
    fake_self = SimpleNamespace(
        qt_wallet=SimpleNamespace(uitx_creator=creator),
        send_test_previous_button=previous_button,
    )

    Wizard._configure_creator_for_embedded_send_test(fake_self, False)

    button_box.setVisible.assert_called_once_with(True)
    creator.set_fee_notification_bars_enabled.assert_called_once_with(True)
    creator.button_back.setVisible.assert_called_once_with(True)
    creator.set_show_reset_button.assert_called_once_with(True)
    button_box.removeButton.assert_called_once_with(previous_button)


def test_receive_create_uses_single_card_list_for_recognized_transaction(qtbot) -> None:
    step = _make_receive_step()

    tutorial_widget = step.create()
    qtbot.addWidget(step.refs.container)
    qtbot.addWidget(tutorial_widget)
    tutorial_widget.show()
    qtbot.waitExposed(tutorial_widget)

    assert isinstance(step.tx_card_list, CardList)
    assert step.tx_card is not None
    assert step.check_button is not None
    assert step.tx_card_list.cards() == [step.tx_card]
    assert step.tx_card_list.count() == 1
    assert step.tx_section is not None and not step.tx_section.isHidden()
    assert not step.tx_card.isHidden()
    assert step.tx_card.header_title.text() == "Receive Test"
    assert step.tx_card.header_subtitle.text() == "Waiting for funds to arrive in the wallet..."
    assert step.tx_card.header_icon.pixmap() is not None
    assert step.check_button.isVisible()


def test_receive_check_wallet_for_utxos_shows_shared_completed_card(qtbot) -> None:
    step = _make_receive_step()
    tutorial_widget = step.create()
    qtbot.addWidget(step.refs.container)
    qtbot.addWidget(tutorial_widget)
    tutorial_widget.show()
    qtbot.waitExposed(tutorial_widget)

    empty_wallet = SimpleNamespace(get_all_utxos=lambda include_not_mine=False: [])
    step.refs.qt_wallet = SimpleNamespace(wallet=empty_wallet)

    assert step.check_wallet_for_utxos() == []
    assert step.tx_section is not None and not step.tx_section.isHidden()
    assert step.tx_card is not None and not step.tx_card.isHidden()
    assert step.tx_card.header_title.text() == "Receive Test"
    assert step.tx_card.header_subtitle.text() == "Waiting for funds to arrive in the wallet..."
    assert step.check_button is not None and step.check_button.isVisible()

    txid = "0123456789abcdef"
    funded_wallet = SimpleNamespace(
        get_all_utxos=lambda include_not_mine=False: [
            SimpleNamespace(outpoint=SimpleNamespace(txid_str=txid))
        ],
        get_tx=lambda current_txid: None if current_txid == txid else object(),
    )
    step.refs.qt_wallet = SimpleNamespace(wallet=funded_wallet)

    utxos = step.check_wallet_for_utxos()

    assert len(utxos) == 1
    assert step.tx_section is not None and not step.tx_section.isHidden()
    assert step.tx_card is not None
    assert not step.tx_card.isHidden()
    assert step.tx_card.header_title.text() == "Receive Test"
    assert "Successfully completed! txid:" in step.tx_card.header_subtitle.text()
    assert txid in step.tx_card.header_subtitle.text()
    assert step.tx_card.expansion_mode() == CardExpansionMode.FIXED_COLLAPSED
    assert step.tx_card.header_widget.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert step.check_button is not None and not step.check_button.isVisible()

    with qtbot.waitSignal(step.tx_card.signal_header_activated):
        qtbot.mouseClick(step.tx_card.header_widget, Qt.MouseButton.LeftButton)


def test_send_refresh_cards_uses_shared_tx_card_helpers() -> None:
    active_card = TutorialTxCard()
    card_list = CardList()
    card_list.add_card(active_card)
    recognized_txid = "0123456789abcdef"
    pending_txid = "abcdef0123456789"

    fake_self = SimpleNamespace(
        test_number=1,
        embedded_viewer=None,
        active_card=active_card,
        history_cards={},
        _history_card_order=[],
        card_list=card_list,
        button_next=SimpleNamespace(setEnabled=Mock()),
        buttonbox=SimpleNamespace(setVisible=Mock()),
        refs=SimpleNamespace(qt_wallet=object()),
        tr=lambda text: text,
        _card_title=lambda number: f"Self-Send Test {number + 1}",
        close_embedded_viewer=Mock(),
    )
    wizard = SimpleNamespace(
        recognized_txids={recognized_txid},
        get_send_test_txid=lambda number: {
            0: pending_txid,
            1: recognized_txid,
        }.get(number),
        open_send_test_tx=Mock(),
    )
    fake_self.wizard_parent = lambda: wizard
    fake_self._status_icon_name = lambda txid: SendTest._status_icon_name(fake_self, txid)

    SendTest.refresh_cards(fake_self)

    assert SendTest._status_icon_name(fake_self, recognized_txid) == TUTORIAL_TX_ICON_RECOGNIZED
    assert SendTest._status_icon_name(fake_self, pending_txid) == TUTORIAL_TX_ICON_SEND
    assert active_card.header_subtitle.text() == completed_tx_subtitle(active_card, recognized_txid)

    history_card = fake_self.history_cards[0]
    assert history_card.header_subtitle.text() == pending_tx_subtitle(history_card, pending_txid)

#
# Bitcoin Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import logging
from collections.abc import Callable
from functools import partial
from typing import cast

from bitcoin_qr_tools.data import SignerInfo
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.card_base import CardList
from bitcoin_safe.gui.qt.custom_edits import AnalyzerState
from bitcoin_safe.hardware_signers import HardwareSigner
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.wallet import ProtoWallet

from ...descriptors import AddressType
from .keystore_ui import KeyStoreUI
from .util import Message, MessageType

logger = logging.getLogger(__name__)


class KeyStoreUIs(QWidget):
    signal_on_tab_change = cast(SignalProtocol[[]], pyqtSignal())
    signal_ui_changed = cast(SignalProtocol[[]], pyqtSignal())
    request_show_register_multisig = cast(SignalProtocol[[HardwareSigner | None]], pyqtSignal(object))

    def __init__(
        self,
        get_editable_protowallet: Callable[[], ProtoWallet],
        get_address_type: Callable[[], AddressType],
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        read_only_mode: bool = False,
        show_register_button: bool = True,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.signal_tracker = SignalTracker()
        self.signals_min = signals_min
        self.loop_in_thread = loop_in_thread
        self.read_only_mode = read_only_mode
        self.show_register_button = show_register_button

        self.get_editable_protowallet = get_editable_protowallet
        self.get_address_type = get_address_type

        self._current_index = 0
        self._keystore_uis: list[KeyStoreUI] = []

        self.layout_main = QVBoxLayout(self)
        self.layout_main.setContentsMargins(0, 0, 0, 0)

        self.card_list = CardList(self)
        self.card_list.set_only_one_expanded_at_a_time(True)
        self.layout_main.addWidget(self.card_list)
        self.scroll_area = self.card_list.scroll_area
        self.content_widget = self.card_list.scroll_area.content_widget
        self.content_layout = self.card_list.content_layout

        self._set_keystore_cards()

        self.signal_tracker.connect(self.signals_min.language_switch, self.updateUi)
        self.signal_tracker.connect(
            self.card_list.signal_current_index_changed, self._on_current_index_changed
        )

    @property
    def protowallet(self) -> ProtoWallet:
        """Protowallet."""
        return self.get_editable_protowallet()

    def _connect_keystore_ui(self, keystore_ui: KeyStoreUI) -> None:
        keystore_ui.signal_signer_infos.connect(self.set_all_using_signer_infos)
        keystore_ui.signal_ui_changed.connect(self.ui_keystore_ui_change)
        keystore_ui.request_show_register_multisig.connect(self.request_show_register_multisig.emit)

    def _on_current_index_changed(self, index: int) -> None:
        self._current_index = index
        self.signal_on_tab_change.emit()

    def _create_keystore_ui(self, index: int) -> KeyStoreUI:
        keystore_ui = KeyStoreUI(
            self.protowallet.network,
            get_address_type=self.get_address_type,
            signals_min=self.signals_min,
            hardware_signer_label=self.protowallet.signer_fallback_name(index),
            loop_in_thread=self.loop_in_thread,
            read_only_mode=self.read_only_mode,
            show_register_button=self.show_register_button,
        )
        self._connect_keystore_ui(keystore_ui)
        return keystore_ui

    def count(self) -> int:
        """Return the number of keystore cards."""
        return len(self._keystore_uis)

    def tabText(self, index: int) -> str:
        """Compatibility helper for existing tests/callers."""
        return self._keystore_uis[index].hardware_signer_label

    def setTabText(self, index: int, text: str) -> None:
        """Compatibility helper."""
        self._keystore_uis[index].set_fallback_hardware_signer_label(text)
        self._keystore_uis[index].updateUi()

    def setTabIcon(self, index: int, icon) -> None:
        """Compatibility helper for callers that previously set tab icons."""
        del index, icon

    def getAllTabData(self) -> dict[QWidget, KeyStoreUI]:
        """Return the widgets in insertion order."""
        return {keystore_ui: keystore_ui for keystore_ui in self._keystore_uis}

    def getCurrentTabData(self) -> KeyStoreUI | None:
        """Return the selected keystore card."""
        if not self._keystore_uis:
            return None
        return self._keystore_uis[self._current_index]

    def currentIndex(self) -> int:
        """Return the selected card index."""
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        """Expand one card by index and scroll it into view."""
        self.expand_only(index)

    def first_unselected_index(self) -> int | None:
        """Return the first signer card without a selected hardware signer."""
        for index, keystore_ui in enumerate(self._keystore_uis):
            if keystore_ui.selected_hardware_signer is None:
                return index
        return None

    def focus_first_unselected_brand_selector(self) -> bool:
        """Expand the first unselected signer card and focus its brand combo box."""
        index = self.first_unselected_index()
        if index is None:
            return False

        self.setCurrentIndex(index)
        QTimer.singleShot(
            0, partial(self._keystore_uis[index].combo_brand.setFocus, Qt.FocusReason.OtherFocusReason)
        )
        return True

    def expand_only(self, index: int) -> None:
        """Expand only the selected card and collapse the others."""
        if not self._keystore_uis:
            self._current_index = 0
            return
        self.card_list.expand_only(index)

    def collapse_all(self) -> None:
        """Collapse every card while keeping the current selection."""
        if not self._keystore_uis:
            self._current_index = 0
            return
        self._current_index = max(0, min(self._current_index, self.count() - 1))
        self.card_list.collapse_all()
        self.signal_on_tab_change.emit()

    def setTabEnabled(self, index: int, enabled: bool) -> None:
        """Enable or disable one keystore card."""
        self._keystore_uis[index].setEnabled(enabled)

    def indexOf(self, keystore_ui: KeyStoreUI) -> int:
        """Return the index for a card."""
        return self._keystore_uis.index(keystore_ui)

    def removeTab(self, index: int) -> None:
        """Remove a card by index."""
        keystore_ui = self._keystore_uis.pop(index)
        self.card_list.remove_card(keystore_ui)
        keystore_ui.close()
        keystore_ui.setParent(None)
        if self._current_index >= self.count():
            self._current_index = max(0, self.count() - 1)
        self.setCurrentIndex(self._current_index)

    def set_all_using_signer_infos(self, signer_infos: list[SignerInfo]) -> None:
        """Set all using signer infos."""
        if len(signer_infos) != self.count():
            logger.error(f"Could not set {len(signer_infos)} signer_infos on {self.count()} keystore_uis")
            return
        Message(
            self.tr("Filling in all {number} signers with the fingerprints {fingerprints}").format(
                number=len(signer_infos),
                fingerprints=", ".join([signer_info.fingerprint for signer_info in signer_infos]),
            ),
            parent=self,
        )
        for signer_info, keystore_ui in zip(signer_infos, self._keystore_uis, strict=False):
            keystore_ui.set_using_signer_info(signer_info)

    def get_warning_and_error_messages(self, keystore_uis: list[KeyStoreUI]) -> list[Message]:
        """Get warning and error messages."""
        return_messages: list[Message] = []
        if not keystore_uis:
            return return_messages

        fingerprints = [keystore_ui.edit_fingerprint.text() for keystore_ui in keystore_uis]
        if "" in fingerprints:
            return_messages.append(
                Message(
                    self.tr("Please import the complete data for Signer {i}!").format(
                        i=fingerprints.index("") + 1
                    ),
                    no_show=True,
                    type=MessageType.Error,
                    parent=self,
                )
            )
        if len(set(fingerprints)) < len(keystore_uis):
            return_messages.append(
                Message(
                    self.tr(
                        "You imported the same fingerprint multiple times!!! Please use a different signing device."
                    ),
                    no_show=True,
                    type=MessageType.Error,
                    parent=self,
                )
            )

        xpubs = [keystore_ui.edit_xpub.text() for keystore_ui in keystore_uis]
        if "" in xpubs:
            return_messages.append(
                Message(
                    self.tr("Please import the complete data for Signer {i}!").format(i=xpubs.index("") + 1),
                    no_show=True,
                    type=MessageType.Error,
                    parent=self,
                )
            )
        duplicate_xpub_signers = self._first_duplicate_signer_indexes(xpubs)
        if duplicate_xpub_signers:
            return_messages.append(
                Message(
                    self._duplicate_xpub_error_message(duplicate_xpub_signers),
                    no_show=True,
                    type=MessageType.Error,
                    parent=self,
                )
            )

        key_origins = [keystore_ui.edit_key_origin.text() for keystore_ui in keystore_uis]
        if "" in key_origins:
            return_messages.append(
                Message(
                    self.tr("Please import the complete data for Signer {i}!").format(
                        i=key_origins.index("") + 1
                    ),
                    no_show=True,
                    type=MessageType.Error,
                    parent=self,
                )
            )
        if len(set(key_origins)) > 1:
            return_messages.append(
                Message(
                    self.tr(
                        "Your imported key origins {key_origins} differ! Please double-check if you intended this."
                    ).format(key_origins=key_origins),
                    no_show=True,
                    type=MessageType.Warning,
                    parent=self,
                )
            )

        for keystore_ui in keystore_uis:
            for analysis in keystore_ui.get_analysis_list(min_state=AnalyzerState.Warning):
                if analysis.state == AnalyzerState.Warning:
                    return_messages.append(
                        Message(
                            f"{keystore_ui.hardware_signer_label}: {analysis.msg}",
                            no_show=True,
                            type=MessageType.Warning,
                            parent=self,
                        )
                    )
                if analysis.state == AnalyzerState.Invalid:
                    return_messages.append(
                        Message(
                            f"{keystore_ui.hardware_signer_label}: {analysis.msg}",
                            no_show=True,
                            type=MessageType.Error,
                            parent=self,
                        )
                    )

        return return_messages

    def _first_duplicate_signer_indexes(self, values: list[str]) -> list[int]:
        duplicate_indexes_by_value: dict[str, list[int]] = {}
        for index, value in enumerate(values):
            normalized = value.strip()
            if not normalized:
                continue
            duplicate_indexes_by_value.setdefault(normalized, []).append(index)

        for duplicate_indexes in duplicate_indexes_by_value.values():
            if len(duplicate_indexes) > 1:
                return duplicate_indexes
        return []

    def _duplicate_xpub_error_message(self, signer_indexes: list[int]) -> str:
        return self.tr(
            "Signer slots {signers} contain the same xpub. This usually means the same signer export was imported twice. Please import a different device or account for each signer."
        ).format(signers=", ".join(str(index + 1) for index in signer_indexes))

    def _update_duplicate_xpub_messages(self) -> None:
        duplicate_indexes = self._first_duplicate_signer_indexes(
            [keystore_ui.edit_xpub.text() for keystore_ui in self._keystore_uis]
        )
        duplicate_message = self._duplicate_xpub_error_message(duplicate_indexes) if duplicate_indexes else ""

        for index, keystore_ui in enumerate(self._keystore_uis):
            keystore_ui.set_duplicate_xpub_message(duplicate_message if index in duplicate_indexes else "")

    def has_blocking_messages(self, keystore_uis: list[KeyStoreUI] | None = None) -> bool:
        """Return whether the selected keystore cards still have blocking validation errors."""
        selected_keystore_uis = (
            keystore_uis if keystore_uis is not None else list(self.getAllTabData().values())
        )
        return any(
            message.type == MessageType.Error
            for message in self.get_warning_and_error_messages(selected_keystore_uis)
        )

    def updateUi(self) -> None:
        """UpdateUi."""
        self._set_keystore_cards()

    def ui_keystore_ui_change(self, *args) -> None:
        """Ui keystore ui change."""
        logger.debug("ui_keystore_ui_change")
        try:
            self.set_protowallet_from_keystore_ui()
            self.set_keystore_ui_from_protowallet()
        except Exception as exc:
            logger.debug(f"{self.__class__.__name__}: {exc}")
            logger.warning("ui_keystore_ui_change: Invalid input")
        self._update_duplicate_xpub_messages()
        self.signal_ui_changed.emit()

    def set_protowallet_from_keystore_ui(self) -> None:
        """Set protowallet from keystore ui."""
        for i, keystore_ui in enumerate(self._keystore_uis):
            ui_keystore = keystore_ui.get_ui_values_as_keystore()
            keystore = self.protowallet.keystores[i]
            if keystore is None:
                self.protowallet.keystores[i] = ui_keystore
            else:
                keystore.from_other_keystore(ui_keystore)

    def _set_keystore_cards(self) -> None:
        keep_all_collapsed = bool(self._keystore_uis) and all(
            not keystore_ui.is_expanded for keystore_ui in self._keystore_uis
        )

        while self.count() < len(self.protowallet.keystores):
            keystore_ui = self._create_keystore_ui(self.count())
            self._keystore_uis.append(keystore_ui)
            self.card_list.add_card(keystore_ui)

        while self.count() > len(self.protowallet.keystores):
            self.removeTab(self.count() - 1)

        for i, (keystore, keystore_ui) in enumerate(
            zip(self.protowallet.keystores, self._keystore_uis, strict=False)
        ):
            keystore_ui.set_fallback_hardware_signer_label(self.protowallet.signer_fallback_name(i))
            if keystore:
                keystore_ui.set_ui_from_keystore(keystore)
            keystore_ui.updateUi()

        if self.count():
            if keep_all_collapsed:
                self.collapse_all()
            else:
                self.setCurrentIndex(self._current_index)

    def set_keystore_ui_from_protowallet(self) -> None:
        """Set keystore ui from protowallet."""
        logger.debug("set_keystore_ui_from_protowallet")
        self._set_keystore_cards()
        for keystore, keystore_ui in zip(self.protowallet.keystores, self._keystore_uis, strict=False):
            if not keystore:
                continue
            keystore_ui.set_ui_from_keystore(keystore)
            keystore_ui.format_all_fields()
        self._update_duplicate_xpub_messages()
        assert len(self.protowallet.keystores) == self.count()

    def get_keystore_uis_with_unexpected_origin(self) -> list[KeyStoreUI]:
        """Get keystore uis with unexpected origin."""
        return [
            keystore_ui
            for keystore_ui in self._keystore_uis
            if keystore_ui.key_origin != keystore_ui.get_expected_key_origin()
        ]

    def ask_accept_unexpected_origins(self) -> bool:
        """Ask accept unexpected origins."""
        for keystore_ui in self.get_keystore_uis_with_unexpected_origin():
            if not question_dialog(
                f"The key derivation path {keystore_ui.key_origin} of {keystore_ui.hardware_signer_label} is not the default {keystore_ui.get_expected_key_origin()} for the address type {keystore_ui.get_address_type().name}. Do you want to proceed anyway?",
                true_button=self.tr("Proceed anyway"),
            ):
                return False
        return True

    def close(self) -> bool:
        """Close."""
        self.signal_tracker.disconnect_all()
        for keystore_ui in self._keystore_uis:
            keystore_ui.close()

        SignalTools.disconnect_all_signals_from(self)
        return super().close()

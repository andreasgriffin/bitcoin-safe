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
from collections.abc import Callable
from typing import cast

from bitcoin_qr_tools.data import SignerInfo
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QTabBar

from bitcoin_safe.gui.qt.custom_edits import AnalyzerState
from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.wallet_util import signer_name

from ...descriptors import AddressType
from ...wallet import ProtoWallet
from .keystore_ui import KeyStoreUI, icon_for_label
from .util import Message, MessageType

logger = logging.getLogger(__name__)


class OrderTrackingTabBar(QTabBar):
    signal_new_tab_order = cast(SignalProtocol[[list[int]]], pyqtSignal(list))

    def __init__(self, parent=None):
        """Initialize instance."""
        super().__init__(parent)
        self.order = []
        self.tabMoved.connect(self.on_tab_moved)  # type: ignore

    def mousePressEvent(self, a0):
        # Capture the tab order when the drag starts
        """MousePressEvent."""
        self.order = list(range(self.count()))
        super().mousePressEvent(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        # When the mouse is released, check if the order changed
        """MouseReleaseEvent."""
        normal_order = list(range(self.count()))
        if normal_order != self.order:
            logger.debug(f"Final order:  {self.order}")
            self.signal_new_tab_order.emit(self.order)
            self.order = normal_order
        super().mouseReleaseEvent(a0)

    def on_tab_moved(self, from_index, to_index):
        """On tab moved."""
        self.order.insert(to_index, self.order.pop(from_index))
        logger.debug(f"New order:  {self.order}")


class KeyStoreUIs(DataTabWidget[KeyStoreUI]):
    def __init__(
        self,
        get_editable_protowallet: Callable[[], ProtoWallet],
        get_address_type: Callable[[], AddressType],
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        slow_hwi_listing=True,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.tab_bar = OrderTrackingTabBar()
        self.setTabBar(self.tab_bar)
        self.setMovable(True)
        self.signal_tracker = SignalTracker()
        self.signals_min = signals_min
        self.slow_hwi_listing = slow_hwi_listing
        self.loop_in_thread = loop_in_thread

        self.get_editable_protowallet = get_editable_protowallet
        self.get_address_type = get_address_type

        for i, _keystore in enumerate(self.protowallet.keystores):
            keystore_ui = KeyStoreUI(
                self.protowallet.network,
                get_address_type=self.get_address_type,
                label=self.protowallet.signer_name(i),
                signals_min=signals_min,
                hardware_signer_label=self.protowallet.sticker_name(i),
                slow_hwi_listing=self.slow_hwi_listing,
                loop_in_thread=loop_in_thread,
            )
            keystore_ui.signal_signer_infos.connect(self.set_all_using_signer_infos)
            self.addTab(
                keystore_ui,
                icon=icon_for_label(keystore_ui.label),
                description=keystore_ui.label,
                data=keystore_ui,
            )

        for signal in (
            [ui.edit_xpub.input_field.textChanged for ui in self.getAllTabData().values()]
            + [ui.edit_fingerprint.input_field.textChanged for ui in self.getAllTabData().values()]
            + [ui.edit_key_origin.input_field.textChanged for ui in self.getAllTabData().values()]
        ):
            signal.connect(self.ui_keystore_ui_change)
        for ui in self.getAllTabData().values():
            ui.edit_seed.input_field.textChanged.connect(self.ui_keystore_ui_change)

        self.signal_tracker.connect(self.signals_min.language_switch, self.updateUi)
        self.signal_tracker.connect(self.tab_bar.signal_new_tab_order, self.on_tab_order_changed)

    def on_tab_order_changed(self, new_order: list[int]):
        """On tab order changed."""
        if len(new_order) != len(self.protowallet.keystores):
            return
        for i, ui in enumerate(self.getAllTabData().values()):
            ui.label = self.protowallet.signer_name(i)

        logger.info(f"Updated keystore order:  {new_order}")
        self.ui_keystore_ui_change()

    def set_all_using_signer_infos(self, signer_infos: list[SignerInfo]):
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
        for signer_info, keystore_ui in zip(signer_infos, self.getAllTabData().values(), strict=False):
            keystore_ui.set_using_signer_info(signer_info)

    def get_warning_and_error_messages(
        self,
        keystore_uis: list[KeyStoreUI],
    ) -> list[Message]:
        """Get warning and error messages."""
        return_messages: list[Message] = []
        if not keystore_uis:
            return return_messages

        # check for empty data and duplicates
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
        if len(set(xpubs)) < len(keystore_uis):
            return_messages.append(
                Message(
                    self.tr(
                        "You imported the same xpub multiple times!!! Please use a different signing device."
                    ),
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

        # messages from status_label
        for keystore_ui in keystore_uis:
            analyzer_indicator = keystore_ui.analyzer_indicator
            for analysis in analyzer_indicator.get_analysis_list(min_state=AnalyzerState.Warning):
                if analysis.state == AnalyzerState.Warning:
                    return_messages += [
                        Message(
                            f"{keystore_ui.label}: {analysis.msg}",
                            no_show=True,
                            type=MessageType.Warning,
                            parent=self,
                        )
                    ]
                if analysis.state == AnalyzerState.Invalid:
                    return_messages += [
                        Message(
                            f"{keystore_ui.label}: {analysis.msg}",
                            no_show=True,
                            type=MessageType.Error,
                            parent=self,
                        )
                    ]

        return return_messages

    def updateUi(self) -> None:
        # udpate the label for where the keystore exists
        """UpdateUi."""
        for i, keystore_ui in enumerate(self.getAllTabData().values()):
            keystore_ui.label = self.protowallet.signer_name(i)

        self._set_keystore_tabs()

    @property
    def protowallet(self) -> ProtoWallet:
        """Protowallet."""
        return self.get_editable_protowallet()

    def ui_keystore_ui_change(self, *args) -> None:
        """Ui keystore ui change."""
        logger.debug("ui_keystore_ui_change")
        try:
            self.set_protowallet_from_keystore_ui()
            self.set_keystore_ui_from_protowallet()
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            logger.warning("ui_keystore_ui_change: Invalid input")

    def set_protowallet_from_keystore_ui(self) -> None:
        # and last are the keystore uis, which can cause exceptions, because the UI is not filled correctly
        """Set protowallet from keystore ui."""
        for i, keystore_ui in enumerate(self.getAllTabData().values()):
            logger.debug("set_keystore_from_ui_values")
            ui_keystore = keystore_ui.get_ui_values_as_keystore()

            keystore = self.protowallet.keystores[i]
            if keystore is None:
                keystore = ui_keystore
                self.protowallet.keystores[i] = keystore
            else:
                keystore.from_other_keystore(ui_keystore)

        for i, keystore in enumerate(self.protowallet.keystores):
            if keystore is None:
                continue
            keystore.label = signer_name(self.protowallet.threshold, i)

    def _set_keystore_tabs(self) -> None:
        # add keystore_ui if necessary
        """Set keystore tabs."""
        if self.count() < len(self.protowallet.keystores):
            for i in range(self.count(), len(self.protowallet.keystores)):
                keystore_ui = KeyStoreUI(
                    self.protowallet.network,
                    get_address_type=self.get_address_type,
                    label=self.protowallet.signer_name(i),
                    signals_min=self.signals_min,
                    hardware_signer_label=self.protowallet.sticker_name(i),
                    slow_hwi_listing=self.slow_hwi_listing,
                    loop_in_thread=self.loop_in_thread,
                )
                keystore_ui.signal_signer_infos.connect(self.set_all_using_signer_infos)
                self.addTab(
                    keystore_ui,
                    icon=icon_for_label(keystore_ui.label),
                    description=keystore_ui.label,
                    data=keystore_ui,
                )

        # remove keystore_ui if necessary
        elif self.count() > len(self.protowallet.keystores):
            for _i in range(len(self.protowallet.keystores), self.count()):
                self.removeTab(self.count() - 1)

        # now make a second pass and set the ui
        for i, (keystore, keystore_ui) in enumerate(
            zip(self.protowallet.keystores, self.getAllTabData().values(), strict=False)
        ):
            keystore_ui.label = keystore.label if keystore else self.protowallet.signer_name(i)

            # set the tab title
            index = self.indexOf(keystore_ui)
            self.setTabText(index, keystore_ui.label)
            self.setTabIcon(index, icon_for_label(keystore_ui.label))
            keystore_ui.format_all_fields()

    def set_keystore_ui_from_protowallet(self) -> None:
        """Set keystore ui from protowallet."""
        logger.debug("set_keystore_ui_from_protowallet")
        self._set_keystore_tabs()
        for keystore, keystore_ui in zip(
            self.protowallet.keystores, self.getAllTabData().values(), strict=False
        ):
            if not keystore:
                continue
            keystore_ui.set_ui_from_keystore(keystore)
            # i have to manually call this, because the signals are blocked
            keystore_ui.format_all_fields()
        assert len(self.protowallet.keystores) == self.count()

    def get_keystore_uis_with_unexpected_origin(self) -> list[KeyStoreUI]:
        """Get keystore uis with unexpected origin."""
        return [
            keystore_ui
            for keystore_ui in self.getAllTabData().values()
            if keystore_ui.key_origin != keystore_ui.get_expected_key_origin()
        ]

    def ask_accept_unexpected_origins(self) -> bool:
        """Ask accept unexpected origins."""
        keystore_uis_with_unexpected_origin = self.get_keystore_uis_with_unexpected_origin()
        for keystore_ui in keystore_uis_with_unexpected_origin:
            if not question_dialog(
                f"The key derivation path {keystore_ui.key_origin} of {keystore_ui.label} is not the default {keystore_ui.get_expected_key_origin()} for the address type {keystore_ui.get_address_type().name}. Do you want to proceed anyway?",
                true_button=self.tr("Proceed anyway"),
            ):
                return False
        return True

    def close(self) -> bool:
        """Close."""
        self.signal_tracker.disconnect_all()
        for tab in self.getAllTabData().values():
            tab.close()

        SignalTools.disconnect_all_signals_from(self)

        return super().close()

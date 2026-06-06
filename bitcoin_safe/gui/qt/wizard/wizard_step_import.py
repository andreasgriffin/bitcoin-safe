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

from functools import partial

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.descriptor_ui import KeyStoreUIs
from bitcoin_safe.gui.qt.step_progress_bar import TutorialWidget

from ..util import MessageType, caught_exception_message
from .wizard_support import BaseTab, WizardTabInfo


class ImportXpubs(BaseTab):
    def __init__(
        self, refs: WizardTabInfo, loop_in_thread: LoopInThread, show_previous_step_button: bool
    ) -> None:
        """Initialize instance."""
        super().__init__(
            refs=refs, loop_in_thread=loop_in_thread, show_previous_step_button=show_previous_step_button
        )
        self.keystore_uis: KeyStoreUIs | None = None

    def _ensure_keystore_uis(self) -> None:
        """Create the signer UI only when the import step is actually needed."""
        if self.refs.qt_wallet or self.keystore_uis:
            return

        self.keystore_uis = KeyStoreUIs(
            get_editable_protowallet=self.refs.qtwalletbase.get_editable_protowallet,
            get_address_type=self.get_address_type,
            signals_min=self.refs.qtwalletbase.signals,
            loop_in_thread=self.loop_in_thread,
        )
        self.keystore_uis.signal_ui_changed.connect(self.updateUi)
        self.keystore_uis.signal_on_tab_change.connect(self.updateUi)
        self.widget_layout.addWidget(self.keystore_uis)
        self.set_current_signer(0)

    def _callback(self, tutorial_widget: TutorialWidget) -> None:
        """Callback."""
        del tutorial_widget
        self._ensure_keystore_uis()

    def _create_wallet(self) -> None:
        """Create wallet."""
        if not self.keystore_uis:
            return

        if not self.ask_if_can_proceed():
            return

        try:
            self.keystore_uis.set_protowallet_from_keystore_ui()
            self.refs.signal_create_wallet.emit(self.keystore_uis.protowallet.id)
        except Exception as e:
            caught_exception_message(e, parent=self.refs.container)

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        self.widget_layout = QVBoxLayout(widget)
        self.widget_layout.setContentsMargins(0, 0, 0, 0)

        self.label_import = QLabel()
        self.widget_layout.addWidget(self.label_import)

        self.button_create_wallet = QPushButton("", self.buttonbox)
        if self.refs.qt_wallet:
            self.keystore_uis = None
        else:
            self.button_next.setHidden(True)
            self.buttonbox.add_action_button(self.button_create_wallet)
            self.button_create_wallet.clicked.connect(self._create_wallet)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.set_callback(partial(self._callback, tutorial_widget))

        self.updateUi()
        return tutorial_widget

    def get_address_type(self):
        """Get address type."""
        return self.refs.qtwalletbase.get_editable_protowallet().address_type

    def set_current_signer(self, value: int) -> None:
        """Set current signer."""
        if not self.keystore_uis:
            return
        self.keystore_uis.setCurrentIndex(value)
        self.updateUi()

    def ask_if_can_proceed(self) -> bool:
        """Ask if can proceed."""
        if not self.keystore_uis:
            return False

        messages = self.keystore_uis.get_warning_and_error_messages(
            keystore_uis=list(self.keystore_uis.getAllTabData().values())
        )
        error_messages = [message for message in messages if message.type == MessageType.Error]
        if error_messages:
            error_messages[0].show()
            return False

        warning_messages = [message for message in messages if message.type == MessageType.Warning]
        for warning_message in warning_messages:
            if not warning_message.ask(
                yes_button=QMessageBox.StandardButton.Ignore,
                no_button=QMessageBox.StandardButton.Cancel,
            ):
                return False
        return True

    def can_go_to_next_step(self) -> bool:
        """Return whether all signer cards are complete enough to continue."""
        if not self.keystore_uis:
            return False
        return not self.keystore_uis.has_blocking_messages()

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.label_import.setText(self.tr("Import hardware signer information into Bitcoin Safe"))
        self.button_create_wallet.setText(
            self.tr("Skip step") if self.refs.qt_wallet else self.tr("Next step")
        )
        self.button_previous.setText(self.tr("Previous Step"))

        if self.keystore_uis:
            self.button_create_wallet.setVisible(True)
            self.button_create_wallet.setEnabled(self.can_go_to_next_step())
            self.button_previous.setVisible(True)

    def set_visibilities(self, should_be_visible: bool) -> None:
        """Refresh the signer cards when the step becomes active."""
        if should_be_visible:
            self._ensure_keystore_uis()
        if should_be_visible and self.keystore_uis:
            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.set_current_signer(min(self.keystore_uis.currentIndex(), self.keystore_uis.count() - 1))

    def close(self) -> None:
        """Close."""
        super().close()
        if self.keystore_uis:
            self.keystore_uis.close()

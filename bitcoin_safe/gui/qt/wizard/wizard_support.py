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

from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from bitcoin_safe.html_utils import html_f
from bitcoin_safe.i18n import translate

from ....pdfrecovery import TEXT_24_WORDS
from ..qt_wallet import QTWallet, QtWalletBase
from ..step_progress_bar import StepProgressContainer, TutorialWidget
from ..util import svg_tools

if TYPE_CHECKING:
    from .wizard import TutorialStep, Wizard


class WizardNavigationBar(QWidget):
    def __init__(
        self,
        go_to_next_index: Callable,
        go_to_previous_index: Callable,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.button_previous = QPushButton(parent=self)
        self.button_previous.clicked.connect(go_to_previous_index)

        self.button_next = QPushButton(parent=self)
        self.button_next.clicked.connect(go_to_next_index)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.button_previous)
        self._layout.addStretch()
        self._layout.addWidget(self.button_next)

    def add_action_button(self, button: QPushButton) -> None:
        """Insert an extra action button before the next-step button."""
        button.setParent(self)
        self._layout.insertWidget(self._layout.count() - 1, button)


class WizardTabInfo:
    def __init__(
        self,
        container: StepProgressContainer,
        qtwalletbase: QtWalletBase,
        go_to_next_index: Callable,
        go_to_previous_index: Callable,
        signal_create_wallet: SignalProtocol[str],
        max_test_fund: int,
        qt_wallet: QTWallet | None = None,
    ) -> None:
        """Initialize instance."""
        self.container = container
        self.wallet_tabs = qtwalletbase.tabs
        self.qtwalletbase = qtwalletbase
        self.go_to_next_index = go_to_next_index
        self.go_to_previous_index = go_to_previous_index
        self.signal_create_wallet = signal_create_wallet
        self.qt_wallet = qt_wallet
        self.max_test_fund = max_test_fund


class BaseTab(QObject):
    def __init__(
        self, refs: WizardTabInfo, loop_in_thread: LoopInThread, show_previous_step_button: bool
    ) -> None:
        """Initialize instance."""
        self.refs = refs
        super().__init__(parent=refs.container)

        self.previous_step_enabled = True
        self.show_previous_step_button = show_previous_step_button

        self.loop_in_thread = loop_in_thread
        self.signal_tracker = SignalTracker()
        self.buttonbox = WizardNavigationBar(
            go_to_next_index=self.refs.go_to_next_index,
            go_to_previous_index=self.refs.go_to_previous_index,
            parent=refs.container,
        )
        self.buttonbox.setVisible(False)
        self.signal_tracker.connect(
            cast(SignalProtocol[[]], self.refs.qtwalletbase.signals.language_switch), self.updateUi
        )

    @property
    def button_next(self) -> QPushButton:
        """Button next."""
        return self.buttonbox.button_next

    @property
    def button_previous(self) -> QPushButton:
        """Button previous."""
        return self.buttonbox.button_previous

    @abstractmethod
    def create(self) -> TutorialWidget:
        """Create."""
        raise NotImplementedError

    def updateUi(self) -> None:
        """UpdateUi."""
        self.apply_next_button_style(self.button_next)
        self.button_previous.setText(translate("basetab", "Previous step"))
        self.button_previous.setVisible(self.show_previous_step_button)
        self.button_previous.setEnabled(self.previous_step_enabled)

    def apply_next_button_style(self, button: QPushButton) -> None:
        """Apply the default style for a button that advances the tutorial."""
        button.setText(self.get_next_button_text())
        button.setIcon(svg_tools.get_QIcon("checkmark.svg") if self.is_last_displayed_step() else QIcon())

    def get_next_button_text(self) -> str:
        """Return the default label for the step-advance button."""
        return (
            translate("basetab", "Finish and go to Dashboard")
            if self.is_last_displayed_step()
            else translate("basetab", "Next step")
        )

    def is_last_displayed_step(self) -> bool:
        """Return whether this tab is the final displayed wizard step."""
        wizard = self.wizard_parent()
        step = self.wizard_step()
        return bool(wizard and step and wizard.get_displayed_steps()[-1] == step)

    def num_keystores(self) -> int:
        """Num keystores."""
        return self.refs.qtwalletbase.get_mn_tuple()[1]

    def get_never_label_text(self) -> str:
        """Get never label text."""
        return html_f(
            html_f(
                translate("tutorial", "Never share the {number} secret words with anyone!").format(
                    number=TEXT_24_WORDS
                ),
                p=True,
                size=12,
                color="red",
            )
            + html_f(
                translate("tutorial", "Never type them into any computer or cellphone!"),
                p=True,
                size=12,
                color="red",
            )
            + html_f(translate("tutorial", "Never make a picture of them!"), p=True, size=12, color="red"),
            add_html_and_body=True,
        )

    def wizard_parent(self) -> Wizard | None:
        """Return the parent wizard when this step is hosted inside one."""
        from .wizard import Wizard

        parent = self.refs.container.parent()
        return parent if isinstance(parent, Wizard) else None

    def wizard_step(self) -> TutorialStep | None:
        """Return the tutorial step mapped to this tab."""
        wizard = self.wizard_parent()
        if not wizard:
            return None
        for step, tab in wizard.tab_generators.items():
            if tab is self:
                return step
        return None

    def set_visibilities(self, should_be_visible: bool) -> None:
        """Set visibilities."""
        del should_be_visible

    def close(self) -> None:
        """Close."""
        self.signal_tracker.disconnect_all()
        self.setParent(None)
        del self.refs

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

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalTools, SignalTracker
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.signals import SignalsMin

from .step_progress_bar import StepProgressContainer

logger = logging.getLogger(__name__)


class WizardBase(QWidget):
    def __init__(
        self,
        step_labels: list[str],
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        current_index: int = 0,
        collapsible_current_active=False,
        clickable=True,
        use_checkmark_icon=True,
        parent=None,
        sub_indices: list[int] | None = None,
        use_resizing_stacked_widget=True,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.step_container = StepProgressContainer(
            step_labels=step_labels,
            signals_min=signals_min,
            current_index=current_index,
            collapsible_current_active=collapsible_current_active,
            clickable=clickable,
            use_checkmark_icon=use_checkmark_icon,
            parent=parent,
            sub_indices=sub_indices,
            use_resizing_stacked_widget=use_resizing_stacked_widget,
            loop_in_thread=loop_in_thread,
        )
        self.loop_in_thread = loop_in_thread
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.step_container)

        self.signal_tracker = SignalTracker()
        self.node = SidebarNode[object](
            title=self.tr("Wizard"),
            data=self,
            widget=self,
            icon=svg_tools.get_QIcon("stars4.svg"),
        )

    def set_visibilities(self) -> None:
        """Set visibilities."""
        pass

    def toggle_tutorial(self) -> None:
        """Toggle tutorial."""
        pass

    def deleterefrences(self):
        """Deleterefrences."""
        pass

    def close(self) -> bool:
        """Close."""
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)

        self.setParent(None)
        return super().close()

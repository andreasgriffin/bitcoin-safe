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
from typing import List

from bitcoin_safe.signal_tracker import SignalTools, SignalTracker
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.threading_manager import ThreadingManager

logger = logging.getLogger(__name__)


from .step_progress_bar import StepProgressContainer


class WizardBase(StepProgressContainer):
    def __init__(
        self,
        step_labels: List[str],
        signals_min: SignalsMin,
        current_index: int = 0,
        collapsible_current_active=False,
        clickable=True,
        use_checkmark_icon=True,
        parent=None,
        sub_indices: List[int] | None = None,
        use_resizing_stacked_widget=True,
        threading_parent: ThreadingManager | None = None,
    ) -> None:
        super().__init__(
            step_labels,
            signals_min,
            current_index,
            collapsible_current_active,
            clickable,
            use_checkmark_icon,
            parent,
            sub_indices,
            use_resizing_stacked_widget,
            threading_parent,
        )

        self.signal_tracker = SignalTracker()

    def set_visibilities(self) -> None:
        pass

    def toggle_tutorial(self) -> None:
        pass

    def deleterefrences(self):
        pass

    def close(self):

        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)

        self.setParent(None)
        super().close()

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
from time import monotonic

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

logger = logging.getLogger(__name__)


class StartupWindowProbe(QObject):
    """Logs unexpected top-level windows that briefly appear during startup."""

    def __init__(self, app: QApplication, expected_main_window: QWidget, active_ms: int = 6000) -> None:
        super().__init__(app)
        self._app = app
        self._expected_main_window = expected_main_window
        self._end_at = monotonic() + (active_ms / 1000)
        self._shown_at: dict[int, float] = {}
        self._reported_ids: set[int] = set()
        self._app.installEventFilter(self)
        QTimer.singleShot(active_ms, self.stop)

    def stop(self) -> None:
        self._app.removeEventFilter(self)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None or a0 is None:
            return False
        if monotonic() > self._end_at:
            self.stop()
            return False
        if not isinstance(a0, QWidget):
            return False

        event_type = a1.type()
        if event_type == QEvent.Type.Show and self._is_tracked_window(a0):
            self._on_show(a0)
        elif event_type == QEvent.Type.Hide and self._is_tracked_window(a0):
            self._on_hide(a0)

        return False

    def _is_tracked_window(self, widget: QWidget) -> bool:
        if widget is self._expected_main_window:
            return False
        if not widget.isWindow():
            return False
        if widget.windowType() in {
            Qt.WindowType.Popup,
            Qt.WindowType.ToolTip,
            Qt.WindowType.SplashScreen,
        }:
            return False
        return True

    def _on_show(self, widget: QWidget) -> None:
        widget_id = id(widget)
        if widget_id in self._reported_ids:
            return
        self._shown_at[widget_id] = monotonic()
        self._reported_ids.add(widget_id)
        logger.warning(
            "Startup window shown: %s",
            self._format_widget(widget),
        )

    def _on_hide(self, widget: QWidget) -> None:
        widget_id = id(widget)
        shown_at = self._shown_at.get(widget_id)
        if shown_at is None:
            return
        duration_ms = int((monotonic() - shown_at) * 1000)
        logger.warning(
            "Startup window hidden after %sms: %s",
            duration_ms,
            self._format_widget(widget),
        )

    @staticmethod
    def _format_widget(widget: QWidget) -> str:
        parent = widget.parentWidget()
        parent_name = parent.__class__.__name__ if parent else None
        button_text = widget.text() if isinstance(widget, QPushButton) else ""
        return (
            f"class={widget.__class__.__name__} title={widget.windowTitle()!r} "
            f"object={widget.objectName()!r} text={button_text!r} parent={parent_name}"
        )

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

from functools import partial
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon, QWidget

from bitcoin_safe.gui.qt.util import Message, svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu

MAX_TRAY_NOTIFICATIONS = 10


class TrayController(QSystemTrayIcon):
    signal_on_close = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, parent: QMainWindow) -> None:
        tray_icon_default = svg_tools.get_QIcon("logo.svg")
        super().__init__(tray_icon_default, parent)
        self._parent = parent
        self._tray_visible_windows: list[QWidget] = []
        self._tray_prev_active: QWidget | None = None
        self._tray_hidden = False
        self._tray_notifications: list[Message] = []
        self._tray_icon_default = tray_icon_default
        self._tray_icon_notification = self._build_tray_notification_icon()

        self.setToolTip("Bitcoin Safe")

        menu = Menu(parent)
        menu.add_action(text=parent.tr("Show/Hide"), slot=self.toggle_window_visibility)
        self._tray_menu_past_notifications = menu.add_menu(parent.tr("Past notifications"))
        self._refresh_tray_notifications_menu()
        menu.addSeparator()
        menu.add_action(text=parent.tr("&Exit"), slot=self.on_tray_close)

        self.setContextMenu(menu)
        self.activated.connect(self._on_tray_activated)
        self.show()

    def set_hidden(self, hidden: bool) -> None:
        self._tray_hidden = hidden
        if not hidden:
            self.setIcon(self._tray_icon_default)

    def is_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show_message(self, message: Message) -> None:
        icon, _ = message.get_icon_and_title()
        tray_icon = Message.system_tray_icon(icon)
        title = message.title or "Bitcoin Safe"
        self._record_tray_notification(message=message)
        if message.msecs:
            self.showMessage(title, message.msg, tray_icon, message.msecs)
            return
        self.showMessage(title, message.msg, tray_icon)

    def show_message_as_tray_notification(self, message: Message) -> None:
        """Show message as tray notification without recording past notifications."""
        icon, _ = message.get_icon_and_title()
        tray_icon = Message.system_tray_icon(icon)
        title = message.title or "Bitcoin Safe"
        if message.msecs:
            self.showMessage(title, message.msg, tray_icon, message.msecs)
            return
        self.showMessage(title, message.msg, tray_icon)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def toggle_window_visibility(self) -> None:
        """Toggle between hidden-to-tray and visible window."""
        if not self.is_available():
            if not self._parent.isVisible() or (self._parent.windowState() & Qt.WindowState.WindowMinimized):
                self._parent.show()
                self._parent.setWindowState(Qt.WindowState.WindowActive)
                self._parent.activateWindow()
            else:
                self._parent.showMinimized()
            return

        if self._parent.isHidden() or (self._parent.windowState() & Qt.WindowState.WindowMinimized):
            self.restore_from_tray()
        else:
            self.minimize_to_tray()

    def minimize_to_tray(self) -> None:
        """Minimize to tray."""
        self._tray_visible_windows = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        self._tray_prev_active = QApplication.activeWindow()
        self.set_hidden(True)

        for window in self._tray_visible_windows:
            window.hide()

    def restore_from_tray(self) -> None:
        """Restore from tray."""
        if not self._tray_visible_windows:
            self._parent.show()
            self._parent.setWindowState(
                (self._parent.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
            )
            self._parent.activateWindow()
            self._parent.raise_()
            self.set_hidden(False)
            return

        for window in self._tray_visible_windows:
            window.show()
            window.setWindowState(
                (window.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
            )

        target = self._tray_prev_active or self._tray_visible_windows[0]
        target.activateWindow()
        target.raise_()

        self._tray_visible_windows = []
        self._tray_prev_active = None
        self.set_hidden(False)

    def minimize_to_tray_from_menu(self) -> None:
        """Minimize to tray from menu, with fallback when tray is unavailable."""
        if self.is_available():
            self.minimize_to_tray()
            return

        self._parent.showMinimized()

    def on_tray_close(self) -> None:
        """Handle tray close action."""
        self.signal_on_close.emit()

    def _record_tray_notification(self, message: Message) -> None:
        history_message = message.clone()
        # Drop the parent reference so tray history does not keep unnecessary
        # references to UI objects alive.
        history_message.strip_parent()
        self._tray_notifications.append(history_message)
        if len(self._tray_notifications) > MAX_TRAY_NOTIFICATIONS:
            self._tray_notifications = self._tray_notifications[-MAX_TRAY_NOTIFICATIONS:]
        if self._tray_hidden:
            self.setIcon(self._tray_icon_notification)
        self._refresh_tray_notifications_menu()

    def _refresh_tray_notifications_menu(self) -> None:
        self._tray_menu_past_notifications.clear()
        if not self._tray_notifications:
            empty_action = self._tray_menu_past_notifications.add_action(
                text=self._parent.tr("No notifications")
            )
            empty_action.setEnabled(False)
            return
        for notification in self._tray_notifications:
            label = self._format_tray_notification_label(notification)
            action = self._tray_menu_past_notifications.add_action(
                text=label,
                slot=partial(self._show_past_notification, notification),
            )
            action.setEnabled(True)
        self._tray_menu_past_notifications.addSeparator()
        self._tray_menu_past_notifications.add_action(
            text=self._parent.tr("Clear notifications"),
            slot=self._clear_tray_notifications,
        )

    def _format_tray_notification_label(self, message: Message) -> str:
        title = message.title or "Bitcoin Safe"
        body = message.msg
        timestamp_str = message.created_at.strftime("%H:%M:%S")
        title_str = title.replace("\n", " ").strip()
        message_str = body.replace("\n", " ").strip()
        label = f"{timestamp_str} {title_str}: {message_str}"
        return self._truncate_tray_label(label, max_len=80)

    def _truncate_tray_label(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return f"{text[: max_len - 3]}..."

    def _clear_tray_notifications(self) -> None:
        self._tray_notifications = []
        self.setIcon(self._tray_icon_default)
        self._refresh_tray_notifications_menu()

    def _show_past_notification(self, message: Message) -> None:
        icon, _ = message.get_icon_and_title()
        tray_icon = Message.system_tray_icon(icon)
        title = message.title or "Bitcoin Safe"
        safe_title = title.replace("\n", " ").strip() or "Bitcoin Safe"
        safe_message = message.msg.replace("\n", " ").strip()
        self.showMessage(
            safe_title,
            safe_message,
            tray_icon,
        )

    def _build_tray_notification_icon(self) -> QIcon:
        base_pixmap = self._tray_icon_default.pixmap(64, 64)
        pixmap = QPixmap(base_pixmap)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        size = min(pixmap.width(), pixmap.height())
        bell_size = int(size * 0.46)
        margin = int(size * 0.05)
        bell_rect = QRectF(
            size - bell_size - margin,
            margin,
            bell_size,
            bell_size,
        )

        painter.setPen(QColor(0, 0, 0))
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawEllipse(bell_rect)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(212, 175, 55))

        body_rect = QRectF(
            bell_rect.x() + bell_rect.width() * 0.25,
            bell_rect.y() + bell_rect.height() * 0.2,
            bell_rect.width() * 0.5,
            bell_rect.height() * 0.45,
        )
        painter.drawRoundedRect(body_rect, bell_rect.width() * 0.2, bell_rect.height() * 0.2)

        rim_rect = QRectF(
            bell_rect.x() + bell_rect.width() * 0.18,
            bell_rect.y() + bell_rect.height() * 0.62,
            bell_rect.width() * 0.64,
            bell_rect.height() * 0.12,
        )
        painter.drawRoundedRect(rim_rect, bell_rect.width() * 0.12, bell_rect.height() * 0.08)

        clapper_rect = QRectF(
            bell_rect.center().x() - bell_rect.width() * 0.07,
            bell_rect.y() + bell_rect.height() * 0.72,
            bell_rect.width() * 0.14,
            bell_rect.height() * 0.14,
        )
        painter.drawEllipse(clapper_rect)

        painter.end()
        return QIcon(pixmap)

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

import enum
import logging
import platform
import sys
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import (
    Any,
    Literal,
)
from urllib.parse import urlparse

import bdkpython as bdk
import PIL.Image as PilImage
from bitcoin_qr_tools.data import ConverterAddress
from bitcoin_safe_lib.caching import register_cache
from bitcoin_safe_lib.gui.qt.icons import SvgTools
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.util import adjust_brightness, is_dark_mode
from bitcoin_safe_lib.util import hash_string
from PyQt6.QtCore import (
    QByteArray,
    QCoreApplication,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPaintEvent,
    QPalette,
    QPixmap,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.execute_config import ENABLE_TIMERS
from bitcoin_safe.gui.qt.custom_edits import AnalyzerState
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.i18n import translate
from bitcoin_safe.util import resource_path

logger = logging.getLogger(__name__)


@dataclass
class TabInfo:
    widget: QWidget
    text: str
    icon: QIcon


if platform.system() == "Windows":
    MONOSPACE_FONT = "Lucida Console"
elif platform.system() == "Darwin":
    MONOSPACE_FONT = "Monaco"
else:
    MONOSPACE_FONT = "monospace"

QWIDGETSIZE_MAX = 16777215


# filter tx files in QFileDialog:
TRANSACTION_FILE_EXTENSION_FILTER_ANY = translate("constant", "Transaction (*.txn *.psbt);;All files (*)")
TRANSACTION_FILE_EXTENSION_FILTER_ONLY_PARTIAL_TX = translate("constant", "Partial Transaction (*.psbt)")
TRANSACTION_FILE_EXTENSION_FILTER_ONLY_COMPLETE_TX = translate("constant", "Complete Transaction (*.txn)")
TRANSACTION_FILE_EXTENSION_FILTER_SEPARATE = (
    f"{TRANSACTION_FILE_EXTENSION_FILTER_ONLY_PARTIAL_TX};;"
    f"{TRANSACTION_FILE_EXTENSION_FILTER_ONLY_COMPLETE_TX};;" + translate("constant", "All files (*)")
)


TX_ICONS: list[str] = [
    "clock0.svg",
    "clock1.svg",
    "clock2.svg",
    "clock3.svg",
    "clock4.svg",
    "clock5.svg",
    "confirmed.svg",
]


ELECTRUM_SERVER_DELAY_MEMPOOL_TX = 1000
ELECTRUM_SERVER_DELAY_BLOCK = 2000


def center_on_screen(widget: QWidget, min_height: int = 0, min_width: int = 0) -> None:
    if not widget or not widget.isWindow():
        return

    # Make sure we have a usable size
    if widget.width() == 0 or widget.height() == 0:
        widget.adjustSize()

    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if not screen:
        return

    # Respect minimum expected size
    w = max(min_width, widget.width())
    h = max(min_height, widget.height())

    geom = screen.availableGeometry()
    x = geom.center().x() - w // 2
    y = geom.center().y() - h // 2
    widget.move(x, y)


def get_icon_path(icon_basename: str) -> str:
    """Get icon path."""
    return resource_path("gui", "icons", icon_basename)


svg_tools = SvgTools(get_icon_path=get_icon_path, theme_file=get_icon_path("theme.csv"))


def get_hardware_signer_path(signer_basename: str) -> str:
    """Get hardware signer path."""
    return resource_path("gui", "icons", "hardware_signers", signer_basename)


svg_tools_hardware_signer = SvgTools(
    get_icon_path=get_hardware_signer_path, theme_file=get_icon_path("theme.csv")
)


def get_generated_hardware_signer_path(signer_basename: str) -> str:
    """Get generated hardware signer path."""
    return resource_path("gui", "icons", "hardware_signers", "generated", signer_basename)


svg_tools_generated_hardware_signer = SvgTools(
    get_icon_path=get_generated_hardware_signer_path, theme_file=get_icon_path("theme.csv")
)


def block_explorer_URL(
    mempool_url: str, kind: Literal["tx", "addr", "block", "mempool"], item: str | int
) -> str | None:
    """Block explorer URL."""
    explorer_url, explorer_dict = (
        mempool_url,
        {
            "tx": "tx/",
            "addr": "address/",
            "block": "block/",
            "mempool": "mempool-block/",
        },
    )
    kind_str = explorer_dict.get(kind)
    if kind_str is None:
        return None
    if explorer_url[-1] != "/":
        explorer_url += "/"
    url_parts = [explorer_url, kind_str, str(item)]
    return "".join(url_parts)


class QtWalletBase(QWidget):
    pass


def sort_id_to_icon(sort_id: int) -> str:
    """Sort id to icon."""
    if sort_id < 0:
        return "offline_tx.svg"
    if sort_id > len(TX_ICONS) - 1:
        sort_id = len(TX_ICONS) - 1

    return TX_ICONS[sort_id]


def open_website(url: str):
    """Open website."""
    QDesktopServices.openUrl(QUrl(url))


def proportional_fit_into_max(x, y, x_max, y_max):
    """Scales (x, y) proportionally to fit within (x_max, y_max) while maintaining
    aspect ratio.

    :param x: Original width
    :param y: Original height
    :param x_max: Maximum allowed width
    :param y_max: Maximum allowed height
    :return: (new_x, new_y) scaled dimensions
    """
    # Calculate scaling factors for width and height
    scale_x = x_max / x
    scale_y = y_max / y

    # Choose the smaller scale factor to maintain aspect ratio
    scale = min(scale_x, scale_y)

    # Compute new dimensions
    new_x = int(x * scale)
    new_y = int(y * scale)

    return new_x, new_y


def qresize(qsize: QSize, max_sizes: tuple[int, int]):
    """Qresize."""
    x, y = proportional_fit_into_max(qsize.width(), qsize.height(), *max_sizes)
    return QSize(int(x), int(y))


def center_in_widget(
    widgets: Iterable[QWidget], parent: QWidget, direction="h", alignment=Qt.AlignmentFlag.AlignCenter
):
    """Center in widget."""
    outer_layout = QHBoxLayout(parent) if direction == "h" else QVBoxLayout(parent)
    outer_layout.setAlignment(alignment)
    for widget in widgets:
        outer_layout.addWidget(widget)
        # outer_layout.setAlignment(widget, alignment)
    return outer_layout


def generate_help_button(help_widget: QWidget, title: str | None = None) -> QPushButton:
    """Generate help button."""
    if title is None:
        title = translate("help", "Help")
    # add the help buttonbox
    button_help = QPushButton()
    button_help.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    button_help.setText(title)
    button_help.setIcon(svg_tools.get_QIcon("bi--question-circle.svg"))

    def show_screenshot_tutorial():
        """Show screenshot tutorial."""
        help_widget.setWindowTitle(title)
        help_widget.show()

    button_help.clicked.connect(show_screenshot_tutorial)
    return button_help


class AspectRatioSvgWidget(QWidget):
    """A drop-in widget that displays an SVG while always preserving its aspect ratio.
    You can optionally dictate the size-hint’s width or height and the other dimension
    will be computed from the SVG’s intrinsic aspect ratio.

    widget = AspectRatioSvgWidget(     svg_content=raw_svg,     size_hint_width=128          # height is auto-
    calculated )
    """

    def __init__(
        self,
        svg_content: str | None = None,
        size_hint_width: int | None = None,
        size_hint_height: int | None = None,
        parent=None,
    ):
        """Initialize instance."""
        super().__init__(parent)

        # Store caller-desired hint(s); they may be refined once the SVG loads
        self._requested_hint_w = size_hint_width
        self._requested_hint_h = size_hint_height

        self._renderer = QSvgRenderer(parent=self)

        if svg_content:
            self.setSvgContent(svg_content)

        self.setMinimumSize(10, 10)

    # ------------------------------------------------------------------ API

    def setSvgContent(self, svg_content: str) -> None:
        """Load an SVG string already in memory."""
        self._renderer.load(QByteArray(svg_content.encode()))
        self.updateGeometry()  # sizeHint may have changed
        self.update()

    def load(self, filepath: str) -> None:
        """Load an SVG from disk (convenience wrapper)."""
        self._renderer.load(filepath)
        self.updateGeometry()
        self.update()

    # -------------------------------------------------------------- Qt stuff

    def sizeHint(self) -> QSize:
        """Return the preferred size according to caller input and/or the SVG’s own
        aspect ratio.

        Falls back to the renderer’s default size when no hints were supplied.
        """
        if not self._renderer.isValid():
            # No valid SVG yet – rely on any caller hints or give a stub size
            if self._requested_hint_w and self._requested_hint_h:
                return QSize(self._requested_hint_w, self._requested_hint_h)
            if self._requested_hint_w:
                return QSize(self._requested_hint_w, self._requested_hint_w)
            if self._requested_hint_h:
                return QSize(self._requested_hint_h, self._requested_hint_h)
            return QSize(100, 100)

        # Renderer knows the intrinsic ViewBox aspect ratio
        view_box: QRectF = self._renderer.viewBoxF()
        if view_box.isEmpty():
            view_box = QRectF(0, 0, 1, 1)
        vw, vh = view_box.width(), view_box.height()
        aspect = vw / vh if vh else 1.0

        # Apply caller-requested hint(s) while preserving aspect
        if self._requested_hint_w and self._requested_hint_h:
            return QSize(self._requested_hint_w, self._requested_hint_h)
        elif self._requested_hint_w:
            return QSize(self._requested_hint_w, int(round(self._requested_hint_w / aspect)))
        elif self._requested_hint_h:
            return QSize(int(round(self._requested_hint_h * aspect)), self._requested_hint_h)
        else:
            # No override – defer to the SVG’s own default size
            return self._renderer.defaultSize()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """PaintEvent."""
        painter = QPainter(self)
        if not self._renderer.isValid():
            return

        view_box: QRectF = self._renderer.viewBoxF()
        if view_box.isEmpty():
            view_box = QRectF(0, 0, 1, 1)

        w, h = self.width(), self.height()
        vw, vh = view_box.width(), view_box.height()

        scale = min(w / vw, h / vh)
        new_w, new_h = vw * scale, vh * scale
        x = (w - new_w) * 0.5
        y = (h - new_h) * 0.5
        target = QRectF(x, y, new_w, new_h)

        self._renderer.render(painter, target)


def add_centered_icons(
    paths: list[str],
    parent_layout: QBoxLayout,
    direction="h",
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    max_sizes: Iterable[tuple[int, int]] = [],
) -> list[AspectRatioSvgWidget]:
    """Add centered icons."""
    max_sizes = max_sizes if max_sizes else [(60, 80) for path in paths]
    if len(paths) > 1 and len(max_sizes) == 1:  # type: ignore
        max_sizes = max_sizes * len(paths)  # type: ignore

    svg_widgets: list[AspectRatioSvgWidget] = []
    for max_size, path in zip(max_sizes, paths, strict=False):
        widget = AspectRatioSvgWidget(
            svg_content=svg_tools.get_svg_content(path),
        )
        widget.setMaximumWidth(max_size[0])
        widget.setMaximumHeight(max_size[1])
        svg_widgets.append(widget)

    widget1 = QWidget()
    parent_layout.addWidget(widget1)
    inner_layout = center_in_widget(svg_widgets, widget1, direction=direction, alignment=alignment)
    inner_layout.setContentsMargins(1, 0, 1, 0)  # left, top, right, bottom

    return svg_widgets


def add_to_buttonbox(
    buttonBox: QDialogButtonBox,
    text: str,
    icon_name: str | QIcon | None = None,
    on_clicked=None,
    role=QDialogButtonBox.ButtonRole.ActionRole,
    button=None,
):
    # Create a custom QPushButton with an icon
    """Add to buttonbox."""
    button = button if button else QPushButton(text)
    if isinstance(icon_name, QIcon):
        button.setIcon(icon_name)
    elif icon_name:
        button.setIcon(svg_tools.get_QIcon(icon_name))

    # Add the button to the QDialogButtonBox
    buttonBox.addButton(button, role)

    # Optionally connect the button's clicked signal
    if on_clicked:
        button.clicked.connect(on_clicked)
    return button


class MessageType(enum.Enum):
    Info = enum.auto()
    Warning = enum.auto()
    Error = enum.auto()
    Critical = enum.auto()

    @classmethod
    def from_analyzer_state(cls, analyzer_state: AnalyzerState) -> MessageType:
        """From analyzer state."""
        return list(MessageType)[int(analyzer_state) - 1]


class Message:
    def __init__(
        self,
        msg: str,
        parent: QWidget | None = None,
        title: str | None = None,
        icon: QIcon | QPixmap | QMessageBox.Icon | None = None,
        msecs=None,
        type: MessageType = MessageType.Info,
        created_at: datetime | None = None,
        no_show=False,
        **kwargs,
    ) -> None:
        """Initialize instance."""
        self.msg = msg
        self.parent = parent
        self.title = title
        self.icon = icon
        self.msecs = msecs
        self.type = type
        self.created_at = created_at or datetime.now()
        self.kwargs = kwargs

        if not no_show:
            self.show()

    def clone(self) -> Message:
        return Message(
            msg=self.msg,
            parent=self.parent,
            title=self.title,
            icon=self.icon,
            msecs=self.msecs,
            type=self.type,
            created_at=self.created_at,
            no_show=True,
            **self.kwargs,
        )

    def strip_parent(self) -> None:
        self.parent = None

    @staticmethod
    def system_tray_icon(
        icon: QIcon | QPixmap | QMessageBox.Icon | QSystemTrayIcon.MessageIcon | None,
    ) -> QIcon | QSystemTrayIcon.MessageIcon:
        """System tray icon."""
        if isinstance(icon, QIcon):
            return icon

        if isinstance(icon, QSystemTrayIcon.MessageIcon):
            return icon

        if isinstance(icon, QPixmap):
            return QIcon(icon)

        if type(icon) is QMessageBox.Icon:
            if icon == QMessageBox.Icon.Information:
                return QSystemTrayIcon.MessageIcon.Information
            if icon == QMessageBox.Icon.Warning:
                return QSystemTrayIcon.MessageIcon.Warning
            if icon == QMessageBox.Icon.Critical:
                return QSystemTrayIcon.MessageIcon.Critical

        return QSystemTrayIcon.MessageIcon.NoIcon

    def get_icon_and_title(self) -> tuple[QIcon | QPixmap | QMessageBox.Icon, str]:
        """Get icon and title."""
        icon = QMessageBox.Icon.Information
        title = "Information"
        if self.type in [MessageType.Warning]:
            icon = QMessageBox.Icon.Warning
            title = "Warning"
        if self.type in [MessageType.Error]:
            icon = QMessageBox.Icon.Warning
            title = "Error"
        if self.type in [MessageType.Critical]:
            icon = QMessageBox.Icon.Critical
            title = "Critical Error"

        return_icon = self.icon or icon
        title = self.title or title
        return return_icon, title

    def show(self) -> None:
        """Show."""
        self.create().exec()

    def create(self) -> QMessageBox:
        """Create."""
        if self.type == MessageType.Info:
            logger.info(str(self.__dict__))
        elif self.type == MessageType.Warning:
            logger.warning(str(self.__dict__))
        elif self.type == MessageType.Error:
            logger.error(str(self.__dict__))

        icon, title = self.get_icon_and_title()

        return self.msg_box(
            icon,
            self.parent,
            title,
            self.msg,
            **self.kwargs,
        )

    def ask(
        self,
        yes_button: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        no_button: QMessageBox.StandardButton = QMessageBox.StandardButton.Cancel,
    ) -> bool:
        """Ask."""
        msg_box = self.create()
        msg_box.setStandardButtons(yes_button | no_button)
        ret = msg_box.exec()

        # Check which button was clicked
        if ret == yes_button:
            return True
        elif ret == no_button:
            return False
        return False

    def emit_with(self, notification_signal: SignalProtocol[Message]):
        """Emit with."""
        logger.debug(str(self.__dict__))
        return notification_signal.emit(self)

    def msg_box(
        self,
        icon: QIcon | QPixmap | QMessageBox.Icon,
        parent,
        title: str,
        text: str,
        *,
        buttons=QMessageBox.StandardButton.Ok,
        defaultButton=QMessageBox.StandardButton.NoButton,
        rich_text=True,
        checkbox=None,
    ) -> QMessageBox:
        # parent = parent or self.top_level_window()
        """Msg box."""
        return custom_message_box(
            icon=icon,
            parent=parent,
            title=title,
            text=text,
            buttons=buttons,
            defaultButton=defaultButton,
            rich_text=rich_text,
            checkbox=checkbox,
        )


def custom_exception_handler(exc_type, exc_value, exc_traceback=None):
    """Custom exception handler to catch unhandled exceptions and display an error
    message box."""
    title = "Error"
    try:
        # Format the traceback for the email
        "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        error_message = f"{exc_type.__name__}: {exc_value}"

        logger.critical(error_message, exc_info=(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(
            None,  # type: ignore[arg-type]
            title,
            f"{error_message}\n\nPlease send the error report via email, so the bug can be fixed.",
        )

    except Exception:
        error_message = str([exc_type, exc_value, exc_traceback])
        logger.critical(error_message)
        QMessageBox.critical(
            None,  # type: ignore[arg-type]
            title,
            f"{error_message}\n\nPlease send the error report via email, so the bug can be fixed.",
        )


def caught_exception_message(
    e: Exception, title: str | None = None, exc_info=None, parent: QWidget | None = None
) -> Message:
    """Caught exception message."""
    exception_msg = str(e).replace("\\", "")
    exception_text = f"{e.__class__}: {exception_msg}"

    logger.error(exception_text, exc_info=exc_info or sys.exc_info())

    text = title + "\n\n" if title else ""
    text += exception_text
    return Message(text, type=MessageType.Error, parent=parent)


def custom_message_box(
    *,
    icon: QIcon | QPixmap | QMessageBox.Icon,
    parent,
    title: str,
    text: str,
    buttons=QMessageBox.StandardButton.Ok,
    defaultButton=QMessageBox.StandardButton.NoButton,
    rich_text=False,
    checkbox=None,
) -> QMessageBox:
    """Custom message box."""
    if not isinstance(icon, (QIcon, QPixmap, QMessageBox.Icon)):
        raise ValueError(f"{icon} is not a valid type")

    if isinstance(icon, QMessageBox.Icon):
        d = QMessageBox(icon, title, str(text), buttons, parent)
    else:
        d = QMessageBox(QMessageBox.Icon.Information, title, str(text), buttons, parent)
        pixmap_icon = None
        if isinstance(icon, QPixmap):
            pixmap_icon = icon
        if isinstance(icon, QIcon):
            pixmap_icon = icon.pixmap(60, 60)

        if pixmap_icon:
            d.setIconPixmap(pixmap_icon)

    d.setWindowModality(Qt.WindowModality.WindowModal)
    d.setDefaultButton(defaultButton)
    if rich_text:
        d.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        # set AutoText instead of RichText
        # AutoText lets Qt figure out whether to render as rich text.
        # e.g. if text is actually plain text and uses "\n" newlines;
        #      and we set RichText here, newlines would be swallowed
        d.setTextFormat(Qt.TextFormat.AutoText)
    else:
        d.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        d.setTextFormat(Qt.TextFormat.PlainText)
    if checkbox is not None:
        d.setCheckBox(checkbox)
    return d


class WindowModalDialog(QDialog):
    """Handy wrapper; window modal dialogs are better for our multi-window daemon model
    as other wallet windows can still be accessed."""

    def __init__(self, parent, title=None):
        """Initialize instance."""
        QDialog.__init__(self, parent)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        if title:
            self.setWindowTitle(title)


class BlockingWaitingDialog(WindowModalDialog):
    """Shows a waiting dialog whilst running a task.

    Should be called from the GUI thread. The GUI thread will be blocked while the task is running; the point
    of the dialog is to provide feedback to the user regarding what is going on.
    """

    def __init__(self, parent: QWidget, message: str, task: Callable[[], Any]):
        """Initialize instance."""
        assert parent
        WindowModalDialog.__init__(self, parent, self.tr("Please wait"))
        self.message_label = QLabel(message)
        vbox = QVBoxLayout(self)
        vbox.addWidget(self.message_label)
        self.finished.connect(self.close)  # see #3956
        # show popup
        self.show()
        # refresh GUI; needed for popup to appear and for message_label to get drawn
        QCoreApplication.processEvents()
        QCoreApplication.processEvents()
        try:
            # block and run given task
            task()
        finally:
            # close popup
            self.accept()


def one_time_signal_connection(signal: SignalProtocol, f: Callable):
    """One time signal connection."""

    def f_wrapper(*args, **kwargs):
        """F wrapper."""
        signal.disconnect(f_wrapper)
        return f(*args, **kwargs)

    signal.connect(f_wrapper)


def create_button_box(
    callback_ok, callback_cancel, ok_text=None, cancel_text=None
) -> tuple[QDialogButtonBox, list[QPushButton]]:
    # Create the QDialogButtonBox instance
    """Create button box."""
    button_box = QDialogButtonBox()
    buttons: list[QPushButton] = []

    # Add an 'Ok' button
    if ok_text is None:
        ok_button = button_box.addButton(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            buttons.append(ok_button)
    else:
        custom_yes_button = QPushButton(ok_text)
        buttons.append(custom_yes_button)
        button_box.addButton(custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        custom_yes_button.clicked.connect(callback_ok)

    # Add a 'Cancel' button
    if cancel_text is None:
        cancel_button = button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button:
            buttons.append(cancel_button)
    else:
        custom_cancel_button = QPushButton(cancel_text)
        buttons.append(custom_cancel_button)
        button_box.addButton(custom_cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        custom_cancel_button.clicked.connect(callback_cancel)

    # Connect the QDialogButtonBox's accepted and rejected signals if default buttons are used
    if ok_text is None:
        button_box.accepted.connect(callback_ok)
    if cancel_text is None:
        button_box.rejected.connect(callback_cancel)

    return button_box, buttons


class ColorSchemeItem:
    def __init__(self, fg_color, bg_color):
        """Initialize instance."""
        self.colors = (fg_color, bg_color)

    @register_cache(always_keep=True)
    def _get_color(self, background):
        """Get color."""
        return self.colors[(int(background) + int(ColorScheme.dark_scheme)) % 2]

    def as_stylesheet(self, background=False):
        """As stylesheet."""
        css_prefix = "background-" if background else ""
        color = self._get_color(background)
        return f"QWidget {{ {css_prefix}color:{color}; }}"

    def as_color(self, background=False):
        """As color."""
        color = self._get_color(background)
        return QColor(color)


class ColorScheme:
    dark_scheme = False

    GREEN = ColorSchemeItem("#117c11", "#8af296")
    YELLOW = ColorSchemeItem("#897b2a", "#ffff00")
    RED = ColorSchemeItem("#7c1111", "#f18c8c")
    BLUE = ColorSchemeItem("#123b7c", "#8cb3f2")
    DEFAULT = ColorSchemeItem("black", "white")
    GRAY = ColorSchemeItem("gray", "gray")

    Purple = ColorSchemeItem("#7616ff", "#7616ff")
    OrangeBitcoin = ColorSchemeItem("#f7931a", "#f7931a")

    @staticmethod
    def has_dark_background(widget: QWidget):
        """Has dark background."""
        background_color = widget.palette().color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Window)
        rgb = background_color.getRgb()[0:3]
        brightness = sum(c for c in rgb if c)
        return brightness < (255 * 3 / 2)

    @staticmethod
    def update_from_widget(widget, force_dark=False):
        """Update from widget."""
        ColorScheme.dark_scheme = bool(force_dark or ColorScheme.has_dark_background(widget))


def screenshot_path(basename: str):
    """Screenshot path."""
    return resource_path("gui", "screenshots", basename)


def char_width_in_lineedit() -> int:
    """Char width in lineedit."""
    char_width = QFontMetrics(QLineEdit().font()).averageCharWidth()
    # 'averageCharWidth' seems to underestimate on Windows, hence 'max()'
    return max(9, char_width)


def font_height() -> int:
    """Font height."""
    return QFontMetrics(QLabel().font()).height()


def clipboard_contains_address(network: bdk.Network) -> bool:
    """Clipboard contains address."""
    clipboard = QApplication.clipboard()
    if not clipboard:
        return False
    return ConverterAddress.is_bitcoin_address(clipboard.text(), network)


def do_copy(text: str, *, title: str | None = None) -> None:
    """Do copy."""
    clipboard = QApplication.clipboard()
    if not clipboard:
        show_tooltip_after_delay("Clipboard not available")
        return
    clipboard.setText(str(text))
    message = (
        translate("d", "Text copied to Clipboard")
        if title is None
        else translate("d", "{} copied to Clipboard").format(title)
    )
    show_tooltip_after_delay(message)


def show_tooltip_after_delay(message):
    """Show tooltip after delay."""
    timer = QTimer()
    if not ENABLE_TIMERS:
        return
    # tooltip cannot be displayed immediately when called from a menu; wait 200ms
    timer.singleShot(200, partial(QToolTip.showText, QCursor.pos(), message))


def qicon_to_pil(qicon: QIcon, size=200) -> PilImage.Image:
    # Convert QIcon to QPixmap
    """Qicon to pil."""
    pixmap = qicon.pixmap(size, size)  # specify the size you want

    # Convert QPixmap to QImage
    qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)

    # Get image dimensions
    img_size = qimage.size()
    width, height = img_size.width(), img_size.height()

    # Convert QImage to raw bytes
    buffer = qimage.bits()
    if buffer:
        buffer.setsize(width * height * 4)  # RGBA8888 = 4 bytes per pixel

    # Convert raw bytes to a PIL image
    pil_image = PilImage.frombuffer("RGBA", (width, height), bytes(buffer), "raw", "RGBA", 0, 1)  # type: ignore[call-overload]

    return pil_image


def save_file_dialog(
    name_filters=None, default_suffix=None, default_filename=None, window_title="Save File"
) -> str | None:
    """Save file dialog."""
    file_dialog = QFileDialog()
    file_dialog.setWindowTitle(window_title)
    if default_suffix:
        file_dialog.setDefaultSuffix(default_suffix)

    # Set a default filename
    if default_filename:
        file_dialog.selectFile(default_filename)

    file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    if name_filters:
        file_dialog.setNameFilters(name_filters)

    if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
        selected_file = file_dialog.selectedFiles()[0]
        # Do something with the selected file path, e.g., save data to the file
        logger.debug(f"Selected save file: {selected_file}")
        return selected_file
    return None


def remove_scheme(url):
    """Check if "://" is in the URL and split it."""
    if "://" in url:
        parts = url.split("://", 1)  # Split only at the first occurrence
        return parts[1]  # Return the part after the "://"
    else:
        return url  # Return the original URL if no scheme is found


def ensure_scheme(url, default_scheme="https://"):
    """Check if "://" is in the URL and split it."""
    if "://" in url:
        return url  # Return the original URL if   scheme is found
    else:
        return f"{default_scheme}{url}"


def get_host_and_port(url) -> tuple[str | None, int | None]:
    """Get host and port."""
    parsed_url = urlparse(ensure_scheme(url))

    # Extract the hostname and port
    return parsed_url.hostname, parsed_url.port


def delayed_execution(f, parent, delay=10):
    """Delayed execution."""
    if not ENABLE_TIMERS:
        f()
        return
    timer = QTimer(parent)
    timer.setSingleShot(True)  # Make sure the timer runs only once
    timer.timeout.connect(f)  # Connect the timeout signal to the function
    timer.start(delay)


def clear_layout(layout: QLayout) -> None:
    """Helper method to remove all widgets from the grid layout."""
    while layout.count():
        item = layout.takeAt(0)
        if not item:
            continue
        widget = item.widget()
        if widget:
            layout.removeWidget(widget)
            widget.setParent(None)  # Remove widget from parent to fully disconnect it


def svg_widget_hardware_signer(
    index: int,
    parent: QWidget,
    sticker=False,
    max_width=200,
    max_height=200,
    size_hint_width: int | None = None,
    size_hint_height: int | None = None,
    replace_tuples: list[tuple[str, str]] | None = None,
) -> AspectRatioSvgWidget:
    """Svg widget hardware signer."""
    base_hardware_signers = [
        {
            "svg_basename": ("coldcard-sticker.svg"),
        },
        {
            "svg_basename": ("jade-sticker.svg"),
        },
        {
            "svg_basename": ("bitbox02-sticker.svg"),
        },
        {
            "svg_basename": ("passport-sticker.svg"),
        },
    ]

    hardware_signer = base_hardware_signers[index % len(base_hardware_signers)]

    if not sticker:
        replace_tuples = replace_tuples if replace_tuples else []
        replace_tuples += [('id="rect304"', 'visibility="hidden" id="rect304"'), ("Label", "")]

    widget = AspectRatioSvgWidget(
        svg_content=svg_tools_hardware_signer.get_svg_content(
            icon_basename=hardware_signer.get("svg_basename"),
            replace_tuples=tuple(replace_tuples) if replace_tuples else None,
        ),
        size_hint_width=size_hint_width,
        size_hint_height=size_hint_height,
        parent=parent,
    )
    widget.setMaximumHeight(max_height)
    widget.setMaximumWidth(max_width)
    return widget


def create_tool_button(parent: QWidget) -> tuple[QToolButton, Menu]:
    """Create tool button."""
    button = QToolButton()
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    menu = Menu(parent)
    button.setMenu(menu)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    return button, menu


def adjust_bg_color_for_darkmode(
    color: QColor,
) -> QColor:
    """Adjust bg color for darkmode."""
    return adjust_brightness(color, -0.4) if is_dark_mode() else color


def rescale(value: float, old_min: float, old_max: float, new_min: float, new_max: float):
    """Rescale."""
    return (value - old_min) / (old_max - old_min) * (new_max - new_min) + new_min


def hash_color(text: str) -> QColor:
    """Hash color."""
    hash_value = int(hash_string(text), 16) & 0xFFFFFF
    r = (hash_value & 0xFF0000) >> 16
    g = (hash_value & 0x00FF00) >> 8
    b = hash_value & 0x0000FF

    r = int(rescale(r, 0, 255, 100, 255))
    g = int(rescale(g, 0, 255, 100, 255))
    b = int(rescale(b, 0, 255, 100, 255))

    return QColor(r, g, b)


def category_color(text: str) -> QColor:
    """Category color."""
    return adjust_bg_color_for_darkmode(hash_color(text))


def create_color_circle(color: QColor, size=24, margin=1):
    """Create color circle."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)  # use a transparent background
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    # Draw the circle centered in the pixmap
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.end()
    return QIcon(pixmap)


def blend_qcolors(c1: QColor, c2: QColor, t: float = 0.5) -> QColor:
    """Linearly interpolate between two QColors.

    Args:
        c1: First QColor.
        c2: Second QColor.
        t:  Blend factor in [0.0, 1.0]. 0.0→c1, 1.0→c2, 0.5→midpoint.

    Returns:
        A new QColor whose components are (1-t)*c1 + t*c2.
    """
    # clamp t
    t = max(0.0, min(1.0, t))

    r = int(c1.red() * (1 - t) + c2.red() * t)
    g = int(c1.green() * (1 - t) + c2.green() * t)
    b = int(c1.blue() * (1 - t) + c2.blue() * t)
    a = int(c1.alpha() * (1 - t) + c2.alpha() * t)

    return QColor(r, g, b, a)


def set_no_margins(layout: QLayout) -> None:
    """Set no margins."""
    layout.setContentsMargins(0, 0, 0, 0)


def set_translucent(widget: QWidget):
    """— make backgrounds transparent —"""
    widget.setObjectName(f"widget{id(widget)}")
    widget.setAutoFillBackground(False)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    widget.setStyleSheet(
        f"""
        #{widget.objectName()} {{
            background: transparent;
        }}
    """
    )


def set_margins(layout: QLayout, margins: Mapping[Qt.Edge, int]) -> None:
    """Set one or more margins on a QLayout, each to its own value.

    :param layout: the layout whose contents-margins you want to adjust
    :param margins: a map from Qt.Edge.{LeftEdge,TopEdge,RightEdge,BottomEdge} to the new margin (in pixels)
        for that edge
    """
    cm = layout.contentsMargins()
    left, top, right, bottom = cm.left(), cm.top(), cm.right(), cm.bottom()

    for edge, val in margins.items():
        if edge == Qt.Edge.LeftEdge:
            left = val
        elif edge == Qt.Edge.TopEdge:
            top = val
        elif edge == Qt.Edge.RightEdge:
            right = val
        elif edge == Qt.Edge.BottomEdge:
            bottom = val
        else:
            raise ValueError(f"Unsupported edge: {edge!r}")

    layout.setContentsMargins(left, top, right, bottom)


class HLine(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)

        # Let QSS paint the background
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Behave like a horizontal separator: expand X, fixed thin height
        self.setFrameShape(QFrame.Shape.NoFrame)  # override built-in line painting
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(1)

        self.setObjectName(f"{id(self)}")

        # Pure background (no border), thin line effect via height=1
        self.setStyleSheet(
            f"""
            #{self.objectName()} {{
                background-color: rgba(128, 128, 128, 0.6);
                margin: 0px;
                padding: 0px;
            }}
            """
        )


class ButtonInfoType(enum.Enum):
    edit = enum.auto()
    rbf = enum.auto()
    cpfp = enum.auto()
    cancel_with_rbf = enum.auto()


@dataclass
class ButtonInfo:
    text: str
    tooltip: str
    icon_name: str

    @property
    def icon(self) -> QIcon:
        """Icon."""
        return svg_tools.get_QIcon(self.icon_name)


def button_info(name: ButtonInfoType) -> ButtonInfo:
    """Button info."""
    if name == ButtonInfoType.edit:
        return ButtonInfo(
            text=translate("util", "Edit"),
            tooltip=translate("util", "Prefill the sending dialog with this transactions information."),
            icon_name="pen.svg",
        )
    if name == ButtonInfoType.rbf:
        return ButtonInfo(
            text=translate("util", "Replace with higher fee (RBF)"),
            tooltip=translate(
                "util",
                "Replace-By-Fee creates a new version of this transaction with a higher fee."
                "\nUse it to speed up confirmation when the original is still unconfirmed."
                "\nRequires the original transaction to signal RBF and your wallet to own a change output.",
            ),
            icon_name="rbf.svg",
        )
    if name == ButtonInfoType.cpfp:
        return ButtonInfo(
            text=translate("util", "Speed up with child (CPFP)"),
            tooltip=translate(
                "util",
                "Child-Pays-For-Parent spends a change output of the pending transaction"
                "\nwith a higher fee to pull both into a block."
                "\nWorks only if you have an available change output and raise the combined fee rate.",
            ),
            icon_name="cpfp.svg",
        )
    if name == ButtonInfoType.cancel_with_rbf:
        return ButtonInfo(
            text=translate("util", "Try cancel by double-spend (RBF)"),
            tooltip=translate(
                "util",
                "Attempts to double-spend the original transaction with a higher fee."
                "\nOnly works on RBF-signaled transactions and is not guaranteed to succeed.",
            ),
            icon_name="pen.svg",
        )


def to_color_name(color: str | QPalette.ColorRole) -> str:
    """To color name."""
    return QApplication.palette().color(color).name() if isinstance(color, QPalette.ColorRole) else color

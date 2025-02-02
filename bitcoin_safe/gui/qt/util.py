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


import enum
import hashlib
import logging
import os
import platform
import sys
import traceback
import webbrowser
from functools import lru_cache, partial
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlparse

import bdkpython as bdk
import numpy as np
import PIL.Image as PilImage
from bitcoin_qr_tools.data import ConverterAddress
from PyQt6.QtCore import QByteArray, QCoreApplication, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFontMetrics,
    QIcon,
    QImage,
    QPalette,
    QPixmap,
)
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
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
from bitcoin_safe.typestubs import TypedPyQtSignal, TypedPyQtSignalNo
from bitcoin_safe.util import (
    adjust_brightness,
    is_dark_mode,
    register_cache,
    resource_path,
)

logger = logging.getLogger(__name__)


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


TX_ICONS: List[str] = [
    "unconfirmed.svg",
    "clock1.png",
    "clock2.png",
    "clock3.png",
    "clock4.png",
    "clock5.png",
    "confirmed.svg",
]


class QtWalletBase(QWidget):
    pass


def sort_id_to_icon(sort_id: int) -> str:
    if sort_id < 0:
        return "offline_tx.png"
    if sort_id > len(TX_ICONS) - 1:
        sort_id = len(TX_ICONS) - 1

    return TX_ICONS[sort_id]


def open_website(url: str):
    QDesktopServices.openUrl(QUrl(url))


def proportional_fit_into_max(x, y, x_max, y_max):
    """
    Scales (x, y) proportionally to fit within (x_max, y_max) while maintaining aspect ratio.

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


def qresize(qsize: QSize, max_sizes: Tuple[int, int]):
    x, y = proportional_fit_into_max(qsize.width(), qsize.height(), *max_sizes)
    return QSize(int(x), int(y))


def center_in_widget(
    widgets: Iterable[QWidget], parent: QWidget, direction="h", alignment=Qt.AlignmentFlag.AlignCenter
):
    outer_layout = QHBoxLayout(parent) if direction == "h" else QVBoxLayout(parent)
    outer_layout.setAlignment(alignment)
    for widget in widgets:
        outer_layout.addWidget(widget)
        # outer_layout.setAlignment(widget, alignment)
    return outer_layout


def generate_help_button(help_widget: QWidget, title=translate("help", "Help")) -> QPushButton:
    # add the help buttonbox
    button_help = QPushButton()
    button_help.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    button_help.setText(title)
    button_help.setIcon(
        (button_help.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion)
    )

    def show_screenshot_tutorial():
        help_widget.setWindowTitle(title)
        help_widget.show()

    button_help.clicked.connect(show_screenshot_tutorial)
    return button_help


def generate_help_message_button(message, title=translate("help", "Help")) -> QPushButton:
    msg_box = QMessageBox()
    msg_box.setWindowTitle(title)
    msg_box.setIcon(QMessageBox.Icon.Information)  # Set icon to Information which is often used for Help
    msg_box.setText(message)
    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)  # Add OK button

    help_button = generate_help_button(msg_box, title=title)
    return help_button


class AspectRatioSvgWidget(QSvgWidget):
    def __init__(self, svg_path: str, max_width: int, max_height: int, parent=None):
        super().__init__(parent)
        self.svg_path = svg_path
        self.load(svg_path)
        self._max_width = max_width
        self._max_height = max_height
        # self.setMinimumSize(max_width, max_height)

        # self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(self.calculate_proportional_size())

    def calculate_proportional_size(self):
        qsize = qresize(self.sizeHint(), (self._max_width, self._max_height))
        return qsize

    def modify_svg_text(self, *replace_tuples: Tuple[str, str]):
        # Load the original SVG content
        with open(self.svg_path, "r", encoding="utf-8") as file:
            original_svg_content = file.read()

        for old_text, new_text in replace_tuples:
            original_svg_content = original_svg_content.replace(old_text, new_text)

        modified_svg_content = QByteArray(original_svg_content.encode())  # type: ignore[call-overload]
        self.load(modified_svg_content)


def add_centered_icons(
    paths: List[str],
    parent_layout: QBoxLayout,
    direction="h",
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    max_sizes: Iterable[Tuple[int, int]] = [],
):
    max_sizes = max_sizes if max_sizes else [(60, 80) for path in paths]
    if len(paths) > 1 and len(max_sizes) == 1:  # type: ignore
        max_sizes = max_sizes * len(paths)  # type: ignore

    svg_widgets = [
        AspectRatioSvgWidget(icon_path(path), *max_size) for max_size, path in zip(max_sizes, paths)
    ]

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
    button = button if button else QPushButton(text)
    if isinstance(icon_name, QIcon):
        button.setIcon(icon_name)
    elif icon_name:
        button.setIcon(QIcon(icon_path(icon_name)))

    # Add the button to the QDialogButtonBox
    buttonBox.addButton(button, role)

    # Optionally connect the button's clicked signal
    if on_clicked:
        button.clicked.connect(on_clicked)
    return button


class Buttons(QHBoxLayout):
    def __init__(self, *buttons):
        QHBoxLayout.__init__(self)
        self.addStretch(1)
        for b in buttons:
            if b is None:
                continue
            self.addWidget(b)


class CloseButton(QPushButton):
    def __init__(self, dialog):
        QPushButton.__init__(self, self.tr("Close"))
        self.clicked.connect(dialog.close)
        self.setDefault(True)


class MessageType(enum.Enum):
    Info = enum.auto()
    Warning = enum.auto()
    Error = enum.auto()
    Critical = enum.auto()

    @classmethod
    def from_analyzer_state(cls, analyzer_state: AnalyzerState) -> "MessageType":
        return list(MessageType)[int(analyzer_state) - 1]


class Message:
    def __init__(
        self,
        msg: str,
        parent: QWidget | None = None,
        title: str | None = None,
        icon: Union[QIcon, QPixmap, QMessageBox.Icon] | None = None,
        msecs=None,
        type: MessageType = MessageType.Info,
        no_show=False,
        **kwargs,
    ) -> None:

        self.msg = msg
        self.parent = parent
        self.title = title
        self.icon = icon
        self.msecs = msecs
        self.type = type
        self.kwargs = kwargs

        if not no_show:
            self.show()

    @staticmethod
    def system_tray_icon(
        icon: Optional[Union[QIcon, QPixmap, QMessageBox.Icon, QSystemTrayIcon.MessageIcon]]
    ) -> Union[QIcon, QSystemTrayIcon.MessageIcon]:
        if isinstance(icon, QIcon):
            return icon

        if isinstance(icon, QSystemTrayIcon.MessageIcon):
            return icon

        if isinstance(icon, QPixmap):
            return QIcon(icon)

        if type(icon) == QMessageBox.Icon:
            if icon == QMessageBox.Icon.Information:
                return QSystemTrayIcon.MessageIcon.Information
            if icon == QMessageBox.Icon.Warning:
                return QSystemTrayIcon.MessageIcon.Warning
            if icon == QMessageBox.Icon.Critical:
                return QSystemTrayIcon.MessageIcon.Critical

        return QSystemTrayIcon.MessageIcon.NoIcon

    def get_icon_and_title(self) -> Tuple[Union[QIcon, QPixmap, QMessageBox.Icon], str]:
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

    def show(self):
        self.create().exec()

    def create(self) -> QMessageBox:
        logger.warning(str(self.__dict__))

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
        msg_box = self.create()
        msg_box.setStandardButtons(yes_button | no_button)
        ret = msg_box.exec()

        # Check which button was clicked
        if ret == yes_button:
            return True
        elif ret == no_button:
            return False
        return False

    def emit_with(self, notification_signal: "TypedPyQtSignal[Message]"):
        logger.debug(str(self.__dict__))
        return notification_signal.emit(self)

    def msg_box(
        self,
        icon: Union[QIcon, QPixmap, QMessageBox.Icon],
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
    """Custom exception handler to catch unhandled exceptions and display an
    error message box."""
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


def caught_exception_message(e: Exception, title=None, log_traceback=True) -> Message:
    exception_text = str(e).replace("\\", "")

    logger.error(exception_text, exc_info=sys.exc_info() if log_traceback else None)

    text = title + "\n\n" if title else ""
    text += exception_text
    return Message(text, type=MessageType.Error)


def custom_message_box(
    *,
    icon: Union[QIcon, QPixmap, QMessageBox.Icon],
    parent,
    title: str,
    text: str,
    buttons=QMessageBox.StandardButton.Ok,
    defaultButton=QMessageBox.StandardButton.NoButton,
    rich_text=False,
    checkbox=None,
) -> QMessageBox:

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
    """Handy wrapper; window modal dialogs are better for our multi-window
    daemon model as other wallet windows can still be accessed."""

    def __init__(self, parent, title=None):
        QDialog.__init__(self, parent)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        if title:
            self.setWindowTitle(title)


class BlockingWaitingDialog(WindowModalDialog):
    """Shows a waiting dialog whilst running a task.

    Should be called from the GUI thread. The GUI thread will be blocked
    while the task is running; the point of the dialog is to provide
    feedback to the user regarding what is going on.
    """

    def __init__(self, parent: QWidget, message: str, task: Callable[[], Any]):
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


def one_time_signal_connection(signal: TypedPyQtSignalNo | TypedPyQtSignal, f: Callable):
    def f_wrapper(*args, **kwargs):
        signal.disconnect(f_wrapper)
        return f(*args, **kwargs)

    signal.connect(f_wrapper)


def create_button_box(
    callback_ok, callback_cancel, ok_text=None, cancel_text=None
) -> Tuple[QDialogButtonBox, List[QPushButton]]:
    # Create the QDialogButtonBox instance
    button_box = QDialogButtonBox()
    buttons: List[QPushButton] = []

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
        self.colors = (fg_color, bg_color)

    @register_cache(always_keep=True)
    def _get_color(self, background):
        return self.colors[(int(background) + int(ColorScheme.dark_scheme)) % 2]

    def as_stylesheet(self, background=False):
        css_prefix = "background-" if background else ""
        color = self._get_color(background)
        return "QWidget {{ {}color:{}; }}".format(css_prefix, color)

    def as_color(self, background=False):
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

    @staticmethod
    def has_dark_background(widget: QWidget):
        background_color = widget.palette().color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Window)
        rgb = background_color.getRgb()[0:3]
        brightness = sum([c for c in rgb if c])
        return brightness < (255 * 3 / 2)

    @staticmethod
    def update_from_widget(widget, force_dark=False):
        ColorScheme.dark_scheme = bool(force_dark or ColorScheme.has_dark_background(widget))


def resource_path_auto_darkmode(*parts: str):
    if is_dark_mode():
        filename = parts[-1]
        name, extension = os.path.splitext(filename)
        modified_parts = list(parts)[:-1] + [f"{name}_darkmode{extension}"]
        combined_path = resource_path(*modified_parts)
        if Path(combined_path).exists():
            return combined_path

    return resource_path(*parts)


def icon_path(icon_basename: str) -> str:
    return resource_path_auto_darkmode("gui", "icons", icon_basename)


def hardware_signer_path(signer_basename: str) -> str:
    return resource_path_auto_darkmode("gui", "icons", "hardware_signers", signer_basename)


def generated_hardware_signer_path(signer_basename: str) -> str:
    return resource_path_auto_darkmode("gui", "icons", "hardware_signers", "generated", signer_basename)


def screenshot_path(basename: str):
    return resource_path("gui", "screenshots", basename)


@lru_cache(maxsize=1000)
def read_QIcon(icon_basename: Optional[str]) -> QIcon:
    if not icon_basename:
        return QIcon()
    return QIcon(icon_path(icon_basename))


def char_width_in_lineedit() -> int:
    char_width = QFontMetrics(QLineEdit().font()).averageCharWidth()
    # 'averageCharWidth' seems to underestimate on Windows, hence 'max()'
    return max(9, char_width)


def font_height() -> int:
    return QFontMetrics(QLabel().font()).height()


def webopen(url: str):
    webbrowser.open(url)


def clipboard_contains_address(network: bdk.Network) -> bool:
    clipboard = QApplication.clipboard()
    if not clipboard:
        return False
    return ConverterAddress.is_bitcoin_address(clipboard.text(), network)


def do_copy(text: str, *, title: str | None = None) -> None:
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
    timer = QTimer()
    if not ENABLE_TIMERS:
        return
    # tooltip cannot be displayed immediately when called from a menu; wait 200ms
    timer.singleShot(200, partial(QToolTip.showText, QCursor.pos(), message))


def qicon_to_pil(qicon: QIcon, size=200) -> PilImage.Image:
    # Convert QIcon to QPixmap
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
) -> Optional[str]:
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
    """Check if "://" is in the URL and split it"""
    if "://" in url:
        parts = url.split("://", 1)  # Split only at the first occurrence
        return parts[1]  # Return the part after the "://"
    else:
        return url  # Return the original URL if no scheme is found


def ensure_scheme(url, default_scheme="https://"):
    """Check if "://" is in the URL and split it"""
    if "://" in url:
        return url  # Return the original URL if   scheme is found
    else:
        return f"{default_scheme}{url}"


def get_host_and_port(url) -> Tuple[str | None, int | None]:

    parsed_url = urlparse(ensure_scheme(url))

    # Extract the hostname and port
    return parsed_url.hostname, parsed_url.port


def delayed_execution(f, parent, delay=10):
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


def svg_widgets_hardware_signers(
    num_keystores: int, parent: QWidget, sticker=False, max_width=200, max_height=200
) -> List[AspectRatioSvgWidget]:
    def stretch(l: List) -> List:
        new = [l[0]] * int(np.ceil(num_keystores / len(l))) + l[1:] * int(np.ceil(num_keystores / len(l)))
        return new[:num_keystores]

    hardware_signers = [
        {
            "path": hardware_signer_path("coldcard-sticker.svg"),
            "max_width": max_width,
            "max_height": max_height,
        },
        {
            "path": hardware_signer_path("jade-sticker.svg"),
            "max_width": max_width,
            "max_height": max_height,
        },
        {
            "path": hardware_signer_path("bitbox02-sticker.svg"),
            "max_width": max_width,
            "max_height": max_height,
        },
        {
            "path": hardware_signer_path("passport-sticker.svg"),
            "max_width": max_width,
            "max_height": max_height,
        },
    ]

    widgets = [
        AspectRatioSvgWidget(
            hardware_signer["path"],
            max_width=hardware_signer["max_width"],
            max_height=hardware_signer["max_height"],
            parent=parent,
        )
        for hardware_signer in stretch(hardware_signers)
    ]

    if not sticker:
        for widget in widgets:
            widget.modify_svg_text(('id="rect304"', 'visibility="hidden" id="rect304"'), ("Label", ""))
    return widgets


def create_tool_button(parent: QWidget) -> Tuple[QToolButton, Menu]:
    button = QToolButton()
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    menu = Menu(parent)
    button.setMenu(menu)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    return button, menu


def adjust_bg_color_for_darkmode(
    color: QColor,
) -> QColor:
    return adjust_brightness(color, -0.4) if is_dark_mode() else color


def hash_string(text: str) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()


def rescale(value: float, old_min: float, old_max: float, new_min: float, new_max: float):
    return (value - old_min) / (old_max - old_min) * (new_max - new_min) + new_min


def hash_color(text: str) -> QColor:
    hash_value = int(hash_string(text), 16) & 0xFFFFFF
    r = (hash_value & 0xFF0000) >> 16
    g = (hash_value & 0x00FF00) >> 8
    b = hash_value & 0x0000FF

    r = int(rescale(r, 0, 255, 100, 255))
    g = int(rescale(g, 0, 255, 100, 255))
    b = int(rescale(b, 0, 255, 100, 255))

    return QColor(r, g, b)


def category_color(text: str) -> QColor:
    return adjust_bg_color_for_darkmode(hash_color(text))


def create_color_square(color: QColor, length=24) -> QIcon:
    # Define the size of the square icon
    size = QSize(length, length)

    # Create a QPixmap of defined size
    pixmap = QPixmap(size)

    # Fill the QPixmap with the provided color
    pixmap.fill(color)

    # Create and return a QIcon from the QPixmap
    return QIcon(pixmap)

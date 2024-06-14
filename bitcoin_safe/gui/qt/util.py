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
import logging
import os
import os.path
import platform
import sys
import traceback
import webbrowser
from functools import lru_cache
from typing import Any, Callable, List, Optional, Tuple
from urllib.parse import urlparse

import bdkpython as bdk
from bitcoin_qr_tools.data import is_bitcoin_address
from PIL import Image as PilImage
from PyQt6.QtCore import QCoreApplication, QSize, Qt, QTimer, QUrl, pyqtSignal
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
    QSystemTrayIcon,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget

from ...i18n import translate
from ...util import register_cache, resource_path

logger = logging.getLogger(__name__)


if platform.system() == "Windows":
    MONOSPACE_FONT = "Lucida Console"
elif platform.system() == "Darwin":
    MONOSPACE_FONT = "Monaco"
else:
    MONOSPACE_FONT = "monospace"

QWIDGETSIZE_MAX = 16777215


# filter tx files in QFileDialog:
TRANSACTION_FILE_EXTENSION_FILTER_ANY = "Transaction (*.txn *.psbt);;All files (*)"
TRANSACTION_FILE_EXTENSION_FILTER_ONLY_PARTIAL_TX = "Partial Transaction (*.psbt)"
TRANSACTION_FILE_EXTENSION_FILTER_ONLY_COMPLETE_TX = "Complete Transaction (*.txn)"
TRANSACTION_FILE_EXTENSION_FILTER_SEPARATE = (
    f"{TRANSACTION_FILE_EXTENSION_FILTER_ONLY_PARTIAL_TX};;"
    f"{TRANSACTION_FILE_EXTENSION_FILTER_ONLY_COMPLETE_TX};;"
    f"All files (*)"
)


TX_ICONS = [
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


def resize(x, y, x_max, y_max):
    def resize_one_side(a, b, amax):
        a_new = min(amax, a)
        return a_new, b * a_new / a

    # resize according to xmax
    x, y = resize_one_side(x, y, x_max)
    # resize according to ymax
    y, x = resize_one_side(y, x, y_max)
    return x, y


def qresize(qsize: QSize, max_sizes: Tuple[int, int]):
    x, y = resize(qsize.width(), qsize.height(), *max_sizes)
    return QSize(int(x), int(y))


def center_in_widget(
    widgets: List[QWidget], parent: QWidget, direction="h", alignment=Qt.AlignmentFlag.AlignCenter
):
    outer_layout = QHBoxLayout(parent) if direction == "h" else QVBoxLayout(parent)
    outer_layout.setAlignment(alignment)
    for widget in widgets:
        outer_layout.addWidget(widget)
        # outer_layout.setAlignment(widget, alignment)
    return outer_layout


def add_centered(
    widgets: List[QWidget], parent: QWidget, direction="h", alignment=Qt.AlignmentFlag.AlignCenter
):
    widget1 = QWidget(parent)
    parent.layout().addWidget(widget1)
    inner_layout = center_in_widget(widgets, widget1, direction=direction, alignment=alignment)
    inner_layout.setContentsMargins(1, 0, 1, 0)  # left, top, right, bottom
    return inner_layout


class AspectRatioSvgWidget(QSvgWidget):
    def __init__(self, svg_path: str, max_width: int, max_height: int, parent=None):
        super().__init__(parent)
        self.load(svg_path)
        self._max_width = max_width
        self._max_height = max_height
        # self.setMinimumSize(max_width, max_height)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(self.calculate_proportional_size())

    def calculate_proportional_size(self):
        qsize = qresize(self.sizeHint(), (self._max_width, self._max_height))
        return qsize


def add_centered_icons(
    paths: List[str], parent, direction="h", alignment=Qt.AlignmentFlag.AlignCenter, max_sizes=None
):
    max_sizes = max_sizes if max_sizes else [(60, 80) for path in paths]
    if isinstance(max_sizes[0], (float, int)):
        max_sizes = [max_sizes]
    if len(paths) > 1 and len(max_sizes) == 1:
        max_sizes = max_sizes * len(paths)

    svg_widgets = [
        AspectRatioSvgWidget(icon_path(path), *max_size) for max_size, path in zip(max_sizes, paths)
    ]

    inner_layout = add_centered(svg_widgets, parent, direction=direction, alignment=alignment)

    return svg_widgets


def add_to_buttonbox(
    buttonBox: QDialogButtonBox,
    text: str,
    icon_name: str = None,
    on_clicked=None,
    role=QDialogButtonBox.ButtonRole.ActionRole,
):
    # Create a custom QPushButton with an icon
    button = QPushButton(text)
    if icon_name:
        button.setIcon(QIcon(icon_path(icon_name)))

    # Add the button to the QDialogButtonBox
    buttonBox.addButton(button, role)

    # Optionally connect the button's clicked signal
    if on_clicked:
        button.clicked.connect(on_clicked)
    return button


def create_button(
    text, icon_paths: List[str], parent: QWidget, max_sizes=None, button_max_height=200, word_wrap=True
) -> QPushButton:
    button = QPushButton(parent)
    if button_max_height:
        button.setMaximumHeight(button_max_height)
    # Set the vertical size policy of the button to Expanding
    size_policy = button.sizePolicy()
    size_policy.setVerticalPolicy(size_policy.Policy.Expanding)
    button.setSizePolicy(size_policy)

    parent.layout().addWidget(button)

    # add the icons to
    widget1 = QWidget(button)
    widget2 = QWidget(button)
    layout = center_in_widget([widget1, widget2], button, direction="v")
    # prent.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
    # layout.setContentsMargins(0, 0, 0, 0)

    label_icon = QLabel()
    label_icon.setWordWrap(word_wrap)
    label_icon.setText(text)
    label_icon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    label_icon.setHidden(not bool(text))
    label_icon.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    layout = center_in_widget([label_icon], widget1, direction="h")
    if not text:
        layout.setContentsMargins(0, 0, 0, 0)

    if not isinstance(icon_paths, (list, tuple)):
        icon_paths = [icon_paths]
    layout = QHBoxLayout(widget2)

    # Calculate total width and height of all widgets in layout
    total_width = 0
    total_height = 0

    if icon_paths:
        max_sizes = max_sizes if max_sizes else [(60, 60)] * len(icon_paths)
        total_width += sum(w for w, h in max_sizes)
        total_height += max(h for w, h in max_sizes)
        add_centered_icons(
            icon_paths,
            widget2,
            layout,
            max_sizes=max_sizes,
        )

    # Add layout margins
    # margins = layout.contentsMargins()
    # total_width += margins.left() + margins.right()
    # total_height += margins.top() + margins.bottom()

    # # Set minimum size of button
    # button.setMinimumSize(total_width, total_height)
    layout.setContentsMargins(0, 0, 0, 0)
    return button


def add_tab_to_tabs(
    tabs: DataTabWidget,
    tab: QWidget,
    icon: QIcon,
    description: str,
    name: str,
    data: Any = None,
    position: int = None,
    focus: bool = False,
):
    tab.tab_icon = icon
    tab.tab_description = description
    tab.tab_name = name

    if position is None:
        tabs.addTab(tab, icon, description.replace("&", "").capitalize(), data=data)
        if focus:
            tabs.setCurrentIndex(tabs.count() - 1)
    else:
        tabs.insertTab(position, tab, icon, description.replace("&", "").capitalize(), data=data)
        if focus:
            tabs.setCurrentIndex(position)


def remove_tab(tab: QWidget, tabs: QTabWidget):
    idx = tabs.indexOf(tab)
    if idx is None or idx < 0:
        return
    tabs.removeTab(idx)


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


class Message:
    def __init__(
        self,
        msg,
        parent=None,
        title=None,
        icon=None,
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
    def icon_to_q_system_tray_icon(icon: Optional[QMessageBox.Icon]) -> QSystemTrayIcon.MessageIcon:
        if icon == QMessageBox.Icon.Information:
            return QSystemTrayIcon.MessageIcon.Information
        if icon == QMessageBox.Icon.Warning:
            return QSystemTrayIcon.MessageIcon.Warning
        if icon == QMessageBox.Icon.Critical:
            return QSystemTrayIcon.MessageIcon.Critical
        return QSystemTrayIcon.MessageIcon.NoIcon

    def get_icon_and_title(self) -> Tuple[QMessageBox.Icon, str]:
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

        icon = self.icon or icon
        title = self.title or title
        return icon, title

    def show(self):
        logger.warning(str(self.__dict__))

        icon, title = self.get_icon_and_title()

        return self.msg_box(
            icon,
            self.parent,
            title,
            self.msg,
            **self.kwargs,
        )

    def emit_with(self, notification_signal: pyqtSignal):
        logger.debug(str(self.__dict__))
        return notification_signal.emit(self)

    def msg_box(
        self,
        icon: QIcon,
        parent,
        title: str,
        text: str,
        *,
        buttons=QMessageBox.StandardButton.Ok,
        defaultButton=QMessageBox.StandardButton.NoButton,
        rich_text=True,
        checkbox=None,
    ):
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
            None,
            title,
            f"{error_message}\n\nPlease send the error report via email, so the bug can be fixed.",
        )

    except:
        error_message = str([exc_type, exc_value, exc_traceback])
        logger.critical(error_message)
        QMessageBox.critical(
            None,
            title,
            f"{error_message}\n\nPlease send the error report via email, so the bug can be fixed.",
        )


def caught_exception_message(e: Exception, title=None, log_traceback=False) -> Message:
    exception_text = str(e).replace("\\", "")

    logger.error(exception_text, exc_info=sys.exc_info() if log_traceback else None)

    text = title + "\n\n" if title else ""
    text += exception_text
    return Message(text, type=MessageType.Error)


def custom_message_box(
    *,
    icon: QIcon,
    parent,
    title: str,
    text: str,
    buttons=QMessageBox.StandardButton.Ok,
    defaultButton=QMessageBox.StandardButton.NoButton,
    rich_text=False,
    checkbox=None,
):
    if type(icon) is QPixmap:
        d = QMessageBox(QMessageBox.Icon.Information, title, str(text), buttons, parent)
        d.setIconPixmap(icon)
    else:
        d = QMessageBox(icon, title, str(text), buttons, parent)
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
    return d.exec()


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
        self.finished.connect(self.deleteLater)  # see #3956
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


def one_time_signal_connection(signal: pyqtSignal, f: Callable):
    def f_wrapper(*args, **kwargs):
        signal.disconnect(f_wrapper)
        return f(*args, **kwargs)

    signal.connect(f_wrapper)


def robust_disconnect(slot: pyqtSignal, f):
    if not slot or not f:
        return
    try:
        slot.disconnect(f)
    except:
        pass


def chained_one_time_signal_connections(
    signals: List[pyqtSignal], fs: List[Callable[..., bool]], disconnect_only_if_f_true=True
):
    "If after the i. f is called, it connects the i+1. signal"

    signal, remaining_signals = signals[0], signals[1:]
    f, remaining_fs = fs[0], fs[1:]

    def f_wrapper(*args, **kwargs):
        res = f(*args, **kwargs)
        if disconnect_only_if_f_true and not res:
            # reconnect
            one_time_signal_connection(signal, f_wrapper)
        elif remaining_signals and remaining_fs:
            chained_one_time_signal_connections(remaining_signals, remaining_fs)
        return res

    one_time_signal_connection(signal, f_wrapper)


def create_button_box(
    callback_ok, callback_cancel, ok_text=None, cancel_text=None
) -> Tuple[QDialogButtonBox, List[QPushButton]]:
    # Create the QDialogButtonBox instance
    button_box = QDialogButtonBox()
    buttons: List[QPushButton] = []

    # Add an 'Ok' button
    if ok_text is None:
        buttons.append(button_box.addButton(QDialogButtonBox.StandardButton.Ok))
    else:
        custom_yes_button = QPushButton(ok_text)
        buttons.append(custom_yes_button)
        button_box.addButton(custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)
        custom_yes_button.clicked.connect(callback_ok)

    # Add a 'Cancel' button
    if cancel_text is None:
        buttons.append(button_box.addButton(QDialogButtonBox.StandardButton.Cancel))
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
        brightness = sum(background_color.getRgb()[0:3])
        return brightness < (255 * 3 / 2)

    @staticmethod
    def update_from_widget(widget, force_dark=False):
        ColorScheme.dark_scheme = bool(force_dark or ColorScheme.has_dark_background(widget))


def icon_path(icon_basename: str):
    return resource_path("gui", "icons", icon_basename)


def screenshot_path(basename: str):
    return resource_path("gui", "screenshots", basename)


@lru_cache(maxsize=1000)
def read_QIcon(icon_basename: str) -> QIcon:
    if icon_basename is None:
        return QIcon()
    return QIcon(icon_path(icon_basename))


def char_width_in_lineedit() -> int:
    char_width = QFontMetrics(QLineEdit().font()).averageCharWidth()
    # 'averageCharWidth' seems to underestimate on Windows, hence 'max()'
    return max(9, char_width)


def font_height() -> int:
    return QFontMetrics(QLabel().font()).height()


def webopen(url: str):
    if sys.platform == "linux" and os.environ.get("APPIMAGE"):
        # When on Linux webbrowser.open can fail in AppImage because it can't find the correct libdbus.
        # We just fork the process and unset LD_LIBRARY_PATH before opening the URL.
        # See #5425
        if os.fork() == 0:
            del os.environ["LD_LIBRARY_PATH"]
            webbrowser.open(url)
            os._exit(0)
    else:
        webbrowser.open(url)


def clipboard_contains_address(network: bdk.Network):
    text = QApplication.clipboard().text()
    return is_bitcoin_address(text, network)


def do_copy(text: str, *, title: str = None) -> None:
    QApplication.clipboard().setText(str(text))
    message = (
        translate("d", "Text copied to Clipboard")
        if title is None
        else translate("d", "{} copied to Clipboard").format(title)
    )
    show_tooltip_after_delay(message)


def show_tooltip_after_delay(message):
    timer = QTimer()
    # tooltip cannot be displayed immediately when called from a menu; wait 200ms
    timer.singleShot(200, lambda: QToolTip.showText(QCursor.pos(), message))


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
    buffer.setsize(width * height * 4)  # RGBA8888 = 4 bytes per pixel

    # Convert raw bytes to a PIL image
    pil_image = PilImage.frombuffer("RGBA", (width, height), bytes(buffer), "raw", "RGBA", 0, 1)

    return pil_image


def save_file_dialog(name_filters=None, default_suffix=None, default_filename=None):
    file_dialog = QFileDialog()
    file_dialog.setWindowTitle("Save File")
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


def get_host_and_port(url) -> Tuple[str, int]:

    parsed_url = urlparse(ensure_scheme(url))

    # Extract the hostname and port
    return parsed_url.hostname, parsed_url.port


def clear_layout(layout: QLayout):
    """
    Remove all widgets from a layout and delete them.

    Parameters:
    - layout: QLayout - The layout from which to remove all widgets.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        else:
            # item might be a layout itself
            clear_layout(item.layout())


def delayed_execution(f, parent, delay=10):
    timer = QTimer(parent)
    timer.setSingleShot(True)  # Make sure the timer runs only once
    timer.timeout.connect(f)  # Connect the timeout signal to the function
    timer.start(delay)

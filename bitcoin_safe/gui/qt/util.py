import enum
import logging

logger = logging.getLogger(__name__)

import os
import os.path
import platform
import sys
import traceback
import webbrowser
from functools import lru_cache
from typing import Any, Callable

from PIL import Image as PilImage
from PySide2.QtCore import (
    QCoreApplication,
    QLocale,
    QSize,
    Qt,
    QTimer,
    QUrl,
    SignalInstance,
)
from PySide2.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFontMetrics,
    QIcon,
    QImage,
    QPalette,
    QPixmap,
)
from PySide2.QtSvg import QSvgWidget
from PySide2.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ...i18n import _, languages
from ...util import Satoshis, TaskThread, is_address, register_cache, resource_path

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


def sort_id_to_icon(sort_id) -> str:
    if sort_id < 0:
        return "offline_tx.png"
    if sort_id > len(TX_ICONS) - 1:
        sort_id = len(TX_ICONS) - 1

    return TX_ICONS[sort_id]


def open_website(url):
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


def qresize(qsize: QSize, max_sizes):
    x, y = resize(qsize.width(), qsize.height(), *max_sizes)
    return QSize(x, y)


def center_in_widget(widgets, parent, direction="h", alignment=Qt.AlignCenter):
    outer_layout = QHBoxLayout(parent) if direction == "h" else QVBoxLayout(parent)
    outer_layout.setAlignment(alignment)
    for widget in widgets:
        outer_layout.addWidget(widget)
        # outer_layout.setAlignment(widget, alignment)
    return outer_layout


def add_centered(widgets, parent, outer_layout, direction="h", alignment=Qt.AlignCenter):
    widget1 = QWidget(parent)
    outer_layout.addWidget(widget1)
    inner_layout = center_in_widget(widgets, widget1, direction=direction, alignment=alignment)
    inner_layout.setContentsMargins(1, 0, 1, 0)  # left, top, right, bottom
    return inner_layout


class AspectRatioSvgWidget(QSvgWidget):
    def __init__(self, svg_path, max_width, max_height, parent=None):
        super().__init__(parent)
        self.load(svg_path)
        self._max_width = max_width
        self._max_height = max_height
        # self.setMinimumSize(max_width, max_height)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(self.calculate_proportional_size())

    def calculate_proportional_size(self):
        qsize = qresize(self.sizeHint(), (self._max_width, self._max_height))
        return qsize


def add_centered_icons(paths, parent, outer_layout, direction="h", alignment=Qt.AlignCenter, max_sizes=None):
    max_sizes = max_sizes if max_sizes else [(60, 80) for path in paths]
    if isinstance(max_sizes[0], (float, int)):
        max_sizes = [max_sizes]
    if len(paths) > 1 and len(max_sizes) == 1:
        max_sizes = max_sizes * len(paths)

    svg_widgets = [
        AspectRatioSvgWidget(icon_path(path), *max_size) for max_size, path in zip(max_sizes, paths)
    ]

    inner_layout = add_centered(svg_widgets, parent, outer_layout, direction=direction, alignment=alignment)

    return svg_widgets


def add_to_buttonbox(buttonBox, text, icon_name, on_clicked=None):
    # Create a custom QPushButton with an icon
    button = QPushButton(text)
    button.setIcon(QIcon(icon_path(icon_name)))

    # Add the button to the QDialogButtonBox
    buttonBox.addButton(button, QDialogButtonBox.ActionRole)

    # Optionally connect the button's clicked signal
    if on_clicked:
        button.clicked.connect(on_clicked)
    return button


def create_button(
    text, icon_paths, parent, outer_layout, max_sizes=None, button_max_height=200, word_wrap=True
) -> QPushButton:
    button = QPushButton(parent)
    if button_max_height:
        button.setMaximumHeight(button_max_height)
    # Set the vertical size policy of the button to Expanding
    size_policy = button.sizePolicy()
    size_policy.setVerticalPolicy(size_policy.Expanding)
    button.setSizePolicy(size_policy)

    outer_layout.addWidget(button)

    # add the icons to
    widget1 = QWidget(button)
    widget2 = QWidget(button)
    layout = center_in_widget([widget1, widget2], button, direction="v")
    # outer_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
    # layout.setContentsMargins(0, 0, 0, 0)

    label_icon = QLabel()
    label_icon.setWordWrap(word_wrap)
    label_icon.setText(text)
    label_icon.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    label_icon.setHidden(not bool(text))
    label_icon.setAlignment(Qt.AlignHCenter)
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


def add_tab_to_tabs(tabs: QTabWidget, tab, icon, description, name, position=None, focus=False):
    tab.tab_icon = icon
    tab.tab_description = description
    tab.tab_name = name

    if position is None:
        tabs.addTab(tab, icon, description.replace("&", "").capitalize())
        if focus:
            tabs.setCurrentIndex(tabs.count() - 1)
    else:
        tabs.insertTab(position, tab, icon, description.replace("&", "").capitalize())
        if focus:
            tabs.setCurrentIndex(position)


class ThreadedButton(QPushButton):
    def __init__(self, text, task, on_success=None, on_error=None):
        QPushButton.__init__(self, text)
        self.task = task
        self.on_success = on_success
        self.on_error = on_error
        self.clicked.connect(self.run_task)

    def run_task(self):
        self.setEnabled(False)
        self.thread = TaskThread(self)
        self.thread.add(self.task, self.on_success, self.done, self.on_error)

    def done(self):
        self.setEnabled(True)
        self.thread.stop()


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
        QPushButton.__init__(self, _("Close"))
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

    def show(self):
        logger.warning(str(self.__dict__))

        icon = QMessageBox.Information
        title = "Information"
        if self.type in [MessageType.Warning]:
            icon = QMessageBox.Warning
            title = "Warning"
        if self.type in [MessageType.Error]:
            icon = QMessageBox.Warning
            title = "Error"
        if self.type in [MessageType.Critical]:
            icon = QMessageBox.Critical
            title = "Critical Error"

        return self.msg_box(
            self.icon or icon,
            self.parent,
            self.title or title,
            self.msg,
            **self.kwargs,
        )

    def emit_with(self, notification_signal):
        logger.debug(str(self.__dict__))
        return notification_signal.emit(self)

    def msg_box(
        self,
        icon,
        parent,
        title,
        text,
        *,
        buttons=QMessageBox.Ok,
        defaultButton=QMessageBox.NoButton,
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


def custom_exception_handler(exc_type, exc_value, exc_traceback):
    """Custom exception handler to catch unhandled exceptions and display an
    error message box."""
    # Format the traceback
    formatted_traceback = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    error_message = f"{exc_type.__name__}: {exc_value}\n\n{formatted_traceback}"
    logger.exception(error_message)
    QMessageBox.critical(None, "Error", error_message)


def custom_message_box(
    *,
    icon,
    parent,
    title,
    text,
    buttons=QMessageBox.Ok,
    defaultButton=QMessageBox.NoButton,
    rich_text=False,
    checkbox=None,
):
    if type(icon) is QPixmap:
        d = QMessageBox(QMessageBox.Information, title, str(text), buttons, parent)
        d.setIconPixmap(icon)
    else:
        d = QMessageBox(icon, title, str(text), buttons, parent)
    d.setWindowModality(Qt.WindowModal)
    d.setDefaultButton(defaultButton)
    if rich_text:
        d.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        # set AutoText instead of RichText
        # AutoText lets Qt figure out whether to render as rich text.
        # e.g. if text is actually plain text and uses "\n" newlines;
        #      and we set RichText here, newlines would be swallowed
        d.setTextFormat(Qt.AutoText)
    else:
        d.setTextInteractionFlags(Qt.TextSelectableByMouse)
        d.setTextFormat(Qt.PlainText)
    if checkbox is not None:
        d.setCheckBox(checkbox)
    return d.exec_()


class WindowModalDialog(QDialog):
    """Handy wrapper; window modal dialogs are better for our multi-window
    daemon model as other wallet windows can still be accessed."""

    def __init__(self, parent, title=None):
        QDialog.__init__(self, parent)
        self.setWindowModality(Qt.WindowModal)
        if title:
            self.setWindowTitle(title)


class WaitingDialog(WindowModalDialog):
    """Shows a please wait dialog whilst running a task.

    It is not necessary to maintain a reference to this dialog.
    """

    def __init__(self, parent: QWidget, message: str, task, on_success=None, on_error=None):
        assert parent
        WindowModalDialog.__init__(self, parent, _("Please wait"))
        self.message_label = QLabel(message)
        vbox = QVBoxLayout(self)
        vbox.addWidget(self.message_label)
        self.accepted.connect(self.on_accepted)
        self.show()
        self.thread = TaskThread(self)
        self.thread.finished.connect(self.deleteLater)  # see #3956
        self.thread.add(task, on_success, self.accept, on_error)

    def wait(self):
        self.thread.wait()

    def on_accepted(self):
        self.thread.stop()

    def update(self, msg):
        print(msg)
        self.message_label.setText(msg)


class BlockingWaitingDialog(WindowModalDialog):
    """Shows a waiting dialog whilst running a task.

    Should be called from the GUI thread. The GUI thread will be blocked
    while the task is running; the point of the dialog is to provide
    feedback to the user regarding what is going on.
    """

    def __init__(self, parent: QWidget, message: str, task: Callable[[], Any]):
        assert parent
        WindowModalDialog.__init__(self, parent, _("Please wait"))
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


def one_time_signal_connection(signal: SignalInstance, f: Callable):
    def f_wrapper(*args, **kwargs):
        signal.disconnect(f_wrapper)
        return f(*args, **kwargs)

    signal.connect(f_wrapper)


def robust_disconnect(slot: SignalInstance, f):
    if not slot or not f:
        return
    try:
        slot.disconnect(f)
    except:
        pass


def create_button_box(callback_ok, callback_cancel, ok_text=None, cancel_text=None):
    # Create the QDialogButtonBox instance
    button_box = QDialogButtonBox()

    # Add an 'Ok' button
    if ok_text is None:
        button_box.addButton(QDialogButtonBox.Ok)
    else:
        custom_yes_button = QPushButton(ok_text)
        button_box.addButton(custom_yes_button, QDialogButtonBox.AcceptRole)
        custom_yes_button.clicked.connect(callback_ok)

    # Add a 'Cancel' button
    if cancel_text is None:
        button_box.addButton(QDialogButtonBox.Cancel)
    else:
        custom_cancel_button = QPushButton(cancel_text)
        button_box.addButton(custom_cancel_button, QDialogButtonBox.RejectRole)
        custom_cancel_button.clicked.connect(callback_cancel)

    # Connect the QDialogButtonBox's accepted and rejected signals if default buttons are used
    if ok_text is None:
        button_box.accepted.connect(callback_ok)
    if cancel_text is None:
        button_box.rejected.connect(callback_cancel)

    return button_box


def get_iconname_qrcode() -> str:
    return "qrcode_white.png" if ColorScheme.dark_scheme else "qrcode.png"


def get_iconname_camera() -> str:
    return "camera_white.png" if ColorScheme.dark_scheme else "camera_dark.png"


def editor_contextMenuEvent(self, p, e):
    m = self.createStandardContextMenu()
    m.addSeparator()
    m.addAction(
        read_QIcon(get_iconname_camera()),
        _("Read QR code with camera"),
        p.on_qr_from_camera_input_btn,
    )
    m.addAction(
        read_QIcon("picture_in_picture.png"),
        _("Read QR code from screen"),
        p.on_qr_from_screenshot_input_btn,
    )
    m.addAction(read_QIcon("file.png"), _("Read file"), p.on_input_file)
    m.exec_(e.globalPos())


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
    def has_dark_background(widget):
        brightness = sum(widget.palette().color(QPalette.Background).getRgb()[0:3])
        return brightness < (255 * 3 / 2)

    @staticmethod
    def update_from_widget(widget, force_dark=False):
        ColorScheme.dark_scheme = bool(force_dark or ColorScheme.has_dark_background(widget))


def icon_path(icon_basename: str):
    return resource_path("gui", "icons", icon_basename)


@lru_cache(maxsize=1000)
def read_QIcon(icon_basename: str) -> QIcon:
    if icon_basename is None:
        return QIcon()
    return QIcon(icon_path(icon_basename))


def get_default_language():
    name = QLocale.system().name()
    return name if name in languages else "en_UK"


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


def clipboard_contains_address():
    text = QApplication.clipboard().text()
    return is_address(text)


def do_copy(text: str, *, title: str = None) -> None:
    QApplication.clipboard().setText(str(text))
    message = _("Text copied to Clipboard") if title is None else _("{} copied to Clipboard").format(title)
    show_tooltip_after_delay(message)


def show_tooltip_after_delay(message):
    timer = QTimer()
    # tooltip cannot be displayed immediately when called from a menu; wait 200ms
    timer.singleShot(200, lambda: QToolTip.showText(QCursor.pos(), message))


def pil_image_to_qimage(im):
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qim = QImage(data, im.size[0], im.size[1], QImage.Format_RGBA8888)

    return qim.copy()  # Making a copy to let data persist after function returns


def pil_image_to_qpix(im):
    return QPixmap.fromImage(
        pil_image_to_qimage(im)
    )  # Making a copy to let data persist after function returns


def qicon_to_pil(qicon, size=200):
    # Convert QIcon to QPixmap
    pixmap = qicon.pixmap(size, size)  # specify the size you want

    # Convert QPixmap to QImage
    qimage = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)

    # Convert QImage to raw bytes
    buffer = qimage.constBits()
    img_size = qimage.size()
    width, height = img_size.width(), img_size.height()

    # Convert raw bytes to a PIL image
    pil_image = PilImage.frombuffer("RGBA", (width, height), buffer, "raw", "RGBA", 0, 1)

    return pil_image


def set_balance_label(label: QLabel, wallets):
    for wallet in wallets:
        wallet_values = [wallet.get_balances_for_piechart()]

    confirmed = [v[0] for v in wallet_values]
    unconfirmed = [v[1] for v in wallet_values]
    unmatured = [v[2] for v in wallet_values]
    label.setText(_("Balance") + f": {Satoshis.sum(wallet_values).str_with_unit()} ")
    details = [
        f"{title}: {Satoshis.sum(values).str_with_unit()}"
        for title, values in [
            ("Confirmed", confirmed),
            ("Unconfirmed", unconfirmed),
            ("Unmatured", unmatured),
        ]
        if Satoshis.sum(values)
    ]
    label.setToolTip(",  ".join(details))


def save_file_dialog(name_filters=None, default_suffix=None, default_filename=None):
    options = QFileDialog.Options()
    # options |= QFileDialog.DontUseNativeDialog  # Use Qt-based dialog, not native platform dialog

    file_dialog = QFileDialog()
    file_dialog.setOptions(options)
    file_dialog.setWindowTitle("Save File")
    if default_suffix:
        file_dialog.setDefaultSuffix(default_suffix)

    # Set a default filename
    if default_filename:
        file_dialog.selectFile(default_filename)

    file_dialog.setAcceptMode(QFileDialog.AcceptSave)
    if name_filters:
        file_dialog.setNameFilters(name_filters)

    if file_dialog.exec_() == QFileDialog.Accepted:
        selected_file = file_dialog.selectedFiles()[0]
        # Do something with the selected file path, e.g., save data to the file
        logger.debug(f"Selected save file: {selected_file}")
        return selected_file

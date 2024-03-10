import logging

logger = logging.getLogger(__name__)

from typing import Callable, List, Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtGui import QResizeEvent

from .chat_gui import ChatGui


def short_key(pub_key_bech32: str):
    return f"[{pub_key_bech32[-8:]}]"


import uuid

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class InvisibleScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.unique_id = uuid.uuid4()

        self.setObjectName(f"{self.unique_id}")
        self.setStyleSheet(f"#{self.unique_id}" + " { background: transparent; border: none; }")

        self.content_widget = QWidget()
        self.content_widget.setObjectName(f"{self.unique_id}_content")
        self.content_widget.setStyleSheet(
            f"#{self.unique_id}_content" + " { background: transparent; border: none; }"
        )

        self.setWidget(self.content_widget)


class CloseButton(QtWidgets.QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            """
            background-color: red;
            """
        )
        self.setText("X")
        self.setFixedSize(15, 15)  # adjust size as needed


class BaseDevice(QWidget):
    signal_close = QtCore.pyqtSignal(QWidget)

    def __init__(self, pub_key_bech32: str):
        super().__init__()
        self.pub_key_bech32 = pub_key_bech32
        self.close_button: Optional[QPushButton] = None

        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

    def resizeEvent(self, event: QResizeEvent) -> None:
        if self.close_button:
            self.close_button.move(self.width() - self.close_button.width(), 0)

    def create_close_button(self):

        self.close_button = CloseButton(self)
        self.close_button.clicked.connect(lambda: self.signal_close.emit(self))


class UnTrustedDevice(BaseDevice):
    signal_trust_me = QtCore.pyqtSignal(str)

    def __init__(self, pub_key_bech32: str):
        super().__init__(pub_key_bech32)

        self.original_button_title = f"Trust {short_key(pub_key_bech32)}"
        self.button_add_trusted = QPushButton(self.original_button_title)
        self.button_add_trusted.clicked.connect(lambda: self.signal_trust_me.emit(pub_key_bech32))
        self.layout().addWidget(self.button_add_trusted)
        self.setMinimumHeight(self.button_add_trusted.sizeHint().height())
        self.timer = QTimer(self)

    def trust_request_active(self) -> bool:
        return self.timer.isActive()

    def set_button_status_to_accept(self):
        # Change the button's color to green and text to "Green"
        self.button_add_trusted.setStyleSheet("background-color: green;")
        self.button_add_trusted.setText(f"Accept trust request from {short_key(self.pub_key_bech32)}")

        self.timer.timeout.connect(self.reset_button)
        minutes = 10
        self.timer.start(minutes * 60 * 1000)  # 10 minutes in milliseconds

    def reset_button(self):
        # Reset the button's style to default and text to "Click me"
        self.button_add_trusted.setStyleSheet("")
        self.button_add_trusted.setText("Click me")
        # Stop the timer to avoid it running indefinitely
        self.timer.stop()


class TrustedDevice(BaseDevice):
    def __init__(
        self, pub_key_bech32: str, on_send: Optional[Callable[[str], None]] = None, chat_visible=True
    ):
        super().__init__(pub_key_bech32)

        self.groupbox = QGroupBox(title=f"Device id: {short_key(pub_key_bech32)}")

        self.layout().addWidget(self.groupbox)

        self.groupbox.setLayout(QtWidgets.QVBoxLayout())
        current_margins = self.groupbox.layout().contentsMargins()

        self.groupbox.layout().setContentsMargins(
            current_margins.left(),
            int(current_margins.top() * 2),
            current_margins.right(),
            current_margins.bottom(),
        )  # Left, Top, Right, Bottom margins

        self.groupbox.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid rgba(128, 128, 128, 0.7); /* Border styling */
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px; /* Horizontal position of the title */
                top: 3px; /* Move the title a few pixels down */
                background-color: transparent; /* Make the title background transparent */
            }            
        """
        )

        # Create a QFont object with the desired properties
        boldFont = QFont()
        boldFont.setBold(True)

        # Apply the QFont to the QGroupBox's title
        self.groupbox.setFont(boldFont)

        label = QLabel(
            """
                     <ul>
                        <li>Syncing Address labels</li>
                        <li>Can share PSBTs</li>
                    </ul>      
                    """
        )
        self.groupbox.layout().addWidget(label)
        self.chat_gui = ChatGui()
        self.chat_gui.setVisible(chat_visible)
        self.groupbox.layout().addWidget(self.chat_gui)
        self.setMinimumHeight(self.groupbox.sizeHint().height())
        if on_send:
            self.chat_gui.signal_on_message_send.connect(on_send)

        self.create_close_button()

    @classmethod
    def from_untrusted(cls, untrusted_device: UnTrustedDevice, chat_visible=True) -> "TrustedDevice":
        return TrustedDevice(untrusted_device.pub_key_bech32, chat_visible=chat_visible)


class DeviceList(QtWidgets.QWidget):
    signal_added_device = QtCore.pyqtSignal(TrustedDevice)

    def __init__(self):
        super().__init__()

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.scrollarea = InvisibleScrollArea()
        self.scrollarea.content_widget.setLayout(QtWidgets.QVBoxLayout())
        self.scrollarea.setWidgetResizable(True)

        self.scrollarea.content_widget.layout().setContentsMargins(0, 0, 0, 0)  # Set all margins to zero
        self.scrollarea.content_widget.layout().setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.main_layout.addWidget(self.scrollarea)

    def add_device(self, device: BaseDevice) -> bool:
        if self.device_already_present(device.pub_key_bech32):
            return False
        device.signal_close.connect(self.remove_device)

        self.scrollarea.content_widget.layout().addWidget(device)
        self.signal_added_device.emit(device)
        return True

    def remove_device(self, device: BaseDevice):
        device.setParent(None)
        self.scrollarea.content_widget.layout().removeWidget(device)

        device.close()
        device.deleteLater()

    def device_already_present(self, pub_key_bech32: str) -> bool:
        for device in self.get_devices():
            if device.pub_key_bech32 == pub_key_bech32:
                return True
        return False

    def get_device(self, pub_key_bech32: str) -> Optional[BaseDevice]:
        for device in self.get_devices():
            if device.pub_key_bech32 == pub_key_bech32:
                return device
        return None

    def get_devices(self) -> List[BaseDevice]:
        devices: List[BaseDevice] = []
        for i in range(self.scrollarea.content_widget.layout().count()):
            layout_item = self.scrollarea.content_widget.layout().itemAt(i)
            widget = layout_item.widget()
            if widget is not None:
                if isinstance(widget, BaseDevice):
                    devices.append(widget)
        return devices


class UnTrustedDeviceList(DeviceList):
    pass


class TrustedDeviceList(DeviceList):
    pass


class ConnectedDevices(QtWidgets.QWidget):
    signal_trust_device = QtCore.pyqtSignal(UnTrustedDevice)
    signal_untrust_device = QtCore.pyqtSignal(TrustedDevice)

    def __init__(self, title: str = "", individual_chats_visible=True) -> None:
        super().__init__()
        self.individual_chats_visible = individual_chats_visible

        self.setLayout(QHBoxLayout())

        left_side = QWidget()
        self.layout().addWidget(left_side)
        left_side.setLayout(QVBoxLayout())

        if title:
            title_label = QLabel(f"<b>{title}</b>")
            left_side.layout().addWidget(title_label)

        group_trusted = QGroupBox("Trusted")
        left_side.layout().addWidget(group_trusted)

        self.trusted_devices = TrustedDeviceList()
        group_trusted.setLayout(QVBoxLayout())
        group_trusted.layout().addWidget(self.trusted_devices)

        group_trusted = QGroupBox("UnTrusted")
        left_side.layout().addWidget(group_trusted)

        self.untrusted_devices = UnTrustedDeviceList()
        group_trusted.setLayout(QVBoxLayout())
        group_trusted.layout().addWidget(self.untrusted_devices)

        self.groupchat_gui = ChatGui()

        self.layout().addWidget(self.groupchat_gui)

    def add_trusted_device(self, device: TrustedDevice):
        if self.trusted_devices.device_already_present(device.pub_key_bech32):
            return

        self.trusted_devices.add_device(device)
        device.signal_close.connect(lambda s: self.signal_untrust_device.emit(device))

    def add_untrusted_device(self, untrusted_device: UnTrustedDevice):
        if self.untrusted_devices.device_already_present(untrusted_device.pub_key_bech32):
            return
        if self.trusted_devices.device_already_present(untrusted_device.pub_key_bech32):
            # no need to add an untrusted device if i am trusting it already
            return

        self.untrusted_devices.add_device(untrusted_device)

        def add_to_trusted(pub_key_bech32: str):
            assert pub_key_bech32 == untrusted_device.pub_key_bech32
            self.signal_trust_device.emit(untrusted_device)
            # self.trust_device(untrusted_device)

        untrusted_device.signal_trust_me.connect(add_to_trusted)

    def trust_device(
        self,
        untrusted_device: UnTrustedDevice,
        callback_on_message_send: Callable = None,
        callback_share_filepath: Callable = None,
        callback_attachement_clicked: Callable = None,
    ) -> TrustedDevice:
        self.untrusted_devices.remove_device(untrusted_device)

        device = self.trusted_devices.get_device(untrusted_device.pub_key_bech32)
        if device:
            return device

        trusted_device = TrustedDevice.from_untrusted(
            untrusted_device, chat_visible=self.individual_chats_visible
        )
        self.add_trusted_device(trusted_device)

        if callback_on_message_send:
            trusted_device.chat_gui.signal_on_message_send.connect(callback_on_message_send)
        if callback_share_filepath:
            trusted_device.chat_gui.signal_share_filepath.connect(callback_share_filepath)
        if callback_share_filepath:
            trusted_device.chat_gui.chat_list_display.signal_attachement_clicked.connect(
                callback_attachement_clicked
            )

        return trusted_device

    def untrust_device(self, trusted_device: TrustedDevice) -> UnTrustedDevice:
        self.trusted_devices.remove_device(trusted_device)

        device = self.untrusted_devices.get_device(trusted_device.pub_key_bech32)
        if device:
            return device

        untrusted_device = UnTrustedDevice(pub_key_bech32=trusted_device.pub_key_bech32)
        self.add_untrusted_device(untrusted_device)
        return untrusted_device

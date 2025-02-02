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

import json
import logging
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QCursor, QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PyQt6.QtWidgets import QLineEdit, QPushButton, QStyle, QVBoxLayout, QWidget

from bitcoin_safe.category_info import CategoryInfo, SubtextType
from bitcoin_safe.gui.qt.taglist.custom_list_widget import (
    AddressDragInfo,
    CustomListWidget,
    CustomListWidgetItem,
    clean_tag,
)
from bitcoin_safe.typestubs import TypedPyQtSignal

from ....i18n import translate
from ....util import qbytearray_to_str

logger = logging.getLogger(__name__)


class DeleteButton(QPushButton):
    signal_delete_item: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    signal_addresses_dropped: TypedPyQtSignal[AddressDragInfo] = pyqtSignal(AddressDragInfo)  # type: ignore

    def __init__(self, *args, **kwargs):
        super(DeleteButton, self).__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        self.setIcon(icon)

    def dragEnterEvent(self, event: QDragEnterEvent | None):
        if not event:
            super().dragEnterEvent(event)
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            json_string = qbytearray_to_str(mime_data.data("application/json"))

            d = json.loads(json_string)
            logger.debug(f"dragEnterEvent: Got {d}")
            if d.get("type") == "drag_tag" or d.get("type") == "drag_addresses":
                event.acceptProposedAction()
                return

        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent | None):
        "this is just to hide/undide the button"
        logger.debug("Drag has left the delete button")

    def dropEvent(self, event: QDropEvent | None):
        super().dropEvent(event)
        if not event or event.isAccepted():
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            json_string = qbytearray_to_str(mime_data.data("application/json"))

            d = json.loads(json_string)
            logger.debug(f"dropEvent: Got {d}")
            if d.get("type") == "drag_tag":
                self.signal_delete_item.emit(d.get("tag"))
                event.acceptProposedAction()
                return
            if d.get("type") == "drag_addresses":
                drag_info = AddressDragInfo([None], d.get("addresses"))
                logger.debug(f"dropEvent: {drag_info}")
                self.signal_addresses_dropped.emit(drag_info)
                event.accept()
                return

        event.ignore()


class TagEditor(QWidget):
    def __init__(
        self,
        parent=None,
        category_infos: list[CategoryInfo] | None = None,
        tag_name="tag",
        subtext_type: SubtextType = SubtextType.balance,
    ):
        super(TagEditor, self).__init__(parent)
        self.tag_name = tag_name
        self._layout = QVBoxLayout(self)

        self.input_field = QLineEdit()
        self.input_field.setClearButtonEnabled(True)
        self.input_field.returnPressed.connect(self.add_new_tag_from_input_field)

        self.delete_button = DeleteButton()
        self.delete_button.hide()

        self.list_widget = CustomListWidget(parent=self, subtext_type=subtext_type)
        self._layout.addWidget(self.input_field)
        self._layout.addWidget(self.delete_button)
        self._layout.addWidget(self.list_widget)
        self.list_widget.signal_start_drag.connect(self.show_delete_button)
        self.list_widget.signal_stop_drag.connect(self.hide_delete_button)
        self.list_widget.signal_addresses_dropped.connect(self.hide_delete_button)
        self.delete_button.signal_delete_item.connect(self.list_widget.delete_item)
        self.delete_button.signal_addresses_dropped.connect(self.hide_delete_button)

        self.setAcceptDrops(True)
        # TagEditor.updateUi  ensure that this is not overwritten in a child class
        TagEditor.updateUi(self)

        if category_infos:
            self.list_widget.recreate(category_infos)

    def updateUi(self):
        self.input_field.setPlaceholderText(self.default_placeholder_text())
        self.delete_button.setText(translate("tageditor", "Delete {name}").format(name=self.tag_name))

    def default_placeholder_text(self):
        return translate("tageditor", "Add new {name}").format(name=self.tag_name)

    def dragEnterEvent(self, event: QDragEnterEvent | None):
        if not event:
            super().dragEnterEvent(event)
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            # print('accept')
            # tag = self.itemAt(event.pos())

            json_string = qbytearray_to_str(mime_data.data("application/json"))
            # dropped_addresses = json.loads(json_string)
            # print(f'drag enter {dropped_addresses,   tag.text()}')
            logger.debug(f"dragEnterEvent: {json_string}")

            event.acceptProposedAction()

            logger.debug(f"show_delete_button")
            self.show_delete_button()
        else:
            event.ignore()
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent | None):
        "this is just to hide/undide the button"
        if not event:
            super().dragLeaveEvent(event)
            return

        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            logger.debug("Drag operation left the TagEditor")
            self.hide_delete_button()
        else:
            event.ignore()
            super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent | None):
        super().dropEvent(event)

        if not event or event.isAccepted():
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            self.hide_delete_button()
            event.accept()
        else:
            event.ignore()
            super().dropEvent(event)

    def show_delete_button(self, *args):
        self.input_field.hide()
        self.delete_button.show()

    def hide_delete_button(self, *args):
        self.input_field.show()
        self.delete_button.hide()

    def add(self, new_tag: str, sub_text: str | None = None) -> Optional[CustomListWidgetItem]:
        if not self.tag_exists(new_tag):
            return self.list_widget.add(new_tag, sub_text=sub_text)
        return None

    def add_new_tag_from_input_field(self):
        new_tag = clean_tag(self.input_field.text())
        item = self.add(new_tag)
        if item:
            self.input_field.setPlaceholderText(self.default_placeholder_text())
        else:
            self.input_field.setPlaceholderText(
                translate("tageditor", "This {name} exists already.").format(name=self.tag_name)
            )
        self.input_field.clear()

    def tag_exists(self, tag: str):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.text() == tag:
                return True
        return False

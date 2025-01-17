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

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QDragEnterEvent
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.taglist.main import (
    AddressDragInfo,
    CustomDelegate,
    CustomListWidget,
    CustomListWidgetItem,
    DeleteButton,
    TagEditor,
    clean_tag,
    qbytearray_to_str,
    str_to_qbytearray,
)
from bitcoin_safe.gui.qt.util import hash_color, rescale
from bitcoin_safe.util import hash_string

logger = logging.getLogger(__name__)


import hashlib

from PyQt6.QtCore import QMimeData, QModelIndex, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QApplication


def test_clean_tag():
    assert clean_tag("  hello  ") == "hello"
    assert clean_tag("world") == "world"
    assert clean_tag("PYTHON ") == "PYTHON"
    assert clean_tag("  multiple words  ") == "multiple words"


def test_hash_string():
    text = "test"
    expected_hash = hashlib.sha256(text.encode()).hexdigest()
    assert hash_string(text) == expected_hash


def test_rescale():
    assert rescale(5, 0, 10, 0, 100) == 50
    assert rescale(0, 0, 10, 0, 100) == 0
    assert rescale(10, 0, 10, 0, 100) == 100
    assert rescale(5, 0, 10, 100, 200) == 150


def test_hash_color():
    color = hash_color("test")
    assert isinstance(color, QColor)
    # Check that the color components are within expected ranges
    r = color.red()
    g = color.green()
    b = color.blue()
    assert 100 <= r <= 255
    assert 100 <= g <= 255
    assert 100 <= b <= 255


def test_address_drag_info():
    tags = ["tag1", "tag2"]
    addresses = ["address1", "address2"]
    adi = AddressDragInfo(tags, addresses)
    assert adi.tags == tags
    assert adi.addresses == addresses
    assert repr(adi) == f"AddressDragInfo({tags}, {addresses})"


def test_custom_list_widget_item(qapp: QApplication):
    item_text = "ItemText"
    sub_text = "SubText"
    item = CustomListWidgetItem(item_text, sub_text)
    assert item.text() == item_text
    assert item.subtext == sub_text
    color = item.data(Qt.ItemDataRole.UserRole + 1)
    assert isinstance(color, QColor)
    stored_subtext = item.data(Qt.ItemDataRole.UserRole + 2)
    assert stored_subtext == sub_text


def test_custom_delegate(qapp: QApplication):
    parent = None
    delegate = CustomDelegate(parent)
    assert delegate.currentlyEditingIndex == QModelIndex()
    assert isinstance(delegate.imageCache, dict)


def test_delete_button(qapp: QApplication):
    button = DeleteButton()
    assert button.acceptDrops()
    # Test that the signals exist
    assert hasattr(button, "signal_delete_item")
    assert hasattr(button, "signal_addresses_dropped")


def test_custom_list_widget(qapp: QApplication):
    widget = CustomListWidget()
    # Test that the widget initializes properly
    assert widget.count() == 0
    # Test adding items
    item = widget.add("TestItem", "SubText")
    assert widget.count() == 1
    assert item.text() == "TestItem"
    assert item.subtext == "SubText"
    # Test get_selected
    widget.setAllSelection(True)
    selected = widget.get_selected()
    assert selected == ["TestItem"]


def test_tag_editor(qapp: QApplication):
    tags = ["Tag1", "Tag2"]
    sub_texts = ["Sub1", "Sub2"]
    editor = TagEditor(tags=tags, sub_texts=sub_texts)
    # Test that the editor initializes properly
    assert editor.list_widget.count() == 2
    item1 = editor.list_widget.item(0)
    item2 = editor.list_widget.item(1)
    assert item1
    assert item2
    assert item1.text() == "Tag1"
    assert isinstance(item1, CustomListWidgetItem)
    assert item1.subtext == "Sub1"
    assert item2.text() == "Tag2"
    assert isinstance(item2, CustomListWidgetItem)
    assert item2.subtext == "Sub2"

    # Test adding a new tag
    editor.input_field.setText("NewTag")
    editor.add_new_tag_from_input_field()
    assert editor.list_widget.count() == 3
    new_item = editor.list_widget.item(2)
    assert new_item
    assert new_item.text() == "NewTag"
    assert isinstance(new_item, CustomListWidgetItem)
    assert new_item.subtext is None


def test_tag_exists(qapp: QApplication):
    editor = TagEditor()
    editor.add("TestTag")
    assert editor.tag_exists("TestTag")
    assert not editor.tag_exists("OtherTag")


def test_list_widget_delete_item(qapp: QApplication):
    widget = CustomListWidget()
    widget.add("TestItem")
    assert widget.count() == 1
    widget.delete_item("TestItem")
    assert widget.count() == 0


def test_list_widget_recreate(qapp: QApplication):
    widget = CustomListWidget()
    tags = ["Tag1", "Tag2", "Tag3"]
    sub_texts = ["Sub1", "Sub2", "Sub3"]
    widget.recreate(tags, sub_texts)
    assert widget.count() == 3
    for i, (tag, sub_text) in enumerate(zip(tags, sub_texts)):
        item = widget.item(i)
        assert item
        assert item.text() == tag
        assert isinstance(item, CustomListWidgetItem)
        assert item.subtext == sub_text


def test_custom_list_widget_item_mime_data(qapp: QApplication):
    item = CustomListWidgetItem("TestItem")
    mime_data = item.mimeData()
    assert mime_data.hasFormat("application/json")
    data = qbytearray_to_str(mime_data.data("application/json"))
    import json

    d = json.loads(data)
    assert d["type"] == "drag_tag"
    assert d["tag"] == "TestItem"


def test_list_widget_get_items(qapp: QApplication):
    widget = CustomListWidget()
    widget.add("Item1")
    widget.add("Item2")
    items = list(widget.get_items())
    assert len(items) == 2
    assert items[0].text() == "Item1"
    assert items[1].text() == "Item2"


def test_list_widget_get_item_texts(qapp: QApplication):
    widget = CustomListWidget()
    widget.add("Item1")
    widget.add("Item2")
    texts = list(widget.get_item_texts())
    assert texts == ["Item1", "Item2"]


def test_tag_editor_add_existing_tag(qapp: QApplication):
    editor = TagEditor()
    editor.add("TestTag")
    item = editor.add("TestTag")
    assert item is None  # Should not add duplicate
    assert editor.list_widget.count() == 1


def test_custom_list_widget_add_multiple_items(qapp: QApplication):
    widget = CustomListWidget()
    items = ["Item1", "Item2", "Item3"]
    for item_text in items:
        widget.add(item_text)
    assert widget.count() == len(items)
    for i, item_text in enumerate(items):
        item = widget.item(i)
        assert item
        assert item.text() == item_text


def test_custom_list_widget_remove_multiple_items(qapp: QApplication):
    widget = CustomListWidget()
    items = ["Item1", "Item2", "Item3"]
    for item_text in items:
        widget.add(item_text)
    # Remove items
    widget.delete_item("Item1")
    widget.delete_item("Item2")
    assert widget.count() == 1
    remaining_item = widget.item(0)
    assert remaining_item
    assert remaining_item.text() == "Item3"


def test_custom_list_widget_remove_nonexistent_item(qapp: QApplication):
    widget = CustomListWidget()
    widget.add("Item1")
    assert widget.count() == 1
    # Try to remove an item that does not exist
    widget.delete_item("NonExistentItem")
    # Count should remain the same
    assert widget.count() == 1
    item = widget.item(0)
    assert item
    assert item.text() == "Item1"


def test_delete_button_drag_drop_events(qapp: QApplication, qtbot):

    button = DeleteButton()
    # We need to show the button for events to work properly
    button.show()

    # Create mime data with the correct format
    mime_data = QMimeData()
    drag_data = {
        "type": "drag_tag",
        "tag": "TestTag",
    }
    import json

    mime_data.setData("application/json", str_to_qbytearray(json.dumps(drag_data)))

    # Create a drag enter event
    pos = QPoint(10, 10)
    event = QDragEnterEvent(
        pos, Qt.DropAction.CopyAction, mime_data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )

    # Call the dragEnterEvent
    button.dragEnterEvent(event)
    assert event.isAccepted()

    # Create a drop event
    pos2 = QPointF(10, 10)
    drop_event = QDropEvent(
        pos2, Qt.DropAction.CopyAction, mime_data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )

    # Connect to the signal to capture the emitted value
    captured = []

    def on_delete_item(tag):
        captured.append(tag)

    button.signal_delete_item.connect(on_delete_item)

    # Call the dropEvent
    button.dropEvent(drop_event)

    # Check that the signal was emitted with the correct tag
    assert len(captured) == 1
    assert captured[0] == "TestTag"


def test_custom_list_widget_drop_event_addresses(qapp: QApplication, qtbot):

    widget = CustomListWidget()
    widget.show()

    # Add an item to the widget at a known position
    item = widget.add("TestItem", "SubText")
    # Ensure the widget is properly laid out
    widget.updateGeometry()
    widget.repaint()
    qtbot.waitExposed(widget)

    # Find the position of the item
    item_rect = widget.visualItemRect(item)
    drop_position = item_rect.center()

    # Create mime data with the correct format
    mime_data = QMimeData()
    drag_data = {
        "type": "drag_addresses",
        "addresses": ["Address1", "Address2"],
    }
    import json

    mime_data.setData("application/json", str_to_qbytearray(json.dumps(drag_data)))

    # Create a drag enter event
    event = QDragEnterEvent(
        drop_position,
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    # Call the dragEnterEvent
    widget.dragEnterEvent(event)
    assert event.isAccepted()

    # Create a drop event at the item's position
    drop_event = QDropEvent(
        drop_position.toPointF(),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    # Connect to the signal to capture the emitted value
    captured = []

    def on_addresses_dropped(address_drag_info):
        captured.append(address_drag_info)

    widget.signal_addresses_dropped.connect(on_addresses_dropped)

    # Call the dropEvent
    widget.dropEvent(drop_event)

    # Check that the signal was emitted with the correct AddressDragInfo
    assert len(captured) == 1
    assert captured[0].addresses == ["Address1", "Address2"]
    assert captured[0].tags == ["TestItem"]


def test_custom_list_widget_signals(qapp: QApplication, qtbot):
    widget = CustomListWidget()
    # Connect to signals to capture emitted values
    added_tags = []
    deleted_tags = []

    def on_tag_added(tag):
        added_tags.append(tag)

    def on_tag_deleted(tag):
        deleted_tags.append(tag)

    widget.signal_tag_added.connect(on_tag_added)
    widget.signal_tag_deleted.connect(on_tag_deleted)

    # Add an item
    widget.add("TestItem")
    assert added_tags == ["TestItem"]
    assert widget.count() == 1

    # Delete the item
    widget.delete_item("TestItem")
    assert deleted_tags == ["TestItem"]
    assert widget.count() == 0


def test_tag_editor_signals(qapp: QApplication, qtbot):
    editor = TagEditor()
    # Connect to signals to capture emitted values
    added_tags = []
    deleted_tags = []
    renamed_tags = []

    def on_tag_added(tag):
        added_tags.append(tag)

    def on_tag_deleted(tag):
        deleted_tags.append(tag)

    def on_tag_renamed(old_tag, new_tag):
        renamed_tags.append((old_tag, new_tag))

    editor.list_widget.signal_tag_added.connect(on_tag_added)
    editor.list_widget.signal_tag_deleted.connect(on_tag_deleted)
    editor.list_widget.signal_tag_renamed.connect(on_tag_renamed)

    # Add a tag via the input field
    editor.input_field.setText("NewTag")
    editor.add_new_tag_from_input_field()
    assert added_tags == ["NewTag"]
    assert editor.list_widget.count() == 1

    # Simulate renaming the tag
    item = editor.list_widget.item(0)
    assert item
    old_text = item.text()
    new_text = "RenamedTag"
    # Begin editing the item (this would normally be handled by the delegate)
    item.setText(new_text)
    # Simulate the itemChanged signal
    editor.list_widget.itemChanged.emit(item)
    # Since signal_tag_renamed is emitted by the delegate during editing, and in this test we're not invoking the delegate's editing process, the signal might not be emitted
    # So we can simulate the delegate's signal directly
    delegate = editor.list_widget.itemDelegate()
    assert isinstance(delegate, CustomDelegate)
    delegate.signal_tag_renamed.emit(old_text, new_text)
    assert renamed_tags == [(old_text, new_text)]

    # Delete the tag
    editor.list_widget.delete_item(new_text)
    assert deleted_tags == [new_text]
    assert editor.list_widget.count() == 0


def test_delegate_cache_eviction(qapp: QApplication):
    delegate = CustomDelegate(None)
    # Set a small cache size for testing
    delegate.cache_size = 5
    # Simulate adding items to the cache
    for i in range(10):
        key = ("index", i)
        value = f"image_{i}"
        delegate.add_to_cache(key, value)
    # Cache size should not exceed cache_size
    assert len(delegate.imageCache) <= delegate.cache_size


def test_custom_list_widget_drag_enter_event_invalid_mime(qapp: QApplication):

    widget = CustomListWidget()
    widget.show()

    # Create mime data with an invalid format
    mime_data = QMimeData()
    mime_data.setText("Invalid data")

    # Create a drag enter event
    pos = QPoint(10, 10)
    event = QDragEnterEvent(
        pos, Qt.DropAction.CopyAction, mime_data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )

    # Call the dragEnterEvent
    widget.dragEnterEvent(event)
    # Since the mime data is invalid, the event should not be accepted
    assert not event.isAccepted()

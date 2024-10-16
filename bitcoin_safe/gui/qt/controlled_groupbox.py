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


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QGroupBox, QVBoxLayout, QWidget


class ControlledGroupbox(QWidget):
    def __init__(self, checkbox_text="Enable GroupBox", groupbox_text="", enabled=True) -> None:
        super().__init__()

        self._layout = QVBoxLayout(self)

        # Create the checkbox and add it to the layout
        self.checkbox = QCheckBox(checkbox_text, self)
        self.checkbox.setChecked(enabled)  # Set the initial state based on the 'enabled' argument
        self._layout.addWidget(self.checkbox)

        # Create the groupbox
        self.groupbox = QGroupBox(groupbox_text, self)
        self.groupbox_layout = QVBoxLayout(self.groupbox)

        # Add the groupbox to the main widget's layout
        self._layout.addWidget(self.groupbox)

        # Set the initial enabled state of the groupbox
        self.groupbox.setEnabled(enabled)
        self.checkbox.stateChanged.connect(self.toggleGroupBox)

    def toggleGroupBox(self, value) -> None:
        """Toggle the enabled state of the groupbox based on the checkbox."""
        self.groupbox.setEnabled(value == Qt.CheckState.Checked.value)


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = ControlledGroupbox(enabled=False)  # Example with the groupbox initially disabled
    window.show()
    sys.exit(app.exec())

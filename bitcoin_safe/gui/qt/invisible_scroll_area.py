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


import uuid

from PyQt6.QtWidgets import QScrollArea, QWidget


class InvisibleScrollArea(QScrollArea):
    def __init__(self, parent=None) -> None:
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

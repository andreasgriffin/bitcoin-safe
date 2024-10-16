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

from bitcoin_safe.gui.qt.analyzers import AnalyzerMessage, AnalyzerState, BaseAnalyzer
from bitcoin_safe.gui.qt.custom_edits import AnalyzerLineEdit, AnalyzerTextEdit

logger = logging.getLogger(__name__)

from typing import List, Optional, Union

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QFontMetrics, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QStyle,
    QWidget,
)


class ElidedLabel(QLabel):
    def __init__(self, elide_mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight):
        super().__init__()
        self.elide_mode = elide_mode

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = QFontMetrics(self.font())
        elided = "\n".join(
            [metrics.elidedText(line, self.elide_mode, self.width()) for line in self.text().split("\n")]
        )
        painter.drawText(self.rect(), self.alignment(), elided)

    def _requirey_y_size(self) -> int:
        # Create a QFontMetrics object to measure text dimensions
        metrics = QFontMetrics(self.font())
        text_height = metrics.height()  # Height of one line of text

        # Count the number of lines in the label's text
        number_of_lines = len(self.text().split("\n"))

        # Calculate the total height based on the number of lines
        total_height = number_of_lines * text_height
        return total_height

    def minimumSizeHint(self):
        return QSize(1, self._requirey_y_size())  # Fixed width, dynamic height


class AnalyzerIndicator(QWidget):
    def __init__(
        self,
        line_edits: List[Union[AnalyzerLineEdit, AnalyzerTextEdit]],
        icon_OK: Optional[QPixmap] = None,
        icon_warning: Optional[QPixmap] = None,
        icon_error: Optional[QPixmap] = None,
        hide_if_all_empty=False,
    ):
        super().__init__()
        self.line_edits = line_edits
        self.hide_if_all_empty = hide_if_all_empty

        # icons
        style = self.style() or QStyle()
        self.icons = {
            AnalyzerState.Valid: (
                icon_OK
                if icon_OK
                else QPixmap(style.standardPixmap(QStyle.StandardPixmap.SP_DialogApplyButton))
            ),
            AnalyzerState.Warning: (
                icon_warning
                if icon_warning
                else QPixmap(style.standardPixmap(QStyle.StandardPixmap.SP_MessageBoxWarning))
            ),
            AnalyzerState.Invalid: (
                icon_error
                if icon_error
                else QPixmap(style.standardPixmap(QStyle.StandardPixmap.SP_MessageBoxCritical))
            ),
        }

        # Setup layout
        layout: QHBoxLayout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # SVG label for icons
        self.icon_label: QLabel = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignRight)

        # title label
        self.title_label: QLabel = QLabel()
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        # Text label
        self.text_label: ElidedLabel = ElidedLabel()
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        # Add widgets to layout
        layout.addWidget(self.icon_label)
        layout.addItem(QSpacerItem(10, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed))
        layout.addWidget(self.title_label)
        layout.addWidget(self.text_label)

        # Connect changes in line edits
        for line_edit in self.line_edits:
            line_edit.textChanged.connect(self.updateUi)

        # Initial update
        self.updateUi()

    def updateUi(self):
        self.update_status()
        self.update_label_text()

    def get_analysis_list(self, min_state=AnalyzerState.Valid) -> List[AnalyzerMessage]:
        analysis_list = []
        for le in self.line_edits:
            analyzer = le.analyzer()
            if not analyzer:
                continue
            analysis = analyzer.analyze(le.text())
            if analysis.state >= min_state:
                analysis_list.append(analysis)
        return analysis_list

    def get_worst_analysis(self) -> AnalyzerMessage:
        return BaseAnalyzer.worst_message(self.get_analysis_list())

    def update_status(self) -> None:
        """Update icon based on line edits' contents and validation."""
        self.icon_label.setPixmap(self.icons[self.get_worst_analysis().state])
        self.icon_label.setToolTip(
            "\n".join([str(analysis) for analysis in self.get_analysis_list(min_state=AnalyzerState.Warning)])
        )

        if self.hide_if_all_empty:
            self.setHidden(all([le.text() == "" for le in self.line_edits]))

    def update_label_text(self) -> None:
        """Update text label to show text of all line edits formatted with their object names."""
        titles = [f"{le.objectName()}:" for le in self.line_edits]
        self.title_label.setText("\n".join(titles))

        texts: List[str] = [le.text() for le in self.line_edits]
        self.text_label.setText("\n".join(texts))
        self.text_label.setToolTip("\n".join(texts))


if __name__ == "__main__":

    class CustomIntAnalyzer(BaseAnalyzer):
        """Custom validator that allows any input but validates numeric input."""

        def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
            if input.isdigit():
                return AnalyzerMessage("ok", AnalyzerState.Valid)
            elif not input:
                return AnalyzerMessage("empty", AnalyzerState.Warning)
            return AnalyzerMessage("invalid", AnalyzerState.Invalid)

    def setup_line_edit(line_edit: Union[AnalyzerLineEdit, AnalyzerTextEdit]):
        """Set up a QLineEdit with a custom validator that allows all inputs and styles the QLineEdit based on validity."""
        analyzer = CustomIntAnalyzer()
        line_edit.setAnalyzer(analyzer)
        # line_edit.textChanged.connect(lambda text, le=line_edit, val=validator: validate_input(le, val))

    def validate_input(line_edit: Union[AnalyzerLineEdit, AnalyzerTextEdit], analyzer: CustomIntAnalyzer):
        """Update the line edit style based on validation."""
        analysis = analyzer.analyze(line_edit.text(), 0)
        if analysis.state == AnalyzerState.Warning:
            line_edit.setStyleSheet(f"{line_edit.__class__.__name__}" + " { background-color: #ff6c54; }")
        else:
            line_edit.setStyleSheet(f"")

    app = QApplication([])
    le1 = AnalyzerLineEdit()
    le1.setObjectName("Field 1")
    setup_line_edit(le1)
    le2 = AnalyzerLineEdit()
    le2.setObjectName("Field 2")
    setup_line_edit(le2)
    le3 = AnalyzerLineEdit()
    le3.setObjectName("Field 3")
    setup_line_edit(le3)

    window = AnalyzerIndicator([le1, le2, le3])
    form = QFormLayout()
    form.addRow(le1.objectName() + ":", le1)
    form.addRow(le2.objectName() + ":", le2)
    form.addRow(le3.objectName() + ":", le3)
    form.addRow(window)

    main_widget = QWidget()
    main_widget.setLayout(form)
    main_widget.show()

    app.exec()

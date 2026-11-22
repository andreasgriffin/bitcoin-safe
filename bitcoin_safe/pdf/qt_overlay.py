#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
#

"""Keep ReportLab's vector graphics while shaping their text with Qt."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from PyQt6.QtCore import QPointF, QSizeF
from PyQt6.QtGui import QColor, QFontMetricsF, QPageSize, QPainter, QTransform
from PyQt6.QtPrintSupport import QPrinter
from reportlab.lib.colors import Color
from reportlab.pdfgen.canvas import Canvas

from .font_manager import PDFFontManager


@dataclass
class TextRun:
    text: str
    x: float
    y: float
    size: float
    color: QColor
    transform: QTransform
    alignment: Literal["left", "center", "right"]


class TextOverlayCanvas(Canvas):
    """Collect graph text while ReportLab draws shapes and links into a PDF."""

    _currentMatrix: tuple[float, float, float, float, float, float]
    _fillColorObj: Color
    _fontsize: float

    def __init__(self, output: BytesIO, pagesize: tuple[float, float]) -> None:
        super().__init__(output, pagesize=pagesize)
        self.text_pages: list[list[TextRun]] = [[]]
        self.page_height = pagesize[1]

    def _record_text(
        self, x: float, y: float, text: str, alignment: Literal["left", "center", "right"]
    ) -> None:
        a, b, c, d, e, f = self._currentMatrix
        color = self._fillColorObj
        self.text_pages[-1].append(
            TextRun(
                text,
                x,
                y,
                self._fontsize,
                QColor.fromRgbF(color.red, color.green, color.blue),
                QTransform(a, -b, -c, d, e, self.page_height - f),
                alignment,
            )
        )

    def drawString(
        self,
        x: float,
        y: float,
        text: str,
        mode: int | None = None,
        charSpace: float = 0,
        direction: str | None = None,
        wordSpace: float | None = None,
        shaping: bool = False,
    ) -> None:
        self._record_text(x, y, text, "left")

    def drawCentredString(
        self,
        x: float,
        y: float,
        text: str,
        mode: int | None = None,
        charSpace: float = 0,
        direction: str | None = None,
        wordSpace: float | None = None,
        shaping: bool = False,
    ) -> None:
        self._record_text(x, y, text, "center")

    def drawRightString(
        self,
        x: float,
        y: float,
        text: str,
        mode: int | None = None,
        charSpace: float = 0,
        direction: str | None = None,
        wordSpace: float | None = None,
        shaping: bool = False,
    ) -> None:
        self._record_text(x, y, text, "right")

    def showPage(self) -> None:
        super().showPage()
        self.text_pages.append([])


def render_text_overlay(
    path: Path, pages: list[list[TextRun]], pagesize: tuple[float, float], language: str
) -> None:
    """Write searchable, shaped text at the positions recorded for each page."""
    PDFFontManager.ensure_loaded()
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setResolution(72)
    printer.setFullPage(True)
    printer.setPageSize(QPageSize(QSizeF(*pagesize), QPageSize.Unit.Point))
    printer.setFontEmbeddingEnabled(True)
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError(f"Could not start PDF printer for {path}")
    try:
        for page_number, runs in enumerate(pages):
            if page_number and not printer.newPage():
                raise RuntimeError(f"Could not advance PDF printer to page {page_number + 1}")
            for run in runs:
                painter.setWorldTransform(run.transform)
                font = PDFFontManager.font("en" if run.text.isascii() else language, run.size)
                painter.setFont(font)
                painter.setPen(run.color)
                width = QFontMetricsF(font, printer).horizontalAdvance(run.text)
                offset = width / 2 if run.alignment == "center" else width if run.alignment == "right" else 0
                painter.drawText(QPointF(run.x - offset, -run.y), run.text)
    finally:
        painter.end()

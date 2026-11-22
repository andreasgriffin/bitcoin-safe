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

"""Render existing ReportLab flowables with Qt's Unicode text engine.

The existing content builders remain unchanged, while Qt handles shaping,
right-to-left text and portable embedded PDF fonts. This is an adapter, not a
pixel-for-pixel reproduction of ReportLab's layout. Keep Python objects alive
until the printer has finished painting.
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from io import BytesIO
from pathlib import Path

from PyQt6.QtCore import QByteArray, QLocale, QRectF, QSizeF, Qt, QUrl
from PyQt6.QtGui import QFontMetricsF, QImage, QPainter, QTextDocument
from PyQt6.QtPrintSupport import QPrinter
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.platypus import Flowable, KeepInFrame, PageBreak, Paragraph, Spacer, Table
from reportlab.platypus import Image as RLImage

from bitcoin_safe.constants import APP_NAME, APP_WEBSITE
from bitcoin_safe.pdf_footer import pdf_timestamp

from .font_manager import PDFFontManager

logger = logging.getLogger(__name__)

_TAGS = re.compile(r"(<[^>]+>)")
_ASCII_RUN = re.compile(r"[ -~]+")


def _latin_runs(markup: str) -> str:
    """Use the full Latin face for ASCII without changing text or its direction."""
    return "".join(
        part
        if part.startswith("<")
        else _ASCII_RUN.sub(r'<span style="font-family:Noto Sans">\g<0></span>', part)
        for part in _TAGS.split(markup)
    )


# Qt's HTML dimensions use 96 pixels per inch; ReportLab uses 72 points.
_CSS_PIXELS_PER_POINT = 96 / 72


class FlowableHTML:
    """Convert the application’s Platypus flowables to Qt HTML."""

    def __init__(self, language: str = "en_US") -> None:
        self.language = language
        self.images: dict[str, bytes] = {}
        self.rtl = False

    def _image(self, element: RLImage) -> str:
        source = element._file  # type: ignore[attr-defined]
        if isinstance(source, (str, Path)):
            content = Path(source).read_bytes()
        else:
            image = element._img  # type: ignore[attr-defined]
            if not image or not isinstance(image.fp, BytesIO):
                raise TypeError(f"Unsupported PDF image source: {type(source)!r}")
            content = image.fp.getvalue()
        key = f"pdf-internal-image-{len(self.images)}.png"
        self.images[key] = content
        width = max(1, round(element.drawWidth * _CSS_PIXELS_PER_POINT))
        height = max(1, round(element.drawHeight * _CSS_PIXELS_PER_POINT))
        return f'<img src="{key}" width="{width}" height="{height}" />'

    def _paragraph(self, element: Paragraph) -> str:
        style = element.style
        text = html.unescape(_TAGS.sub("", element.text))
        first_strong = next(
            (
                unicodedata.bidirectional(char)
                for char in text
                if unicodedata.bidirectional(char) in {"L", "R", "AL"}
            ),
            "L",
        )
        direction = "rtl" if first_strong in {"R", "AL"} else "ltr"
        align = (
            "center"
            if style.alignment == TA_CENTER
            else "right"
            if direction == "rtl" or style.alignment == TA_RIGHT
            else "left"
        )
        size = float(style.fontSize)
        indent = max(0, float(style.leftIndent))
        return (
            f'<p dir="{direction}" style="margin:1px 0 3px {indent:.1f}px; '
            f'text-align:{align}; font-size:{size:.2f}pt;">{_latin_runs(element.text)}</p>'
        )

    def _table(self, table: Table) -> str:
        values = table._cellvalues  # type: ignore[attr-defined]
        widths = table._colWidths  # type: ignore[attr-defined]
        row_heights = table._rowHeights  # type: ignore[attr-defined]
        span_commands = table._spanCmds  # type: ignore[attr-defined]
        valid_widths = [w if isinstance(w, (float, int)) and w > 0 else 0 for w in widths]
        width_sum = sum(valid_widths)
        spans = {(start[1], start[0]): (end[1], end[0]) for _, start, end in span_commands}
        has_grid = any(
            command[0] in {"GRID", "INNERGRID", "BOX"}
            and command[3] > 0
            and (command[4].red, command[4].green, command[4].blue) != (1, 1, 1)
            for command in table._linecmds  # type: ignore[attr-defined]
        )
        repeat_header = bool(table.repeatRows) and has_grid
        # Some existing tables intentionally have invisible borders.
        grid = "1" if has_grid else "0"
        is_label_table = any(isinstance(cell, KeepInFrame) for row in values for cell in row)
        table_width = (
            str(round(width_sum * _CSS_PIXELS_PER_POINT)) if is_label_table and width_sum else "100%"
        )
        parts = [
            f'<table width="{table_width}" align="center" border="{grid}" cellspacing="0" cellpadding="3">'
        ]
        for ri, row in enumerate(values):
            if ri == 0 and repeat_header:
                parts.append("<thead>")
            elif ri == 1 and repeat_header:
                parts.append("<tbody>")
            parts.append("<tr>")
            for ci, cell in enumerate(row):
                if any(
                    start_row <= ri <= end_row
                    and start_col <= ci <= end_col
                    and (ri, ci) != (start_row, start_col)
                    for (start_row, start_col), (end_row, end_col) in spans.items()
                ):
                    continue
                end_row, end_col = spans.get((ri, ci), (ri, ci))
                colspan = f' colspan="{end_col - ci + 1}"' if end_col > ci else ""
                rowspan = f' rowspan="{end_row - ri + 1}"' if end_row > ri else ""
                pct = (
                    f' width="{100 * valid_widths[ci] / width_sum:.3f}%"'
                    if width_sum and ci < len(valid_widths)
                    else ""
                )
                # Readability first: use dark text on pale headers, unlike
                # ReportLab's legacy light-grey/whitesmoke combination.
                bg = ' bgcolor="#e8edf1"' if has_grid and ri == 0 and not is_label_table else ""
                height = row_heights[ri]
                cell_height = f' height="{round(height)}"' if isinstance(height, (int, float)) else ""
                parts.append(f"<td{pct}{bg}{colspan}{rowspan}{cell_height}>")
                parts.append(self._cell(cell))
                parts.append("</td>")
            parts.append("</tr>")
            if ri == 0 and repeat_header:
                parts.append("</thead>")
        if repeat_header and len(values) > 1:
            parts.append("</tbody>")
        parts.append("</table>")
        return "".join(parts)

    def _cell(self, value: object) -> str:
        if isinstance(value, (list, tuple)):
            return "".join(self._cell(item) for item in value)
        if isinstance(value, KeepInFrame):
            items = value._content  # type: ignore[attr-defined]
            content = "".join(self.flowable(item) for item in items)
            if len(items) == 1 and isinstance(items[0], Paragraph):
                paragraph = items[0]
                size = float(paragraph.style.fontSize)
                width = QFontMetricsF(PDFFontManager.font(self.language, size)).horizontalAdvance(
                    paragraph.getPlainText()
                )
                available = max(1, value.maxWidth * _CSS_PIXELS_PER_POINT - 12)
                adjusted_size = size * min(1, available / max(width, 1))
                content = content.replace(f"font-size:{size:.2f}pt", f"font-size:{adjusted_size:.2f}pt", 1)
            # Leave room for the table cell padding and paragraph margins.
            line_height = max(1, value.maxHeight * _CSS_PIXELS_PER_POINT - 9)
            return content.replace('style="', f'style="line-height:{line_height:.1f}px; ', 1)
        if isinstance(value, str):
            escaped = html.escape(value).replace("\n", "<br/>")
            return _latin_runs(escaped)
        if isinstance(value, (Paragraph, Table, RLImage, Spacer, PageBreak)):
            return self.flowable(value)
        if value is None:
            return ""
        if isinstance(value, Flowable):
            raise TypeError(f"Unsupported PDF flowable {type(value).__name__}; refusing to omit content")
        return html.escape(str(value))

    def flowable(self, value: object) -> str:
        if isinstance(value, Paragraph):
            return self._paragraph(value)
        if isinstance(value, Table):
            return self._table(value)
        if isinstance(value, RLImage):
            return f'<p style="margin:0 0 2px 0;">{self._image(value)}</p>'
        if isinstance(value, Spacer):
            return f'<p style="margin:0; height:{max(1, value.height):.1f}px;"></p>'
        if isinstance(value, PageBreak):
            return '<p style="page-break-before:always;"></p>'
        raise TypeError(f"Unsupported PDF flowable {type(value).__name__}; refusing to omit content")

    def convert(self, values: list[object], rtl: bool) -> str:
        self.rtl = rtl
        direction = "rtl" if rtl else "ltr"
        body = "\n".join(self.flowable(item) for item in values)
        return (
            '<html><head><meta charset="utf-8" /></head>'
            f'<body dir="{direction}" style="color:#242424;">{body}</body></html>'
        )


class QtPDFRenderer:
    """Paginated, searchable, embedded-font PDF output using Qt."""

    PAGE_WIDTH = 612.0  # US Letter, points
    PAGE_HEIGHT = 792.0
    LEFT_MARGIN = 36.0
    RIGHT_MARGIN = 36.0
    TOP_MARGIN = 36.0
    BOTTOM_MARGIN = 58.0  # reserve a dedicated non-overlapping footer region

    def __init__(
        self,
        lang_code: str,
        footer: str | None = None,
        created_at: str | None = None,
        page_offset: int | None = None,
    ):
        self.lang_code = lang_code
        self.footer = footer
        self.created_at = created_at
        self.page_offset = page_offset

    def _draw_footer(self, painter: QPainter, page_index: int, pages: int) -> None:
        if not self.footer:
            return
        painter.save()
        font = PDFFontManager.font(self.lang_code, 7.5)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.darkGray)
        y = self.PAGE_HEIGHT - 28.0
        w = self.PAGE_WIDTH
        if self.footer == "transaction":
            painter.drawLine(int(self.LEFT_MARGIN), int(y - 9), int(w - self.RIGHT_MARGIN), int(y - 9))
            painter.drawText(
                QRectF(self.LEFT_MARGIN, y, 240, 15),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{APP_NAME} | {APP_WEBSITE}",
            )
            # Use the locale that generated the PDF, not the machine's locale.
            from PyQt6.QtCore import QDate

            date = QLocale(self.lang_code).toString(QDate.currentDate(), QLocale.FormatType.ShortFormat)
            painter.drawText(
                QRectF(w / 2 - 80, y, 160, 15),
                Qt.AlignmentFlag.AlignCenter,
                date,
            )
        elif self.footer == "statement":
            painter.drawText(
                QRectF(w / 2 - 150, y, 300, 15),
                Qt.AlignmentFlag.AlignCenter,
                f"Date: {self.created_at or pdf_timestamp()}",
            )
        painter.drawText(
            QRectF(w - self.RIGHT_MARGIN - 90, y, 90, 15),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"Page {self.page_offset + page_index + 1}"
            if self.page_offset is not None
            else f"{page_index + 1}/{pages}",
        )
        painter.restore()

    def save(self, elements: list[object], filename: str) -> None:
        PDFFontManager.ensure_loaded()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(filename)
        printer.setResolution(72)  # points, matching QTextDocument coordinates
        printer.setFullPage(True)
        from PyQt6.QtGui import QPageSize

        printer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
        printer.setFontEmbeddingEnabled(True)

        converter = FlowableHTML(self.lang_code)
        locale = QLocale(self.lang_code)
        rtl = locale.textDirection() == Qt.LayoutDirection.RightToLeft
        markup = converter.convert(elements, rtl=rtl)

        document = QTextDocument()
        layout = document.documentLayout()
        assert layout is not None
        layout.setPaintDevice(printer)
        document.setDefaultFont(PDFFontManager.font(self.lang_code))
        document.setDocumentMargin(0)
        # Keep image bytes in memory for the full duration of printing.
        qt_images = []
        for key, data in converter.images.items():
            qimage = QImage.fromData(QByteArray(data))
            if qimage.isNull():
                raise ValueError(f"Invalid PDF image data: {key}")
            qt_images.append(qimage)
            document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(key), qimage)
        document.setHtml(markup)
        document.setPageSize(
            QSizeF(
                self.PAGE_WIDTH - self.LEFT_MARGIN - self.RIGHT_MARGIN,
                self.PAGE_HEIGHT - self.TOP_MARGIN - self.BOTTOM_MARGIN,
            )
        )
        pages = max(1, document.pageCount())

        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError(f"Could not start PDF printer for {filename}")
        try:
            page_height = document.pageSize().height()
            page_width = document.pageSize().width()
            for i in range(pages):
                if i and not printer.newPage():
                    raise RuntimeError(f"Could not advance PDF printer to page {i + 1}")
                painter.save()
                painter.translate(self.LEFT_MARGIN, self.TOP_MARGIN)
                painter.setClipRect(QRectF(0, 0, page_width, page_height))
                painter.translate(0, -i * page_height)
                document.drawContents(painter, QRectF(0, i * page_height, page_width, page_height))
                painter.restore()
                self._draw_footer(painter, i, pages)
        finally:
            painter.end()
        logger.debug("Saved Qt PDF (%s pages) to %s", pages, filename)

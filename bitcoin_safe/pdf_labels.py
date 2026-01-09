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

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import KeepInFrame, Paragraph, Spacer, Table, TableStyle

from bitcoin_safe.i18n import translate
from bitcoin_safe.pdfrecovery import BasePDF, white_space, write_and_open_temp_pdf


class PDFLabels(BasePDF):
    def __init__(self, lang_code: str) -> None:
        """Initialize instance."""
        super().__init__(lang_code)

        self.style_label = ParagraphStyle(
            "labels_label",
            fontName=self.font_name,
            parent=self.styles["Heading4"],
            alignment=TA_CENTER,
            fontSize=8,
            leading=9,
            spaceBefore=0,
            spaceAfter=0,
        )
        self.style_device = ParagraphStyle(
            "labels_device",
            fontName=self.font_name,
            parent=self.styles["BodyText"],
            alignment=TA_CENTER,
            fontSize=6,
            leading=7,
            spaceBefore=0,
            spaceAfter=0,
        )
        self.elements: list[Any] = []

    def add_labels(self, wallet_id: str, label_pairs: list[tuple[str, str]]) -> None:
        """Add labels."""
        heading = Paragraph(
            translate(
                "pdf",
                'Hardware signer labels for wallet "{wallet_id}"',
                no_translate=self.no_translate,
            ).format(wallet_id=wallet_id),
            self.style_heading,
        )
        self.elements.append(heading)

        self.elements.append(
            Paragraph(
                translate("pdf", "Created with", no_translate=self.no_translate)
                + f" Bitcoin Safe: {white_space * 5} www.bitcoin-safe.org",
                self.style_paragraph,
            )
        )
        self.elements.append(Paragraph("", self.style_paragraph))

        instruction_text = translate(
            "pdf",
            "Cut out the labels below and attach each one to the matching hardware signer.",
            no_translate=self.no_translate,
        )
        self.elements.append(Paragraph(instruction_text, self.style_paragraph))
        self.elements.append(Spacer(1, 12))

        if not label_pairs:
            self.elements.append(
                Paragraph(
                    translate(
                        "pdf",
                        "No hardware signers configured yet.",
                        no_translate=self.no_translate,
                    ),
                    self.style_paragraph,
                )
            )
            return

        label_width = 5 * cm
        label_height = 1 * cm
        columns = 1
        col_widths = [label_width] * columns

        rows: list[list[Any]] = []
        for i in range(0, len(label_pairs), columns):
            row: list[Any] = []
            for label, _device_name in label_pairs[i : i + columns]:
                cell_flowables: list[Any] = [
                    Paragraph(
                        f"{label}",
                        self.style_label,
                    ),
                ]
                row.append(
                    KeepInFrame(
                        label_width,
                        label_height,
                        cell_flowables,
                        hAlign="CENTER",
                        vAlign="MIDDLE",
                        mode="shrink",
                    )
                )
            while len(row) < columns:
                row.append("")
            rows.append(row)

        row_heights = [label_height] * len(rows)
        table = Table(rows, colWidths=col_widths, rowHeights=row_heights, hAlign="CENTER")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 1, colors.black),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )

        self.elements.append(table)


def make_and_open_labels_pdf(wallet_id: str, label_pairs: list[tuple[str, str]], lang_code: str) -> None:
    """Make and open labels pdf."""
    pdf_labels = PDFLabels(lang_code=lang_code)
    pdf_labels.add_labels(wallet_id=wallet_id, label_pairs=label_pairs)

    filename = translate(
        "pdf",
        "Hardware signer labels for {id}",
        no_translate=pdf_labels.no_translate,
    ).format(id=wallet_id)
    write_and_open_temp_pdf(pdf_labels, filename)

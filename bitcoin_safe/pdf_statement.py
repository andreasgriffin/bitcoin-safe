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

import datetime
import logging
import os
from pathlib import Path
from typing import Any, List, Tuple

import bdkpython as bdk
import numpy as np
from bitcoin_qr_tools.qr_generator import QRGenerator
from bitcoin_usb.address_types import DescriptorInfo
from PyQt6.QtCore import QDateTime, QLocale
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

from bitcoin_safe.i18n import translate
from bitcoin_safe.pdfrecovery import pilimage_to_reportlab, register_font, white_space
from bitcoin_safe.util import Satoshis, unit_str
from bitcoin_safe.util_os import xdg_open_file

from .wallet import Wallet

logger = logging.getLogger(__name__)


class PdfStatement:

    def __init__(self, network: bdk.Network, lang_code: str) -> None:
        font_info = register_font(lang_code=lang_code)
        self.font_name = font_info.font_name
        self.network = network
        self.no_translate = font_info.supported_lang_code == "en_US"

        styles = getSampleStyleSheet()
        self.style_paragraph = ParagraphStyle(
            name="Centered",
            fontName=self.font_name,
            parent=styles["BodyText"],
            alignment=TA_CENTER,
        )
        self.style_paragraph_left = ParagraphStyle(
            name="LEFT",
            fontName=self.font_name,
            parent=styles["BodyText"],
            alignment=TA_LEFT,
        )
        self.style_paragraph_right = ParagraphStyle(
            name="LEFT",
            fontName=self.font_name,
            parent=styles["BodyText"],
            alignment=TA_RIGHT,
        )
        self.style_heading = ParagraphStyle(
            "centered_heading",
            fontName=self.font_name,
            parent=styles["Heading1"],
            alignment=TA_CENTER,
        )
        self.style_text = ParagraphStyle(
            name="normal",
            fontName=self.font_name,
        )
        self.elements: List[Any] = []

    @property
    def TEXT_24_WORDS(self):
        return translate("pdf", "12 or 24", no_translate=self.no_translate)

    def create_balance_table(
        self,
        table: np.ndarray,
        widths: List[int],
        header: List[str],
        styles: List[ParagraphStyle] | None = None,
        header_styles: List[ParagraphStyle] | None = None,
    ) -> Table:
        if not styles:
            styles = [self.style_paragraph for i in range(table.shape[1])]
        else:
            styles += [self.style_paragraph for i in range(table.shape[1] - len(styles))]

        if not header_styles:
            header_styles = styles
        else:
            header_styles = (header_styles + styles)[: len(styles)]

        # Convert numpy array to a list of lists for ReportLab compatibility
        data = [[Paragraph(entry, style=style) for entry, style in zip(row, styles)] for row in table]
        data.insert(
            0, [Paragraph(entry, style=style) for entry, style in zip(header, header_styles)]
        )  # Insert the header at the beginning of the data list

        # Create the table
        t = Table(data, colWidths=widths)

        # Define the style for the table
        style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),  # Header background color
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),  # Header text color
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),  # Default alignment to center
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),  # Grid color and size
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),  # Font style for header
            ]
        )

        # Apply the style to the table
        t.setStyle(style)

        return t

    @staticmethod
    def create_invisible_table(columns: List[Any], col_widths: List[int]) -> Table:
        # Validate input and create data for the table
        max_rows = max([len(col) for col in columns])
        data = []
        for i in range(max_rows):
            row = [col[i] if i < len(col) else "" for col in columns]
            data.append(row)

        # Create a Table with data and specify column widths
        table = Table(data, colWidths=col_widths)

        # Apply TableStyle to make the borders invisible
        style = TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0, colors.white),  # Outer border
                ("INNERGRID", (0, 0), (-1, -1), 0, colors.white),  # Inner grid
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),  # Vertical alignment for all cells
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),  # Vertical alignment for all cells
                # ('VALIGN', (0, 0), (0, 0), 'TOP'),                  # Vertical alignment for first cell
                # ('VALIGN', (1, 0), (1, 0), 'BOTTOM')                # Vertical alignment for second cell
            ]
        )

        table.setStyle(style)

        return table

    def add_page_break(self) -> None:
        self.elements.append(PageBreak())  # Add a page break between documents if needed

    def _address_table(self, address_info: List[Tuple[str, str]]) -> None:

        self.elements.append(
            self.create_balance_table(
                table=np.array(address_info),
                widths=[400, 120],
                header=["Address", f"Balance [{unit_str(self.network)}]"],
                styles=[self.style_paragraph_left, self.style_paragraph_right],
            )
        )

    def _descriptor_part(
        self,
        wallet_descriptor_string: str,
        threshold: int,
    ) -> None:
        qr_image = pilimage_to_reportlab(
            QRGenerator.create_qr_PILimage(wallet_descriptor_string), width=200, height=200
        )
        if threshold > 1:
            desc_str = Paragraph(
                translate(
                    "pdf",
                    "The wallet descriptor (QR Code) <br/><br/>{wallet_descriptor_string}<br/><br/> allows you to create a watch-only wallet to see your balance. To spent from it you need {threshold} Seeds and the wallet descriptor.",
                    no_translate=self.no_translate,
                ).format(threshold=threshold, wallet_descriptor_string=wallet_descriptor_string),
                self.style_paragraph,
            )
        else:
            desc_str = Paragraph(
                translate(
                    "pdf",
                    "The wallet descriptor (QR Code) <br/><br/>{wallet_descriptor_string}<br/><br/> allows you to create a watch-only wallet to see your balance.  To spent from it you need the secret {number} words (Seed).",
                    no_translate=self.no_translate,
                ).format(number=self.TEXT_24_WORDS, wallet_descriptor_string=wallet_descriptor_string),
                self.style_paragraph,
            )
        self.elements.append(self.create_invisible_table([[qr_image], [desc_str]], [250, 300]))

    def create_pdf(
        self,
        title: str,
        wallet_descriptor_string: str,
        address_info: List[Tuple[str, str]],
        threshold: int,
    ) -> None:
        self.elements.append(Paragraph(title, style=self.style_heading))

        localized_date = QLocale().toString(QDateTime(datetime.datetime.now()))
        # Small subtitle
        self.elements.append(
            Paragraph(
                translate("pdf", "Created at {date} with", no_translate=self.no_translate).format(
                    date=localized_date
                )
                + f" Bitcoin Safe: {white_space*2} www.bitcoin-safe.org",
                self.style_paragraph,
            )
        )
        self.elements.append(Paragraph(f"", self.style_paragraph))

        self._descriptor_part(wallet_descriptor_string, threshold)

        self._address_table(address_info=address_info)

    def save_pdf(self, filename: str) -> None:

        # Adjust these values to set your desired margins (values are in points; 72 points = 1 inch)
        LEFT_MARGIN = 36  # 0.5 inch
        RIGHT_MARGIN = 36  # 0.5 inch
        TOP_MARGIN = 36  # 0.5 inch
        BOTTOM_MARGIN = 36  # 0.5 inch

        document = SimpleDocTemplate(
            filename,
            pagesize=letter,
            leftMargin=LEFT_MARGIN,
            rightMargin=RIGHT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
        )
        document.build(self.elements)

    def open_pdf(self, filename: str) -> None:
        if os.path.exists(filename):
            xdg_open_file(Path(filename))
        else:
            logger.info("File not found!")


def make_and_open_pdf_statement(wallet: Wallet, lang_code: str) -> None:
    info = DescriptorInfo.from_str(wallet.multipath_descriptor.as_string())

    address_info: List[Tuple[str, str]] = []
    for address in wallet.get_addresses():
        balance = wallet.get_addr_balance(address).total
        if balance:
            address_info.append(
                (
                    address,
                    Satoshis(value=balance, network=wallet.network).format(
                        color_formatting="rich", show_unit=False, unicode_space_character=False
                    ),
                )
            )
    address_info = sorted(address_info, key=lambda row: row[1], reverse=True)

    pdf_statement = PdfStatement(lang_code=lang_code, network=wallet.network)

    file_title = translate(
        "pdf",
        "Balance Statement of {id}",
        no_translate=pdf_statement.no_translate,
    ).format(id=wallet.id)
    title = translate(
        "pdf",
        'Balance Statement of "{id}"',
        no_translate=pdf_statement.no_translate,
    ).format(id=wallet.id)
    pdf_statement.create_pdf(
        title=title,
        wallet_descriptor_string=wallet.multipath_descriptor.as_string(),
        address_info=address_info,
        threshold=info.threshold,
    )

    temp_file = os.path.join(Path.home(), f"{file_title}.pdf")
    pdf_statement.save_pdf(temp_file)
    pdf_statement.open_pdf(temp_file)
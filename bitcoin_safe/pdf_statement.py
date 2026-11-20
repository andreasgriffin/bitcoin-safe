#
# Bitcoin-Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

from __future__ import annotations

import logging
from typing import Any
from xml.sax.saxutils import escape

import bdkpython as bdk
from bitcoin_qr_tools.qr_generator import QRGenerator
from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol, Satoshis
from bitcoin_usb.address_types import DescriptorInfo
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

from bitcoin_safe.constants import APP_NAME, APP_WEBSITE
from bitcoin_safe.i18n import translate
from bitcoin_safe.pdf_footer import draw_pdf_footer, pdf_timestamp
from bitcoin_safe.pdfrecovery import BasePDF, pilimage_to_reportlab, white_space, write_and_open_temp_pdf

from .wallet import Wallet

logger = logging.getLogger(__name__)


class PdfStatement(BasePDF):
    def __init__(self, network: bdk.Network, lang_code: str, created_at: str | None = None) -> None:
        """Initialize instance."""
        super().__init__(lang_code=lang_code)
        self.network = network
        self.created_at = created_at if created_at is not None else pdf_timestamp()
        # Use an ASCII unit so statements distinguish test coins without font issues.
        self.bitcoin_symbol = "BTC" if network == bdk.Network.BITCOIN else "tBTC"

    def draw_footer(self, canvas: Canvas, document: BaseDocTemplate) -> None:
        """Draw the statement footer on every page."""
        draw_pdf_footer(canvas, letter[0], self.font_name, self.created_at)

    def save_pdf(self, filename: str) -> None:
        """Save the statement with a footer on every page."""
        document = SimpleDocTemplate(
            filename, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
        )
        document.build(self.elements, onFirstPage=self.draw_footer, onLaterPages=self.draw_footer)

    @property
    def TEXT_24_WORDS(self):
        """TEXT 24 WORDS."""
        return translate("pdf", "12 or 24", no_translate=self.no_translate)

    def create_balance_table(self, rows: list[tuple[str, str, str, str]], header: list[str]) -> Table:
        """Fit address, label, and balance columns within the printable page width."""
        styles = [self.style_paragraph_left] * 3 + [self.style_paragraph_right]
        data = [[Paragraph(escape(value), style) for value, style in zip(header, styles, strict=True)]]
        data.extend(
            [
                Paragraph(escape(value) if column < 3 else value, styles[column])
                for column, value in enumerate(row)
            ]
            for row in rows
        )
        # The widths fit inside the padded statement frame; paragraphs wrap as needed.
        widths = [68, 211, 149, 100]

        table = Table(data, colWidths=widths, repeatRows=1, splitInRow=1)
        table.setStyle(self.statement_table_style(include_total=True))
        return table

    @staticmethod
    def create_invisible_table(columns: list[Any], col_widths: list[int]) -> Table:
        # Validate input and create data for the table
        """Create invisible table."""
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
        """Add page break."""
        self.elements.append(PageBreak())  # Add a page break between documents if needed

    def _address_table(self, address_info: list[tuple[str, str, str, str]], total_amount: str) -> None:
        """Add the funded addresses, their labels, and the total."""
        self.elements.append(
            self.create_balance_table(
                rows=address_info + [(translate("pdf", "Total"), "", "", total_amount)],
                header=[
                    translate("pdf", "Category"),
                    translate("pdf", "Address"),
                    translate("pdf", "Label"),
                    translate("pdf", "Balance") + f" [{self.bitcoin_symbol}]",
                ],
            )
        )

    def _descriptor_part(
        self,
        wallet_descriptor_string: str,
        threshold: int,
    ) -> None:
        """Descriptor part."""
        qr_image = pilimage_to_reportlab(
            QRGenerator.create_qr_PILimage(wallet_descriptor_string), width=200, height=200
        )
        if threshold > 1:
            desc_str = Paragraph(
                translate(
                    "pdf",
                    "The wallet descriptor (QR Code) <br/><br/>{wallet_descriptor_string}<br/><br/> allows "
                    "you to create a watch-only wallet to see your balance. "
                    "To spent from it you need {threshold} Seeds and the wallet descriptor.",
                    no_translate=self.no_translate,
                ).format(threshold=threshold, wallet_descriptor_string=wallet_descriptor_string),
                self.style_paragraph,
            )
        else:
            desc_str = Paragraph(
                translate(
                    "pdf",
                    "The wallet descriptor (QR Code) <br/><br/>{wallet_descriptor_string}<br/><br/>"
                    " allows you to create a watch-only wallet to see your balance. "
                    "To spent from it you need the secret {number} words (Seed).",
                    no_translate=self.no_translate,
                ).format(number=self.TEXT_24_WORDS, wallet_descriptor_string=wallet_descriptor_string),
                self.style_paragraph,
            )
        self.elements.append(self.create_invisible_table([[qr_image], [desc_str]], [250, 300]))

    def create_pdf(
        self,
        title: str,
        wallet_descriptor_string: str,
        address_info: list[tuple[str, str, str, str]],
        threshold: int,
        total_amount: str,
        max_tip: int,
        label_sync_nsec: str | None = None,
    ) -> None:
        """Create pdf."""
        self.elements.append(Paragraph(escape(title), style=self.style_heading))

        # Small subtitle
        self.elements.append(
            Paragraph(
                translate("pdf", "Created with", no_translate=self.no_translate)
                + f" {APP_NAME}: {white_space * 2} {APP_WEBSITE}",
                self.style_paragraph,
            )
        )
        self.elements.append(Paragraph("", self.style_paragraph))

        self._descriptor_part(wallet_descriptor_string, threshold)

        self._address_table(address_info=address_info, total_amount=total_amount)

        # max_tip
        if max_tip > 20:
            self.elements.append(
                Paragraph(
                    translate(
                        "pdf",
                        "On rescanning this wallet, scan to at least address index "
                        "{max_tip} to discover all funded addresses.",
                        no_translate=self.no_translate,
                    ).format(max_tip=max_tip),
                    self.style_paragraph,
                )
            )
        if label_sync_nsec:
            self.elements.append(
                Paragraph(
                    translate(
                        "pdf",
                        "Label syncronization backup key: {label_sync_nsec}",
                        no_translate=self.no_translate,
                    ).format(label_sync_nsec=label_sync_nsec),
                    self.style_paragraph,
                )
            )


def create_pdf_statement(
    wallet: Wallet, lang_code: str, label_sync_nsec: str | None = None, created_at: str | None = None
) -> PdfStatement:
    """Build the balance statement for a wallet."""
    info = DescriptorInfo.from_str(str(wallet.multipath_descriptor))

    addresses_and_balances: list[tuple[str, str, str, int]] = []  # category, address, label, amount
    total_amount = 0
    for address in wallet.get_addresses():
        balance = wallet.get_addr_balance(address).total
        if balance:
            total_amount += balance
            addresses_and_balances.append(
                (
                    wallet.labels.get_category(address),
                    address,
                    wallet.get_label_for_address(address),
                    balance,
                )
            )

    address_infos = [
        wallet.get_address_info_min(address) for category, address, label, balance in addresses_and_balances
    ]
    address_infos_nonempty = [address_info.index for address_info in address_infos if address_info]
    max_tip = max(address_infos_nonempty) if address_infos_nonempty else 0

    addresses_and_balances = sorted(addresses_and_balances, key=lambda row: (row[0], -row[3]))

    pdf_statement = PdfStatement(lang_code=lang_code, network=wallet.network, created_at=created_at)

    title = translate(
        "pdf",
        'Balance Statement of "{id}"',
        no_translate=pdf_statement.no_translate,
    ).format(id=wallet.id)
    pdf_statement.create_pdf(
        title=title,
        wallet_descriptor_string=str(wallet.multipath_descriptor),
        address_info=[
            (
                category,
                address,
                label,
                Satoshis(value=amount, network=wallet.network).format(
                    color_formatting="rich",
                    show_unit=False,
                    unicode_space_character=False,
                    btc_symbol=BitcoinSymbol.ISO.value,  # fixed symbol to not get unicode issues in pdfs (with asian fonts)
                ),
            )
            for category, address, label, amount in addresses_and_balances
        ],
        threshold=info.threshold,
        total_amount=Satoshis(value=total_amount, network=wallet.network).format(
            color_formatting="rich",
            show_unit=False,
            unicode_space_character=False,
            btc_symbol=BitcoinSymbol.ISO.value,  # fixed symbol to not get unicode issues in pdfs (with asian fonts)
        ),
        max_tip=max_tip,
        label_sync_nsec=label_sync_nsec,
    )

    return pdf_statement


def make_and_open_pdf_statement(wallet: Wallet, lang_code: str, label_sync_nsec: str | None = None) -> None:
    """Build and open a wallet balance statement."""
    pdf_statement = create_pdf_statement(wallet, lang_code, label_sync_nsec)
    file_title = translate(
        "pdf", "Balance Statement of {id}", no_translate=pdf_statement.no_translate
    ).format(id=wallet.id)
    write_and_open_temp_pdf(pdf_statement, file_title)

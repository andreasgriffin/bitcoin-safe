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


import io
import os
import webbrowser
from pathlib import Path
from typing import Any, List, Optional

from bitcoin_qr_tools.qr_generator import QRGenerator
from bitcoin_usb.address_types import DescriptorInfo
from PIL import Image as PilImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .gui.qt.util import qicon_to_pil, read_QIcon
from .wallet import Wallet


def pilimage_to_reportlab(pilimage: PilImage, width=200, height=200) -> Image:
    buffer = io.BytesIO()
    pilimage.save(buffer, format="PNG")
    buffer.seek(0)
    return Image(buffer, width=width, height=height)


def create_table(columns: List, col_widths: List[int]) -> Table:
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


class BitcoinWalletRecoveryPDF:
    def __init__(self) -> None:
        styles = getSampleStyleSheet()
        self.style_paragraph = ParagraphStyle(name="Centered", parent=styles["BodyText"], alignment=TA_CENTER)
        self.style_paragraph_left = ParagraphStyle(
            name="LEFT",
            parent=styles["BodyText"],
        )
        self.style_heading = ParagraphStyle(
            "centered_heading", parent=styles["Heading1"], alignment=TA_CENTER
        )
        self.elements: List[Any] = []

    def add_page_break(self) -> None:
        self.elements.append(PageBreak())  # Add a page break between documents if needed

    def _seed_part(self, seed: Optional[str], keystore_description: str, num_signers: int) -> None:
        self.elements.append(Spacer(1, 5))
        # Additional subtitle
        if num_signers == 1:
            instructions1 = Paragraph(
                f"""1. Write the secret 24 words (Mnemonic Seed) in this table<br/>
                2. Fold this  paper at the line below <br/>
                3. Put this paper in a secure location, where only you have access<br/>
                4. You can put the hardware signer either a) together with the paper seed backup, or b)   in another secure  location (if available)   
                """,
                self.style_paragraph_left,
            )
        else:
            instructions1 = Paragraph(
                f"""1. Write the secret 24 words (Mnemonic Seed) in this table<br/>
                2. Fold this  paper at the line below <br/>
                3. Put each paper in a different secure location, where only you have access<br/>
                4. You can put the hardware signers either a) together with the corresponding paper seed backup, or b)   each  in yet another secure  location (if available)   
                """,
                self.style_paragraph_left,
            )

        # No photography icon
        icon = read_QIcon("no-typing-icon.svg")
        icon2 = read_QIcon("no-photography-icon.svg")
        reportlab_icon = pilimage_to_reportlab(qicon_to_pil(icon), width=50, height=50)
        reportlab_icon2 = pilimage_to_reportlab(qicon_to_pil(icon2), width=50, height=50)

        self.elements.append(
            create_table(
                [[reportlab_icon], [instructions1], [reportlab_icon2]],
                [60, 400, 60],
            )
        )

        self.elements.append(Spacer(1, 5))

        # Table title
        table_title = (
            "Secret seed words for a hardware signer: Never type into a computer. Never make a picture."
        )
        seed_placeholder = "___________________"

        # split seed words if available
        if seed:
            seed_items = seed.split(" ")
            seed_items = seed_items + [seed_placeholder for i in range(24 - len(seed_items))]
        else:
            seed_items = [seed_placeholder for i in range(24)]

        # 24 words placeholder in three columns
        data = [[table_title, "", ""]]  # First row is the title
        for i in range(8):
            data.append([f"{i + j+1} {seed_items[i+j]}" for j in [0, 8, 16]])

        table = Table(data)

        # Table styling with border and title formatting
        table_style = TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("SPAN", (0, 0), (2, 0)),  # Merging the cells of the title row
                (
                    "BACKGROUND",
                    (0, 0),
                    (2, 0),
                    colors.grey,
                ),  # Background color for the title
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (2, 0),
                    colors.whitesmoke,
                ),  # Text color for the title
                ("FONTNAME", (0, 0), (2, 0), "Helvetica-Bold"),  # Font for the title
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),  # Vertical alignment for all cells
            ]
        )

        table.setStyle(table_style)
        table.hAlign = "CENTER"
        self.elements.append(table)

        description_text = Paragraph(
            f"{keystore_description}<br/><br/>Instructions for the heirs:",
            self.style_paragraph_left,
        )

        self.elements.append(
            create_table(
                [[reportlab_icon2], [description_text], [reportlab_icon]],
                [60, 400, 60],
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
                f"The wallet descriptor (QR Code) <br/><br/>{wallet_descriptor_string}<br/><br/> allows you to create a watch-only wallet, to see your balances, but to spent from it you need {threshold} Seeds and the wallet descriptor.",
                self.style_paragraph,
            )
        else:
            desc_str = Paragraph(
                f"The wallet descriptor (QR Code) <br/><br/>{wallet_descriptor_string}<br/><br/> allows you to create a watch-only wallet, to see your balances, but to spent from it you need the secret 24 words (Seed).",
                self.style_paragraph,
            )
        self.elements.append(create_table([[qr_image], [desc_str]], [250, 300]))

    def create_pdf(
        self,
        title: str,
        wallet_descriptor_string: str,
        keystore_description: str,
        threshold: int,
        seed: Optional[str] = None,
        num_signers: int = 1,
    ) -> None:
        self.elements.append(Paragraph(f"<font size=12><b>{title}</b></font>", self.style_heading))

        # Small subtitle
        self.elements.append(
            Paragraph(
                f"Created with Bitcoin Safe: &nbsp;&nbsp;&nbsp; https://github.com/andreasgriffin/bitcoin-safe ",
                self.style_paragraph,
            )
        )
        self.elements.append(Paragraph(f"", self.style_paragraph))

        self._seed_part(seed, keystore_description, num_signers)

        self.elements.append(Spacer(1, 10))

        # Add a horizontal line as an element
        line = Paragraph(
            "________________________________________________________________________________",
            self.style_paragraph,
        )
        line.keepWithNext = True  # Ensure line and text stay together on the same page
        self.elements.append(line)
        # Add text at the line as an element
        text = "Please fold here!&nbsp;&nbsp;&nbsp;&nbsp;Please fold here!&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Please fold here!&nbsp;&nbsp;&nbsp;&nbsp;Please fold here!&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Please fold here!"
        text_paragraph = Paragraph(text, style=getSampleStyleSheet()["Normal"])
        text_paragraph.spaceBefore = -10  # Adjust the space before the text if needed
        self.elements.append(text_paragraph)

        self._descriptor_part(wallet_descriptor_string, threshold)

    def save_pdf(self, filename: str) -> None:
        document = SimpleDocTemplate(filename, pagesize=letter)
        document.build(self.elements)

    def open_pdf(self, filename: str) -> None:
        if os.path.exists(filename):
            file_uri = Path(filename).absolute().as_uri()
            webbrowser.open_new_tab(file_uri)
        else:
            print("File not found!")


def make_and_open_pdf(wallet: Wallet) -> None:
    info = DescriptorInfo.from_str(wallet.multipath_descriptor.as_string())
    pdf_recovery = BitcoinWalletRecoveryPDF()

    for i, keystore in enumerate(wallet.keystores):
        title = (
            f'Descriptor and {i+1}. seed backup of a  ({info.threshold} of {len(wallet.keystores)}) Multi-Sig Wallet: "{wallet.id}"'
            if len(wallet.keystores) > 1
            else f"{wallet.id }"
        )
        pdf_recovery.create_pdf(
            title,
            wallet.multipath_descriptor.as_string(),
            f"Description of hardware signer {i+1}: {wallet.keystores[i].description}"
            if wallet.keystores[i].description
            else "",
            threshold=info.threshold,
            seed=keystore.mnemonic,
            num_signers=len(wallet.keystores),
        )
        pdf_recovery.add_page_break()
    temp_file = os.path.join(Path.home(), f"Descriptor and seed backup of {wallet.id}.pdf")
    pdf_recovery.save_pdf(temp_file)
    pdf_recovery.open_pdf(temp_file)


# # Example Usage
# wallet_name = "My Wallet Name"
# wallet_descriptor_qr_code = Image("../bitcoin_safe/gui/icons/qrcode.png")  # Replace with path to your QR code image
# wallet_descriptor_string = "Your wallet descriptor string here"
# wallet_description = "Your wallet description here"

# pdf_creator = BitcoinWalletRecoveryPDF(wallet_name, wallet_descriptor_qr_code, wallet_descriptor_string, wallet_description)
# pdf_creator.create_pdf()
# pdf_filename = "wallet_recovery.pdf"
# pdf_creator.save_pdf(pdf_filename)
# pdf_creator.open_pdf(pdf_filename)

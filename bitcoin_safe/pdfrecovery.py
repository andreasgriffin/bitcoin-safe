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

import atexit
import io
import logging
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import platformdirs
from bitcoin_qr_tools.qr_generator import QRGenerator
from bitcoin_usb.address_types import DescriptorInfo
from PIL.Image import Image as PilImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.i18n import translate

from .gui.qt.util import qicon_to_pil
from .util_os import xdg_open_file
from .wallet import Wallet

logger = logging.getLogger(__name__)

_TEMP_PDFS: set[Path] = set()


def _cleanup_temp_pdfs() -> None:
    for path in list(_TEMP_PDFS):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except PermissionError:
            logger.warning("Could not remove temporary PDF at %s", path)


atexit.register(_cleanup_temp_pdfs)


TEXT_24_WORDS = translate("pdf", "12 or 24")
DEFAULT_MARGIN = 36


def _safe_filename_prefix(filename: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in filename)


def write_and_open_temp_pdf(pdf: BasePDF, filename: str) -> None:
    """Write a PDF to the user cache directory and open it with the OS."""
    safe_prefix = _safe_filename_prefix(filename)
    cache_dir = Path(platformdirs.user_cache_dir("bitcoin_safe"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_file = tempfile.mkstemp(prefix=f"{safe_prefix}-", suffix=".pdf", dir=cache_dir)
    os.close(temp_fd)
    pdf.save_pdf(temp_file)
    pdf.open_pdf(temp_file)
    _TEMP_PDFS.add(Path(temp_file))


def pilimage_to_reportlab(pilimage: PilImage, width=200, height=200) -> Image:
    """Pilimage to reportlab."""
    buffer = io.BytesIO()
    pilimage.save(buffer, format="PNG")
    buffer.seek(0)
    return Image(buffer, width=width, height=height)


# Define an enum for font types
class FontType(Enum):
    CID = "cid"
    BUILTIN = "builtin"


@dataclass
class FontInfo:
    font_name: str
    font_type: FontType
    supported_lang_code: str


def register_font(lang_code: str) -> FontInfo:
    """Registers a font for the given language code and returns a FontInfo object that
    contains the font details, font type, and supported language.

    If the language is not fully supported, it falls back to 'en_US' and uses Helvetica.

    :param lang_code: The language code to register the font for (e.g., 'zh_CN', 'ru_RU').
    :return: A FontInfo object with the font details and the supported language.
    """
    # Mapping language codes to FontInfo instances
    FONT_MAP: dict[str, FontInfo] = {
        # CID Fonts
        "zh_CN": FontInfo("STSong-Light", FontType.CID, "zh_CN"),  # Simplified Chinese
        "zh_TW": FontInfo("MSung-Light", FontType.CID, "zh_TW"),  # Traditional Chinese (Taiwan)
        "zh_HK": FontInfo("MHei-Medium", FontType.CID, "zh_HK"),  # Traditional Chinese (Hong Kong)
        "ja_JP": FontInfo("HeiseiMin-W3", FontType.CID, "ja_JP"),  # Japanese
        "ko_KR": FontInfo("HYGoThic-Medium", FontType.CID, "ko_KR"),  # Korean
        # Built-in Fonts (Latin-based)
        "es_ES": FontInfo("Helvetica", FontType.BUILTIN, "es_ES"),  # Spanish
        "fr_FR": FontInfo("Helvetica", FontType.BUILTIN, "fr_FR"),  # French
        "en_US": FontInfo("Helvetica", FontType.BUILTIN, "en_US"),  # English (US)
        "en_GB": FontInfo("Helvetica", FontType.BUILTIN, "en_GB"),  # English (UK)
        "pt_PT": FontInfo("Helvetica", FontType.BUILTIN, "pt_PT"),  # Portuguese (Portugal)
        "pt_BR": FontInfo("Helvetica", FontType.BUILTIN, "pt_BR"),  # Portuguese (Brazil)
        "it_IT": FontInfo("Helvetica", FontType.BUILTIN, "it_IT"),  # Italian
        "de_DE": FontInfo("Helvetica", FontType.BUILTIN, "de_DE"),  # German
        "nl_NL": FontInfo("Helvetica", FontType.BUILTIN, "nl_NL"),  # Dutch (Netherlands)
        "nl_BE": FontInfo("Helvetica", FontType.BUILTIN, "nl_BE"),  # Dutch (Belgium)
        "sv_SE": FontInfo("Helvetica", FontType.BUILTIN, "sv_SE"),  # Swedish
        "da_DK": FontInfo("Helvetica", FontType.BUILTIN, "da_DK"),  # Danish
        "no_NO": FontInfo("Helvetica", FontType.BUILTIN, "no_NO"),  # Norwegian
        "fi_FI": FontInfo("Helvetica", FontType.BUILTIN, "fi_FI"),  # Finnish
        "is_IS": FontInfo("Helvetica", FontType.BUILTIN, "is_IS"),  # Icelandic
        "pl_PL": FontInfo("Helvetica", FontType.BUILTIN, "pl_PL"),  # Polish
        "cs_CZ": FontInfo("Helvetica", FontType.BUILTIN, "cs_CZ"),  # Czech
        "sk_SK": FontInfo("Helvetica", FontType.BUILTIN, "sk_SK"),  # Slovak
        "sl_SI": FontInfo("Helvetica", FontType.BUILTIN, "sl_SI"),  # Slovenian
        "hu_HU": FontInfo("Helvetica", FontType.BUILTIN, "hu_HU"),  # Hungarian
        "ro_RO": FontInfo("Helvetica", FontType.BUILTIN, "ro_RO"),  # Romanian
        "hr_HR": FontInfo("Helvetica", FontType.BUILTIN, "hr_HR"),  # Croatian
        "sr_RS": FontInfo("Helvetica", FontType.BUILTIN, "sr_RS"),  # Serbian (Latin)
        "bs_BA": FontInfo("Helvetica", FontType.BUILTIN, "bs_BA"),  # Bosnian
        "mk_MK": FontInfo("Helvetica", FontType.BUILTIN, "mk_MK"),  # Macedonian (Latin)
        "mt_MT": FontInfo("Helvetica", FontType.BUILTIN, "mt_MT"),  # Maltese
        "gl_ES": FontInfo("Helvetica", FontType.BUILTIN, "gl_ES"),  # Galician
        "ca_ES": FontInfo("Helvetica", FontType.BUILTIN, "ca_ES"),  # Catalan
        "eu_ES": FontInfo("Helvetica", FontType.BUILTIN, "eu_ES"),  # Basque
        "lv_LV": FontInfo("Helvetica", FontType.BUILTIN, "lv_LV"),  # Latvian
        "lt_LT": FontInfo("Helvetica", FontType.BUILTIN, "lt_LT"),  # Lithuanian
        "et_EE": FontInfo("Helvetica", FontType.BUILTIN, "et_EE"),  # Estonian
        "af_ZA": FontInfo("Helvetica", FontType.BUILTIN, "af_ZA"),  # Afrikaans
        "vi_VN": FontInfo("Helvetica", FontType.BUILTIN, "vi_VN"),  # Vietnamese (Latin-based characters)
        "ms_MY": FontInfo("Helvetica", FontType.BUILTIN, "ms_MY"),  # Malay
        "id_ID": FontInfo("Helvetica", FontType.BUILTIN, "id_ID"),  # Indonesian
    }

    if lang_code in FONT_MAP:
        font_info: FontInfo = FONT_MAP[lang_code]

        if font_info.font_type == FontType.CID:
            # Register the CID font
            pdfmetrics.registerFont(UnicodeCIDFont(font_info.font_name))
            print(f"Using built-in CID font: {font_info.font_name} for language code: {lang_code}")
        elif font_info.font_type == FontType.BUILTIN:
            # No registration needed for built-in fonts like Helvetica
            print(f"Using built-in font: {font_info.font_name} for language code: {lang_code}")

        return font_info

    else:
        print(f"No font found for language code: {lang_code}, returning en_US")
        return FontInfo("Helvetica", FontType.BUILTIN, "en_US")  # Default fallback to en_US


white_space = '<font color="white"> - </font>'


class BasePDF:
    def __init__(self, lang_code: str) -> None:
        """Initialize instance."""
        font_info = register_font(lang_code=lang_code)
        self.font_name = font_info.font_name
        self.no_translate = font_info.supported_lang_code == "en_US"

        self.styles = getSampleStyleSheet()
        self.style_paragraph = ParagraphStyle(
            name="Centered",
            fontName=self.font_name,
            parent=self.styles["BodyText"],
            alignment=TA_CENTER,
        )
        self.style_paragraph_left = ParagraphStyle(
            name="LEFT",
            fontName=self.font_name,
            parent=self.styles["BodyText"],
            alignment=TA_LEFT,
        )
        self.style_paragraph_right = ParagraphStyle(
            name="LEFT",
            fontName=self.font_name,
            parent=self.styles["BodyText"],
            alignment=TA_RIGHT,
        )
        self.style_heading = ParagraphStyle(
            "centered_heading",
            fontName=self.font_name,
            parent=self.styles["Heading1"],
            alignment=TA_CENTER,
        )
        self.style_text = ParagraphStyle(
            name="normal",
            fontName=self.font_name,
        )
        self.elements: list[Any] = []

    def save_pdf(self, filename: str) -> None:
        # Adjust these values to set your desired margins (values are in points; 72 points = 1 inch)
        """Save pdf."""
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
        """Open pdf."""
        if os.path.exists(filename):
            xdg_open_file(Path(filename))
        else:
            logger.info(translate("pdf", "File not found!"))


class DataExportPDF(BasePDF):
    def create_pdf(
        self,
        title: str,
        txid: str | None,
        serialized: str,
        data_label: str,
        qr_images: list[PilImage],
        ur_qr_images: list[PilImage] | None = None,
    ) -> None:
        """Create a PDF that captures serialized data and its QR codes."""

        self.elements.append(Paragraph(title, style=self.style_heading))
        self.elements.append(
            Paragraph(
                translate("pdf", "Created with", no_translate=self.no_translate)
                + f" Bitcoin Safe: {white_space * 5} www.bitcoin-safe.org",
                self.style_paragraph,
            )
        )
        self.elements.append(Spacer(1, 12))

        if txid:
            self.elements.append(
                Paragraph(
                    translate("pdf", "Transaction ID: {txid}", no_translate=self.no_translate).format(
                        txid=txid
                    ),
                    self.style_paragraph_left,
                )
            )
            self.elements.append(Spacer(1, 6))

        self.elements.append(
            Paragraph(
                translate("pdf", "Serialized {label}:", no_translate=self.no_translate).format(
                    label=data_label
                ),
                self.style_paragraph_left,
            )
        )
        self.elements.append(Paragraph(serialized, self.style_paragraph_left))
        self.elements.append(Spacer(1, 12))

        def _append_qr_section(title: str, images: list[PilImage]):
            if not images:
                return

            self.elements.append(Paragraph(title, self.style_paragraph))
            for idx, image in enumerate(images):
                self.elements.append(
                    Paragraph(
                        translate(
                            "pdf",
                            "{title}: Fragment {index} of {total}",
                            no_translate=self.no_translate,
                        ).format(index=idx + 1, total=len(images), title=title),
                        self.style_paragraph,
                    )
                )
                self.elements.append(pilimage_to_reportlab(image, width=200, height=200))
                self.elements.append(Spacer(1, 6))

        _append_qr_section(translate("pdf", "BBQr QR", no_translate=self.no_translate), qr_images)
        _append_qr_section(translate("pdf", "UR QR", no_translate=self.no_translate), ur_qr_images or [])

        if not qr_images and not ur_qr_images:
            self.elements.append(
                Paragraph(
                    translate("pdf", "No QR data available", no_translate=self.no_translate),
                    self.style_paragraph_left,
                )
            )


class BitcoinWalletRecoveryPDF(BasePDF):
    @property
    def TEXT_24_WORDS(self):
        """TEXT 24 WORDS."""
        return translate("pdf", "12 or 24", no_translate=self.no_translate)

    @staticmethod
    def create_table(columns: list[Any], col_widths: list[int]) -> Table:
        # Validate input and create data for the table
        """Create table."""
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

    def _seed_part(
        self,
        seed: str | None,
        keystore_description: str,
        keystore_fingerprint: str,
        keystore_label: str,
        num_signers: int,
    ) -> None:
        """Seed part."""
        self.elements.append(Spacer(1, 5))
        # Additional subtitle
        if num_signers == 1:
            instructions1 = Paragraph(
                translate(
                    "pdf",
                    """1. Attach the 'Recovery sheet' ({number} words) to this paper or duplicate the 12/24 words onto this paper.<br/>
                2. Fold this  paper at the line below <br/>
                3. Put this paper in a secure location, where only you have access<br/>
                4. You can put the hardware signer either a) together with the paper seed backup, or b)   in another secure  location (if available)   
                """,  # noqa: E501
                    no_translate=self.no_translate,
                ).format(number=self.TEXT_24_WORDS),
                self.style_paragraph_left,
            )
        else:
            instructions1 = Paragraph(
                translate(
                    "pdf",
                    """1. Attach the 'Recovery sheet' ({number} words) to this paper or duplicate the 12/24 words onto this paper.<br/>
                2. Fold this  paper at the line below <br/>
                3. Put each paper in a different secure location, where only you have access<br/>
                4. You can put the hardware signers either a) together with the corresponding paper seed backup, or b)   each  in yet another secure  location (if available)   
                """,  # noqa: E501
                    no_translate=self.no_translate,
                ).format(number=self.TEXT_24_WORDS),
                self.style_paragraph_left,
            )

        # No photography icon
        icon = svg_tools.get_QIcon("no-typing-icon.svg")
        icon2 = svg_tools.get_QIcon("no-photography-icon.svg")
        reportlab_icon = pilimage_to_reportlab(qicon_to_pil(icon), width=50, height=50)
        reportlab_icon2 = pilimage_to_reportlab(qicon_to_pil(icon2), width=50, height=50)

        self.elements.append(
            self.create_table(
                [[reportlab_icon], [instructions1], [reportlab_icon2]],
                [60, 400, 60],
            )
        )

        self.elements.append(Spacer(1, 5))

        # Table title
        table_title = translate(
            "pdf",
            "Secret seed words for a hardware signer: Never type into a computer. Never make a picture.",
            no_translate=self.no_translate,
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
            data.append([f"{i + j + 1} {seed_items[i + j]}" for j in [0, 8, 16]])

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
                ("FONTNAME", (0, 0), (2, 0), self.font_name),  # Font for the title
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),  # Vertical alignment for all cells
                ("LINEBELOW", (0, -1), (-1, -1), 1, colors.black),  # Add the closing horizontal line below
            ],
            fontName=self.font_name,
        )

        table.setStyle(table_style)
        table.hAlign = "CENTER"
        self.elements.append(table)
        self.elements.append(Spacer(1, 1))

        description_text = Paragraph(
            translate(
                "pdf",
                "{keystore_label} ({keystore_fingerprint}): {keystore_description}<br/><br/>"
                "Instructions for the heirs:",
                no_translate=self.no_translate,
            ).format(
                keystore_description=keystore_description.replace("\n", "<br/>"),
                keystore_fingerprint=keystore_fingerprint,
                keystore_label=keystore_label,
            ),
            self.style_paragraph_left,
        )

        self.elements.append(
            self.create_table(
                [[reportlab_icon2], [description_text], [reportlab_icon]],
                [60, 400, 60],
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
                    "The wallet descriptor (QR Code) <br/><br/>{wallet_descriptor_string}<br/><br/> "
                    "allows you to create a watch-only wallet to see your balance. "
                    "To spent from it you need {threshold} Seeds and the wallet descriptor.",
                    no_translate=self.no_translate,
                ).format(threshold=threshold, wallet_descriptor_string=wallet_descriptor_string),
                self.style_paragraph,
            )
        else:
            desc_str = Paragraph(
                translate(
                    "pdf",
                    "The wallet descriptor (QR Code) <br/><br/>{wallet_descriptor_string}<br/><br/> allows "
                    "you to create a watch-only wallet to see your balance. "
                    "To spent from it you need the secret {number} words (Seed).",
                    no_translate=self.no_translate,
                ).format(number=self.TEXT_24_WORDS, wallet_descriptor_string=wallet_descriptor_string),
                self.style_paragraph,
            )
        self.elements.append(self.create_table([[qr_image], [desc_str]], [250, 300]))

    def create_pdf(
        self,
        title: str,
        wallet_descriptor_string: str,
        keystore_description: str,
        keystore_label: str,
        keystore_xpub: str,
        keystore_key_origin: str,
        keystore_fingerprint: str,
        threshold: int,
        seed: str | None = None,
        num_signers: int = 1,
    ) -> None:
        """Create pdf."""
        self.elements.append(Paragraph(title, style=self.style_heading))

        # Small subtitle
        self.elements.append(
            Paragraph(
                translate("pdf", "Created with", no_translate=self.no_translate)
                + f" Bitcoin Safe: {white_space * 5} www.bitcoin-safe.org",
                self.style_paragraph,
            )
        )
        self.elements.append(Paragraph("", self.style_paragraph))

        self._seed_part(
            seed,
            num_signers=num_signers,
            keystore_label=keystore_label,
            keystore_fingerprint=keystore_fingerprint,
            keystore_description=keystore_description,
        )

        self.elements.append(Spacer(1, 15))

        # Add a horizontal line as an element
        line = Paragraph(
            "________________________________________________________________________________",
            self.style_paragraph,
        )
        # line.keepWithNext = True  # Ensure line and text stay together on the same page
        self.elements.append(line)
        # Add text at the line as an element
        text = (white_space * 5).join(
            [translate("pdf", "Please fold here!", no_translate=self.no_translate)] * 5
        )
        text_paragraph = Paragraph(text, style=self.style_text)
        # text_paragraph.spaceBefore = -10  # Adjust the space before the text if needed
        self.elements.append(text_paragraph)

        self._descriptor_part(wallet_descriptor_string, threshold)

        keystore_info_text = Paragraph(
            translate(
                "pdf",
                "{keystore_label}: Fingerprint: {keystore_fingerprint}, "
                "Key origin: {keystore_key_origin}, {keystore_xpub}",
                no_translate=self.no_translate,
            ).format(
                keystore_label=keystore_label,
                keystore_fingerprint=keystore_fingerprint,
                keystore_key_origin=keystore_key_origin,
                keystore_xpub=keystore_xpub,
            ),
            self.style_paragraph_left,
        )
        self.elements.append(keystore_info_text)


def make_and_open_pdf(wallet: Wallet, lang_code: str) -> None:
    """Make and open pdf."""
    info = DescriptorInfo.from_str(str(wallet.multipath_descriptor))
    pdf_recovery = BitcoinWalletRecoveryPDF(lang_code=lang_code)

    for i, keystore in enumerate(wallet.keystores):
        title = (
            translate(
                "pdf",
                '{i}. Seed backup of a {threshold} of {m} Multi-Sig Wallet: "{id}"',
                no_translate=pdf_recovery.no_translate,
            ).format(i=i + 1, threshold=info.threshold, m=len(wallet.keystores), id=wallet.id)
            if len(wallet.keystores) > 1
            else f"{wallet.id}"
        )
        pdf_recovery.create_pdf(
            title=title,
            wallet_descriptor_string=str(wallet.multipath_descriptor),
            threshold=info.threshold,
            seed=keystore.mnemonic,
            num_signers=len(wallet.keystores),
            keystore_xpub=keystore.xpub,
            keystore_description=keystore.description,
            keystore_fingerprint=keystore.fingerprint,
            keystore_key_origin=keystore.key_origin,
            keystore_label=keystore.label,
        )
        pdf_recovery.add_page_break()
    filename = translate("pdf", "Seed backup of {id}").format(id=wallet.id)
    write_and_open_temp_pdf(pdf_recovery, filename)

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

from collections.abc import Iterator
from pathlib import Path

import bdkpython as bdk
import cv2
import pytest
from PIL import Image
from PyQt6.QtCore import QLocale, QSize, QTranslator
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.config import UserConfig
from bitcoin_safe.pdf_labels import PDFLabels
from bitcoin_safe.pdf_statement import create_pdf_statement
from bitcoin_safe.pdfrecovery import BitcoinWalletRecoveryPDF, DataExportPDF, QRGenerator
from bitcoin_safe.pythonbdk_types import Recipient
from tests.non_gui.test_inheritance_overview import wallet
from tests.pdf_glyphs import missing_glyphs

LOCALES_PATH = UserConfig.locales_path
LANGUAGES = sorted({"en_US", *(path.stem.removeprefix("app_") for path in LOCALES_PATH.glob("app_*.qm"))})


@pytest.fixture(params=LANGUAGES)
def language(qapp: QApplication, request: pytest.FixtureRequest) -> Iterator[str]:
    code: str = request.param
    translator = QTranslator()
    if code != "en_US":
        assert translator.load(str(LOCALES_PATH / f"app_{code}.qm")), code
        qapp.installTranslator(translator)
    previous_locale = QLocale()
    QLocale.setDefault(QLocale(code))
    try:
        yield code
    finally:
        QLocale.setDefault(previous_locale)
        qapp.removeTranslator(translator)


def export_text(path: Path) -> str:
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_
    return "\n".join(document.getAllText(page).text() for page in range(document.pageCount()))


@pytest.mark.marker_qt_1
@pytest.mark.parametrize("kind", ["transaction", "statement", "recovery", "labels"])
def test_pdf_exports_preserve_content_and_glyphs(tmp_path: Path, language: str, kind: str) -> None:
    sample = wallet("Savings", ["AABBCCDD"])
    if kind == "transaction":
        pdf = DataExportPDF(language)
        pdf.create_pdf(
            title="Transaction export",
            txid="abcdef123456",
            serialized="0123456789abcdef" * 5,
            data_label="Transaction",
            qr_images=[Image.new("RGB", (40, 40), "white")],
            recipients=[Recipient("bc1qexample", 12345, "Gift & savings <family>")],
            network=bdk.Network.BITCOIN,
            tx_label="Payment <test>",
            fee_amount=100,
        )
        expected = ["abcdef123456", "0123456789abcdef" * 5, "Gift & savings <family>", "Payment <test>"]
    elif kind == "statement":
        pdf = create_pdf_statement(sample, language)
        expected = [str(sample.multipath_descriptor), "0.00125000", "Gift & savings <family>"]
    elif kind == "recovery":
        pdf = BitcoinWalletRecoveryPDF(language)
        pdf.create_pdf(
            title="Recovery sheet",
            wallet_descriptor_string=str(sample.multipath_descriptor),
            keystore_description="Stored <safely>",
            keystore_label="Signer A",
            keystore_xpub="xpub1234",
            keystore_key_origin="m/84h/1h/0h",
            keystore_fingerprint="AABBCCDD",
            threshold=1,
            seed=" ".join(f"word{number:02}" for number in range(1, 25)),
        )
        expected = [str(sample.multipath_descriptor), "word01", "word12", "word24", "Stored <safely>"]
    else:
        pdf = PDFLabels(language)
        pdf.add_labels("Savings", [("Alpha <one>", "Device"), ("Bravo & two", "Device")])
        expected = ["Alpha <one>", "Bravo & two"]
    output = tmp_path / f"{kind}-{language}.pdf"
    pdf.save_pdf(str(output))
    errors = missing_glyphs(output)
    assert not errors, f"Missing glyphs in {kind} ({language}):\n" + "\n".join(errors)
    compact_text = "".join(export_text(output).split())
    for value in expected:
        assert "".join(value.split()) in compact_text, f"Missing {value!r} in {kind} ({language})"


@pytest.mark.marker_qt_1
def test_signer_labels_keep_print_dimensions(qapp: QApplication, tmp_path: Path) -> None:
    pdf = PDFLabels("en_US")
    long_label = "Signer location " * 8
    pdf.add_labels("Savings", [("Alpha", "Device"), (long_label, "Device")])
    output = tmp_path / "labels.pdf"
    pdf.save_pdf(str(output))
    document = QPdfDocument(None)
    assert document.load(str(output)) == QPdfDocument.Error.None_
    assert "".join(long_label.split()) in "".join(document.getAllText(0).text().split())
    image_path = tmp_path / "labels.png"
    assert document.render(0, QSize(1224, 1584)).save(str(image_path))  # Letter at 144 DPI
    image = Image.open(image_path).convert("RGBA")
    background = Image.new("RGBA", image.size, "white")
    background.alpha_composite(image)
    pixels = background.convert("RGB")
    # The label borders cross the middle of the page without interruption.
    horizontal = [
        y for y in range(pixels.height) if all(max(pixels.getpixel((x, y))) < 230 for x in range(490, 735))
    ]
    lines = [y for y in horizontal if y - 1 not in horizontal]
    assert len(lines) == 3
    assert all(abs((bottom - top) - 144 / 2.54) < 4 for top, bottom in zip(lines, lines[1:], strict=False))
    border = [x for x in range(pixels.width) if max(pixels.getpixel((x, lines[0]))) < 230]
    assert abs((max(border) - min(border)) - 5 * 144 / 2.54) < 5


@pytest.mark.marker_qt_1
def test_transaction_pdf_qr_is_scannable(qapp: QApplication, tmp_path: Path) -> None:
    value = "0123456789abcdef" * 8
    pdf = DataExportPDF("en_US")
    pdf.create_pdf(
        "Transaction export", value[:64], value, "Transaction", [QRGenerator.create_qr_PILimage(value)]
    )
    output = tmp_path / "transaction.pdf"
    pdf.save_pdf(str(output))
    document = QPdfDocument(None)
    assert document.load(str(output)) == QPdfDocument.Error.None_
    detector = cv2.QRCodeDetector()
    decoded = []
    for page in range(document.pageCount()):
        image_path = tmp_path / f"page-{page}.png"
        assert document.render(page, QSize(1224, 1584)).save(str(image_path))
        decoded.append(detector.detectAndDecode(cv2.imread(str(image_path)))[0])
    assert value in decoded


@pytest.mark.marker_qt_1
@pytest.mark.parametrize("language", ["ar_AE", "fa_IR"])
@pytest.mark.parametrize("label", ["Payment <test>", "0123456789abcdef", "100% <savings> & fees"])
def test_rtl_transaction_label_keeps_exact_text(
    qapp: QApplication, tmp_path: Path, language: str, label: str
) -> None:
    translator = QTranslator()
    assert translator.load(str(LOCALES_PATH / f"app_{language}.qm"))
    qapp.installTranslator(translator)
    try:
        pdf = DataExportPDF(language)
        pdf.create_pdf("Transaction", None, "abcdef", "Transaction", [], tx_label=label)
        output = tmp_path / "label.pdf"
        pdf.save_pdf(str(output))
        text = export_text(output)
        assert label in text
        assert not set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069").intersection(text)
    finally:
        qapp.removeTranslator(translator)

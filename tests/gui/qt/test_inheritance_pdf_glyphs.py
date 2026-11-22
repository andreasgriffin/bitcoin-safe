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

from pathlib import Path

import pytest
from pypdf import PdfReader
from PyQt6.QtCore import QLocale, QTranslator
from PyQt6.QtGui import QColor, QTransform
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QApplication
from reportlab.pdfgen.canvas import Canvas

from bitcoin_safe.config import UserConfig
from bitcoin_safe.inheritance_overview import InheritanceOverviewPDF
from bitcoin_safe.pdf.qt_overlay import TextRun, render_text_overlay
from tests.non_gui.test_inheritance_overview import wallet
from tests.pdf_glyphs import missing_glyphs

LOCALES_PATH = UserConfig.locales_path
LANGUAGES = sorted({"en_US", *(path.stem.removeprefix("app_") for path in LOCALES_PATH.glob("app_*.qm"))})


def test_missing_glyph_check_detects_reportlab_substitution(tmp_path: Path) -> None:
    path = tmp_path / "missing-glyph.pdf"
    canvas = Canvas(str(path))
    canvas.setFont("Helvetica", 12)
    canvas.drawString(50, 750, "Missing: 漢")
    canvas.save()
    assert missing_glyphs(path), "The PDF glyph check missed a known unsupported character"


@pytest.mark.marker_qt_1
def test_missing_glyph_check_detects_qt_notdef(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "qt-missing-glyph.pdf"
    run = TextRun("Missing: \U0010ffff", 40, 100, 12, QColor("black"), QTransform(1, 0, 0, 1, 0, 200), "left")
    render_text_overlay(path, [[run]], (300, 200), "en_US")
    assert any(".notdef" in error for error in missing_glyphs(path))


@pytest.mark.marker_qt_1
@pytest.mark.parametrize("language", LANGUAGES)
def test_inheritance_pdf_has_no_missing_glyphs(qapp: QApplication, tmp_path: Path, language: str) -> None:
    translator = QTranslator()
    if language != "en_US":
        assert translator.load(str(LOCALES_PATH / f"app_{language}.qm")), language
        qapp.installTranslator(translator)
    previous_locale = QLocale()
    QLocale.setDefault(QLocale(language))
    try:
        wallets = [wallet("Savings", ["AABBCCDD", "11223344"]), wallet("Family", ["AABBCCDD"])]
        wallets[0].keystores[0].description = "Home safe"
        output = tmp_path / f"inheritance-{language}.pdf"
        InheritanceOverviewPDF(wallets, language).save_pdf(str(output))
        errors = missing_glyphs(output)
        assert not errors, f"Missing glyphs in {language}:\n" + "\n".join(errors)
    finally:
        QLocale.setDefault(previous_locale)
        qapp.removeTranslator(translator)


@pytest.mark.marker_qt_1
@pytest.mark.parametrize("language", ["en_US", "ar_AE"])
def test_inheritance_statement_preserves_descriptor_and_amount(
    qapp: QApplication, tmp_path: Path, language: str
) -> None:
    translator = QTranslator()
    if language != "en_US":
        assert translator.load(str(LOCALES_PATH / f"app_{language}.qm"))
        qapp.installTranslator(translator)
    try:
        sample = wallet("Savings", ["AABBCCDD"])
        output = tmp_path / "overview.pdf"
        InheritanceOverviewPDF([sample], language).save_pdf(str(output))
        document = QPdfDocument(None)
        assert document.load(str(output)) == QPdfDocument.Error.None_
        statement_text = document.getAllText(document.pageCount() - 1).text()
        compact_text = "".join(statement_text.split())
        assert str(sample.multipath_descriptor) in compact_text
        assert "0.00125000" in compact_text
        assert "Gift & savings <family>" in statement_text
    finally:
        qapp.removeTranslator(translator)


@pytest.mark.marker_qt_1
def test_inheritance_overview_retains_translated_text_links_and_page_numbers(
    qapp: QApplication, tmp_path: Path
) -> None:
    class ArabicTranslator(QTranslator):
        def translate(
            self, context: str | None, sourceText: str | None, disambiguation: str | None = None, n: int = -1
        ) -> str:
            if context == "pdf" and sourceText == "HOW TO RECOVER A WALLET":
                return "مفتاح سري"
            return sourceText or ""

    translator = ArabicTranslator()
    qapp.installTranslator(translator)
    try:
        output = tmp_path / "overview.pdf"
        InheritanceOverviewPDF([wallet("Savings", ["AABBCCDD"])], "ar_AE").save_pdf(str(output))
        document = QPdfDocument(None)
        assert document.load(str(output)) == QPdfDocument.Error.None_
        assert document.pageCount() == 3
        pages = [document.getAllText(index).text() for index in range(document.pageCount())]
        assert "مفتاح سري" in pages[0], repr(pages[0])
        assert all(f"Page {index + 1}" in text for index, text in enumerate(pages))
        reader = PdfReader(output)
        links = reader.pages[0]["/Annots"]
        assert any("bitcoin.org/en/choose-your-wallet" in str(link.get_object()) for link in links)
    finally:
        qapp.removeTranslator(translator)


@pytest.mark.marker_qt_1
def test_inheritance_overview_paginates_graph_and_signer_notes(qapp: QApplication, tmp_path: Path) -> None:
    sample = wallet("Savings", [f"{index:08x}" for index in range(1, 9)])
    sample.keystores[0].description = "Recovery note " * 160
    output = tmp_path / "multipage.pdf"
    InheritanceOverviewPDF([sample], "en_US").save_pdf(str(output))
    document = QPdfDocument(None)
    assert document.load(str(output)) == QPdfDocument.Error.None_
    assert document.pageCount() >= 5
    pages = [document.getAllText(index).text() for index in range(document.pageCount())]
    compact_pages = ["".join(text.split()) for text in pages]
    assert any("Signernotescontinued" in text for text in compact_pages)
    assert any("seepage" in text for text in compact_pages)
    assert all(f"Page{index + 1}" in text for index, text in enumerate(compact_pages))

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

"""Smoke tests for bundled-font, Qt-based, multilingual PDF output."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, Spacer, Table

from bitcoin_safe.pdf.font_manager import FONT_ARCHIVE, FONT_FILES, PDFFontManager
from bitcoin_safe.pdf.qt_renderer import QtPDFRenderer


@pytest.mark.parametrize(
    ("locale", "sample"),
    [
        ("en_US", "English text and éłőš"),
        ("ar_AE", "تصدير المعاملة إلى ملف PDF"),
        ("fa_IR", "گزارش تراکنش بیت کوین"),
        ("he_IL", "דו״ח עסקה בעברית"),
        ("hi_IN", "बिटकॉइन लेनदेन विवरण"),
        ("bn_BD", "বিটকয়েন লেনদেন"),
        ("ta_IN", "பிட்காயின் பரிவர்த்தனை"),
        ("th_TH", "ธุรกรรมบิตคอยน์"),
        ("zh_CN", "比特币交易报告"),
        ("ja_JP", "ビットコイン取引"),
        ("ko_KR", "비트코인 거래"),
    ],
)
def test_multilingual_pdf_is_generated(qapp: object, tmp_path: Path, locale: str, sample: str) -> None:
    font = PDFFontManager.family(locale)
    assert font
    stylesheet = getSampleStyleSheet()
    content = [
        Paragraph(sample, stylesheet["Normal"]),
        Paragraph("bc1q" + "a" * 50, stylesheet["Normal"]),
        Table([["Address", "Label"], ["bc1q" + "a" * 50, sample]], colWidths=[280, 220]),
        Spacer(1, 30),
    ]
    output = tmp_path / (locale + ".pdf")
    QtPDFRenderer(locale, footer="transaction").save(content, str(output))
    assert output.read_bytes()[:5] == b"%PDF-"
    assert output.stat().st_size > 3000
    if tool := shutil.which("pdffonts"):
        result = subprocess.run([tool, str(output)], check=True, capture_output=True, text=True)
        assert "yes" in result.stdout.lower(), result.stdout


def test_font_bundle_contains_every_expected_file() -> None:
    import tarfile

    with tarfile.open(FONT_ARCHIVE, "r:xz") as archive:
        assert set(archive.getnames()) == set(FONT_FILES)
        assert all(member.isfile() for member in archive.getmembers())


FORBIDDEN_BIDI_CONTROLS = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


@pytest.mark.parametrize(
    "locale,prefix,suffix",
    [
        ("en_US", "Address ", " end"),
        ("ar_AE", "عنوان ", " نهاية"),
        ("he_IL", "כתובת ", " סוף"),
        ("fa_IR", "نشانی ", " پایان"),
        ("ar_AE", "Mixed عنوان ", " نهاية end"),
    ],
)
@pytest.mark.parametrize("in_table", [False, True])
def test_protocol_data_survives_pdf_extraction(
    qapp: object, tmp_path: Path, locale: str, prefix: str, suffix: str, in_table: bool
) -> None:
    from xml.sax.saxutils import escape

    from pypdf import PdfReader

    values = [
        "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        "ad3f46e852baf14e216ae0d24cf2b12c9e1dfd54a6925931d5d2e4328cb01b34",
        "wpkh([5aa39a43/84'/1'/0']tpubDD2ww8jti4Xc8vkaJH2yC1r7C9TVb9bG3kTi6BFm5w3aAZmtFHktK6Mv2wfyBvSPqV9QeH1QXrmHzabuNh1sgRtAsUoG7dzVjc9WvGm78PD/<0;1>/*)#xaf9qzlf",
    ]
    style = getSampleStyleSheet()["Normal"].clone("small")
    style.fontSize = 4
    paragraphs = [Paragraph(escape(prefix + value + suffix), style) for value in values]
    content = [Table([[paragraph] for paragraph in paragraphs], colWidths=[520])] if in_table else paragraphs
    output = tmp_path / "protocol.pdf"
    QtPDFRenderer(locale).save(content, str(output))
    extracted = "\n".join(page.extract_text() for page in PdfReader(output).pages)
    assert not FORBIDDEN_BIDI_CONTROLS.intersection(extracted)
    for value in values:
        assert value in extracted


def test_long_table_text_uses_qt_pagination(qapp: object, tmp_path: Path) -> None:
    stylesheet = getSampleStyleSheet()
    long_label = "الدفعة الكبيرة " * 400
    table = Table(
        [[Paragraph("Address", stylesheet["Normal"]), Paragraph("Label", stylesheet["Normal"])]]
        + [
            [Paragraph(str(i), stylesheet["Normal"]), Paragraph(long_label, stylesheet["Normal"])]
            for i in range(4)
        ],
        colWidths=[100, 400],
    )
    output = tmp_path / "long-table.pdf"
    QtPDFRenderer("ar_AE", footer="statement").save([table], str(output))
    assert output.read_bytes()[:5] == b"%PDF-"
    if tool := shutil.which("pdfinfo"):
        result = subprocess.run([tool, str(output)], check=True, capture_output=True, text=True)
        pages = int(
            next(
                line.split(":", 1)[1].strip()
                for line in result.stdout.splitlines()
                if line.startswith("Pages:")
            )
        )
        assert pages > 1


@pytest.mark.xfail(strict=True, reason="Qt bidi layout splits a leading digit from mixed RTL protocol data")
def test_digit_leading_transaction_id_in_rtl_text(qapp: object, tmp_path: Path) -> None:
    from pypdf import PdfReader

    txid = "4d3f46e852baf14e216ae0d24cf2b12c9e1dfd54a6925931d5d2e4328cb01b34"
    paragraph = Paragraph(f"عنوان {txid} نهاية", getSampleStyleSheet()["Normal"])
    output = tmp_path / "rtl-txid.pdf"
    QtPDFRenderer("ar_AE").save([paragraph], str(output))
    assert txid in PdfReader(output).pages[0].extract_text()


def test_renderer_without_gui_application_fails_clearly(tmp_path: Path) -> None:
    import os
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from bitcoin_safe.pdf.qt_renderer import QtPDFRenderer; "
            f"QtPDFRenderer('en_US').save([], {str(tmp_path / 'no-application.pdf')!r})",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode != 0
    assert "Qt PDF rendering requires a QGuiApplication" in result.stderr


@pytest.mark.parametrize(
    ("locale", "region"),
    [("zh_CN", "SC"), ("zh_TW", "TC"), ("zh_HK", "HK"), ("ja_JP", "JP"), ("ko_KR", "KR")],
)
def test_regional_cjk_font_is_used(qapp: object, locale: str, region: str) -> None:
    from PyQt6.QtGui import QTextLayout

    layout = QTextLayout("骨漢字", PDFFontManager.font(locale))
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(500)
    layout.endLayout()
    assert {run.rawFont().familyName() for run in layout.glyphRuns()} == {f"Noto Sans CJK {region}"}


@pytest.mark.parametrize("corrupt", [False, True])
def test_font_bundle_errors_are_clear(qapp: object, tmp_path: Path, corrupt: bool) -> None:
    from unittest.mock import patch

    bundle = tmp_path / "fonts.tar.xz"
    if corrupt:
        bundle.write_bytes(b"not a font bundle")
    with (
        patch("bitcoin_safe.pdf.font_manager.FONT_ARCHIVE", bundle),
        patch.object(PDFFontManager, "_families", {}),
        pytest.raises(RuntimeError, match="Unable to read bundled PDF fonts"),
    ):
        PDFFontManager.ensure_loaded()

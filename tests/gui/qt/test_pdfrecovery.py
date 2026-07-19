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

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication
from reportlab.platypus import Paragraph, Table

from bitcoin_safe.hardware_signers import HardwareSigners
from bitcoin_safe.pdfrecovery import BitcoinWalletRecoveryPDF


def _create_pdf_with_footer(
    hardware_signer=HardwareSigners.bitbox02,
    keystore_xpub: str = "xpub6CUGRU..." * 4,
) -> BitcoinWalletRecoveryPDF:
    pdf = BitcoinWalletRecoveryPDF(lang_code="en_US")
    pdf.create_pdf(
        title="Title",
        wallet_descriptor_string="wsh(sortedmulti(2,[abcd1234/48h/1h/0h/2h]xpub...))",
        keystore_description="Test signer",
        keystore_label="BitBox02",
        keystore_xpub=keystore_xpub,
        keystore_key_origin="m/48h/1h/0h/2h",
        keystore_fingerprint="A1B2C3D4",
        threshold=2,
        hardware_signer=hardware_signer,
    )
    return pdf


@pytest.mark.marker_qt_1
def test_create_pdf_footer_includes_hardware_signer_icon(qapp: QApplication) -> None:
    del qapp
    pdf = _create_pdf_with_footer()

    footer = pdf.elements[-1]
    assert isinstance(footer, Table)
    assert footer._ncols == 2
    assert footer._cellvalues[0][0].__class__.__name__ == "Image"
    assert isinstance(footer._cellvalues[0][1], Paragraph)
    assert "BitBox02" in footer._cellvalues[0][1].text


@pytest.mark.marker_qt_1
def test_create_pdf_footer_falls_back_to_text_for_generic_signer(qapp: QApplication) -> None:
    del qapp
    pdf = _create_pdf_with_footer(hardware_signer=None)

    footer = pdf.elements[-1]
    assert isinstance(footer, Paragraph)
    assert "Fingerprint: A1B2C3D4" in footer.text


@pytest.mark.marker_qt_1
def test_create_pdf_footer_wraps_long_text_with_icon(qapp: QApplication) -> None:
    del qapp
    pdf = _create_pdf_with_footer(keystore_xpub="xpub1234567890" * 24)

    footer = pdf.elements[-1]
    assert isinstance(footer, Table)
    _width, height = footer.wrap(522, 1000)
    assert height > 16

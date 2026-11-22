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
from unittest.mock import Mock, patch

import bdkpython as bdk
import pytest
from PIL import Image
from PyQt6.QtCore import QLocale
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.platypus import Image as PDFImage
from reportlab.platypus import Table

from bitcoin_safe.pdfrecovery import DataExportPDF
from bitcoin_safe.pythonbdk_types import Recipient


def test_transaction_pdf_outputs_and_diagram(qapp: object, tmp_path: Path) -> None:
    pdf = DataExportPDF("en_US")
    pdf.create_pdf(
        title="Transaction export",
        txid="123",
        serialized="abcdef",
        data_label="Transaction",
        qr_images=[],
        recipients=[Recipient("bc1q" + "a" * 58, 12345, "Alice & Bob <test>")],
        network=bdk.Network.BITCOIN,
        diagram=Image.new("RGB", (800, 400), "white"),
    )
    table = next(element for element in pdf.elements if isinstance(element, Table))
    assert table._cellvalues[0][1].getPlainText() == "Amount [BTC]"
    assert [cell.getPlainText() for cell in table._cellvalues[1]] == [
        "bc1q" + "a" * 58,
        "0.00012345",
        "Alice & Bob <test>",
    ]
    for row in table._cellvalues:
        assert row[0].style.alignment == TA_LEFT
        assert row[1].style.alignment == TA_RIGHT
    diagram = next(element for element in pdf.elements if isinstance(element, PDFImage))
    assert diagram.drawWidth / diagram.drawHeight == 2
    path = tmp_path / "transaction.pdf"
    pdf.save_pdf(str(path))
    assert path.stat().st_size > 0


def test_transaction_pdf_qr_rows_and_footer(qapp: object, tmp_path: Path) -> None:
    from pypdf import PdfReader

    image = Image.new("RGB", (200, 200), "white")
    pdf = DataExportPDF("en_US")
    pdf.create_pdf("Transaction", None, "abcdef", "Transaction", [image, image, image])
    rows = [element for element in pdf.elements if isinstance(element, Table)]
    assert len(rows) == 2
    assert len(rows[0]._cellvalues[0][0]) == 2
    assert len(rows[0]._cellvalues[0][1]) == 2
    assert not rows[1]._cellvalues[0][1]
    path = tmp_path / "qr.pdf"
    pdf.save_pdf(str(path))
    pages = PdfReader(path).pages
    for i, page in enumerate(pages):
        assert f"{i + 1}/{len(pages)}" in page.extract_text()


def test_transaction_pdf_explorer_qr(qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bitcoin_safe.pdfrecovery import QRGenerator

    urls: list[str] = []

    def create_qr(url: str) -> Image.Image:
        urls.append(url)
        return Image.new("RGB", (100, 100), "white")

    monkeypatch.setattr(QRGenerator, "create_qr_PILimage", create_qr)
    pdf = DataExportPDF("en_US")
    url = "https://example.com/tx/123"
    pdf.create_pdf("Transaction", "123", "abcdef", "Transaction", [], explorer_url=url)
    assert urls == [url]
    pdf.save_pdf(str(tmp_path / "explorer.pdf"))


def test_future_transaction_locktime() -> None:
    from bitcoin_safe.gui.qt.transaction_pdf_export import get_future_nlocktime

    def transaction(locktime: int, sequence: int = 0xFFFFFFFE) -> bdk.Transaction:
        raw = (
            bytes.fromhex("0200000001" + "00" * 32 + "0000000000")
            + sequence.to_bytes(4, "little")
            + bytes.fromhex("01010000000000000000")
            + locktime.to_bytes(4, "little")
        )
        return bdk.Transaction(raw)

    assert get_future_nlocktime(transaction(100), 99) == 100
    assert get_future_nlocktime(transaction(100), 100) is None
    assert get_future_nlocktime(transaction(100), None) is None
    assert get_future_nlocktime(transaction(100, 0xFFFFFFFF), 99) is None
    assert get_future_nlocktime(transaction(4_000_000_000), None) == 4_000_000_000
    assert get_future_nlocktime(transaction(500_000_000), None) is None


def test_transaction_pdf_locktime_text() -> None:
    from reportlab.platypus import Paragraph

    pdf = DataExportPDF("en_US")
    pdf.create_pdf("Transaction", None, "abcdef", "Transaction", [], nlocktime=123456)
    assert any(
        "nLocktime: block height 123456" in element.getPlainText()
        for element in pdf.elements
        if isinstance(element, Paragraph)
    )


def test_collapsed_diagram_renders_for_pdf(qapp: object) -> None:
    from bitcoin_safe.gui.qt.sankey_widget import SankeyWidget

    widget = SankeyWidget()
    widget.resize(0, 0)
    widget.set([100], [100])
    image = widget.render_for_pdf()
    assert image is not None
    assert image.width() == 1000
    assert image.height() == 200
    assert image.pixelColor(500, 100).name() != "#ffffff"
    widget.close()


def test_export_includes_collapsed_diagram(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bitcoin_qr_tools.data import Data, DataType

    from bitcoin_safe.gui.qt.export_data import FileToolButton
    from bitcoin_safe.gui.qt.sankey_widget import SankeyWidget
    from tests.non_gui.test_psbt_util import p2wsh_psbt_0_1of1

    widget = SankeyWidget()
    widget.resize(0, 0)
    widget.set([100], [100])
    button = FileToolButton(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )
    from bitcoin_safe.gui.qt.transaction_pdf_export import TransactionPDFContext, TransactionPDFExporter

    class DiagramExporter(TransactionPDFExporter):
        def context(self) -> TransactionPDFContext:
            return TransactionPDFContext(diagram=widget)

    button.pdf_exporter = DiagramExporter()
    diagrams: list[Image.Image] = []
    original_create = DataExportPDF.create_pdf

    def record_create(pdf: DataExportPDF, *args: object, **kwargs: object) -> None:
        diagram = kwargs["diagram"]
        assert isinstance(diagram, Image.Image)
        diagrams.append(diagram)
        original_create(pdf, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(DataExportPDF, "create_pdf", record_create)
    monkeypatch.setattr(DataExportPDF, "open_pdf", lambda self, filename: None)
    button.export_to_pdf(tmp_path / "export.pdf")
    assert len(diagrams) == 1
    widget.close()
    button.close()


@pytest.mark.parametrize(
    ("amount", "estimated", "expected"),
    [(0, False, ["Fee", "0.00000000", ""]), (1234, True, ["Fee (estimated)", "0.00001234", ""])],
)
def test_transaction_pdf_fee_row(amount: int, estimated: bool, expected: list[str]) -> None:
    pdf = DataExportPDF("en_US")
    pdf.create_pdf(
        "Transaction",
        None,
        "abcdef",
        "Transaction",
        [],
        recipients=[Recipient("address", 5000)],
        fee_amount=amount,
        fee_amount_is_estimated=estimated,
    )
    table = next(element for element in pdf.elements if isinstance(element, Table))
    assert [cell.getPlainText() for cell in table._cellvalues[-1]] == expected


def test_transaction_pdf_omits_unknown_fee() -> None:
    pdf = DataExportPDF("en_US")
    pdf.create_pdf("Transaction", None, "abcdef", "Transaction", [], recipients=[Recipient("address", 5000)])
    table = next(element for element in pdf.elements if isinstance(element, Table))
    assert len(table._cellvalues) == 2


def test_transaction_label_is_escaped_in_pdf() -> None:
    from reportlab.platypus import Paragraph

    pdf = DataExportPDF("en_US")
    pdf.create_pdf("Transaction", None, "abcdef", "Transaction", [], tx_label="Rent & bills <April>")
    paragraphs = [element.getPlainText() for element in pdf.elements if isinstance(element, Paragraph)]
    assert "Transaction label:" in paragraphs
    assert "Rent & bills <April>" in paragraphs


@pytest.mark.parametrize("data_type", ["tx", "psbt"])
def test_viewer_pdf_uses_current_labels(qapp: object, tmp_path: Path, data_type: str) -> None:
    from bitcoin_qr_tools.data import Data, DataType

    from bitcoin_safe.gui.qt.export_data import FileToolButton
    from bitcoin_safe.gui.qt.recipient_csv import get_recipients_from_data
    from bitcoin_safe.gui.qt.transaction_pdf_export import ViewerTransactionPDFExporter
    from tests.non_gui.test_psbt_util import p2wsh_psbt_0_1of1

    data = (
        Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST)
        if data_type == "tx"
        else Data(p2wsh_psbt_0_1of1, DataType.PSBT, bdk.Network.REGTEST)
    )
    address = get_recipients_from_data(data, bdk.Network.REGTEST)[0].address
    button = FileToolButton(data, bdk.Network.REGTEST)
    button.add_meta_data({address: "stale label"})
    viewer = Mock()
    viewer.column_sankey.sankey_bitcoin = None
    viewer.config.network_config.mempool_url = None
    viewer._get_robust_height.return_value = 0
    viewer.fee_info = None
    viewer.recipients.get_address_labels_dict.return_value = {address: "first address"}
    viewer.label_line_edit.label.return_value = "first transaction"
    button.pdf_exporter = ViewerTransactionPDFExporter(viewer)

    with (
        patch.object(DataExportPDF, "create_pdf") as create_pdf,
        patch.object(DataExportPDF, "save_pdf"),
        patch.object(DataExportPDF, "open_pdf"),
    ):
        button.export_to_pdf(tmp_path / "first.pdf")
        assert create_pdf.call_args.kwargs["recipients"][0].label == "first address"
        assert create_pdf.call_args.kwargs["tx_label"] == "first transaction"

        viewer.recipients.get_address_labels_dict.return_value = {address: "updated address"}
        viewer.label_line_edit.label.return_value = "updated transaction"
        button.export_to_pdf(tmp_path / "second.pdf")
        assert create_pdf.call_args.kwargs["recipients"][0].label == "updated address"
        assert create_pdf.call_args.kwargs["tx_label"] == "updated transaction"

        viewer.recipients.get_address_labels_dict.return_value = {}
        viewer.label_line_edit.label.return_value = ""
        button.export_to_pdf(tmp_path / "third.pdf")
        assert create_pdf.call_args.kwargs["recipients"][0].label is None
        assert create_pdf.call_args.kwargs["tx_label"] == ""
    button.close()


@pytest.mark.parametrize("label_type", ["addr", "tx"])
def test_label_editor_refreshes_external_changes_without_losing_edits(qapp: object, label_type: str) -> None:
    from bitcoin_safe.gui.qt.labeledit import WalletLabelAndCategoryEdit
    from bitcoin_safe.labels import LabelType
    from bitcoin_safe.signals import UpdateFilter

    kind = LabelType.addr if label_type == "addr" else LabelType.tx
    editor = WalletLabelAndCategoryEdit(Mock(), lambda: "ref", kind)
    editor.set_label("old label")
    update = UpdateFilter(addresses=["ref"] if kind == LabelType.addr else [], txids=["ref"])
    with (
        patch("bitcoin_safe.gui.qt.labeledit.get_label_from_any_wallet", return_value="new label") as lookup,
        patch("bitcoin_safe.gui.qt.labeledit.get_wallet_of_address", return_value=None),
    ):
        editor.update_with_filter(UpdateFilter(addresses=["other"], txids=["other"]))
        assert editor.label() == "old label"
        editor.update_with_filter(update)
        assert editor.label() == "new label"

        editor.label_edit.setText("unfinished edit")
        editor.update_with_filter(update)
        assert editor.label() == "unfinished edit"

        editor.set_label("new label")
        lookup.return_value = None
        editor.update_with_filter(update)
        assert editor.label() == ""
    editor.close()


def test_transaction_pdf_translates_title_with_file_button_context(qapp: object, tmp_path: Path) -> None:
    from bitcoin_qr_tools.data import Data, DataType
    from PyQt6.QtCore import QTranslator
    from PyQt6.QtWidgets import QApplication

    from bitcoin_safe.gui.qt.export_data import FileToolButton
    from tests.non_gui.test_psbt_util import p2wsh_psbt_0_1of1

    class TestTranslator(QTranslator):
        def translate(
            self, context: str | None, sourceText: str | None, disambiguation: str | None = None, n: int = -1
        ) -> str:
            return (
                "Transaktionsexport"
                if (context, sourceText) == ("FileToolButton", "Transaction export")
                else ""
            )

    assert isinstance(qapp, QApplication)
    translator = TestTranslator()
    qapp.installTranslator(translator)
    previous_locale = QLocale()
    QLocale.setDefault(QLocale("de_DE"))
    button = FileToolButton(
        Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST), bdk.Network.REGTEST
    )
    button.txid = None
    try:
        with (
            patch.object(DataExportPDF, "create_pdf") as create_pdf,
            patch.object(DataExportPDF, "save_pdf"),
            patch.object(DataExportPDF, "open_pdf"),
            patch.object(Path, "home", return_value=tmp_path),
        ):
            filename = button.export_to_pdf()
        assert create_pdf.call_args.kwargs["title"] == "Transaktionsexport"
        assert filename and Path(filename).name.startswith("Transaktionsexport_")
    finally:
        button.close()
        QLocale.setDefault(previous_locale)
        qapp.removeTranslator(translator)

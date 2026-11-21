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

import io
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_qr_tools.qr_generator import QRGenerator
from bitcoin_qr_tools.unified_encoder import QrExportTypes, UnifiedEncoder
from PIL import Image
from PyQt6.QtCore import QBuffer, QIODevice, QLocale
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.recipient_csv import get_recipients_from_data
from bitcoin_safe.gui.qt.sankey_widget import SankeyWidget
from bitcoin_safe.gui.qt.util import Message, block_explorer_URL
from bitcoin_safe.i18n import translate
from bitcoin_safe.locktime_estimation import LOCKTIME_THRESHOLD, is_nlocktime_already_valid
from bitcoin_safe.pdfrecovery import DataExportPDF
from bitcoin_safe.tx import short_tx_id

if TYPE_CHECKING:
    from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer


def get_future_nlocktime(tx: bdk.Transaction, current_block_height: int | None) -> int | None:
    if not tx.is_lock_time_enabled():
        return None
    locktime = tx.lock_time()
    if locktime < LOCKTIME_THRESHOLD and current_block_height is None:
        return None
    return None if is_nlocktime_already_valid(locktime, current_block_height or 0) else locktime


@dataclass
class TransactionPDFContext:
    diagram: SankeyWidget | None = None
    explorer_base_url: str | None = None
    current_block_height: int | None = None
    tx_label: str = ""
    address_labels: Mapping[str, str] | None = None
    fee_amount: int | None = None
    fee_amount_is_estimated: bool = False


class TransactionPDFExporter:
    def context(self) -> TransactionPDFContext:
        return TransactionPDFContext()

    def export(
        self,
        data: Data,
        network: bdk.Network,
        txid: str | None,
        data_label: str,
        address_labels: Mapping[str, str],
        parent: QWidget,
        filepath: Path | None = None,
    ) -> str | None:
        if data.data_type not in [DataType.Tx, DataType.PSBT]:
            Message(
                translate("FileToolButton", "PDF export is only available for transactions or PSBTs."),
                parent=parent,
            )
            return None
        serialized = data.data_as_string()
        if not serialized:
            Message(translate("FileToolButton", "Not available"), parent=parent)
            return None
        export_name = translate("FileToolButton", "Transaction export")
        safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in export_name)
        default_filename = (
            f"{short_tx_id(txid)}.pdf"
            if txid
            else f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
        filepath = filepath or Path.home() / default_filename
        context = self.context()
        images = []
        for qr_type in (QrExportTypes.bbqr, QrExportTypes.ur):
            fragments = UnifiedEncoder.generate_fragments_for_qr(data=data, qr_export_type=qr_type)
            images.append([QRGenerator.create_qr_PILimage(fragment) for fragment in fragments])
        diagram = None
        if context.diagram and (diagram_image := context.diagram.render_for_pdf()):
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if diagram_image.save(buffer, "PNG"):
                diagram = Image.open(io.BytesIO(buffer.data().data()))
        explorer_url = (
            block_explorer_URL(context.explorer_base_url, "tx", txid)
            if txid and context.explorer_base_url
            else None
        )
        tx = data.data if isinstance(data.data, bdk.Transaction) else None
        if isinstance(data.data, bdk.Psbt):
            tx = data.data.extract_tx()
        fee_amount = context.fee_amount
        if fee_amount is None and isinstance(data.data, bdk.Psbt):
            try:
                fee_amount = data.data.fee()
            except (bdk.PsbtError.MissingUtxo, bdk.PsbtError.NegativeFee, bdk.PsbtError.FeeOverflow):
                pass
        pdf = DataExportPDF(lang_code=QLocale().name())
        pdf.create_pdf(
            title=translate("FileToolButton", "Transaction export", no_translate=pdf.no_translate),
            txid=txid,
            explorer_url=explorer_url,
            nlocktime=get_future_nlocktime(tx, context.current_block_height) if tx else None,
            tx_label=context.tx_label.strip(),
            fee_amount=fee_amount,
            fee_amount_is_estimated=context.fee_amount_is_estimated,
            serialized=serialized,
            data_label=data_label,
            qr_images=images[0],
            ur_qr_images=images[1],
            recipients=get_recipients_from_data(
                data,
                network,
                context.address_labels if context.address_labels is not None else address_labels,
            ),
            network=network,
            diagram=diagram,
        )
        pdf.save_pdf(str(filepath))
        pdf.open_pdf(str(filepath))
        return str(filepath)


class ViewerTransactionPDFExporter(TransactionPDFExporter):
    def __init__(self, viewer: UITx_Viewer) -> None:
        self.viewer = viewer

    def context(self) -> TransactionPDFContext:
        fee_info = self.viewer.fee_info
        return TransactionPDFContext(
            diagram=self.viewer.column_sankey.sankey_bitcoin,
            explorer_base_url=self.viewer.config.network_config.mempool_url,
            current_block_height=self.viewer._get_robust_height() or None,
            tx_label=self.viewer.label_line_edit.label(),
            address_labels=self.viewer.recipients.get_address_labels_dict(),
            fee_amount=fee_info.fee_amount if fee_info else None,
            fee_amount_is_estimated=fee_info.fee_amount_is_estimated if fee_info else False,
        )

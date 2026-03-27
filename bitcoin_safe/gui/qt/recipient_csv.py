#
# Bitcoin Safe
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

import csv
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_safe_lib.gui.qt.satoshis import unit_sat_str
from PyQt6.QtWidgets import QFileDialog, QWidget

from bitcoin_safe.i18n import translate
from bitcoin_safe.pythonbdk_types import Recipient, TxOut, robust_address_str_from_txout

logger = logging.getLogger(__name__)


def get_recipient_csv_header(network: bdk.Network) -> list[str]:
    """Get the translated CSV header used for recipient import/export."""
    return [
        translate("Recipients", "Address"),
        translate("Recipients", "Amount [{unit}]").format(unit=unit_sat_str(network)),
        translate("Recipients", "Label"),
    ]


def recipients_to_csv_rows(
    recipients: Sequence[Recipient], network: bdk.Network, include_header: bool = True
) -> list[list[str | int]]:
    """Convert recipients into CSV rows."""
    rows: list[list[str | int]] = []
    if include_header:
        header: list[str | int] = list(get_recipient_csv_header(network))
        rows.append(header)

    rows.extend([[recipient.address, recipient.amount, recipient.label or ""] for recipient in recipients])
    return rows


def get_recipients_from_data(
    data: Data,
    network: bdk.Network,
    address_labels_dict: Mapping[str, str] | None = None,
) -> list[Recipient]:
    """Build recipients from transaction-like data."""
    tx: bdk.Transaction | None = None
    if data.data_type == DataType.PSBT and isinstance(data.data, bdk.Psbt):
        tx = data.data.extract_tx()
    elif data.data_type == DataType.Tx and isinstance(data.data, bdk.Transaction):
        tx = data.data

    if tx is None:
        return []

    return [
        Recipient(
            address=(address := robust_address_str_from_txout(TxOut.from_bdk(output), network=network)),
            amount=output.value.to_sat(),
            label=(address_labels_dict or {}).get(address),
        )
        for output in tx.output()
    ]


def export_recipients_csv(
    recipients: Sequence[Recipient],
    network: bdk.Network,
    parent: QWidget | None = None,
    file_path: str | Path | None = None,
) -> Path | None:
    """Export recipients to a CSV file."""
    if not file_path:
        file_path, _ = QFileDialog.getSaveFileName(
            parent,
            translate("Recipients", "Export csv"),
            "recipients.csv",
            translate("Recipients", "All Files (*);;Wallet Files (*.csv)"),
        )
        if not file_path:
            logger.info(translate("Recipients", "No file selected"))
            return None

    path = Path(file_path)
    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(recipients_to_csv_rows(recipients=recipients, network=network))

    logger.debug("CSV Table saved to %s", path)
    return path

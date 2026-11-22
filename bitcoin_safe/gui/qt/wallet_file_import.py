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

"""Import public wallet data from another wallet application."""

from __future__ import annotations

import base64
import copy
import re
from pathlib import Path
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_usb.address_types import AddressTypes
from bitcoin_usb.usb_gui import USBGui
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.dialogs import PasswordQuestion
from bitcoin_safe.gui.qt.util import svg_tools, svg_tools_hardware_signer
from bitcoin_safe.wallet import ProtoWallet
from bitcoin_safe.wallet_import.adapters import (
    MAX_FILE,
    import_bip329_jsonl,
    import_specter_address_csv,
    load_file,
)
from bitcoin_safe.wallet_import.bitcoin_safe_bridge import NETWORKS, label_import_data, make_protowallet
from bitcoin_safe.wallet_import.descriptors import add_checksum, norm_path, strip_checksum
from bitcoin_safe.wallet_import.electrum import (
    ELECTRUM_STORAGE_XPUB_PATH,
    complete_cosigner_origins,
    is_electrum_encrypted,
    missing_cosigner_origins,
)
from bitcoin_safe.wallet_import.ledger_live_db import discover_ledger_live_app_json
from bitcoin_safe.wallet_import.model import ExchangeError, PasswordRequired, WalletExchange
from bitcoin_safe.wallet_import.sparrow_crypto import is_sprw1
from bitcoin_safe.wallet_import.sparrow_h2 import H2_MAGIC
from bitcoin_safe.xpub_utils import check_xpub_origin_depth_and_child_number

WALLET_FILE_FORMATS = (
    ("Electrum", "electrum"),
    ("Sparrow", "sparrow"),
    ("Specter Desktop", "specter"),
    ("Wasabi", "wasabi"),
    ("Ledger Live", "ledger"),
)


class ImportWorker(QThread):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)
    password_required = pyqtSignal(str)

    def __init__(
        self,
        path: str,
        format_id: str,
        password: str | None,
        parent: QWidget,
        bip39_passphrase: str | None = None,
        bip39_passphrases: dict[str, str] | None = None,
        electrum_hw_xpub: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.format_id = format_id
        self.password = password
        self.bip39_passphrase = bip39_passphrase
        self.bip39_passphrases = dict(bip39_passphrases or {})
        self.electrum_hw_xpub = electrum_hw_xpub

    def run(self) -> None:
        try:
            wallets = load_file(
                self.path,
                hint=self.format_id,
                password=self.password,
                bip39_passphrase=self.bip39_passphrase,
                bip39_passphrases=self.bip39_passphrases,
                electrum_hw_xpub=self.electrum_hw_xpub,
            )
        except PasswordRequired as exc:
            self.password_required.emit(str(exc))
        except IsADirectoryError:
            self.failed.emit(self.tr("This is a folder. Open it and select the wallet file inside."))
        except FileNotFoundError:
            self.failed.emit(
                self.tr("A selected file could not be found. Check the file paths and try again.")
            )
        except PermissionError:
            self.failed.emit(self.tr("Cannot read a selected file. Check its permissions and try again."))
        except OSError:
            self.failed.emit(self.tr("Cannot read a selected file. Check the files and try again."))
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(wallets)
        finally:
            self.password = None
            self.bip39_passphrase = None
            self.bip39_passphrases = {}
            self.electrum_hw_xpub = None


class WalletFileImportScreen(QWidget):
    """Embedded setup screen for importing one public wallet account."""

    signal_import_ready = cast(SignalProtocol[[ProtoWallet, WalletExchange]], pyqtSignal(object, object))
    signal_cancel = cast(SignalProtocol[[]], pyqtSignal())
    signal_busy_changed = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    formats_with_labels = frozenset({"electrum", "sparrow", "specter"})

    def __init__(
        self,
        wallet_id: str,
        network: bdk.Network,
        parent: QWidget | None = None,
        loop_in_thread: LoopInThread | None = None,
    ) -> None:
        super().__init__(parent)
        self.wallet_id = wallet_id
        self.network = network
        # Reuse bitcoin_usb's generic picker/backends and platform-specific
        # threading. Never open a vendor-specific device connection here.
        self.usb_gui = (
            USBGui(network=network, loop_in_thread=loop_in_thread, parent=self, enable_bluetooth=False)
            if loop_in_thread is not None
            else None
        )
        self.wallets: list[WalletExchange] = []
        self.worker: ImportWorker | None = None
        self._pending_password_prompt = False
        self._pending_signer_prompts: list[tuple[str, str]] = []
        self._signer_passphrases: dict[str, str] = {}
        self._source_wallet_password: str | None = None
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel(self.tr("Import wallet file"), self)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        title.setFont(title_font)
        outer_layout.addWidget(title)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer_layout.addWidget(scroll)
        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        form = QFormLayout()
        self.form = form
        layout.addLayout(form)
        self.format = QComboBox(self)
        hardware_icons = {
            "ledger": "ledgernano-icon.svg",
        }
        for title, hint in WALLET_FILE_FORMATS:
            icon = (
                svg_tools_hardware_signer.get_QIcon(hardware_icons[hint])
                if hint in hardware_icons
                else svg_tools.get_QIcon("bi--wallet2.svg")
            )
            self.format.addItem(icon, title, hint)
        form.addRow(self.tr("Wallet format"), self.format)
        self.format_help = QLabel(self)
        self.format_help.setWordWrap(True)
        form.addRow("", self.format_help)
        self.wallet_path = self._file_row(form, self.tr("Wallet file"), self.tr("Choose wallet file"))
        self.labels_path = self._file_row(
            form, self.tr("BIP-329 labels (optional)"), self.tr("Choose labels file")
        )
        self.specter_path = self._file_row(
            form, self.tr("Specter address CSV (optional)"), self.tr("Choose address CSV")
        )
        self.bip39_passphrase = QLabel(
            self.tr("Passphrases are requested separately for each software signer after reading the file."),
            self,
        )
        self.bip39_passphrase.setWordWrap(True)
        form.addRow(self.tr("BIP39 signer passphrases"), self.bip39_passphrase)
        wallet_row = self.wallet_path.parentWidget()
        assert wallet_row is not None
        self.wallet_row = wallet_row
        labels_row = self.labels_path.parentWidget()
        assert labels_row is not None
        self.labels_row = labels_row
        self.load_button = QPushButton(self.tr("Read wallet file"), self)
        self.load_button.clicked.connect(self.read_wallet)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.accounts = QComboBox(self)
        account_form = QFormLayout()
        account_form.addRow(self.tr("Account"), self.accounts)
        layout.addLayout(account_form)
        self.accounts.setEnabled(False)
        self.accounts.currentIndexChanged.connect(self.update_account_state)
        self.import_button = QPushButton(self.tr("Import"), self)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.prepare_import)
        self.cancel_button = QPushButton(self.tr("Back"), self)
        self.cancel_button.clicked.connect(self.cancel)
        self.button_row = QHBoxLayout()
        self.button_row.addStretch()
        self.button_row.addWidget(self.cancel_button)
        self.button_row.addWidget(self.load_button)
        self.button_row.addWidget(self.import_button)
        layout.addLayout(self.button_row)
        self.format.currentIndexChanged.connect(self.update_format)
        self.wallet_path.textChanged.connect(self.clear_accounts)
        self.update_format()

    def _file_row(self, form: QFormLayout, label: str, caption: str, file_filter: str = "") -> QLineEdit:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(row)
        button = QPushButton(self.tr("Browse…"), row)
        button.clicked.connect(lambda: self.choose_file(edit, caption, file_filter))
        layout.addWidget(edit)
        layout.addWidget(button)
        form.addRow(label, row)
        return edit

    def choose_file(self, edit: QLineEdit, caption: str, file_filter: str = "") -> None:
        path, _ = QFileDialog.getOpenFileName(self, caption, filter=file_filter)
        if path:
            edit.setText(path)

    def clear_accounts(self) -> None:
        self._signer_passphrases.clear()
        self._source_wallet_password = None
        self._pending_signer_prompts = []
        self.wallets = []
        self.accounts.clear()
        self.accounts.setEnabled(False)
        self.import_button.setEnabled(False)
        self.status.clear()

    def update_format(self) -> None:
        self.clear_accounts()
        fmt = self.format.currentData()
        if fmt == "electrum":
            info = self.tr(
                "Electrum wallet file: password-protected BIE1 files are supported; BIE2 requires an Electrum export."
            )
        elif fmt == "sparrow":
            info = self.tr(
                "Sparrow JSON and password-protected H2 wallet files are supported. Close Sparrow before importing. H2 imports automatically read BIP39 seeds to recover signer data. Mainnet seeds are not imported; verified test-network seeds may be saved for signing and can also control mainnet funds."
            )
        elif fmt == "ledger":
            info = self.tr(
                "Ledger Live accounts are read automatically from your local app.json user-data file. "
                "No file selection is needed. An application password may be required, not the device PIN."
            )
        elif fmt == "wasabi":
            info = self.tr(
                "Wasabi public wallet data is imported without a password. Supported native SegWit "
                "labels are converted from verified key paths. You can also select a BIP-329 "
                "labels file for labels that cannot be resolved."
            )
        else:
            info = self.tr(
                "Native password protection is not supported for this format. Select a public wallet or account export."
            )
        self.format_help.setText(info)
        self.form.setRowVisible(self.bip39_passphrase, fmt == "sparrow")
        self.form.setRowVisible(self.wallet_row, fmt != "ledger")
        self.form.setRowVisible(self.labels_row, fmt not in self.formats_with_labels)
        self.form.setRowVisible(self.specter_path.parentWidget(), fmt == "specter")
        self.load_button.setText(
            self.tr("Discover Ledger accounts") if fmt == "ledger" else self.tr("Read wallet file")
        )

    def read_wallet(self) -> None:
        self.clear_accounts()
        if self.format.currentData() == "ledger":
            try:
                selected_path = str(discover_ledger_live_app_json())
            except FileNotFoundError:
                self.show_error(
                    self.tr(
                        "Ledger Live app.json was not found in the default user-data folder. "
                        "Open Ledger Live → Settings → Help → View user data, and check that "
                        "the application stores its accounts locally."
                    )
                )
                return
        else:
            selected_path = self.wallet_path.text().strip()
            if not selected_path:
                self.show_error(self.tr("Choose a wallet file using Browse before reading it."))
                return
        try:
            path = Path(selected_path).expanduser()
            with path.open("rb") as stream:
                header = stream.read(1024)
            electrum_encrypted = is_electrum_encrypted(header)
            electrum_bie2 = electrum_encrypted and base64.b64decode(
                header.strip()[:8], validate=True
            ).startswith(b"BIE2")
            encrypted = header.startswith(H2_MAGIC) or is_sprw1(header) or electrum_encrypted
        except RuntimeError:
            self.show_error(self.tr("Cannot resolve the wallet file path. Choose the file using Browse."))
            return
        except IsADirectoryError:
            self.show_error(self.tr("This is a folder. Open it and select the wallet file inside."))
            return
        except FileNotFoundError:
            self.show_error(
                self.tr("The wallet file could not be found. Choose an existing file using Browse.")
            )
            return
        except PermissionError:
            self.show_error(self.tr("Cannot read this wallet file. Check its permissions and try again."))
            return
        except OSError:
            self.show_error(self.tr("Cannot read this wallet file. Check the file and try again."))
            return
        except ExchangeError as exc:
            self.show_error(str(exc))
            return
        password = None
        electrum_hw_xpub = None
        if electrum_bie2:
            if self.format.currentData() != "electrum":
                self.show_error(self.tr("Select the Electrum format for this encrypted wallet."))
                return
            if self.usb_gui is None:
                self.show_error(self.tr("USB device access is unavailable for this import screen."))
                return
            self.status.setText(
                self.tr("Select and unlock the hardware wallet used to encrypt this Electrum file.")
            )
            try:
                # Electrum BIE2 uses a special hardened *public* xpub path;
                # bitcoin_usb handles all supported USB hardware backends.
                result = self.usb_gui.get_fingerprint_and_xpub(ELECTRUM_STORAGE_XPUB_PATH)
            except Exception as exc:
                self.show_error(self.tr("Could not read Electrum storage xpub: {error}").format(error=exc))
                return
            if result is None:
                self.status.setText(self.tr("USB hardware wallet selection was cancelled or failed."))
                return
            _selected, _fingerprint, electrum_hw_xpub = result
        elif encrypted:
            password = PasswordQuestion(self, self.tr("Enter the source wallet password:")).ask_for_password()
            if password is None:
                return
        self.start_import(password, electrum_hw_xpub=electrum_hw_xpub)

    def start_import(self, password: str | None, *, electrum_hw_xpub: str | None = None) -> None:
        self._source_wallet_password = password
        self.wallets = []
        self.accounts.clear()
        self.import_button.setEnabled(False)
        fmt = str(self.format.currentData())
        if fmt == "ledger":
            try:
                path = str(discover_ledger_live_app_json())
            except FileNotFoundError:
                self.show_error(
                    self.tr("Ledger Live app.json was not found in the default user-data folder.")
                )
                return
        else:
            path = str(Path(self.wallet_path.text().strip()).expanduser())
        self.worker = ImportWorker(
            path,
            fmt,
            password,
            self,
            bip39_passphrases=dict(self._signer_passphrases) if fmt == "sparrow" else None,
            electrum_hw_xpub=electrum_hw_xpub,
        )
        self.worker.loaded.connect(self.on_loaded)
        self.worker.failed.connect(self.show_error)
        self.worker.password_required.connect(self.on_password_required)
        self.worker.finished.connect(self.on_finished)
        self.load_button.setEnabled(False)
        self.format.setEnabled(False)
        self.wallet_row.setEnabled(False)
        self.bip39_passphrase.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.signal_busy_changed.emit(True)
        self.status.setText(self.tr("Reading wallet file…"))
        self.worker.start()

    def on_loaded(self, wallets: list[WalletExchange]) -> None:
        self.wallets = wallets
        self._pending_signer_prompts = []
        seen: set[str] = set()
        for account in wallets:
            for index, key in enumerate(account.keystores, 1):
                ref = key.extra.get("signer_input_ref")
                required = key.extra.get("signer_input_required")
                if not required or not isinstance(ref, str) or not ref or ref in seen:
                    continue
                seen.add(ref)
                if ref not in self._signer_passphrases:
                    label = key.label or self.tr("Signer {index}").format(index=index)
                    self._pending_signer_prompts.append((ref, f"{account.name} — {label}"))
        for account in wallets:
            state = self.tr("ready") if account.descriptor else self.tr("descriptor unavailable")
            self.accounts.addItem(f"{account.name} — {account.network} — {state}")
        self.accounts.setEnabled(bool(wallets))
        self.update_account_state()

    def update_account_state(self) -> None:
        index = self.accounts.currentIndex()
        if not 0 <= index < len(self.wallets):
            self.import_button.setEnabled(False)
            return
        account = self.wallets[index]
        self.import_button.setEnabled(bool(account.descriptor) and self.worker is None)
        if account.descriptor:
            if account.source_wallet == "electrum" and missing_cosigner_origins(account):
                self.status.setText(
                    self.tr("Choose an account and select Import. Missing signer details will be requested.")
                )
            else:
                self.status.setText(self.tr("Choose an account and select Import."))
        elif account.source_wallet == "sparrow-h2":
            self.status.setText(
                self.tr(
                    "This Sparrow file does not contain enough public information to reconstruct the descriptor. "
                    "Check the BIP39 passphrase and read the file again, or export a public descriptor from Sparrow."
                )
            )
        else:
            self.status.setText(
                self.tr(
                    "This account cannot be imported because its complete receive-and-change descriptor "
                    "is unavailable. Export a compatible descriptor from the source wallet."
                )
            )

    def on_password_required(self, message: str) -> None:
        del message
        self.status.setText(self.tr("Ledger Live requires an application password."))
        self._pending_password_prompt = True

    def on_finished(self) -> None:
        self.load_button.setEnabled(True)
        self.format.setEnabled(True)
        self.wallet_row.setEnabled(True)
        self.bip39_passphrase.setEnabled(True)
        self.cancel_button.setEnabled(True)
        if self.worker:
            self.worker.deleteLater()
        self.worker = None
        self.update_account_state()
        self.signal_busy_changed.emit(False)
        if self._pending_signer_prompts:
            requests = self._pending_signer_prompts
            self._pending_signer_prompts = []
            for ref, label in requests:
                phrase, accepted = QInputDialog.getText(
                    self,
                    self.tr("Sparrow signer BIP39 passphrase"),
                    self.tr("BIP39 passphrase for {signer}:").format(signer=label),
                    QLineEdit.EchoMode.Password,
                )
                if not accepted:
                    self.status.setText(self.tr("Signer passphrase entry cancelled. No wallet was imported."))
                    return
                self._signer_passphrases[ref] = phrase
            self.start_import(self._source_wallet_password)
            return
        if self._pending_password_prompt:
            self._pending_password_prompt = False
            password = PasswordQuestion(
                self, self.tr("Enter your Ledger Live application password:")
            ).ask_for_password()
            if password is not None:
                self.start_import(password)

    def cancel(self) -> None:
        if self.worker is None:
            self.signal_cancel.emit()

    def show_error(self, message: str) -> None:
        self.status.setText(message)
        QMessageBox.warning(self, self.tr("Wallet import"), message)

    def complete_ledger_origin(self, exchange: WalletExchange) -> bool:
        """Request signer origins absent from Ledger's public account data."""
        if exchange.source_wallet != "ledger-live" or not exchange.descriptor:
            return True
        for keystore in exchange.keystores:
            if not keystore.xpub or (keystore.fingerprint and keystore.key_origin):
                continue
            fingerprint = keystore.fingerprint
            if not fingerprint:
                fingerprint, accepted = QInputDialog.getText(
                    self,
                    self.tr("Ledger signer fingerprint"),
                    self.tr("Enter the 8-character master fingerprint shown by your Ledger signer:"),
                )
                if not accepted:
                    return False
                fingerprint = fingerprint.strip().lower()
                if not re.fullmatch(r"[0-9a-f]{8}", fingerprint):
                    raise ExchangeError(
                        self.tr("The master fingerprint must contain exactly eight hexadecimal characters.")
                    )
            origin = keystore.key_origin
            if not origin:
                path, accepted = QInputDialog.getText(
                    self,
                    self.tr("Ledger account derivation"),
                    self.tr(
                        "Enter the account derivation path shown by your Ledger signer (for example m/84h/0h/0h):"
                    ),
                )
                if not accepted:
                    return False
                origin = norm_path(path.strip())
            if not origin or not re.fullmatch(r"m(?:/[0-9]+[hH']?)+", origin):
                raise ExchangeError(self.tr("Enter a valid account derivation path."))
            check_xpub_origin_depth_and_child_number(keystore.xpub, origin)
            descriptor = strip_checksum(exchange.descriptor)
            matches = list(re.finditer(r"(?:\[[^\]]+\])?" + re.escape(keystore.xpub), descriptor))
            if len(matches) != 1:
                raise ExchangeError(self.tr("The Ledger descriptor has an unsupported key origin."))
            match = matches[0]
            expression = f"[{fingerprint}/{origin.removeprefix('m/')}]" + keystore.xpub
            exchange.descriptor = add_checksum(
                descriptor[: match.start()] + expression + descriptor[match.end() :]
            )
            keystore.fingerprint = fingerprint
            keystore.key_origin = origin
        return True

    def complete_electrum_origins(self, exchange: WalletExchange) -> bool:
        if exchange.source_wallet != "electrum":
            return True
        missing = missing_cosigner_origins(exchange)
        if not missing:
            return True
        origins: dict[int, tuple[str, str]] = {}
        for index in missing:
            key = exchange.keystores[index - 1]
            fingerprint = key.fingerprint
            if not fingerprint or fingerprint == "00000000":
                fingerprint, accepted = QInputDialog.getText(
                    self,
                    self.tr("Electrum signer fingerprint"),
                    self.tr(
                        "Enter the genuine master fingerprint for Electrum signer {number}. Check the fingerprint on the hardware signer or its original backup:"
                    ).format(number=index),
                )
                if not accepted:
                    return False
            origin = key.key_origin
            if not origin:
                address_type = {"wsh": AddressTypes.p2wsh, "sh-wsh": AddressTypes.p2sh_p2wsh}.get(
                    exchange.address_type or ""
                )
                default_path = address_type.key_origin(self.network) if address_type else ""
                origin, accepted = QInputDialog.getText(
                    self,
                    self.tr("Electrum signer derivation"),
                    self.tr("Enter the account derivation path for Electrum signer {number}:").format(
                        number=index
                    ),
                    text=default_path,
                )
                if not accepted:
                    return False
            origins[index] = (fingerprint, origin)
        complete_cosigner_origins(exchange, origins)
        return True

    def prepare_import(self) -> None:
        index = self.accounts.currentIndex()
        if not 0 <= index < len(self.wallets):
            return
        exchange = copy.deepcopy(self.wallets[index])
        try:
            source_network = NETWORKS.get(exchange.network)
            inferred = bool(exchange.extra.get("network_inferred_from_keys"))
            if source_network is not None and source_network != self.network:
                if not (
                    inferred and source_network != bdk.Network.BITCOIN and self.network != bdk.Network.BITCOIN
                ):
                    raise ExchangeError(
                        self.tr("The source wallet network does not match the active network.")
                    )
            if source_network is None or (inferred and self.network != bdk.Network.BITCOIN):
                answer = QMessageBox.question(
                    self,
                    self.tr("Confirm network"),
                    self.tr(
                        "This file does not establish the exact network. Confirm that this wallet belongs to the active network: {network}."
                    ).format(network=self.network.name),
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            labels = self.labels_path.text().strip()
            if labels and self.format.currentData() not in self.formats_with_labels:
                path = Path(labels)
                if path.stat().st_size > MAX_FILE:
                    raise ExchangeError(self.tr("Labels file is too large."))
                import_bip329_jsonl(exchange, path.read_text(encoding="utf-8-sig"))
            csv = self.specter_path.text().strip()
            if csv and self.format.currentData() == "specter":
                path = Path(csv)
                if path.stat().st_size > MAX_FILE:
                    raise ExchangeError(self.tr("Address CSV is too large."))
                import_specter_address_csv(exchange, path.read_text(encoding="utf-8-sig"))
            if not self.complete_ledger_origin(exchange):
                return
            if not self.complete_electrum_origins(exchange):
                return
            proto = make_protowallet(exchange, self.wallet_id, self.network)
            _, warnings = label_import_data(exchange)
        except (OSError, UnicodeError, ValueError) as exc:
            self.show_error(str(exc))
            return
        warnings = list(dict.fromkeys(exchange.warnings + warnings))
        if any(key.non_mainnet_seed for key in exchange.keystores):
            text = self.tr(
                "Verified test-network BIP39 seeds will be imported and saved with this wallet. "
                "These seeds can also control mainnet funds; protect this wallet like a recovery backup. "
                "Verify the first receive and change addresses against the source wallet before receiving funds."
            )
        else:
            text = self.tr(
                "Only public wallet data is imported. Verify the first receive and change addresses against the source wallet before receiving funds. Signing requires the original signer or device."
            )
        if self.network == bdk.Network.BITCOIN and any(
            key.recovery_material == "SEED_REDACTED" for key in exchange.keystores
        ):
            text += "\n\n" + self.tr(
                "The source wallet contained a mainnet seed. It was not retained or imported. Keep your original recovery backup; this wallet cannot sign with that seed."
            )
        if exchange.source_wallet == "electrum" and any(
            key.fingerprint == "00000000" for key in exchange.keystores
        ):
            text += "\n\n" + self.tr(
                "A signer fingerprint is set to 00000000. This placeholder does not identify the original signer; replace it with the real fingerprint when available."
            )
        if warnings:
            text += "\n\n" + "\n".join(warnings)
        if (
            QMessageBox.warning(
                self,
                self.tr("Review wallet import"),
                text,
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Ok
        ):
            return
        self._signer_passphrases.clear()
        self._source_wallet_password = None
        self.signal_import_ready.emit(proto, exchange)

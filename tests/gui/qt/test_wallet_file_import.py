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
from unittest.mock import patch

import bdkpython as bdk
from PyQt6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.wallet_file_import import WalletFileImportScreen
from bitcoin_safe.wallet_import import from_descriptor
from tests.non_gui.wallet_import.test_wallet_exchange import expressions, xpub


def choose_format(dialog: WalletFileImportScreen, fmt: str) -> None:
    dialog.format.setCurrentIndex(dialog.format.findData(fmt))


def test_wallet_formats_have_icons(qtbot: QtBot) -> None:
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    assert [screen.format.itemData(i) for i in range(screen.format.count())] == [
        "electrum",
        "sparrow",
        "specter",
        "wasabi",
        "ledger",
        "green",
    ]
    assert all(not screen.format.itemIcon(i).isNull() for i in range(screen.format.count()))


def test_import_green_descriptor_and_labels(qtbot: QtBot, tmp_path: Path) -> None:
    source = tmp_path / "wallet.txt"
    source.write_text(expressions()[2])
    labels = tmp_path / "labels.jsonl"
    labels.write_text('{"type":"tx","ref":"' + "a" * 64 + '","label":"test"}\n')
    dialog = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(dialog)
    dialog.show()
    choose_format(dialog, "green")
    assert "descriptor" in dialog.format_help.text()
    dialog.wallet_path.setText(str(source))
    dialog.labels_path.setText(str(labels))
    dialog.read_wallet()
    qtbot.waitUntil(lambda: dialog.worker is None, timeout=10000)
    assert dialog.accounts.count() == 1
    with (
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Ok,
        ),
        qtbot.waitSignal(dialog.signal_import_ready) as imported,
    ):
        dialog.prepare_import()
    proto, exchange = imported.args
    assert proto.id == "Imported"
    assert exchange.labels[0].label == "test"


def test_inferred_testnet_requires_confirmation(qtbot: QtBot) -> None:
    dialog = WalletFileImportScreen("Imported", bdk.Network.TESTNET4)
    qtbot.addWidget(dialog)
    key = xpub(0x043587CF)
    exchange = from_descriptor(f"wpkh([f00dbabe/84h/1h/0h]{key}/<0;1>/*)")
    dialog.on_loaded([exchange])
    with patch(
        "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ) as question:
        dialog.prepare_import()
    question.assert_called_once()


def test_wrong_network(qtbot: QtBot) -> None:
    dialog = WalletFileImportScreen("Imported", bdk.Network.REGTEST)
    qtbot.addWidget(dialog)
    dialog.on_loaded([from_descriptor(expressions()[2])])
    with patch("bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning") as warning:
        dialog.prepare_import()
    assert "network" in warning.call_args.args[2]


def test_sparrow_h2_import_needs_no_external_driver(qtbot: QtBot, tmp_path: Path) -> None:
    from tests.non_gui.wallet_import.test_h2_python import sample_mvstore_file

    source = tmp_path / "wallet.mv.db"
    source.write_bytes(sample_mvstore_file())
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "sparrow")
    screen.wallet_path.setText(str(source))
    screen.read_wallet()
    qtbot.waitUntil(lambda: screen.worker is None, timeout=10000)
    assert len(screen.wallets) == 1
    assert screen.wallets[0].name == "Synthetic"
    assert "driver" not in screen.format_help.text().lower()


def test_sparrow_h2_automatically_recovers_testnet_seed(qtbot: QtBot, tmp_path: Path) -> None:
    from tests.non_gui.wallet_import.test_h2_python import sample_mvstore_file
    from tests.non_gui.wallet_import.test_sparrow_seed_public import SYNTHETIC_WORDS

    source = tmp_path / "wallet.mv.db"
    source.write_bytes(sample_mvstore_file(2, SYNTHETIC_WORDS))
    screen = WalletFileImportScreen("Imported", bdk.Network.REGTEST)
    qtbot.addWidget(screen)
    choose_format(screen, "sparrow")
    assert screen.bip39_passphrase.isEnabled()
    assert "automatically" in screen.format_help.text()
    screen.wallet_path.setText(str(source))
    screen.read_wallet()
    qtbot.waitUntil(lambda: screen.worker is None, timeout=10000)
    assert screen.import_button.isEnabled()
    assert screen.wallets[0].keystores[0].non_mainnet_seed == SYNTHETIC_WORDS


def test_electrum_import_requests_missing_signer_origins(qtbot: QtBot) -> None:
    from bitcoin_safe.wallet_import.electrum import from_electrum
    from tests.non_gui.wallet_import.test_electrum_cosigner_origins import electrum_multisig

    screen = WalletFileImportScreen("Imported", bdk.Network.TESTNET)
    qtbot.addWidget(screen)
    screen.on_loaded([from_electrum(electrum_multisig())])
    origins = [("deadbeef", True), ("m/48h/1h/0h", True), ("12345678", True), ("m/48h/1h/0h", True)]
    with (
        patch("bitcoin_safe.gui.qt.wallet_file_import.QInputDialog.getText", side_effect=origins),
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Ok,
        ),
        qtbot.waitSignal(screen.signal_import_ready) as imported,
    ):
        screen.prepare_import()
    assert imported.args[1].keystores[1].fingerprint == "deadbeef"
    assert imported.args[1].keystores[2].fingerprint == "12345678"


def test_encrypted_electrum_password_retry(qtbot: QtBot, tmp_path: Path) -> None:
    from tests.non_gui.wallet_import.test_added_wallets import _encrypt_electrum

    data = {
        "wallet_type": "standard",
        "keystore": {
            "type": "bip32",
            "xpub": xpub(0x04B24746),
            "root_fingerprint": "beefcafe",
            "derivation": "m/84h/0h/0h",
        },
    }
    source = tmp_path / "electrum"
    source.write_bytes(_encrypt_electrum(data, "correct"))
    dialog = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(dialog)
    dialog.wallet_path.setText(str(source))
    with (
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.PasswordQuestion.ask_for_password",
            side_effect=["wrong", "correct"],
        ),
        patch("bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning") as warning,
    ):
        dialog.read_wallet()
        qtbot.waitUntil(lambda: dialog.worker is None, timeout=10000)
        assert dialog.accounts.count() == 0
        assert "password" in warning.call_args.args[2].lower()
        dialog.read_wallet()
        qtbot.waitUntil(lambda: dialog.worker is None, timeout=10000)
    assert dialog.accounts.count() == 1


def test_multi_account_selection_imports_only_selected_account(qtbot: QtBot) -> None:
    first = from_descriptor(expressions()[2], name="First")
    second = from_descriptor(expressions()[2], name="Second")
    dialog = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(dialog)
    dialog.on_loaded([first, second])
    dialog.accounts.setCurrentIndex(1)
    with (
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Ok,
        ),
        qtbot.waitSignal(dialog.signal_import_ready) as imported,
    ):
        dialog.prepare_import()
    assert imported.args[1].name == "Second"


def test_main_window_import_saves_labels(qtbot: QtBot, test_config, tmp_path: Path) -> None:
    from bitcoin_safe.wallet_import.model import Label
    from tests.gui.qt.helpers import main_window_context

    key = xpub(0x043587CF)
    exchange = from_descriptor(f"wpkh([f00dbabe/84h/1h/0h]{key}/<0;1>/*)")
    exchange.labels.append(Label("tx", "b" * 64, "Saved import label"))
    wallet_file = tmp_path / "imported.wallet"
    with main_window_context(test_config) as window:
        window.welcome_screen.set_wallet_name("Imported")
        window.click_import_wallet()
        node = window.tab_wallets.currentNode()
        assert node is not None and isinstance(node.data, WalletFileImportScreen)
        screen = node.data
        assert window.tab_wallets.stack.currentWidget() is screen
        screen.on_loaded([exchange])
        with (
            patch(
                "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch(
                "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning",
                return_value=QMessageBox.StandardButton.Ok,
            ),
            patch(
                "bitcoin_safe.gui.qt.qt_wallet.QFileDialog.getSaveFileName",
                return_value=(str(wallet_file), ""),
            ),
            patch("bitcoin_safe.gui.qt.qt_wallet.PasswordCreation.get_password", return_value=""),
            patch("bitcoin_safe.gui.qt.qt_wallet.QTWallet.sync"),
        ):
            screen.prepare_import()
        assert wallet_file.is_file()
        assert "Saved import label" in wallet_file.read_text()
        assert window.qt_wallets["Imported"].wallet.labels.data["b" * 64].label == "Saved import label"
        assert window.tab_wallets.root.findNodeByWidget(screen) is None


def test_bie2_explains_device_requirement_without_password_prompt(qtbot: QtBot, tmp_path: Path) -> None:
    import base64

    source = tmp_path / "electrum"
    source.write_bytes(base64.b64encode(b"BIE2" + b"e" * 81))
    dialog = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(dialog)
    dialog.wallet_path.setText(str(source))
    with (
        patch("bitcoin_safe.gui.qt.wallet_file_import.PasswordQuestion.ask_for_password") as password,
        patch("bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning") as warning,
    ):
        dialog.read_wallet()
    password.assert_not_called()
    assert "device" in warning.call_args.args[2].lower()


def test_label_field_only_for_formats_without_embedded_labels(qtbot: QtBot, tmp_path: Path) -> None:
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    labels = tmp_path / "labels.jsonl"
    labels.write_text('{"type":"tx","ref":"' + "a" * 64 + '","label":"external"}\n')
    screen.labels_path.setText(str(labels))
    for format_id in ("electrum", "sparrow", "specter"):
        choose_format(screen, format_id)
        assert not screen.form.isRowVisible(screen.labels_row)
    for format_id in ("wasabi", "ledger", "green"):
        choose_format(screen, format_id)
        assert screen.form.isRowVisible(screen.labels_row)
    choose_format(screen, "electrum")
    screen.on_loaded([from_descriptor(expressions()[2])])
    with (
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Ok,
        ),
        qtbot.waitSignal(screen.signal_import_ready) as imported,
    ):
        screen.prepare_import()
    assert not imported.args[1].labels


def test_back_and_busy_import_preserve_sidebar_lifecycle(qtbot: QtBot, test_config) -> None:
    from unittest.mock import Mock

    from tests.gui.qt.helpers import main_window_context

    with main_window_context(test_config) as window:
        window.click_import_wallet()
        node = window.tab_wallets.currentNode()
        assert node is not None and isinstance(node.data, WalletFileImportScreen)
        screen = node.data
        screen.worker = Mock()
        screen.signal_busy_changed.emit(True)
        assert not node.closable
        window.close_tab(node)
        assert window.tab_wallets.root.findNodeByWidget(screen) is node
        with patch("bitcoin_safe.gui.qt.main.Message"):
            assert window.wallet_import_in_progress()
        screen.worker = None
        screen.signal_busy_changed.emit(False)
        screen.cancel()
        assert window.tab_wallets.root.findNodeByWidget(screen) is None


def test_encrypted_ledger_import_prompts_and_recovers_signer_origin(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    import json

    from tests.non_gui.wallet_import.test_ledger_live_native_password import (
        node_encrypt_accounts,
        rows_fixture,
    )

    password = "Ledger desktop password"
    source = tmp_path / "app.json"
    source.write_text(json.dumps({"data": {"accounts": node_encrypt_accounts(rows_fixture(), password)}}))
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "ledger")
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.wallet_file_import.discover_ledger_live_app_json",
        lambda: source,
    )
    assert not screen.form.isRowVisible(screen.wallet_row)
    with patch(
        "bitcoin_safe.gui.qt.wallet_file_import.PasswordQuestion.ask_for_password", return_value=password
    ) as prompt:
        screen.read_wallet()
        qtbot.waitUntil(lambda: screen.worker is None and screen.accounts.count() == 1, timeout=10000)
    prompt.assert_called_once()
    with (
        patch("bitcoin_safe.gui.qt.wallet_file_import.QInputDialog.getText", return_value=("F00DBABE", True)),
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Ok,
        ),
        qtbot.waitSignal(screen.signal_import_ready) as imported,
    ):
        screen.prepare_import()
    proto, exchange = imported.args
    assert proto.id == "Imported"
    assert exchange.keystores[0].fingerprint == "f00dbabe"
    assert exchange.keystores[0].key_origin == "m/84h/0h/0h"
    assert proto.to_multipath_descriptor() is not None


def test_cancel_ledger_password_and_invalid_fingerprint(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    import json

    from bitcoin_safe.wallet_import import from_ledger_account

    source = tmp_path / "app.json"
    source.write_text(json.dumps({"data": {"accounts": "locked"}}))
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "ledger")
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.wallet_file_import.discover_ledger_live_app_json",
        lambda: source,
    )
    assert not screen.form.isRowVisible(screen.wallet_row)
    with patch("bitcoin_safe.gui.qt.wallet_file_import.PasswordQuestion.ask_for_password", return_value=None):
        screen.read_wallet()
        qtbot.waitUntil(lambda: screen.worker is None, timeout=10000)
    assert screen.accounts.count() == 0
    screen.on_loaded(
        [from_ledger_account({"currencyId": "bitcoin", "xpub": xpub(), "derivationMode": "native_segwit"})]
    )
    with (
        patch("bitcoin_safe.gui.qt.wallet_file_import.QInputDialog.getText", return_value=("bad", True)),
        patch("bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning") as warning,
    ):
        screen.prepare_import()
    assert "fingerprint" in warning.call_args.args[2].lower()


def test_wasabi_public_data_imports_without_a_password(qtbot: QtBot, tmp_path: Path) -> None:
    import json

    source = tmp_path / "wasabi.json"
    source.write_text(
        json.dumps({"ExtPubKey": xpub(), "EncryptedSecret": "unused", "BlockchainState": {"Network": "Main"}})
    )
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "wasabi")
    screen.wallet_path.setText(str(source))
    with patch("bitcoin_safe.gui.qt.wallet_file_import.PasswordQuestion.ask_for_password") as prompt:
        screen.read_wallet()
        qtbot.waitUntil(lambda: screen.worker is None, timeout=10000)
    prompt.assert_not_called()
    assert screen.accounts.count() == 1
    assert not any("password" in warning.lower() for warning in screen.wallets[0].warnings)


def test_ledger_missing_path_is_requested_even_with_fingerprint(qtbot: QtBot) -> None:
    from bitcoin_safe.wallet_import import from_ledger_account

    exchange = from_ledger_account(
        {
            "currencyId": "bitcoin",
            "xpub": xpub(),
            "masterFingerprint": "f00dbabe",
            "derivationMode": "native_segwit",
        }
    )
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "ledger")
    screen.on_loaded([exchange])
    with (
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.QInputDialog.getText", return_value=("m/84h/0h/0h", True)
        ) as prompt,
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Ok,
        ),
        qtbot.waitSignal(screen.signal_import_ready) as imported,
    ):
        screen.prepare_import()
    prompt.assert_called_once()
    assert imported.args[1].keystores[0].key_origin == "m/84h/0h/0h"
    assert imported.args[0].keystores[0].key_origin == "m/84h/0h/0h"


def test_incorrect_ledger_password_can_be_retried(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    import json

    from tests.non_gui.wallet_import.test_ledger_live_native_password import (
        node_encrypt_accounts,
        rows_fixture,
    )

    source = tmp_path / "app.json"
    source.write_text(json.dumps({"data": {"accounts": node_encrypt_accounts(rows_fixture(), "correct")}}))
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "ledger")
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.wallet_file_import.discover_ledger_live_app_json",
        lambda: source,
    )
    assert not screen.form.isRowVisible(screen.wallet_row)
    with (
        patch(
            "bitcoin_safe.gui.qt.wallet_file_import.PasswordQuestion.ask_for_password",
            side_effect=["wrong", "correct"],
        ),
        patch("bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning") as warning,
    ):
        screen.read_wallet()
        qtbot.waitUntil(lambda: screen.worker is None, timeout=10000)
        assert screen.accounts.count() == 0
        assert "password" in warning.call_args.args[2].lower()
        screen.read_wallet()
        qtbot.waitUntil(lambda: screen.worker is None and screen.accounts.count() == 1, timeout=10000)


def test_missing_wallet_file_errors_are_actionable(qtbot: QtBot, tmp_path: Path) -> None:
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    with patch("bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning") as warning:
        screen.read_wallet()
        assert "choose a wallet file" in warning.call_args.args[2].lower()
        screen.wallet_path.setText(str(tmp_path))
        screen.read_wallet()
        assert "folder" in warning.call_args.args[2].lower()
        assert "21" not in warning.call_args.args[2]
        screen.wallet_path.setText(str(tmp_path / "missing.wallet"))
        screen.read_wallet()
        assert "could not be found" in warning.call_args.args[2].lower()
        with patch("pathlib.Path.open", side_effect=PermissionError):
            screen.read_wallet()
        assert "permissions" in warning.call_args.args[2].lower()


def test_green_login_file_is_not_offered_as_importable(qtbot: QtBot, tmp_path: Path) -> None:
    import json

    source = tmp_path / "wallet.json"
    source.write_text(json.dumps({"name": "Green", "deployment": "mainnet", "xpub_hash_id": "login"}))
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "green")
    assert "login files cannot be imported" in screen.format_help.text().lower()
    screen.wallet_path.setText(str(source))
    screen.read_wallet()
    qtbot.waitUntil(lambda: screen.worker is None, timeout=10000)
    assert screen.accounts.count() == 1
    assert not screen.import_button.isEnabled()
    assert "login information only" in screen.status.text().lower()


def test_green_compatible_descriptor_text_can_be_imported(qtbot: QtBot, tmp_path: Path) -> None:
    source = tmp_path / "green-descriptor.txt"
    source.write_text(expressions()[2])
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "green")
    screen.wallet_path.setText(str(source))
    screen.read_wallet()
    qtbot.waitUntil(lambda: screen.worker is None, timeout=10000)
    assert screen.import_button.isEnabled()
    assert screen.wallets[0].source_wallet == "blockstream-green"


def test_gnupg_is_not_advertised_as_a_wallet_format_feature(qtbot: QtBot) -> None:
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    for index in range(screen.format.count()):
        screen.format.setCurrentIndex(index)
        assert "gnupg" not in screen.format_help.text().lower()


def test_import_worker_reports_a_directory_without_system_error_number(qtbot: QtBot, tmp_path: Path) -> None:
    from bitcoin_safe.gui.qt.wallet_file_import import ImportWorker

    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    worker = ImportWorker(str(tmp_path), "electrum", None, screen)
    with qtbot.waitSignal(worker.failed) as failure:
        worker.run()
    assert "folder" in failure.args[0].lower()
    assert "21" not in failure.args[0]


def test_import_button_tracks_whether_selected_account_has_descriptor(qtbot: QtBot) -> None:
    from bitcoin_safe.wallet_import import WalletExchange

    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    screen.on_loaded([WalletExchange("example", "Incomplete"), from_descriptor(expressions()[2])])
    assert not screen.import_button.isEnabled()
    assert "cannot be imported" in screen.status.text().lower()
    screen.accounts.setCurrentIndex(1)
    assert screen.import_button.isEnabled()
    screen.accounts.setCurrentIndex(0)
    assert not screen.import_button.isEnabled()


def test_gnupg_wallet_file_is_not_prompted_as_native_encryption(qtbot: QtBot, tmp_path: Path) -> None:
    source = tmp_path / "accounts.json.gpg"
    source.write_bytes(b"\x8c\x0d" + b"not a native wallet format")
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    choose_format(screen, "specter")
    screen.wallet_path.setText(str(source))
    with (
        patch("bitcoin_safe.gui.qt.wallet_file_import.PasswordQuestion.ask_for_password") as password,
        patch("bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning") as warning,
    ):
        screen.read_wallet()
        qtbot.waitUntil(lambda: screen.worker is None, timeout=10000)
    password.assert_not_called()
    assert "binary wallet format not recognized" in warning.call_args.args[2].lower()


def test_electrum_origin_defaults_follow_script_and_network(qtbot: QtBot) -> None:
    from bitcoin_usb.address_types import AddressTypes

    from bitcoin_safe.wallet_import.electrum import from_electrum
    from tests.non_gui.wallet_import.test_electrum_cosigner_origins import electrum_multisig

    for network in (bdk.Network.BITCOIN, bdk.Network.TESTNET):
        for script, address_type in (("wsh", AddressTypes.p2wsh), ("sh-wsh", AddressTypes.p2sh_p2wsh)):
            screen = WalletFileImportScreen("Imported", network)
            qtbot.addWidget(screen)
            exchange = from_electrum(electrum_multisig())
            exchange.address_type = script
            with patch(
                "bitcoin_safe.gui.qt.wallet_file_import.QInputDialog.getText",
                side_effect=[("deadbeef", True), ("", False)],
            ) as prompt:
                assert not screen.complete_electrum_origins(exchange)
            assert not prompt.call_args_list[0].kwargs.get("text", "")
            assert "hardware signer" in prompt.call_args_list[0].args[2]
            assert prompt.call_args_list[1].kwargs["text"] == address_type.key_origin(network)


def test_import_warns_when_mainnet_seed_was_detected(qtbot: QtBot) -> None:
    exchange = from_descriptor(expressions()[2])
    exchange.keystores[0].recovery_material = "SEED_REDACTED"
    screen = WalletFileImportScreen("Imported", bdk.Network.BITCOIN)
    qtbot.addWidget(screen)
    screen.on_loaded([exchange])
    with patch(
        "bitcoin_safe.gui.qt.wallet_file_import.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Cancel,
    ) as warning:
        screen.prepare_import()
    assert "mainnet seed" in warning.call_args.args[2]
    assert "not retained or imported" in warning.call_args.args[2]

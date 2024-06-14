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


import logging

from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget
from bitcoin_safe.gui.qt.dialogs import question_dialog
from bitcoin_safe.signals import SignalsMin

logger = logging.getLogger(__name__)

from typing import Callable, List

from ...descriptors import AddressType
from ...wallet import ProtoWallet
from .keystore_ui import KeyStoreUI, icon_for_label


class KeyStoreUIs(DataTabWidget):
    def __init__(
        self,
        get_editable_protowallet: Callable[[], ProtoWallet],
        get_address_type: Callable[[], AddressType],
        signals_min: SignalsMin,
    ) -> None:
        super().__init__()
        self.signals_min = signals_min

        self.get_editable_protowallet = get_editable_protowallet
        self.get_address_type = get_address_type

        self.keystore_uis: List[KeyStoreUI] = []

        for i, keystore in enumerate(self.protowallet.keystores):
            keystore_ui = KeyStoreUI(
                keystore,
                self,
                self.protowallet.network,
                get_address_type=self.get_address_type,
                label=self.protowallet.signer_name(i),
                signals_min=signals_min,
            )
            self.keystore_uis.append(keystore_ui)

        for signal in (
            [ui.edit_xpub.input_field.textChanged for ui in self.keystore_uis]
            + [ui.edit_fingerprint.input_field.textChanged for ui in self.keystore_uis]
            + [ui.edit_key_origin.input_field.textChanged for ui in self.keystore_uis]
        ):
            signal.connect(self.ui_keystore_ui_change)
        for ui in self.keystore_uis:
            ui.edit_seed.input_field.textChanged.connect(self.ui_keystore_ui_change)

        self.signals_min.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        # udpate the label for where the keystore exists
        for i, keystore in enumerate(self.protowallet.keystores):
            if not keystore:
                continue
            keystore.label = self.protowallet.signer_name(i)

        self._set_keystore_tabs()

    @property
    def protowallet(self) -> ProtoWallet:
        return self.get_editable_protowallet()

    def ui_keystore_ui_change(self, *args) -> None:
        logger.debug("ui_keystore_ui_change")
        try:
            self.set_protowallet_from_keystore_ui()
            self.set_keystore_ui_from_protowallet()
        except:
            logger.warning("ui_keystore_ui_change: Invalid input")

    def set_protowallet_from_keystore_ui(self) -> None:

        # and last are the keystore uis, which can cause exceptions, because the UI is not filled correctly
        for i, keystore_ui in enumerate(self.keystore_uis):
            logger.debug(f"set_keystore_from_ui_values in {keystore_ui.label}")
            ui_keystore = keystore_ui.get_ui_values_as_keystore()

            keystore = self.protowallet.keystores[i]
            if keystore is None:
                keystore = ui_keystore
                self.protowallet.keystores[i] = keystore
            else:
                keystore.from_other_keystore(ui_keystore)

        for i, keystore in enumerate(self.protowallet.keystores):
            if keystore is None:
                continue
            keystore.label = self.protowallet.signer_names(self.protowallet.threshold, i)

    def _set_keystore_tabs(self) -> None:
        # add keystore_ui if necessary
        if len(self.keystore_uis) < len(self.protowallet.keystores):
            for i in range(len(self.keystore_uis), len(self.protowallet.keystores)):
                self.keystore_uis.append(
                    KeyStoreUI(
                        self.protowallet.keystores[i],
                        self,
                        self.protowallet.network,
                        get_address_type=self.get_address_type,
                        label=self.protowallet.signer_name(i),
                        signals_min=self.signals_min,
                    )
                )
        # remove keystore_ui if necessary
        elif len(self.keystore_uis) > len(self.protowallet.keystores):
            for i in range(len(self.protowallet.keystores), len(self.keystore_uis)):
                self.keystore_uis[-1].remove_tab()
                self.keystore_uis.pop()

        # now make a second pass and connect point the keystore_ui.keystore correctly
        for i, (keystore, keystore_ui) in enumerate(zip(self.protowallet.keystores, self.keystore_uis)):
            if keystore_ui.keystore and keystore:
                keystore_ui.keystore.from_other_keystore(keystore)
            elif keystore:
                keystore_ui.keystore = keystore.clone()
            elif keystore_ui:
                # keystore is None
                # so don't I cant set aynthing here except the ui label
                keystore_ui.label = self.protowallet.signer_name(i)
            else:
                # keystore is None
                # so don't I cant set aynthing here except the ui label
                pass

            # set the tab title
            index = keystore_ui.tabs.indexOf(keystore_ui.tab)
            self.setTabText(index, keystore_ui.label)
            self.setTabIcon(index, icon_for_label(keystore_ui.label))

    def set_keystore_ui_from_protowallet(self) -> None:
        logger.debug(f"set_keystore_ui_from_protowallet")
        self._set_keystore_tabs()
        for keystore, keystore_ui in zip(self.protowallet.keystores, self.keystore_uis):
            if not keystore:
                continue
            keystore_ui.set_ui_from_keystore(keystore)
            # i have to manually call this, because the signals are blocked
            keystore_ui.format_all_fields()
        assert len(self.protowallet.keystores) == len(self.keystore_uis)

    def get_keystore_uis_with_unexpected_origin(self) -> List[KeyStoreUI]:
        return [
            keystore_ui
            for keystore_ui in self.keystore_uis
            if keystore_ui.key_origin != keystore_ui.get_expected_key_origin()
        ]

    def ask_accept_unexpected_origins(self) -> bool:
        keystore_uis_with_unexpected_origin = self.get_keystore_uis_with_unexpected_origin()
        for keystore_ui in keystore_uis_with_unexpected_origin:
            if not question_dialog(
                f"The key derivation path {keystore_ui.key_origin} of {keystore_ui.label} is not the default {keystore_ui.get_expected_key_origin()} for the address type {keystore_ui.get_address_type().name}. Do you want to proceed anyway?"
            ):
                return False
        return True

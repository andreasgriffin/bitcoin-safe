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

from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.register_multisig import RegisterMultisigInteractionWidget
from bitcoin_safe.hardware_signers import HardwareSigners


def test_register_multisig_title_uses_wallet_name_when_signer_unknown(qtbot: QtBot) -> None:
    widget = RegisterMultisigInteractionWidget(
        wallet_functions=None,
        wallet=None,
        loop_in_thread=None,
        hardware_signer=None,
        wallet_name="MultiSig 001",
    )
    qtbot.addWidget(widget)

    assert widget.windowTitle() == "Register 'MultiSig 001'"


def test_register_multisig_title_includes_signer_name_when_known(qtbot: QtBot) -> None:
    widget = RegisterMultisigInteractionWidget(
        wallet_functions=None,
        wallet=None,
        loop_in_thread=None,
        hardware_signer=HardwareSigners.jade,
        wallet_name="MultiSig 001",
    )
    qtbot.addWidget(widget)

    assert widget.windowTitle() == "Register 'MultiSig 001' to 'Jade'"
    assert "every external signer you plan to use" in widget.registration_info_label.text()

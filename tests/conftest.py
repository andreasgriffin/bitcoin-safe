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


import pytest

from bitcoin_safe.logging_setup import setup_logging
from tests.gui.qt.helpers import mytest_start_time  # type: ignore

setup_logging()

from bitcoin_safe.gui.qt import custom_edits

from .gui.qt.helpers import mytest_start_time  # type: ignore
from .helpers import test_config_main_chain  # type: ignore
from .helpers import test_config, test_config_session  # type: ignore
from .non_gui.test_wallet_coin_select import test_wallet_config  # type: ignore
from .setup_bitcoin_core import bitcoin_core  # type: ignore
from .setup_fulcrum import Faucet, faucet, fulcrum  # type: ignore


@pytest.fixture(autouse=True)
def override_global_constant(monkeypatch):
    """
    Runs once, before any tests, and patches GLOBAL_CONSTANT
    in mypackage.some_module for every test.
    """
    monkeypatch.setattr(custom_edits, "ENABLE_COMPLETERS", False, raising=True)
    # no yield needed if you don’t need teardown

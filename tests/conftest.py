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

from __future__ import annotations

import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread

from bitcoin_safe.logging_setup import setup_logging
from tests.gui.qt.helpers import mytest_start_time

setup_logging()

from bitcoin_safe.gui.qt import custom_edits

from .faucet import Faucet, faucet, faucet_session
from .gui.qt.helpers import mytest_start_time
from .helpers import (
    test_config,
    test_config_main_chain,
    test_config_session,
)
from .non_gui.test_wallet_coin_select import test_funded_wallet_session, test_wallet_config
from .setup_bitcoin_core import bitcoin_core
from .setup_fulcrum import fulcrum

pytestmark = pytest.mark.usefixtures("backend_marker")


def pytest_addoption(parser):
    group = parser.getgroup("bitcoin-safe")
    group.addoption(
        "--fulcrum",
        action="store_true",
        default=False,
        help="Run tests against the Fulcrum/Electrum backend",
    )
    group.addoption(
        "--cbf",
        action="store_true",
        default=False,
        help="Run tests against the Compact Block Filters backend",
    )


def _selected_backends(config) -> list[str]:
    selected = []
    if config.getoption("--fulcrum"):
        selected.append("fulcrum")
    if config.getoption("--cbf"):
        selected.append("cbf")
    if not selected:
        selected = ["cbf"]
    return selected


def pytest_generate_tests(metafunc):
    if "backend" in metafunc.fixturenames:
        metafunc.parametrize("backend", _selected_backends(metafunc.config), scope="session")


@pytest.fixture(scope="session")
def backend(request) -> str:
    """Selected blockchain backend for the test session."""
    return request.param


@pytest.fixture(scope="session")
def backend_marker(backend: str) -> str:
    """Ensure the backend fixture is part of every test run."""
    return backend


@pytest.fixture(scope="session")
def loop_in_thread() -> LoopInThread:
    return LoopInThread()


@pytest.fixture(autouse=True)
def override_global_constant(monkeypatch):
    """Runs once, before any tests, and patches GLOBAL_CONSTANT in mypackage.some_module
    for every test."""
    monkeypatch.setattr(custom_edits, "ENABLE_COMPLETERS", False, raising=True)
    # no yield needed if you don’t need teardown

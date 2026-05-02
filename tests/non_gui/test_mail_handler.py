#
# Bitcoin Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import logging
import sys
from unittest.mock import patch

from _pytest.logging import LogCaptureFixture

from bitcoin_safe.logging_handlers import mail_error_repot, text_error_report

logger = logging.getLogger(__name__)


def test_no_error_logging(caplog: LogCaptureFixture) -> None:
    """Test no error logging."""
    with patch("bitcoin_safe.logging_handlers.compose_email") as mock_compose_email:
        mock_compose_email.return_value = "Mocked Function"

        with caplog.at_level(logging.INFO):
            try:
                int("aaa")
            except Exception as e:
                # Log without exc_info; should not trigger email compose.
                logger.error(str(e))

            # Check that no exc_info is included
            assert not caplog.records[-1].exc_info

            mock_compose_email.assert_not_called()


def test_exception_logging(caplog: LogCaptureFixture) -> None:
    """Test exception logging."""
    with patch("bitcoin_safe.logging_handlers.OpenLogHandler.emit") as mock_OpenLogHandler_emit:
        mock_OpenLogHandler_emit.return_value = "Mocked OpenLogHandler.emit"
        with patch("bitcoin_safe.logging_handlers.compose_email") as mock_compose_email:
            mock_compose_email.return_value = "Mocked Function"

            with caplog.at_level(logging.INFO):
                # Logging with exc_info should trigger email composition and handler emit.
                logger.critical("this should compose an email", exc_info=sys.exc_info())

                # Assert that the mocked function was called
                mock_compose_email.assert_called_once()
                # Assert that the mocked function was called
                mock_OpenLogHandler_emit.assert_called_once()


def test_text_error_report_includes_plugin_diagnostics() -> None:
    with patch(
        "bitcoin_safe.logging_handlers.format_external_plugin_diagnostics_as_text"
    ) as mock_plugin_diagnostics:
        mock_plugin_diagnostics.return_value = "External Plugins:\n- sentinel"

        report = text_error_report("boom")

    assert "External Plugins:\n- sentinel" in report


def test_mail_error_repot_includes_plugin_diagnostics() -> None:
    with patch("bitcoin_safe.logging_handlers.compose_email") as mock_compose_email:
        with patch(
            "bitcoin_safe.logging_handlers.format_external_plugin_diagnostics_as_text"
        ) as mock_plugin_diagnostics:
            mock_compose_email.return_value = "Mocked Function"
            mock_plugin_diagnostics.return_value = "External Plugins:\n- sentinel"

            mail_error_repot("boom")

    assert mock_compose_email.call_count == 1
    assert "External Plugins:\n- sentinel" in mock_compose_email.call_args.args[2]

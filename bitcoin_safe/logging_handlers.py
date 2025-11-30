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

import logging
import os
import platform
import sys
import tempfile
from pathlib import Path
from types import TracebackType

from bitcoin_safe_lib.util_os import xdg_open_file

from bitcoin_safe import __version__

from .simple_mailer import compose_email


def remove_absolute_paths(line: str) -> str:
    """Replaces absolute paths in a traceback line with relative ones, based on the
    current script's execution path."""
    current_path = os.getcwd() + os.sep
    return line.replace(current_path, "")


def get_system_info_as_text() -> str:
    """Get system info as text."""
    distro_name = "Unknown"
    distro_version = ""

    if hasattr(platform, "freedesktop_os_release"):
        try:
            os_release_info = platform.freedesktop_os_release()
            distro_name = os_release_info.get("NAME", "Unknown")
            distro_version = os_release_info.get("VERSION", "")
        except Exception:
            pass

    body = "\n\nSystem Info:\n"
    body += f"OS: {platform.platform()}\n"
    body += f"Distribution: {distro_name} {distro_version}\n"
    body += f"Python Version: {sys.version}\n"
    body += f"Bitcoin Safe Version: {__version__}\n\n"
    return body


def text_error_report(error_report: str, file_path: Path | None = None) -> str:
    """Text error report."""
    email = "andreasgriffin@proton.me"
    subject = f"Error report - Bitcoin Safe Version: {__version__}"
    body = ""
    if file_path:
        body += f"You can see the full logfile at: {file_path}\n\n"

    body += f"Please email this to: {email}\n\n"
    body += f"{subject}\n\n"
    body += f"""Error:
            {error_report}
            """.replace("    ", "")

    # Write additional system info if needed
    body += get_system_info_as_text()
    return body


def mail_error_repot(error_report: str) -> None:
    """Mail error repot."""
    email = "andreasgriffin@proton.me"
    subject = f"Error report - Bitcoin Safe Version: {__version__}"
    body = f"""Error:
            {error_report}
            """.replace("    ", "")

    body += get_system_info_as_text()
    return compose_email(email, subject, body)


def mail_feedback() -> None:
    """Mail feedback."""
    email = "andreasgriffin@proton.me"
    subject = f"Feedback - Bitcoin Safe Version: {__version__}"
    body = ""

    body += get_system_info_as_text()
    return compose_email(email, subject, body)


def mail_contact() -> None:
    """Mail feedback."""
    email = "andreasgriffin@proton.me"
    subject = "Contact"
    body = ""

    return compose_email(email, subject, body)


class RelativePathFormatter(logging.Formatter):
    def formatException(
        self, ei: tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]
    ) -> str:
        """FormatException."""
        return remove_absolute_paths(super().formatException(ei))

    def format(self, record) -> str:
        """Format."""
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info)
        return super().format(record)


class MailHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET, must_include_exc_info=True) -> None:
        """Initialize instance."""
        super().__init__(level)
        self.must_include_exc_info = must_include_exc_info

    def emit(self, record) -> None:
        """'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename', 'funcName',
        'getMessage', 'levelname', 'levelno', 'lineno', 'message', 'module', 'msecs',
        'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated',
        'stack_info', 'thread', 'threadName."""

        if (self.must_include_exc_info and record.exc_info) or not self.must_include_exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info  # type: ignore

            message = str(self.format(record))
            mail_error_repot(message)


class OpenLogHandler(logging.Handler):
    def __init__(self, file_path: Path, level=logging.CRITICAL) -> None:
        """Initialize instance."""
        super().__init__(level)
        self.file_path = file_path

    def emit(self, record) -> None:
        """Emit."""
        message = text_error_report(str(self.format(record)), file_path=self.file_path)

        # Create a temporary file with a message to the user
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt") as temp_file:
            temp_file.write(message)
            temp_file_path = temp_file.name

        xdg_open_file(Path(temp_file_path), is_text_file=True)

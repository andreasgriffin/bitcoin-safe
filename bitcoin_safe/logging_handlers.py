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
import os
import platform
import sys

from bitcoin_safe import __version__

from .simple_mailer import compose_email


def remove_absolute_paths(line: str) -> str:
    """
    Replaces absolute paths in a traceback line with relative ones,
    based on the current script's execution path.
    """
    current_path = os.getcwd() + os.sep
    return line.replace(current_path, "")


def mail_error_repot(error_report: str) -> None:
    email = "andreasgriffin@proton.me"
    subject = f"Error report - Bitcoin Safe Version: {__version__}"
    body = f"""Error:
            {error_report}
            """.replace(
        "    ", ""
    )

    # Write additional system info if needed
    body += "\n\nSystem Info:\n"
    body += f"OS: {platform.platform()}\n"
    body += f"Python Version: {sys.version}\n"
    body += f"Bitcoin Safe Version: {__version__}\n\n"
    return compose_email(email, subject, body)


class RelativePathFormatter(logging.Formatter):
    def formatException(self, exc_info) -> str:
        return remove_absolute_paths(super().formatException(exc_info))

    def format(self, record) -> str:
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info)
        return super().format(record)


class MailHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET, must_include_exc_info=True) -> None:
        super().__init__(level)
        self.must_include_exc_info = must_include_exc_info

    def emit(self, record) -> None:
        """'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'getMessage', 'levelname', 'levelno', 'lineno', 'message', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'stack_info', 'thread', 'threadName"""

        if (self.must_include_exc_info and record.exc_info) or not self.must_include_exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info  # type: ignore

            message = str(self.format(record))
            mail_error_repot(message)

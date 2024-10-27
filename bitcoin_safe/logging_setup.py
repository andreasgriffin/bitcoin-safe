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
import logging.config
import logging.handlers
import platform
import sys
from pathlib import Path

import appdirs

from bitcoin_safe import __version__
from bitcoin_safe.logging_handlers import MailHandler, RelativePathFormatter


def setup_logging() -> None:

    # Configuring formatters
    relative_path_formatter = RelativePathFormatter(
        fmt="%(asctime)s - %(levelname)s - [%(threadName)s] - %(name)s - %(message)s"
    )

    # Configuring handlers
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(relative_path_formatter)

    app_name = "bitcoin_safe"
    config_dir = Path(appdirs.user_config_dir(app_name))
    config_dir.mkdir(parents=True, exist_ok=True)

    log_file = config_dir / ".bitcoin_safe.log"
    file_handler = logging.handlers.RotatingFileHandler(filename=log_file, maxBytes=1000000, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(relative_path_formatter)

    custom_handler = (
        MailHandler()
    )  # Assuming MailHandler is correctly implemented in bitcoin_safe.logging_handlers
    custom_handler.setLevel(logging.CRITICAL)
    custom_handler.setFormatter(relative_path_formatter)
    # Assuming 'must_include_exc_info' is handled internally in the MailHandler implementation

    # Configuring loggers
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(custom_handler)
    root_logger.propagate = True

    logger = logging.getLogger(__name__)

    # Set the function to handle uncaught exceptions
    def handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_uncaught_exception

    logger.info(f"========================= Starting Bitcoin Safe ========================")
    logger.info(f"Version: {__version__}")
    logger.info(f"Python version: {sys.version}. On platform: {describe_os_version()}")
    # logger.info(f"Logging to file: {str(logger.handlers[-1].filename)}")
    logger.info(f"Logging {logging.DEBUG} to {log_file}")


def describe_os_version() -> str:
    return platform.platform()


setup_logging()

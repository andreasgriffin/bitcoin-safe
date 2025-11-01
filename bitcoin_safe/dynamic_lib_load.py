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

import certifi

logger = logging.getLogger(__name__)


def set_os_env_ssl_certs():
    """Set os env ssl certs."""
    os.environ["SSL_CERT_FILE"] = certifi.where()


def ensure_pyzbar_works() -> None:
    # Get the platform-specific path to the binary library
    """Ensure pyzbar works."""
    logger.info(f"Platform: {platform.system()}")
    if platform.system() == "Windows":
        # Determine the base path:
        if hasattr(sys, "_MEIPASS"):
            # Running as a PyInstaller bundle; _MEIPASS is the temporary folder
            base_path = sys._MEIPASS  # type: ignore
        else:
            # Otherwise, use the directory of this script
            base_path = os.path.dirname(os.path.abspath(__file__))

        # Construct the path to the libzbar-0.dll in the base_path=_internal subfolder
        libzbar_dll_path = os.path.join(base_path, "libzbar-64.dll")

        # Set the PYZBAR_LIBRARY environment variable for pyzbar to load the DLL
        os.environ["PYZBAR_LIBRARY"] = os.path.abspath(libzbar_dll_path)
        logger.debug(f"set PYZBAR_LIBRARY={os.environ['PYZBAR_LIBRARY']}")

        try:
            from pyzbar import pyzbar

            pyzbar.__name__  # noqa: B018
            logger.info("pyzbar successfully loaded ")
        except (
            Exception
        ) as e:  #  Do not restrict it to FileNotFoundError, because it can cause other exceptions
            logger.debug(str(e))
            logger.warning("pyzbar could not be loaded ")
    elif platform.system() == "Darwin":
        # Compute the absolute path of the current file
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # Construct the path to libzbar.dylib relative to the current file.
        # This goes one directory up (to Contents) and then into Frameworks.
        libzbar_path = os.path.join(current_dir, "..", "Frameworks", "libzbar.dylib")

        # Set the environment variable
        os.environ["PYZBAR_LIBRARY"] = os.path.abspath(libzbar_path)

        logger.debug(f"set PYZBAR_LIBRARY={os.environ['PYZBAR_LIBRARY']}")

    elif platform.system() == "Linux":
        # On Linux it seems to find the lib
        pass
    else:
        logger.warning("Unknown OS")

    # check pyzbar no matter what
    try:
        from pyzbar import pyzbar

        logger.info("pyzbar could be loaded successfully")
    except Exception:
        logger.warning("failed to load pyzbar")

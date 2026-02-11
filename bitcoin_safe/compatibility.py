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
import platform

from bitcoin_safe.gui.qt.util import caught_exception_message

from .util import fast_version

logger = logging.getLogger(__name__)


def check_compatibility():
    # Only enforce on macOS
    """Check compatibility."""
    if platform.system().lower() != "darwin":
        return

    # Get the macOS version string, e.g. "14.0.1" or "13.4.1"
    ver_str = platform.mac_ver()[0]
    if not ver_str:
        logger.error("Unable to determine macOS version")

    current_ver = fast_version(ver_str)

    # Detect CPU architecture
    arch = platform.machine().lower()  # "arm64" or "x86_64" typically

    # Define minimum required versions
    required_ver = fast_version("13.0")  # this depends on the github runner
    if arch == "arm64":
        required_ver = fast_version("14.0")  # this depends on the github runner
    elif arch == "x86_64":
        required_ver = fast_version("13.0")  # this depends on the github runner
    else:
        logger.error(RuntimeError(f"Unsupported architecture: {arch!r}"))

    # Compare
    if current_ver < required_ver:
        caught_exception_message(
            RuntimeError(
                f"Unsupported macOS version: {current_ver} on {arch!r} — "
                f"requires macOS {required_ver} or newer."
            ),
            parent=None,
        )


if __name__ == "__main__":
    check_compatibility()

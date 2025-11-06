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
from dataclasses import dataclass

from bitcoin_usb.address_types import DescriptorInfo

logger = logging.getLogger(__name__)


@dataclass
class PluginConditions:
    """If a condition is None, it means it is not active."""

    # allowed_address_types:List[ AddressType]|None =None
    # disallowed_address_types:List[ AddressType]|None =None

    min_allowed_signers: int | None = None
    max_allowed_signers: int | None = None

    # min_allowed_threshold:int|None =None
    # max_allowed_threshold:int|None =None

    def descriptor_allowed(self, descriptor: str) -> bool:
        """Descriptor allowed."""
        descriptor_info = DescriptorInfo.from_str(descriptor)
        if (self.min_allowed_signers is not None) and not (
            self.min_allowed_signers <= len(descriptor_info.spk_providers)
        ):
            return False
        if (self.max_allowed_signers is not None) and not (
            len(descriptor_info.spk_providers) <= self.max_allowed_signers
        ):
            return False
        return True

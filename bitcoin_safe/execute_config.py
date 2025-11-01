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

IS_PRODUCTION = True  # change this for testing

DEMO_MODE = False
DEFAULT_MAINNET = IS_PRODUCTION
ENABLE_THREADING = True
ENABLE_PLUGINS = True
ENABLE_TIMERS = True
DEFAULT_LANG_CODE = "en_US"
MEMPOOL_SCHEDULE_TIMER = 10 * 60 * 1000 if IS_PRODUCTION else 1 * 60 * 1000
GENERAL_RBF_AVAILABLE = False
DONATION_ADDRESS = "bc1qs8vxaclc0ncf92nrhc4rcdgppwganny6mpn9d4"

if IS_PRODUCTION:
    if not ENABLE_TIMERS:
        raise ValueError("Timers must be enabled for production")
    if not ENABLE_THREADING:
        raise ValueError("Threading must be enabled for production")
    if DEMO_MODE:
        raise ValueError("Cannot be in demo mode for production")

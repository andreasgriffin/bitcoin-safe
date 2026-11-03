#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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

from bitcoin_safe.plugin_framework.plugin_btcpay_manifest import BtcpayManifestConfig

TEST_BUSINESS_PLAN_ID = "plan_4JmXn9YxbMbTv75dNK"
TEST_SCHEDULE_PLAN_ID = "plan_E8A8xrESQqhG4UGXga"
TEST_MONTHLY_PLAN_ID = "plan_JCvJEumcQBEDrxHgs4"
TEST_YEARLY_PLAN_ID = "plan_6GdwKTCXLDtSMR8WL1"

TEST_BTCPAY_SUBSCRIPTION_CONFIG = BtcpayManifestConfig(
    plan_ids=(TEST_MONTHLY_PLAN_ID, TEST_YEARLY_PLAN_ID),
)

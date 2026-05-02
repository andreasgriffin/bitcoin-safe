#
# Bitcoin Safe
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

from btcpay_tools.config import BTCPayConfig

_BTCPAY_CONFIG_YAML = """
btcpay_base:
  base_url: "https://pay.bitcoin-safe.org"
  pos_app_id: "U59nqzCsTq9vECCHaxiXwnwoSmL"
  store_id: "7agECo6zfJRp4Thi8vnBCjCoopb2yrnstaA5FophRfJe"

products:
  business-plan:
    - offering_id: offering_Lnh3PrdKrZgn9XnzQh
      plan_id: plan_JqASqLMXqgzzQoCopE
      pos_id: business-plan
      trial_pos_id: business-plan-trial
      duration: year

client:
  npub_bitcoin_safe_pos: npub150ncc39ala3h9zudddrjqy9f7wenp7d20rjm99wchwtkdpze07wqukr9cu
"""

BTCPAY_SUBSCRIPTION_CONFIG = BTCPayConfig.loads(_BTCPAY_CONFIG_YAML)

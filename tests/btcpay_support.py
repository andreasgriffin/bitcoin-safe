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

TEST_BTCPAY_CONFIG_YAML = """
btcpay_base:
  base_url: https://testnet.demo.btcpayserver.org
  pos_app_id: 3sgZmTZfKP8mRQciCqNh6g5F1G1s
  store_id: 98rXQCLFR3jmjbh5V5BomnqKJT5xC9kYejFRJHfmLWBq

products:
  demo-plugin:
    - offering_id: offering_89j5mBhvUYuvFfxNL1
      plan_id: plan_Bqm6FpomH4TvZLj113
      pos_id: demo-plugin
      trial_pos_id: demo-plugin-trial
      duration: month
    - offering_id: offering_89j5mBhvUYuvFfxNL1
      plan_id: plan_C777vfiXKT7okGGzSs
      pos_id: demo-plugin-yearly
      trial_pos_id: demo-plugin-yearly-trial
      duration: year
  business-plan:
    - offering_id: offering_CLbpG77sJMWjoM9jB4
      plan_id: plan_7TezijGHpX3wzZRhbV
      pos_id: business-plan
      trial_pos_id: business-plan-trial
      duration: year

client:
  npub_bitcoin_safe_pos: npub150ncc39ala3h9zudddrjqy9f7wenp7d20rjm99wchwtkdpze07wqukr9cu
"""

TEST_BTCPAY_SUBSCRIPTION_CONFIG = BTCPayConfig.loads(TEST_BTCPAY_CONFIG_YAML)

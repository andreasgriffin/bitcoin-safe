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

import ipaddress
import json

from bitcoin_safe.geoip_rough import RoughGeoIpDatabase


def test_lookup_ipv4_and_ipv6(tmp_path) -> None:
    ipv4_key = int(ipaddress.ip_address("8.8.8.8")) >> (32 - 12)
    ipv6_key = int(ipaddress.ip_address("2001:4860:4860::8888")) >> (128 - 32)

    db_file = tmp_path / "geoip_rough_v1.json"
    db_file.write_text(
        json.dumps(
            {
                "prefix_lengths": {"ipv4": 12, "ipv6": 32},
                "ipv4": {str(ipv4_key): [52.52, 13.4, "DE"]},
                "ipv6": {str(ipv6_key): [37.77, -122.41, "US"]},
            }
        ),
        encoding="utf-8",
    )

    db = RoughGeoIpDatabase(db_path=db_file)

    location_v4 = db.lookup_host("8.8.8.8")
    assert location_v4
    assert location_v4.country_code == "DE"

    location_v6 = db.lookup_host("2001:4860:4860::8888")
    assert location_v6
    assert location_v6.country_code == "US"


def test_missing_db_returns_none(tmp_path) -> None:
    db = RoughGeoIpDatabase(db_path=tmp_path / "missing.json")
    assert db.lookup_host("8.8.8.8") is None

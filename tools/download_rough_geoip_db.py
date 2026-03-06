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

import argparse
import csv
import gzip
import io
import ipaddress
import json
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DBIP_CITY_LITE_PAGE_URL = "https://db-ip.com/db/download/ip-to-city-lite"
NATURAL_EARTH_COUNTRIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_countries.geojson"
)
DBIP_CITY_CSV_REGEX = re.compile(
    r"https://download\\.db-ip\\.com/free/dbip-city-lite-\\d{4}-\\d{2}\\.csv\\.gz"
)
DEFAULT_USER_AGENT = "bitcoin-safe-geoip-downloader/1.0 (+https://github.com/andreasgriffin/bitcoin-safe)"


@dataclass(frozen=True)
class DbIpCityLiteRow:
    start_ip: str
    country_code: str
    state_name: str | None
    latitude: float | None
    longitude: float | None


def open_url(url: str, timeout: int):
    request = urllib.request.Request(url=url, headers={"User-Agent": DEFAULT_USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_text(url: str) -> str:
    with open_url(url, timeout=60) as response:
        return response.read().decode("utf-8")


def extract_dbip_city_csv_url(download_page_html: str) -> str:
    matches = DBIP_CITY_CSV_REGEX.findall(download_page_html)
    if matches:
        return sorted(set(matches))[-1]
    return discover_dbip_city_csv_url()


def discover_dbip_city_csv_url(look_back_months: int = 24) -> str:
    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month

    for _ in range(look_back_months):
        candidate = f"https://download.db-ip.com/free/dbip-city-lite-{year:04d}-{month:02d}.csv.gz"
        if url_exists(candidate):
            return candidate

        month -= 1
        if month == 0:
            month = 12
            year -= 1

    raise RuntimeError("Could not discover DB-IP city-lite CSV URL")


def download_to_temp_file(url: str) -> Path:
    with open_url(url, timeout=180) as response:
        with tempfile.NamedTemporaryFile(
            prefix="dbip-city-lite-", suffix=".csv.gz", delete=False
        ) as temp_file:
            shutil.copyfileobj(response, temp_file)
            return Path(temp_file.name)


def parse_dbip_city_lite_row(row: list[str]) -> DbIpCityLiteRow | None:
    if len(row) < 8:
        return None

    start_ip = row[0].strip()
    # DB-IP city-lite columns:
    # [0]=start_ip, [1]=end_ip, [2]=continent_code, [3]=country_code,
    # [4]=state/province, [5]=city, [6]=latitude, [7]=longitude
    country_code = row[3].strip().upper()
    if len(country_code) != 2:
        return None

    state_raw = row[4].strip()
    state_name = state_raw or None

    latitude: float | None = None
    longitude: float | None = None
    raw_latitude = row[6].strip()
    raw_longitude = row[7].strip()
    if raw_latitude and raw_longitude:
        try:
            latitude = float(raw_latitude)
            longitude = float(raw_longitude)
        except ValueError:
            latitude = None
            longitude = None

    return DbIpCityLiteRow(
        start_ip=start_ip,
        country_code=country_code,
        state_name=state_name,
        latitude=latitude,
        longitude=longitude,
    )


def iter_dbip_city_lite_rows(csv_gzip_path: Path):
    with csv_gzip_path.open("rb") as file_handle:
        with gzip.GzipFile(fileobj=file_handle) as zipped:
            text_stream = io.TextIOWrapper(zipped, encoding="utf-8", newline="")
            reader = csv.reader(text_stream)
            for row in reader:
                parsed = parse_dbip_city_lite_row(row)
                if parsed:
                    yield parsed


def compute_state_centroids(
    csv_gzip_path: Path,
) -> tuple[dict[tuple[str, str], tuple[float, float]], dict[str, tuple[float, float]]]:
    state_sums: dict[tuple[str, str], tuple[float, float, int]] = {}
    country_sums: dict[str, tuple[float, float, int]] = {}

    for row in iter_dbip_city_lite_rows(csv_gzip_path):
        if row.latitude is None or row.longitude is None:
            continue

        country_sum = country_sums.get(row.country_code)
        if not country_sum:
            country_sums[row.country_code] = (row.latitude, row.longitude, 1)
        else:
            country_sums[row.country_code] = (
                country_sum[0] + row.latitude,
                country_sum[1] + row.longitude,
                country_sum[2] + 1,
            )

        if not row.state_name:
            continue

        state_key = (row.country_code, row.state_name)
        state_sum = state_sums.get(state_key)
        if not state_sum:
            state_sums[state_key] = (row.latitude, row.longitude, 1)
        else:
            state_sums[state_key] = (
                state_sum[0] + row.latitude,
                state_sum[1] + row.longitude,
                state_sum[2] + 1,
            )

    state_centroids = {
        key: (lat_sum / count, lon_sum / count)
        for key, (lat_sum, lon_sum, count) in state_sums.items()
        if count > 0
    }
    country_centroids = {
        key: (lat_sum / count, lon_sum / count)
        for key, (lat_sum, lon_sum, count) in country_sums.items()
        if count > 0
    }
    return state_centroids, country_centroids


def url_exists(url: str) -> bool:
    request = urllib.request.Request(url=url, method="HEAD", headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20):
            return True
    except urllib.error.URLError:
        return False


def polygon_area_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    """Return signed area and centroid for one polygon ring.

    Uses planar shoelace formula in lon/lat degrees.
    """
    if len(ring) < 3:
        return 0.0, 0.0, 0.0

    area2 = 0.0
    cx = 0.0
    cy = 0.0

    for index, point in enumerate(ring):
        x0, y0 = float(point[0]), float(point[1])
        x1, y1 = float(ring[(index + 1) % len(ring)][0]), float(ring[(index + 1) % len(ring)][1])
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross

    if area2 == 0:
        return 0.0, 0.0, 0.0

    area = area2 / 2.0
    return area, cx / (3.0 * area2), cy / (3.0 * area2)


def geometry_centroid(geometry: dict[str, Any]) -> tuple[float, float] | None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    polygons: list[list[list[float]]] = []
    if geometry_type == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            return None
        first_ring = coordinates[0]
        if not isinstance(first_ring, list):
            return None
        polygons = [first_ring]
    elif geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list):
            return None
        for polygon in coordinates:
            if not isinstance(polygon, list) or not polygon:
                continue
            first_ring = polygon[0]
            if isinstance(first_ring, list):
                polygons.append(first_ring)
    else:
        return None

    total_area = 0.0
    weighted_lon = 0.0
    weighted_lat = 0.0

    for polygon in polygons:
        area, lon, lat = polygon_area_centroid(polygon)
        abs_area = abs(area)
        if abs_area == 0:
            continue
        total_area += abs_area
        weighted_lon += lon * abs_area
        weighted_lat += lat * abs_area

    if total_area == 0:
        return None

    return weighted_lat / total_area, weighted_lon / total_area


def compute_country_centroids() -> dict[str, tuple[float, float]]:
    payload = fetch_text(NATURAL_EARTH_COUNTRIES_URL)
    feature_collection = json.loads(payload)

    centroids: dict[str, tuple[float, float]] = {}
    for feature in feature_collection.get("features", []):
        properties = feature.get("properties", {})
        country_code = properties.get("ISO_A2_EH") or properties.get("ISO_A2")
        if not isinstance(country_code, str):
            continue
        if len(country_code) != 2 or country_code == "-99":
            continue

        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue

        centroid = geometry_centroid(geometry)
        if not centroid:
            continue

        centroids[country_code] = centroid

    return centroids


def insert_prefix(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    location: tuple[float, float],
    country_code: str,
    ipv4_prefix: int,
    ipv6_prefix: int,
    ipv4_map: dict[int, tuple[float, float, str]],
    ipv6_map: dict[int, tuple[float, float, str]],
) -> None:
    if isinstance(ip, ipaddress.IPv4Address):
        prefix_key = int(ip) >> (32 - ipv4_prefix)
        if prefix_key not in ipv4_map:
            ipv4_map[prefix_key] = (location[0], location[1], country_code)
        return

    prefix_key = int(ip) >> (128 - ipv6_prefix)
    if prefix_key not in ipv6_map:
        ipv6_map[prefix_key] = (location[0], location[1], country_code)


def build_rough_geoip_prefix_maps(
    csv_gzip_path: Path,
    state_centroids: dict[tuple[str, str], tuple[float, float]],
    dbip_country_centroids: dict[str, tuple[float, float]],
    natural_earth_country_centroids: dict[str, tuple[float, float]],
    ipv4_prefix: int,
    ipv6_prefix: int,
) -> tuple[dict[int, tuple[float, float, str]], dict[int, tuple[float, float, str]]]:
    ipv4_map: dict[int, tuple[float, float, str]] = {}
    ipv6_map: dict[int, tuple[float, float, str]] = {}

    for row in iter_dbip_city_lite_rows(csv_gzip_path):
        country_code = row.country_code

        location: tuple[float, float] | None = None
        if row.state_name:
            location = state_centroids.get((country_code, row.state_name))
        if not location:
            location = dbip_country_centroids.get(country_code)
        if not location:
            location = natural_earth_country_centroids.get(country_code)

        if not location:
            continue

        try:
            ip = ipaddress.ip_address(row.start_ip)
        except ValueError:
            continue

        insert_prefix(
            ip=ip,
            location=location,
            country_code=country_code,
            ipv4_prefix=ipv4_prefix,
            ipv6_prefix=ipv6_prefix,
            ipv4_map=ipv4_map,
            ipv6_map=ipv6_map,
        )

    return ipv4_map, ipv6_map


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Download open-license IP data and generate a compact rough GeoIP database for "
            "IP -> lat/lon mapping in Bitcoin Safe."
        )
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("bitcoin_safe/data/geoip_rough_v1.json"),
        help="Output JSON path",
    )
    p.add_argument(
        "--ipv4-prefix",
        type=int,
        default=10,
        help=(
            "IPv4 prefix length used for rough grouping. "
            "Lower values produce a much smaller DB with coarser accuracy "
            "(default: 10)."
        ),
    )
    p.add_argument(
        "--ipv6-prefix",
        type=int,
        default=24,
        help=(
            "IPv6 prefix length used for rough grouping. "
            "Lower values produce a much smaller DB with coarser accuracy "
            "(default: 24)."
        ),
    )
    return p


def main() -> None:
    args = parser().parse_args()

    if args.ipv4_prefix <= 0 or args.ipv4_prefix > 32:
        raise ValueError("--ipv4-prefix must be in [1, 32]")
    if args.ipv6_prefix <= 0 or args.ipv6_prefix > 128:
        raise ValueError("--ipv6-prefix must be in [1, 128]")

    print("Resolving latest DB-IP city-lite CSV URL…")
    dbip_html = fetch_text(DBIP_CITY_LITE_PAGE_URL)
    dbip_csv_url = extract_dbip_city_csv_url(dbip_html)
    print(f"Using DB-IP CSV: {dbip_csv_url}")

    print("Downloading DB-IP city-lite CSV…")
    dbip_csv_path = download_to_temp_file(dbip_csv_url)
    print(f"Saved DB-IP CSV to temporary file: {dbip_csv_path}")

    print("Computing state/country centroids from DB-IP city-lite…")
    state_centroids, dbip_country_centroids = compute_state_centroids(dbip_csv_path)
    print(f"Loaded {len(state_centroids)} state centroids")
    print(f"Loaded {len(dbip_country_centroids)} country centroids from DB-IP")

    print("Computing country centroids from Natural Earth…")
    natural_earth_country_centroids = compute_country_centroids()
    print(f"Loaded {len(natural_earth_country_centroids)} country centroids")

    print("Building rough prefix database…")
    try:
        ipv4_map, ipv6_map = build_rough_geoip_prefix_maps(
            csv_gzip_path=dbip_csv_path,
            state_centroids=state_centroids,
            dbip_country_centroids=dbip_country_centroids,
            natural_earth_country_centroids=natural_earth_country_centroids,
            ipv4_prefix=args.ipv4_prefix,
            ipv6_prefix=args.ipv6_prefix,
        )
    finally:
        dbip_csv_path.unlink(missing_ok=True)

    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prefix_lengths": {"ipv4": args.ipv4_prefix, "ipv6": args.ipv6_prefix},
        "sources": {
            "db_ip_city_lite_download_page": DBIP_CITY_LITE_PAGE_URL,
            "db_ip_city_lite_csv": dbip_csv_url,
            "natural_earth_countries_geojson": NATURAL_EARTH_COUNTRIES_URL,
        },
        "licenses": {
            "db_ip_city_lite": {
                "name": "Creative Commons Attribution 4.0 International",
                "url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution": "Contains IP geolocation data from DB-IP (https://db-ip.com).",
            },
            "natural_earth": {
                "name": "Public Domain",
                "url": "https://www.naturalearthdata.com/about/terms-of-use/",
                "attribution": "Contains country geometry data from Natural Earth.",
            },
        },
        "ipv4": {str(key): list(value) for key, value in sorted(ipv4_map.items())},
        "ipv6": {str(key): list(value) for key, value in sorted(ipv6_map.items())},
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    print(f"Wrote rough GeoIP DB to {args.output}")
    print(f"IPv4 prefixes: {len(ipv4_map)}")
    print(f"IPv6 prefixes: {len(ipv6_map)}")


if __name__ == "__main__":
    main()

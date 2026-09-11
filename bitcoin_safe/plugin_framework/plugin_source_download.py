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

from pathlib import Path
from urllib.parse import unquote, urlparse
from zipfile import ZipInfo

import requests

from bitcoin_safe.network_utils import ProxyInfo, RequestsGetException, default_timeout
from bitcoin_safe.plugin_framework.external_plugin_registry_dataclasses import ExternalPluginError

MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_SIGNATURE_BYTES = 1 * 1024 * 1024
MAX_PLUGIN_METADATA_BYTES = 1 * 1024 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
_DOWNLOAD_CHUNK_SIZE = 64 * 1024


def require_safe_plugin_source_url(url: str) -> None:
    if urlparse(url).scheme == "http":
        raise ExternalPluginError("Remote plugin sources must use HTTPS.")


def fetch_plugin_source_bytes(
    url: str,
    headers: dict[str, str],
    proxy_info: ProxyInfo | None,
    max_bytes: int,
    purpose: str,
) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return _fetch_https_bytes(url, headers, proxy_info, max_bytes, purpose)
    if parsed.scheme == "http":
        raise ExternalPluginError("Remote plugin sources must use HTTPS.")
    if parsed.scheme == "file":
        return _read_limited_file(Path(unquote(parsed.path)), max_bytes, purpose)

    path = Path(url)
    if path.exists():
        return _read_limited_file(path, max_bytes, purpose)
    raise ExternalPluginError(f"Could not read {purpose} from {url}.")


def validate_plugin_archive_members(members: list[ZipInfo]) -> None:
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ExternalPluginError(f"Plugin archive exceeds the {MAX_ARCHIVE_MEMBERS} file limit.")

    uncompressed_size = 0
    for member in members:
        if member.is_dir():
            continue
        mode = member.external_attr >> 16
        if mode and mode & 0o170000 not in (0, 0o100000):
            raise ExternalPluginError(f"Plugin archive contains unsupported entry {member.filename!r}.")
        if member.file_size > MAX_ARCHIVE_MEMBER_UNCOMPRESSED_BYTES:
            raise ExternalPluginError("Plugin archive contains an oversized file.")
        uncompressed_size += member.file_size
        if uncompressed_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ExternalPluginError("Plugin archive exceeds the uncompressed size limit.")


def _fetch_https_bytes(
    url: str,
    headers: dict[str, str],
    proxy_info: ProxyInfo | None,
    max_bytes: int,
    purpose: str,
) -> bytes:
    try:
        with requests.get(
            url,
            headers=headers,
            timeout=default_timeout(proxy_info),
            proxies=proxy_info.get_requests_proxy_dict() if proxy_info else None,
            stream=True,
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    content_size = int(content_length)
                except ValueError:
                    content_size = 0
                if content_size > max_bytes:
                    raise ExternalPluginError(_size_error(purpose, max_bytes))
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(_DOWNLOAD_CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise ExternalPluginError(_size_error(purpose, max_bytes))
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.RequestException as exc:
        raise RequestsGetException(f"Could not download plugin source URL {url}: {exc}") from exc


def _read_limited_file(path: Path, max_bytes: int, purpose: str) -> bytes:
    try:
        if path.stat().st_size > max_bytes:
            raise ExternalPluginError(_size_error(purpose, max_bytes))
        return path.read_bytes()
    except OSError as exc:
        raise ExternalPluginError(f"Could not read {purpose} from {path}: {exc}") from exc


def _size_error(purpose: str, max_bytes: int) -> str:
    return f"{purpose.capitalize()} exceeds the {max_bytes // (1024 * 1024)} MiB download limit."

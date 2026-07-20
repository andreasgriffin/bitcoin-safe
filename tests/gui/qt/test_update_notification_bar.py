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

import pytest

from bitcoin_safe.gui.qt.update_notification_bar import UpdateNotificationBar
from bitcoin_safe.signature_manager import Asset, GitHubAssetDownloader, GitHubRelease


class _MockResponse:
    def __init__(self, json_payload: list[dict], status_code: int = 200) -> None:
        self.status_code = status_code
        self._json_payload = json_payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP error: {self.status_code}")

    def json(self) -> list[dict]:
        return self._json_payload


def _release(tag: str, prerelease: bool) -> GitHubRelease:
    return GitHubRelease(
        tag=tag,
        prerelease=prerelease,
        assets=[
            Asset(
                tag=tag,
                url=f"https://example.com/{tag}",
                name=f"bitcoin-safe-{tag}-x86_64.AppImage",
            )
        ],
    )


def test_select_newest_eligible_release_ignores_prerelease_for_stable_versions() -> None:
    release = UpdateNotificationBar.select_newest_eligible_release(
        releases=[_release("1.1.0rc1", prerelease=True), _release("1.0.1", prerelease=False)],
        current_version="1.0.0",
        show_prerelease_updates=False,
    )

    assert release
    assert release.tag == "1.0.1"


def test_select_newest_eligible_release_can_include_prerelease_for_stable_versions() -> None:
    release = UpdateNotificationBar.select_newest_eligible_release(
        releases=[_release("1.1.0rc1", prerelease=True), _release("1.0.1", prerelease=False)],
        current_version="1.0.0",
        show_prerelease_updates=True,
    )

    assert release
    assert release.tag == "1.1.0rc1"


def test_select_newest_eligible_release_includes_prerelease_for_dev_versions() -> None:
    release = UpdateNotificationBar.select_newest_eligible_release(
        releases=[_release("1.0.0rc1", prerelease=True)],
        current_version="1.0.0.dev1",
        show_prerelease_updates=False,
    )

    assert release
    assert release.tag == "1.0.0rc1"


def test_select_newest_eligible_release_treats_final_release_as_newer_than_rc() -> None:
    release = UpdateNotificationBar.select_newest_eligible_release(
        releases=[_release("1.0.0", prerelease=False), _release("1.0.0rc2", prerelease=True)],
        current_version="1.0.0rc1",
        show_prerelease_updates=False,
    )

    assert release
    assert release.tag == "1.0.0"


def test_select_newest_eligible_release_returns_none_without_eligible_update() -> None:
    release = UpdateNotificationBar.select_newest_eligible_release(
        releases=[_release("1.1.0rc1", prerelease=True), _release("1.0.0", prerelease=False)],
        current_version="1.0.0",
        show_prerelease_updates=False,
    )

    assert release is None


def test_get_releases_ignores_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: int, proxies: dict | None) -> _MockResponse:
        del url, timeout, proxies
        return _MockResponse(
            [
                {
                    "tag_name": "1.0.1",
                    "prerelease": False,
                    "draft": False,
                    "assets": [{"name": "bitcoin-safe-1.0.1-x86_64.AppImage", "browser_download_url": "ok"}],
                },
                {
                    "tag_name": "1.1.0rc1",
                    "prerelease": True,
                    "draft": True,
                    "assets": [
                        {"name": "bitcoin-safe-1.1.0rc1-x86_64.AppImage", "browser_download_url": "skip"}
                    ],
                },
            ]
        )

    monkeypatch.setattr("bitcoin_safe.signature_manager.requests.get", fake_get)

    releases = GitHubAssetDownloader("andreasgriffin/bitcoin-safe", proxies=None).get_releases()

    assert [release.tag for release in releases] == ["1.0.1"]

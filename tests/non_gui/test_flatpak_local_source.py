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

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest
from tools.build_linux.flathub_flatpak import populate_cli, repo_builder, tracked_repo_files


@pytest.mark.parametrize(
    ("mode", "release_tag", "fetch_expected"),
    [("local-dir", None, False), ("local-dir", "v1", True), ("archive", None, True)],
)
def test_flatpak_source_metadata_selection(
    tmp_path: Path, mode: str, release_tag: str | None, fetch_expected: bool
) -> None:
    repository = Path(__file__).resolve().parents[2]
    version = repo_builder.read_local_app_version(repository)
    source = tmp_path / "source-tree"
    (source / "bitcoin_safe").mkdir(parents=True)
    (source / "bitcoin_safe" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (source / "release-notes").mkdir()
    (source / "release-notes" / f"{version}.md").write_text("Release notes")
    args = Namespace(
        release_tag=release_tag,
        source_repo_url=None,
        local_source_checkout=str(source),
        output_dir=str(tmp_path),
        only_write_dependency_modules=False,
        refresh_tracked_only=False,
        app_source_mode=mode,
        run_flatpak=False,
        skip_validate=True,
        skip_lint=False,
        skip_build=False,
    )
    with (
        patch.object(populate_cli, "parse_args", return_value=args),
        patch.object(
            repo_builder,
            "fetch_release",
            return_value=repo_builder.ReleaseInfo(
                source_repo_url=repo_builder.DEFAULT_SOURCE_REPO_URL,
                tag_name="v1",
                published_at="2026-01-01T00:00:00Z",
                prerelease=False,
                tarball_url="https://example.com/archive.tar.gz",
                html_url="https://example.com/release",
                body="",
            ),
        ) as fetch_release,
        patch.object(tracked_repo_files, "refresh_tracked_files_for_context"),
        patch.object(tracked_repo_files, "validate_tracked_generated_assets"),
        patch.object(tracked_repo_files, "validate_tracked_dependency_requirements_for_context"),
        patch.object(repo_builder, "clean_transient_artifacts"),
        patch.object(repo_builder, "generate_repo") as generate_repo,
        patch.object(repo_builder, "validate_repo"),
    ):
        populate_cli.main()

    if fetch_expected:
        fetch_release.assert_called_once_with(repo_builder.DEFAULT_SOURCE_REPO_URL, release_tag)
    else:
        fetch_release.assert_not_called()
    context = generate_repo.call_args.args[1]
    assert context.tree_root == source
    assert context.app_version == repo_builder.read_local_app_version(source)
    assert generate_repo.call_args.kwargs["app_source_mode"] == mode

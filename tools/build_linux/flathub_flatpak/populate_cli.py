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

import argparse
from pathlib import Path

from bitcoin_safe.constants import APP_NAME
from tools.build_linux.flathub_flatpak import repo_builder, tracked_repo_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Populate the {APP_NAME} Flathub manifest repo.")
    parser.add_argument(
        "--source-repo-url",
        help=(
            "Upstream repository URL to read release metadata from. "
            f"Defaults to {repo_builder.DEFAULT_SOURCE_REPO_URL} when no source override is provided."
        ),
    )
    parser.add_argument(
        "--local-source-checkout",
        help=(
            "Local bitcoin-safe checkout to use for manifests, lockfile, and assets. "
            "When provided, this takes precedence over downloading the release tarball."
        ),
    )
    parser.add_argument(
        "--release-tag",
        help="GitHub release tag or arbitrary commit hash to build from.",
    )
    parser.add_argument(
        "--refresh-tracked-only",
        action="store_true",
        help="Refresh only the checked-in Flathub assets and requirements from a local checkout.",
    )
    parser.add_argument("--output-dir", default=str(repo_builder.DEFAULT_OUTPUT_DIR))
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument("--skip-lint", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--run-flatpak", action="store_true")
    parser.add_argument("--only-write-dependency-modules", action="store_true")
    parser.add_argument(
        "--app-source-mode",
        choices=["archive", "local-dir"],
        default="archive",
        help=(
            "How the generated manifest should reference the bitcoin-safe app source. "
            "'archive' keeps the Flathub default, while 'local-dir' points at --local-source-checkout."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tag_name = args.release_tag
    repo_url = args.source_repo_url or repo_builder.DEFAULT_SOURCE_REPO_URL
    local_source_checkout = Path(args.local_source_checkout).resolve() if args.local_source_checkout else None
    output_dir = Path(args.output_dir).resolve()
    repo_builder.log_step(f"Source repository: {repo_url}")
    if local_source_checkout:
        repo_builder.log_step(f"Local source override: {local_source_checkout}")
    repo_builder.log_step(f"Output directory: {output_dir}")
    if tag_name:
        repo_builder.log_step(f"Requested source ref: {tag_name}")
    else:
        repo_builder.log_step("Requested source ref: latest published release")

    if args.only_write_dependency_modules:
        if not local_source_checkout:
            raise RuntimeError("--only-write-dependency-modules requires --local-source-checkout")
        tracked_repo_files.validate_tracked_dependency_requirements_for_tree(local_source_checkout, repo_url)
        repo_builder.generate_dependency_modules(output_dir, local_source_checkout)
        repo_builder.log_step("Dependency module generation completed successfully")
        return

    if args.refresh_tracked_only:
        if not local_source_checkout:
            raise RuntimeError("--refresh-tracked-only requires --local-source-checkout")
        tracked_repo_files.refresh_tracked_files(local_source_checkout, repo_url)
        repo_builder.log_step("Tracked Flathub file refresh completed successfully")
        return

    if args.app_source_mode == "local-dir" and not local_source_checkout:
        raise RuntimeError("--app-source-mode local-dir requires --local-source-checkout")
    if args.run_flatpak and args.skip_validate:
        raise RuntimeError("--run-flatpak cannot be used together with --skip-validate")
    if args.run_flatpak and args.skip_build:
        raise RuntimeError("--run-flatpak cannot be used together with --skip-build")

    context = repo_builder.build_source_context(
        repo_url=repo_url,
        local_source_checkout=str(local_source_checkout) if local_source_checkout else None,
        release_tag=tag_name,
    )
    if local_source_checkout:
        tracked_repo_files.refresh_tracked_files_for_context(context)

    repo_builder.clean_transient_artifacts(output_dir)
    tracked_repo_files.validate_tracked_generated_assets(context)
    tracked_repo_files.validate_tracked_dependency_requirements_for_context(context)
    repo_builder.generate_repo(output_dir, context, app_source_mode=args.app_source_mode)
    repo_builder.validate_repo(
        output_dir,
        skip_validate=args.skip_validate,
        skip_lint=args.skip_lint,
        skip_build=args.skip_build,
        run_flatpak=args.run_flatpak,
    )
    repo_builder.log_step("Populate completed successfully")


if __name__ == "__main__":
    main()

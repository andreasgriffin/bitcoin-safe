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
import fnmatch
import hashlib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare SHA-256 checksums across two artifact directories.")
    parser.add_argument(
        "--first-dir", type=Path, required=True, help="Directory containing the first artifact set."
    )
    parser.add_argument(
        "--second-dir", type=Path, required=True, help="Directory containing the second artifact set."
    )
    parser.add_argument(
        "--pattern",
        action="append",
        required=True,
        help="Filename glob to include in the comparison. Repeat to include multiple patterns.",
    )
    parser.add_argument("--label", default="artifact set", help="Human-readable label used in log output.")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        while chunk := file_handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def matches_patterns(path: Path, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def collect_artifacts(root_dir: Path, patterns: list[str]) -> dict[str, Path]:
    if not root_dir.is_dir():
        raise ValueError(f"Artifact directory does not exist: {root_dir}")

    artifacts: dict[str, Path] = {}
    for path in sorted(root_dir.rglob("*")):
        if not path.is_file() or not matches_patterns(path, patterns):
            continue
        existing_path = artifacts.get(path.name)
        if existing_path is not None:
            raise ValueError(
                f"Found duplicate artifact basename {path.name!r} under {root_dir}: {existing_path} and {path}"
            )
        artifacts[path.name] = path

    if not artifacts:
        joined_patterns = ", ".join(patterns)
        raise ValueError(f"No artifacts matching {joined_patterns} found under {root_dir}")

    return artifacts


def compare_artifacts(first_dir: Path, second_dir: Path, patterns: list[str], label: str) -> int:
    first_artifacts = collect_artifacts(first_dir, patterns)
    second_artifacts = collect_artifacts(second_dir, patterns)

    first_names = set(first_artifacts)
    second_names = set(second_artifacts)
    if first_names != second_names:
        missing_from_first = sorted(second_names - first_names)
        missing_from_second = sorted(first_names - second_names)
        if missing_from_first:
            print(f"{label}: missing from first build: {', '.join(missing_from_first)}")
        if missing_from_second:
            print(f"{label}: missing from second build: {', '.join(missing_from_second)}")
        return 1

    has_mismatch = False
    for artifact_name in sorted(first_names):
        first_hash = sha256_file(first_artifacts[artifact_name])
        second_hash = sha256_file(second_artifacts[artifact_name])
        status = "MATCH" if first_hash == second_hash else "MISMATCH"
        print(f"{label}: {artifact_name}: {status}\n  first : {first_hash}\n  second: {second_hash}")
        if first_hash != second_hash:
            has_mismatch = True

    return 1 if has_mismatch else 0


def main() -> int:
    args = parse_args()
    return compare_artifacts(args.first_dir, args.second_dir, args.pattern, args.label)


if __name__ == "__main__":
    raise SystemExit(main())

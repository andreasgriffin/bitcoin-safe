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

import ast
from pathlib import Path

from bitcoin_safe.constants import APP_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONSTANTS_PATH = PROJECT_ROOT / "bitcoin_safe/constants.py"


def test_app_name_is_not_hardcoded_in_python_strings() -> None:
    violations: list[str] = []
    python_paths = sorted((PROJECT_ROOT / "bitcoin_safe").rglob("*.py")) + sorted(
        (PROJECT_ROOT / "tools").rglob("*.py")
    )

    for path in python_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if APP_NAME not in node.value:
                continue
            if path == CONSTANTS_PATH and node.value == APP_NAME:
                continue
            violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert not violations, f"Use APP_NAME instead of hardcoding it in: {', '.join(violations)}"

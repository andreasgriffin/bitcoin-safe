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

from pathlib import Path

from bitcoin_safe.plugin_framework.plugin_source_hash import iter_plugin_source_files


def test_iter_plugin_source_files_ignores_nested_virtualenv_directory(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "demo-plugin"
    nested_venv_dir = plugin_dir / "plugins" / "demo" / ".venv"
    nested_venv_dir.mkdir(parents=True)
    included_file = plugin_dir / "plugins" / "demo" / "plugin_bundle.py"
    ignored_file = nested_venv_dir / "ignored.py"
    included_file.write_text("PLUGIN_CLIENTS = ()\n", encoding="utf-8")
    ignored_file.write_text("print('ignored')\n", encoding="utf-8")

    files = iter_plugin_source_files(plugin_dir)

    assert files == [included_file]

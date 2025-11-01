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

import tomlkit

from bitcoin_safe import __version__


def update_poetry_version(file_path, new_version):
    # Read the pyproject.toml file
    """Update poetry version."""
    with open(file_path) as file:
        data = tomlkit.load(file)

    # Update the version under tool.poetry
    if "tool" in data and "poetry" in data["tool"] and "version" in data["tool"]["poetry"]:
        data["tool"]["poetry"]["version"] = new_version

        # Write the updated data back to pyproject.toml
        with open(file_path, "w") as file:
            tomlkit.dump(data, file)
        print(f"Version updated to {new_version} in pyproject.toml")
    else:
        print("Could not find the 'tool.poetry.version' key in the pyproject.toml")


update_poetry_version("pyproject.toml", __version__)

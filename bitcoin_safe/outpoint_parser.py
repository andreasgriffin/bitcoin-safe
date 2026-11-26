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

"""Parse explicitly imported transaction outpoints."""

from .pythonbdk_types import OutPoint


def parse_outpoints(text: str, existing: set[OutPoint]) -> tuple[list[OutPoint], list[str]]:
    outpoints: list[OutPoint] = []
    errors: list[str] = []
    seen = set(existing)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            txid, index = line.split(":")
            if len(txid) != 64 or not index.isascii() or not index.isdecimal():
                raise ValueError("Expected a 64-character transaction ID and a nonnegative output index")
            outpoint = OutPoint.from_str(line)
            if not 0 <= outpoint.vout <= 0xFFFFFFFF:
                raise ValueError("Output index is out of range")
        except Exception as exc:
            errors.append(f"{line}: {exc}")
            continue
        if outpoint in seen:
            errors.append(f"{line}: duplicate outpoint")
            continue
        seen.add(outpoint)
        outpoints.append(outpoint)
    return outpoints, errors

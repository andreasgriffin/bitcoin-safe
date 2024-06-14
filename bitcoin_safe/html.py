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


import logging

logger = logging.getLogger(__name__)


def html_f(s: str, color=None, bf=False, p=False, size=None, add_html_and_body=False) -> str:
    if bf:
        s = f"<b>{s}</b>"

    if isinstance(size, int):
        size = f"{size}pt"

    if color and size:
        s = f'<span style="color: {color}; font-size: {size};">{s}</span>'
    elif size:
        s = f'<span style=" font-size: {size};">{s}</span>'
    elif color:
        s = f"<font color='{color}'>{s}</font>"
    if p:
        s = f"<p>{s}</p>"
    if add_html_and_body:
        s = f"<html><body>{s}</body></html>"
    return s


def link(url, text=None) -> str:
    return f"<a href='{url}'>{text if text else url}</a>"

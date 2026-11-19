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

"""Common date and page-number footer for printable PDFs."""

from PyQt6.QtCore import QDateTime
from reportlab.lib.colors import Color
from reportlab.pdfgen.canvas import Canvas


def pdf_timestamp() -> str:
    """Return the local date, time and timezone for a generated document."""
    return QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss t")


def draw_pdf_footer(pdf: Canvas, width: float, font: str, timestamp: str) -> None:
    """Draw the document timestamp and current page number."""
    pdf.saveState()
    pdf.setFillColor(Color(0.25, 0.25, 0.25))
    pdf.setFont(font, 8)
    pdf.drawCentredString(width / 2, 24, f"Date: {timestamp}")
    pdf.drawRightString(width - 36, 24, f"Page {pdf.getPageNumber()}")
    pdf.restoreState()

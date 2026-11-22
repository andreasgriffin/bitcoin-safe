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

from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ByteStringObject, ContentStream, TextStringObject
from PyQt6.QtPdf import QPdfDocument

# ReportLab substitutes unsupported characters with a black square; the other
# characters are common missing-glyph and Unicode replacement markers.
MISSING_GLYPHS = frozenset("\u25a0\u25a1\u25af\ufffd\x00")


def missing_glyphs(path: Path) -> list[str]:
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_, f"Could not open {path}"
    assert document.pageCount() > 0, f"No pages in {path}"
    errors = []
    for page in range(document.pageCount()):
        text = document.getAllText(page).text()
        assert text.strip(), f"No extractable text on page {page + 1} of {path}"
        for line in text.splitlines():
            if any(character in MISSING_GLYPHS for character in line):
                errors.append(f"page {page + 1}: {line}")
    # Qt embeds CID fonts with identity mapping; CID 0 is the .notdef glyph,
    # which may be invisible or extract as an ordinary Unicode character.
    reader = PdfReader(path)
    for page_number, page in enumerate(reader.pages, 1):
        fonts = page["/Resources"]["/Font"]
        font_is_identity = False
        font_stack: list[bool] = []
        for operands, operator in ContentStream(page.get_contents(), reader).operations:
            if operator == b"q":
                font_stack.append(font_is_identity)
            elif operator == b"Q" and font_stack:
                font_is_identity = font_stack.pop()
            elif operator == b"Tf":
                font = fonts[operands[0]].get_object()
                font_is_identity = font.get("/Encoding") == "/Identity-H"
            elif font_is_identity and operator in (b"Tj", b"TJ"):
                parts = operands[0] if operator == b"TJ" else [operands[0]]
                for part in parts:
                    if isinstance(part, (TextStringObject, ByteStringObject)):
                        data = part.original_bytes
                        if any(data[index : index + 2] == b"\x00\x00" for index in range(0, len(data), 2)):
                            errors.append(f"page {page_number}: missing font glyph (.notdef)")
                            break
    return errors

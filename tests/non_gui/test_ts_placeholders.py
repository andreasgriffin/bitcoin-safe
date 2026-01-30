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

import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

PLACEHOLDER_RE = re.compile(r"{[^{}]+}")


def _collect_placeholders(text: str) -> Counter[str]:
    """Return a counter of curly-brace placeholders in the given text."""
    placeholders: list[str] = []
    for match in PLACEHOLDER_RE.findall(text):
        inner = match[1:-1].strip()
        placeholders.append(f"{{{inner}}}")
    return Counter(placeholders)


def _iter_messages(root: ET.Element):
    """Yield (context, source, translation) tuples for every message element."""
    for context in root.findall("context"):
        context_name = context.findtext("name", default="UNKNOWN")
        for message in context.findall("message"):
            source_el = message.find("source")
            translation_el = message.find("translation")
            if source_el is None or translation_el is None:
                continue
            source_text = "".join(source_el.itertext()) or ""
            translation_text = "".join(translation_el.itertext()) or ""
            yield context_name, source_text, translation_text, translation_el


def _format_counter(counter: Counter[str]) -> str:
    if not counter:
        return "(none)"
    return ", ".join(
        f"{placeholder}×{count}" if count > 1 else placeholder
        for placeholder, count in sorted(counter.items())
    )


def test_ts_placeholder_parity():
    """Ensure translations keep the exact set and count of curly-brace placeholders."""
    locales_dir = Path(__file__).resolve().parents[2] / "bitcoin_safe" / "gui" / "locales"
    assert locales_dir.is_dir(), f"Locales directory missing at {locales_dir}"

    ts_files = sorted(locales_dir.glob("*.ts"))
    assert ts_files, "No translation files found"

    errors = []
    for ts_path in ts_files:
        tree = ET.parse(ts_path)
        root = tree.getroot()
        file_modified = False
        for context_name, source_text, translation_text, translation_el in _iter_messages(root):
            source_placeholders = _collect_placeholders(source_text)
            translation_placeholders = _collect_placeholders(translation_text)

            if source_placeholders != translation_placeholders:
                errors.append(
                    f"{ts_path.name}::{context_name}\n"
                    f"  source: {source_text}\n"
                    f"  translation: {translation_text}\n"
                    f"  expected: {_format_counter(source_placeholders)}\n"
                    f"  found: {_format_counter(translation_placeholders)}"
                )
                # remove translation content so translators can fix later
                translation_el.text = ""
                for child in list(translation_el):
                    translation_el.remove(child)
                file_modified = True
        if file_modified:
            tree.write(ts_path, encoding="utf-8", xml_declaration=True)
    if errors:
        pytest.fail("Mismatching curly-brace placeholders:\n\n" + "\n\n".join(errors))

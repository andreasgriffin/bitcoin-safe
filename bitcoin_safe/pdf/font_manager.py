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

"""Bundled fonts for portable, multilingual Qt PDF output.

Fonts are deliberately shipped with the application.  Fontconfig/system font
availability differs between Windows, macOS, Linux and Flatpak.
"""

from __future__ import annotations

import lzma
import tarfile
from io import BytesIO
from pathlib import Path

from PyQt6.QtCore import QByteArray, QChar
from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication

FONT_ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "fonts" / "pdf-fonts.tar.xz"
FONT_FILES = (
    "NotoSans-Regular.ttf",
    "NotoSans-Bold.ttf",
    "NotoSansArabic-Regular.ttf",
    "NotoSansHebrew-Regular.ttf",
    "NotoSansDevanagari-Regular.ttf",
    "NotoSansBengali-Regular.ttf",
    "NotoSansTamil-Regular.ttf",
    "NotoSansTelugu-Regular.ttf",
    "NotoSansMalayalam-Regular.ttf",
    "NotoSansKannada-Regular.ttf",
    "NotoSansGurmukhi-Regular.ttf",
    "NotoSansThai-Regular.ttf",
    "NotoSansLao-Regular.ttf",
    "NotoSansMyanmar-Regular.ttf",
    "NotoSansEthiopic-Regular.ttf",
    "NotoSansKhmer-Regular.ttf",
    "NotoSansGujarati-Regular.ttf",
    "NotoSansSinhala-Regular.ttf",
    "NotoSansOriya-Regular.ttf",
    "NotoSansSymbols-Regular.ttf",
    "NotoSansSymbols2-Regular.ttf",
    "NotoSansMath-Regular.ttf",
    "NotoSansCJK-Regional.ttc",
)

# Scripts used by selectable translations and recipient labels.
SCRIPT_FONT = {
    QChar.Script.Script_Arabic: "NotoSansArabic-Regular.ttf",
    QChar.Script.Script_Hebrew: "NotoSansHebrew-Regular.ttf",
    QChar.Script.Script_Devanagari: "NotoSansDevanagari-Regular.ttf",
    QChar.Script.Script_Bengali: "NotoSansBengali-Regular.ttf",
    QChar.Script.Script_Tamil: "NotoSansTamil-Regular.ttf",
    QChar.Script.Script_Telugu: "NotoSansTelugu-Regular.ttf",
    QChar.Script.Script_Malayalam: "NotoSansMalayalam-Regular.ttf",
    QChar.Script.Script_Kannada: "NotoSansKannada-Regular.ttf",
    QChar.Script.Script_Gurmukhi: "NotoSansGurmukhi-Regular.ttf",
    QChar.Script.Script_Thai: "NotoSansThai-Regular.ttf",
    QChar.Script.Script_Lao: "NotoSansLao-Regular.ttf",
    QChar.Script.Script_Myanmar: "NotoSansMyanmar-Regular.ttf",
    QChar.Script.Script_Ethiopic: "NotoSansEthiopic-Regular.ttf",
    QChar.Script.Script_Khmer: "NotoSansKhmer-Regular.ttf",
    QChar.Script.Script_Gujarati: "NotoSansGujarati-Regular.ttf",
    QChar.Script.Script_Sinhala: "NotoSansSinhala-Regular.ttf",
    QChar.Script.Script_Oriya: "NotoSansOriya-Regular.ttf",
    QChar.Script.Script_Han: "NotoSansCJK-Regional.ttc",
    QChar.Script.Script_Hiragana: "NotoSansCJK-Regional.ttc",
    QChar.Script.Script_Katakana: "NotoSansCJK-Regional.ttc",
    QChar.Script.Script_Hangul: "NotoSansCJK-Regional.ttc",
}

LOCALE_FONT = {
    "ar": "NotoSansArabic-Regular.ttf",
    "fa": "NotoSansArabic-Regular.ttf",
    "ur": "NotoSansArabic-Regular.ttf",
    "he": "NotoSansHebrew-Regular.ttf",
    "hi": "NotoSansDevanagari-Regular.ttf",
    "mr": "NotoSansDevanagari-Regular.ttf",
    "bn": "NotoSansBengali-Regular.ttf",
    "ta": "NotoSansTamil-Regular.ttf",
    "te": "NotoSansTelugu-Regular.ttf",
    "ml": "NotoSansMalayalam-Regular.ttf",
    "kn": "NotoSansKannada-Regular.ttf",
    "pa": "NotoSansGurmukhi-Regular.ttf",
    "th": "NotoSansThai-Regular.ttf",
    "lo": "NotoSansLao-Regular.ttf",
    "my": "NotoSansMyanmar-Regular.ttf",
    "am": "NotoSansEthiopic-Regular.ttf",
    "gu": "NotoSansGujarati-Regular.ttf",
}


class PDFFontManager:
    """Register the pinned bundled fonts once for the process lifetime."""

    _families: dict[str, list[str]] = {}

    @classmethod
    def ensure_loaded(cls) -> None:
        if not isinstance(QGuiApplication.instance(), QGuiApplication):
            raise RuntimeError("Qt PDF rendering requires a QGuiApplication")
        if cls._families:
            return

        try:
            # Decompress in memory: no writable font directory or system fonts
            # are required, and XZ verifies the integrity of the entire bundle.
            data = lzma.decompress(FONT_ARCHIVE.read_bytes())
            with tarfile.open(fileobj=BytesIO(data), mode="r:") as archive:
                members = archive.getmembers()
                if (
                    len(members) != len(FONT_FILES)
                    or {member.name for member in members} != set(FONT_FILES)
                    or any(not member.isfile() for member in members)
                ):
                    raise RuntimeError(f"PDF font bundle has missing or unexpected files: {FONT_ARCHIVE}")
                families: dict[str, list[str]] = {}
                for filename in FONT_FILES:
                    source = archive.extractfile(filename)
                    if source is None:
                        raise RuntimeError(f"Invalid PDF font in {FONT_ARCHIVE}: {filename}")
                    font_id = QFontDatabase.addApplicationFontFromData(QByteArray(source.read()))
                    if font_id < 0:
                        raise RuntimeError(f"Unable to register bundled PDF font: {filename}")
                    names = QFontDatabase.applicationFontFamilies(font_id)
                    if not names:
                        raise RuntimeError(f"Font file contains no usable font family: {filename}")
                    families[filename] = names
        except (OSError, EOFError, lzma.LZMAError, tarfile.TarError) as exc:
            raise RuntimeError(f"Unable to read bundled PDF fonts: {FONT_ARCHIVE}") from exc

        # Qt handles contextual shaping, bidi and character-level font fallback.
        # Register fallbacks explicitly so behavior does not depend on the OS.
        for script, filename in SCRIPT_FONT.items():
            for family in families[filename]:
                QFontDatabase.addApplicationFallbackFontFamily(script, family)

        # Symbols and Latin are used in mixed-language texts, too.
        for script in (QChar.Script.Script_Latin, QChar.Script.Script_Common):
            for filename in (
                "NotoSans-Regular.ttf",
                "NotoSansSymbols-Regular.ttf",
                "NotoSansSymbols2-Regular.ttf",
                "NotoSansMath-Regular.ttf",
            ):
                QFontDatabase.addApplicationFallbackFontFamily(script, families[filename][0])
        cls._families = families

    @classmethod
    def family(cls, locale_code: str) -> str:
        cls.ensure_loaded()
        locale = locale_code.replace("-", "_")
        language = locale.split("_", 1)[0].lower()
        if language in {"zh", "ja", "ko"}:
            region = "SC" if language == "zh" else {"ja": "JP", "ko": "KR"}.get(language, "SC")
            if language == "zh" and locale.lower() in {"zh_tw", "zh_hk", "zh_mo"}:
                region = "TC" if locale.lower() != "zh_hk" else "HK"
            names = cls._families["NotoSansCJK-Regional.ttc"]
            return next((name for name in names if name.upper().endswith(" " + region)), names[0])
        filename = LOCALE_FONT.get(language, "NotoSans-Regular.ttf")
        return cls._families[filename][0]

    @classmethod
    def font(cls, locale_code: str, size: float = 10.0) -> QFont:
        font = QFont(cls.family(locale_code))
        font.setPointSizeF(size)
        return font

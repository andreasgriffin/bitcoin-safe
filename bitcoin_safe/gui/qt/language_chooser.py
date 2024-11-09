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

from bitcoin_safe.gui.qt.util import read_QIcon
from bitcoin_safe.gui.qt.wrappers import Menu

logger = logging.getLogger(__name__)

import os
from typing import Dict, List, Optional

from PyQt6.QtCore import (
    QLibraryInfo,
    QLocale,
    QObject,
    Qt,
    QTranslator,
    pyqtBoundSignal,
)
from PyQt6.QtGui import QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.config import UserConfig

FLAGS = {
    "en_US": "🇺🇸",
    "en_GB": "🇬🇧",
    "zh_CN": "🇨🇳",
    "zh_TW": "🇹🇼",
    "es_ES": "🇪🇸",
    "es_MX": "🇲🇽",
    "ru_RU": "🇷🇺",
    "hi_IN": "🇮🇳",
    "pt_PT": "🇵🇹",
    "pt_BR": "🇧🇷",
    "ja_JP": "🇯🇵",
    "ar_AE": "🇦🇪",
    "it_IT": "🇮🇹",
    "fr_FR": "🇫🇷",
    "de_DE": "🇩🇪",
    "ko_KR": "🇰🇷",
    "nl_NL": "🇳🇱",
    "sv_SE": "🇸🇪",
    "no_NO": "🇳🇴",
    "da_DK": "🇩🇰",
    "fi_FI": "🇫🇮",
    "pl_PL": "🇵🇱",
    "tr_TR": "🇹🇷",
    "el_GR": "🇬🇷",
    "cs_CZ": "🇨🇿",
    "hu_HU": "🇭🇺",
    "he_IL": "🇮🇱",
    "th_TH": "🇹🇭",
    "id_ID": "🇮🇩",
    "ms_MY": "🇲🇾",
    "vi_VN": "🇻🇳",
    "ro_RO": "🇷🇴",
    "uk_UA": "🇺🇦",
    "bg_BG": "🇧🇬",
    "sk_SK": "🇸🇰",
    "sl_SI": "🇸🇮",
    "hr_HR": "🇭🇷",
    "lt_LT": "🇱🇹",
    "lv_LV": "🇱🇻",
    "et_EE": "🇪🇪",
    "is_IS": "🇮🇸",
    "mt_MT": "🇲🇹",
    "ga_IE": "🇮🇪",
    "af_ZA": "🇿🇦",
    "ur_PK": "🇵🇰",
    "fa_IR": "🇮🇷",
    "am_ET": "🇪🇹",
    "sw_KE": "🇰🇪",
    "bn_BD": "🇧🇩",
    "ta_IN": "🇮🇳",
    "te_IN": "🇮🇳",
    "ml_IN": "🇮🇳",
    "kn_IN": "🇮🇳",
    "mr_IN": "🇮🇳",
    "pa_IN": "🇮🇳",
}


class LanguageDialog(QDialog):
    def __init__(self, languages: Dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Language")
        self._layout = QVBoxLayout(self)
        self.comboBox = QComboBox()
        self.setupComboBox(languages)
        self._layout.addWidget(self.comboBox)

        # Add dialog buttons
        self.buttonBox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._layout.addWidget(self.buttonBox)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.setModal(True)
        self.setWindowIcon(read_QIcon("logo.svg"))
        self.centerOnScreen()

    def centerOnScreen(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        rect = screen.geometry()
        dialog_size = self.geometry()
        x = (rect.width() - dialog_size.width()) // 2
        y = (rect.height() - dialog_size.height()) // 2
        self.move(x, y)

    def setupComboBox(self, languages: Dict[str, str]) -> None:
        for lang, name in languages.items():
            icon = LanguageChooser.create_flag_icon(FLAGS[lang]) if lang in FLAGS else QIcon()
            self.comboBox.addItem(icon, name, lang)

    def choose_language(self) -> Optional[str]:
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.comboBox.currentData()
        else:
            return None


class LanguageChooser(QObject):
    def __init__(
        self, parent: QWidget, config: UserConfig, signals_language_switch: List[pyqtBoundSignal]
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.signals_language_switch = signals_language_switch
        self.installed_translators: List[QTranslator] = []
        self.current_language_code: str = "en_US"

        # Start with default language (English) in the list
        self.availableLanguages = {"en_US": QLocale("en_US").nativeLanguageName()}
        logger.debug(f"initialized {self}")

    @staticmethod
    def create_flag_icon(unicode_flag: str, size: int = 32) -> QIcon:
        # Create a QPixmap to render the flag onto
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)  # Start with a transparent background

        # Set up the QPainter to draw the flag
        painter = QPainter(pixmap)
        font = QFont()
        font.setPointSize(int(size * 0.7))  # Adjust font size relative to the icon size
        painter.setFont(font)

        # Draw the Unicode flag character centered on the pixmap
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, unicode_flag)
        painter.end()

        # Create and return the QIcon from the pixmap
        return QIcon(pixmap)

    def get_current_lang_code(self) -> str:
        return self.current_language_code

    def default_lang(self) -> str:
        return list(self.availableLanguages.keys())[0]

    def dialog_choose_language(self, parent) -> str:
        logger.debug(f"dialog_choose_language")
        dialog = LanguageDialog(self.get_languages(), parent)
        lang = dialog.choose_language()
        if lang:
            return lang
        return self.default_lang()

    def get_languages(self) -> Dict[str, str]:
        # Scan for other languages and add them to the list
        self.availableLanguages.update(self.scanForLanguages())
        return self.availableLanguages

    def populate_language_menu(self, language_menu: Menu) -> None:
        language_menu.clear()

        # Menu Bar for language selection
        def factory(lang):
            def f(lang=lang):
                self.switchLanguage(langCode=lang)

            return f

        for lang, name in self.get_languages().items():
            icon = self.create_flag_icon(FLAGS[lang]) if lang in FLAGS else QIcon()
            language_menu.add_action(text=name, slot=factory(lang), icon=icon)

    def scanForLanguages(self) -> Dict[str, str]:
        languages: Dict[str, str] = {}

        if not os.path.exists(self.config.locales_path):
            return languages
        for file in os.listdir(self.config.locales_path):
            if file.endswith(".qm"):
                # Extract the locale code after the first underscore and before ".qm"
                langCode = file[file.index("_") + 1 : file.rfind(".")]
                # Use the full locale code to create a QLocale object
                locale = QLocale(langCode)
                # Combine the language and country (if available) for a more specific identification
                langName = (
                    f"{locale.language().name} - {locale.nativeLanguageName()}"
                    if locale.country() != QLocale.Country.AnyCountry
                    else locale.nativeLanguageName()
                )
                languages[langCode] = langName
        return languages

    def _install_translator(self, name: str, path: str) -> None:
        translator_qt = QTranslator()
        instance = QApplication.instance()
        if translator_qt.load(name, path) and instance:
            instance.installTranslator(translator_qt)
            self.installed_translators.append(translator_qt)

    def set_language(self, langCode: Optional[str]) -> None:
        langCode = langCode if langCode else "en_US"
        # remove all installed translators
        instance = QApplication.instance()
        while self.installed_translators and instance:
            instance.removeTranslator(self.installed_translators.pop())

        # first install the qt translations
        self._install_translator(
            f"qt_{langCode}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        )

        # there are other translations available:
        # qtbase_zh_CN.qm
        # qtconnectivity_zh_CN.qm
        # qtdeclarative_zh_CN.qm
        # qt_help_zh_CN.qm
        # qtlocation_zh_CN.qm
        # qtmultimedia_zh_CN.qm
        # qtserialport_zh_CN.qm
        # qt_zh_CN.qm

        self._install_translator(f"app_{langCode}", str(self.config.locales_path))
        QLocale.setDefault(QLocale(langCode))
        self.current_language_code = langCode

    def switchLanguage(self, langCode) -> None:
        self.set_language(langCode)
        for signal in self.signals_language_switch:
            signal.emit()  # Emit the signal when the language is switched
        self.config.language_code = langCode

    def add_signal_language_switch(self, signal_language_switch: pyqtBoundSignal):
        self.signals_language_switch.append(signal_language_switch)

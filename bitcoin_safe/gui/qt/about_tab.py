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

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe import __version__
from bitcoin_safe.gui.qt.util import get_icon_path, svg_tools
from bitcoin_safe.html_utils import link


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        """Initialize instance."""
        super().__init__(parent)
        self.setWindowTitle(self.tr("License Info"))
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        self.setModal(True)
        self.initUI()

    def initUI(self):
        """InitUI."""
        layout = QVBoxLayout(self)

        # Create a QWidget to hold the content
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        # Adding QLabel
        label = QLabel(
            """                       
<p><b>Bitcoin-Safe</b></p>                       

<p>Bitcoin-Safe: A bitcoin wallet for the entire family.<br>
Copyright (C) 2024  Andreas Griffin</p>

<p>This program is free software: you can redistribute it and/or modify<br>
it under the terms of version 3 of the GNU General Public License as<br>
published by the Free Software Foundation.</p>

<p>This program is distributed in the hope that it will be useful,<br>
but WITHOUT ANY WARRANTY; without even the implied warranty of<br>
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the<br>
GNU General Public License for more details.</p>

<p>You should have received a copy of the GNU General Public License<br>
along with this program.  If not, see {link}.</p>
                       
<p>THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.          </p>             
                       
<p><b>Included libraries and software components</b></p>                       
<p><b>UR</b></p>                       

    <p>This software uses the 'ur' library, copyrighted by Foundation Devices, Inc. &copy; 2020. The 'ur' library is provided under the BSD-2-Clause Plus Patent License. The terms of this license permit redistribution and use in source and binary forms, with or without modification, subject to the following conditions:</p>
    <ol>
        <li>Redistributions of the source code must retain the above copyright notice, this list of conditions, and the following disclaimer.</li>
        <li>Redistributions in binary form must reproduce the above copyright notice, this list of conditions, and the following disclaimer in the documentation and/or other materials provided with the distribution.</li>
    </ol>
    <p>THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDERS OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES.</p>

<p><b>Electrum</b></p>                                       


<p>Electrum - lightweight Bitcoin client<br>
Copyright (C) 2023 The Electrum Developers</p>    

<p>Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation files
(the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software,
and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:</p>    

<p>The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.</p>    

<p>THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.</p>    
                    
                       """.format(link=link("https://www.gnu.org/licenses/gpl-3.0.html")),
            self,
        )
        label.setOpenExternalLinks(True)  # Allows opening links
        label.setTextFormat(Qt.TextFormat.RichText)  # Set text as rich text
        label.setWordWrap(True)
        content_layout.addWidget(label)

        # Create a QScrollArea
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)  # Important to make the scroll area adapt to the content
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)

        # Adding QDialogButtonBox
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

        self.setLayout(layout)


class AboutTab(QWidget):
    def __init__(self, license_dialog: LicenseDialog, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.setSpacing(10)

        logo_label = QLabel(parent=self)
        logo_label.setPixmap(QPixmap(get_icon_path("logo.png")))
        logo_label.setFixedSize(96, 96)
        logo_label.setScaledContents(True)

        title_label = QLabel(self.tr("Bitcoin-Safe"), parent=self)
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        tagline_label = QLabel(self.tr("A secure bitcoin savings wallet for everyone."), parent=self)
        tagline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline_label.setWordWrap(True)

        version_label = QLabel(
            self.tr("Version {version}").format(version=__version__),
            parent=self,
        )
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        foss_label = QLabel(self.tr("FOSS - Free & Open Source Software"), parent=self)
        foss_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        licence_label = QLabel(f'<a href="#">{self.tr("Licence")}</a>', parent=self)
        licence_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        licence_label.setTextFormat(Qt.TextFormat.RichText)
        licence_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        licence_label.setCursor(Qt.CursorShape.PointingHandCursor)
        licence_label.linkActivated.connect(license_dialog.exec)

        layout.addStretch()
        layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        layout.addWidget(tagline_label)
        layout.addSpacing(6)
        layout.addWidget(version_label)
        layout.addSpacing(6)
        layout.addWidget(foss_label)
        layout.addWidget(licence_label)
        layout.addStretch()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dialog = LicenseDialog()
    dialog.show()
    sys.exit(app.exec())

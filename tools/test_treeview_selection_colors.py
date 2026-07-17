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

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QApplication, QStyleFactory, QTreeView

from bitcoin_safe.gui.qt.color_corrected_treeview import ColorCorrectedTreeView


def build_view(tree_view: QTreeView) -> QTreeView:
    model = QStandardItemModel()
    item = QStandardItem("MMMM Selected Text MMMM")
    item.setForeground(QBrush(QColor("black")))
    model.appendRow([item])

    tree_view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
    tree_view.setModel(model)

    selection_model = tree_view.selectionModel()
    assert selection_model is not None
    selection_model.select(
        model.index(0, 0),
        selection_model.SelectionFlag.Select | selection_model.SelectionFlag.Rows,
    )
    return tree_view


def render_view(tree_view: QTreeView, target: Path) -> QImage:
    tree_view.resize(420, 120)
    tree_view.show()
    QApplication.processEvents()

    viewport = tree_view.viewport()
    if not viewport:
        return QImage()
    image = QImage(viewport.size(), QImage.Format.Format_ARGB32)
    image.fill(viewport.palette().base().color())
    painter = QPainter(image)
    viewport.render(painter)
    painter.end()
    image.save(str(target))
    tree_view.close()
    return image


def images_differ(left: QImage, right: QImage) -> bool:
    if left.size() != right.size():
        return True

    for y in range(left.height()):
        for x in range(left.width()):
            if left.pixel(x, y) != right.pixel(x, y):
                return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tempfile.mkdtemp(prefix="treeview-selection-demo-")),
        help="Directory where the rendered screenshots are written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    available_styles = {name.lower() for name in QStyleFactory.keys()}
    if "windows11" not in available_styles:
        print("windows11 Qt style is not available on this machine.")
        return 1

    old_style = app.style()  # type: ignore
    old_style_name = old_style.objectName() if old_style else ""
    windows11_style = QStyleFactory.create("windows11")
    assert windows11_style is not None
    app.setStyle(windows11_style)  # type: ignore

    try:
        broken_view = build_view(QTreeView())
        corrected_view = build_view(ColorCorrectedTreeView())

        broken_path = args.output_dir / "native_background_black_text.png"
        corrected_path = args.output_dir / "native_background_white_text.png"

        broken_image = render_view(broken_view, broken_path)
        corrected_image = render_view(corrected_view, corrected_path)
    finally:
        if old_style_name:
            restored_style = QStyleFactory.create(old_style_name)
            if restored_style is not None:
                app.setStyle(restored_style)  # type: ignore

    differs = images_differ(broken_image, corrected_image)
    print(f"Broken render:    {broken_path}")
    print(f"Corrected render: {corrected_path}")
    print(f"Images differ:    {differs}")
    return 0 if differs else 1


if __name__ == "__main__":
    raise SystemExit(main())

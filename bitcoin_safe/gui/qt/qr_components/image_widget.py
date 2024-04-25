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


import io
import logging
import sys
from typing import List, Optional, Tuple

from PIL import Image
from PyQt6.QtCore import QByteArray, QEvent, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QImage, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QDialog, QSizePolicy, QWidget

from .qr import create_qr, create_qr_svg

logger = logging.getLogger(__name__)


def pil_image_to_qimage(im: Image):
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qim = QImage(data, im.size[0], im.size[1], QImage.Format.Format_RGBA8888)

    return qim.copy()  # Making a copy to let data persist after function returns


class ImageWidget(QWidget):
    def __init__(self, pil_image: Image = None, parent=None, size_hint: Tuple[int, int] = None):
        super().__init__(parent)
        self.pil_image = pil_image
        self.size_hint = size_hint
        self.qt_image = pil_image_to_qimage(pil_image) if pil_image else QImage()
        self.scaled_image = self.qt_image

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if not self.qt_image.isNull():
            widget_width, widget_height = self.width(), self.height()

            # choose minimum of image and self sizes
            width = min(self.qt_image.size().width(), widget_width)
            height = min(self.qt_image.size().height(), widget_height)

            # Scale the image to fit within the widget while maintaining aspect ratio
            self.scaled_image = self.qt_image.scaled(
                width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )

            # Calculate position to center the image
            x = (widget_width - self.scaled_image.width()) // 2
            y = (widget_height - self.scaled_image.height()) // 2

            # Draw the image centered
            painter.drawImage(x, y, self.scaled_image)

    def set_image(self, pil_image: Image):
        self.pil_image = pil_image
        self.qt_image = pil_image_to_qimage(pil_image)
        self.update()  # Trigger a repaint

    def load_from_file(self, filepath: str):
        self.set_image(Image.open(filepath))

    def sizeHint(self) -> QSize:
        if not self.qt_image.isNull():
            if not self.size_hint:
                return self.qt_image.size()
            else:
                s = QSize()
                s.setWidth(self.size_hint[0])
                s.setHeight(self.size_hint[1])
                return s
        return super().sizeHint()


class EnlargableImageWidget(ImageWidget):
    def __init__(self, pil_image: Image = None, parent=None, size_hint: Tuple[int, int] = None):
        super().__init__(pil_image, parent, size_hint=size_hint)
        self.enlarged_image: Optional[EnlargedImage] = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enlarge_image(self):
        if not self.enlarged_image:
            self.enlarged_image = EnlargedImage(self.pil_image)

        if self.enlarged_image.isVisible():
            self.enlarged_image.close()
        else:
            self.enlarged_image.show()

    def mousePressEvent(self, event: QMouseEvent):
        self.enlarge_image()


class EnlargedImage(ImageWidget):
    def __init__(self, pil_image: Image, parent=None, screen_fraction=0.4):
        super().__init__(pil_image, parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.installEventFilter(self)  # Install the event filter for this widget

        # Get screen resolution
        screen = QApplication.screens()[0].size()

        # Calculate the new size maintaining the aspect ratio
        image_aspect_ratio = self.qt_image.width() / self.qt_image.height()
        new_width = min(screen.width() * screen_fraction, self.qt_image.width())
        new_height = new_width / image_aspect_ratio

        # Ensure the height does not exceed 50% of the screen height
        if new_height > screen.height() * screen_fraction:
            new_height = screen.height() * screen_fraction
            new_width = new_height * image_aspect_ratio

        # Calculate position to center the window
        x = round((screen.width() - new_width) / 2)
        y = round((screen.height() - new_height) / 2)

        self.setGeometry(x, y, round(new_width), round(new_height))

    def eventFilter(self, source: QWidget, event: QEvent) -> bool:
        # Check for the FocusOut event
        if event.type() in [QEvent.Type.FocusOut, QEvent.Type.WindowDeactivate]:
            # Close the widget if it loses focus
            if source is self:
                self.close()
        return super().eventFilter(source, event)

    def mousePressEvent(self, event: QMouseEvent):
        self.close()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close()


class QRCodeWidget(EnlargableImageWidget):
    def __init__(self, parent=None, clickable=True):
        super().__init__(parent=parent)
        # QR code specific initializations, if any

    def set_data(self, data: str):
        # Implement QR code generation and setting image
        self.set_image(create_qr(data))


#######################################
# svg widgets


class QRCodeWidgetSVG(QWidget):
    def __init__(self, always_animate=False, clickable=True, parent=None):
        super().__init__(parent)
        self.svg_renderers: List[QSvgRenderer] = []
        self.current_index = 0
        self.enlarged_image = None
        self.clickable = clickable
        self.always_animate = always_animate
        self.is_hovered = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_svg)

    def set_data_list(self, data_list: List[str]):
        self.svg_renderers = [
            QSvgRenderer(QByteArray(create_qr_svg(data).encode("utf-8"))) for data in data_list
        ]
        self.current_index = 0
        self.manage_animation()

    def set_always_animate(self, always_animate: bool):
        self.always_animate = always_animate
        self.manage_animation()

    def set_images(self, image_list: List[str]):
        self.svg_renderers = [QSvgRenderer(QByteArray(image.encode("utf-8"))) for image in image_list]
        self.current_index = 0
        self.manage_animation()

    def manage_animation(self):
        should_animate = len(self.svg_renderers) > 1 and (
            self.always_animate
            or self.is_hovered
            or (self.enlarged_image and self.enlarged_image.isVisible())
        )
        if should_animate:
            self.timer.start(1000)  # Change SVG every 1 second
        else:
            self.timer.stop()

    def next_svg(self):
        if not self.svg_renderers:
            return

        self.current_index = (self.current_index + 1) % len(self.svg_renderers)
        self.update()
        if self.enlarged_image and self.enlarged_image.isVisible():
            self.enlarged_image.update_image(self.svg_renderers[self.current_index])
        else:
            self.manage_animation()

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self.svg_renderers:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        widget_width, widget_height = self.width(), self.height()
        side = min(widget_width, widget_height)
        x = (widget_width - side) // 2
        y = (widget_height - side) // 2

        self.svg_renderers[self.current_index].render(painter, QRectF(x, y, side, side))

    def enterEvent(self, event: QEvent) -> None:
        self.is_hovered = True
        self.manage_animation()

    def leaveEvent(self, event: QEvent) -> None:
        self.is_hovered = False
        self.manage_animation()

    def enlarge_image(self):
        if not self.svg_renderers:
            return

        if not self.enlarged_image:
            self.is_hovered = False
            self.enlarged_image = EnlargedSVG(self.svg_renderers[self.current_index])

        self.enlarged_image.exec()
        self.enlarged_image.update_image(self.svg_renderers[self.current_index])
        self.manage_animation()

    def mousePressEvent(self, event: QMouseEvent):
        if self.clickable:
            self.enlarge_image()

    def save_file(self, base_filename: str, format="PNG", antialias=False):
        """Save all QR codes to files. If format is 'GIF', combines them into
        an animated GIF.

        :param base_filename: Base path and filename without extension.
        :param format: The format in which to save the image (e.g.,
            'PNG', 'GIF').
        :param antialias: Boolean to indicate if anti-aliasing should be
            used.
        """
        if format.upper() == "GIF":
            images = []
            for renderer in self.svg_renderers:
                if not renderer.isValid():
                    continue
                images.append(self.renderer_to_pil(renderer, antialias))
            images[0].save(
                f"{base_filename}.gif",
                save_all=True,
                append_images=images[1:],
                loop=0,
                duration=1000,
            )
        else:
            for i, renderer in enumerate(self.svg_renderers):
                if not renderer.isValid():
                    continue
                image = self.renderer_to_pil(renderer, antialias)
                image.save(f"{base_filename}_{i}.{format.lower()}")

    def renderer_to_pil(self, renderer: QSvgRenderer, antialias: bool):
        """Convert a QR code renderer to a PIL Image.

        :param renderer: The QR code renderer.
        :param antialias: Boolean to indicate if anti-aliasing should be
            used.
        :return: PIL Image object.
        """
        size = self.size()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.white)
        painter = QPainter(pixmap)

        if antialias:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        renderer.render(painter, QRectF(0, 0, size.width(), size.height()))
        painter.end()

        # Convert QPixmap to QImage
        qimage = pixmap.toImage()

        # Convert QImage to PIL Image
        buffer = io.BytesIO()
        qimage.save(buffer, "PNG")
        buffer.seek(0)
        return Image.open(buffer)

    def as_pil_images(self):
        """Convert all the QR codes to PIL Images.

        :return: List of PIL Image objects.
        """
        return [
            self.renderer_to_pil(renderer, antialias=True)
            for renderer in self.svg_renderers
            if renderer.isValid()
        ]


class EnlargedSVG(QDialog):
    def __init__(self, svg_renderer: QSvgRenderer, parent=None, screen_fraction=0.5):
        super().__init__(parent)
        self.svg_renderer = svg_renderer
        self.setWindowTitle("QR Code")
        # self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        screen = QApplication.screens()[0].size()
        width = height = round(min(screen.width(), screen.height()) * screen_fraction)
        self.setGeometry(
            round((screen.width() - width) / 2),
            round((screen.height() - height) / 2),
            width,
            height,
        )

    def update_image(self, new_renderer: QSvgRenderer):
        self.svg_renderer = new_renderer
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self.svg_renderer:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        widget_width, widget_height = self.width(), self.height()
        side = min(widget_width, widget_height)
        x = (widget_width - side) // 2
        y = (widget_height - side) // 2

        self.svg_renderer.render(painter, QRectF(x, y, side, side))

    def mousePressEvent(self, event: QMouseEvent):
        super().mousePressEvent(event)
        self.close()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = QRCodeWidgetSVG()
    data_list = ["data1", "data2", "data3"]
    widget.set_data_list(data_list)
    widget.show()

    # To convert the current QR code to PIL Image:
    pil_image = widget.as_pil_image()
    if pil_image:
        pil_image.show()  # or save using pil_image.save('filename.png')

    sys.exit(app.exec())

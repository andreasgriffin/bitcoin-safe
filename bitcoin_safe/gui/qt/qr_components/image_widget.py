from PySide2.QtWidgets import QWidget
from PySide2.QtGui import QPainter, QImage
from PySide2.QtSvg import QSvgRenderer
from PySide2.QtCore import Qt
from PySide2.QtCore import Qt, QRectF
import io
from PySide2.QtWidgets import QWidget, QApplication
from PySide2.QtGui import QPainter, QImage
from PySide2.QtCore import Qt
from PIL import Image
import sys
from PySide2.QtCore import QSize
from .qr import create_qr, create_qr_svg
from PySide2.QtCore import Qt, QByteArray
import logging
from typing import Callable, List, Dict
from PySide2.QtGui import QPainter, QColor
from PySide2.QtGui import QPainter, QColor, QPixmap

logger = logging.getLogger(__name__)


def pil_image_to_qimage(im):
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qim = QImage(data, im.size[0], im.size[1], QImage.Format_RGBA8888)

    return qim.copy()  # Making a copy to let data persist after function returns


class QRCodeWidget(QWidget):
    def __init__(self, clickable=True, parent=None):
        super().__init__(parent)
        self.pil_image = None
        self.enlarged_image = None
        self.clickable = clickable
        # Set the cursor to a pointing hand if the label is clickable
        if clickable:
            self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        # Calculate the aspect ratio and size for the centered square image
        widget_width, widget_height = self.width(), self.height()
        side = min(widget_width, widget_height)
        x = (widget_width - side) // 2
        y = (widget_height - side) // 2

        # Scale the image to fit within the square
        scaled_img = self.qt_image.scaled(
            side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        # Draw the image centered
        painter.drawImage(x, y, scaled_img)

    def set_image(self, pil_image):
        self.pil_image = pil_image
        self.qt_image = pil_image_to_qimage(self.pil_image)
        self.enlarged_image = EnlargedImage(self.pil_image)

    def set_data(self, data: str):
        self.set_image(create_qr(data))

    def enlarge_image(self):
        if not self.enlarged_image:
            return

        if self.enlarged_image.isVisible():
            self.enlarged_image.close()
        else:
            self.enlarged_image.show()

    def mousePressEvent(self, event):
        if self.clickable:
            self.enlarge_image()


class EnlargedImage(QRCodeWidget):
    def __init__(self, pil_image):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint)
        screen_resolution = QApplication.desktop().screenGeometry()
        screen_fraction = 3 / 4
        width = height = (
            min(screen_resolution.width(), screen_resolution.height()) * screen_fraction
        )
        self.setGeometry(
            (screen_resolution.width() - width) / 2,
            (screen_resolution.height() - height) / 2,
            width,
            height,
        )

        self.qt_image = pil_image_to_qimage(pil_image)

    def mousePressEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


class QRCodeWidgetSVG(QWidget):
    def __init__(self, clickable=True, parent=None):
        super().__init__(parent)
        self.svg_renderer = QSvgRenderer()
        self.enlarged_image = None
        self.clickable = clickable
        if clickable:
            self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        if not self.svg_renderer:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        widget_width, widget_height = self.width(), self.height()
        side = min(widget_width, widget_height)

        # Adjust x, y, width, and height to reduce border
        x = (widget_width - side) // 2
        y = (widget_height - side) // 2
        width = side
        height = side

        # Render the SVG within the adjusted area
        self.svg_renderer.render(painter, QRectF(x, y, width, height))

    def set_data(self, data: str):
        self.set_image(create_qr_svg(data))

    def set_image(self, svg_data):
        self.set_svg_data(svg_data)

    def set_svg_data(self, svg_data):
        self.svg_renderer.load(QByteArray(svg_data.encode("utf-8")))
        self.enlarged_image = EnlargedSVG(self.svg_renderer)
        self.update()

    def enlarge_image(self):
        if not self.enlarged_image:
            return

        if self.enlarged_image.isVisible():
            self.enlarged_image.close()
        else:
            self.enlarged_image.show()

    def mousePressEvent(self, event):
        if self.clickable:
            self.enlarge_image()

    def save_file(self, filename, format="PNG", antialias=False):
        """
        Save the rendered SVG to a file with dynamically calculated size.

        :param filename: Path of the file where the image will be saved.
        :param format: The format in which to save the image (e.g., 'PNG', 'JPG').
        :param antialias: Boolean to indicate if anti-aliasing should be used.
        """
        if not self.svg_renderer.isValid():
            return False

        # Get viewBox size of the SVG
        viewBox = self.svg_renderer.viewBoxF()

        # Check if viewBox is valid, otherwise use default size
        if viewBox.isValid():
            size = QSize(viewBox.width() * 10, viewBox.height() * 10)
        else:
            size = self.size()  # Fallback to widget size or some default value

        pixmap = QPixmap(size)
        pixmap.fill(Qt.white)
        painter = QPainter(pixmap)

        if antialias:
            painter.setRenderHint(QPainter.Antialiasing)

        self.svg_renderer.render(painter)
        painter.end()

        return pixmap.save(filename, format.upper())

    def as_pil_image(self):
        """
        Convert the rendered SVG to a PIL Image.

        :return: PIL Image object.
        """
        if not self.svg_renderer.isValid():
            return None

        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.white)  # Fill with white background or any desired color
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        self.svg_renderer.render(painter)
        painter.end()

        # Convert QPixmap to QImage
        qimage = pixmap.toImage()

        # Convert QImage to PIL Image
        buffer = io.BytesIO()
        qimage.save(buffer, "PNG")
        buffer.seek(0)
        pil_image = Image.open(buffer)

        return pil_image


class EnlargedSVG(QRCodeWidgetSVG):
    def __init__(self, svg_renderer):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint)
        screen_resolution = QApplication.desktop().screenGeometry()
        screen_fraction = 3 / 4
        width = height = (
            min(screen_resolution.width(), screen_resolution.height()) * screen_fraction
        )
        self.setGeometry(
            (screen_resolution.width() - width) / 2,
            (screen_resolution.height() - height) / 2,
            width,
            height,
        )

        self.svg_renderer = svg_renderer
        self.update()

    def mousePressEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


if __name__ == "__main__":

    def main():
        app = QApplication(sys.argv)

        # Load your PIL image here
        pil_image = Image.open("1.png")

        image_widget = QRCodeWidgetSVG(pil_image)
        image_widget.show()

        sys.exit(app.exec_())

    main()

import io
import logging
import sys

from PIL import Image
from PySide2.QtCore import QByteArray, QEvent, QRectF, Qt, QTimer
from PySide2.QtGui import QImage, QPainter, QPixmap
from PySide2.QtSvg import QSvgRenderer
from PySide2.QtWidgets import QApplication, QSizePolicy, QWidget

from .qr import create_qr, create_qr_svg

logger = logging.getLogger(__name__)


def pil_image_to_qimage(im):
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qim = QImage(data, im.size[0], im.size[1], QImage.Format_RGBA8888)

    return qim.copy()  # Making a copy to let data persist after function returns


class ImageWidget(QWidget):
    def __init__(self, pil_image=None, parent=None):
        super().__init__(parent)
        self.pil_image = pil_image
        self.qt_image = pil_image_to_qimage(pil_image) if pil_image else QImage()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        if not self.qt_image.isNull():
            widget_width, widget_height = self.width(), self.height()

            # Scale the image to fit within the widget while maintaining aspect ratio
            scaled_img = self.qt_image.scaled(
                widget_width, widget_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

            # Calculate position to center the image
            x = (widget_width - scaled_img.width()) // 2
            y = (widget_height - scaled_img.height()) // 2

            # Draw the image centered
            painter.drawImage(x, y, scaled_img)

    def set_image(self, pil_image):
        self.pil_image = pil_image
        self.qt_image = pil_image_to_qimage(pil_image)
        self.update()  # Trigger a repaint

    def load_from_file(self, filepath):
        self.set_image(Image.open(filepath))

    def sizeHint(self):
        if not self.qt_image.isNull():
            return self.qt_image.size()
        return super().sizeHint()


class EnlargableImageWidget(ImageWidget):
    def __init__(self, pil_image=None, parent=None):
        super().__init__(pil_image, parent)
        self.enlarged_image = None
        self.setCursor(Qt.PointingHandCursor)

    def enlarge_image(self):
        if not self.enlarged_image:
            self.enlarged_image = EnlargedImage(self.pil_image)

        if self.enlarged_image.isVisible():
            self.enlarged_image.close()
        else:
            self.enlarged_image.show()

    def mousePressEvent(self, event):
        self.enlarge_image()


class EnlargedImage(ImageWidget):
    def __init__(self, pil_image: Image, parent=None, screen_fraction=0.5):
        super().__init__(pil_image, parent)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.installEventFilter(self)  # Install the event filter for this widget

        # Get screen resolution
        screen_resolution = QApplication.desktop().screenGeometry()
        screen_width = screen_resolution.width()
        screen_height = screen_resolution.height()

        # Calculate the new size maintaining the aspect ratio
        image_aspect_ratio = self.qt_image.width() / self.qt_image.height()
        new_width = min(screen_width * screen_fraction, self.qt_image.width())
        new_height = new_width / image_aspect_ratio

        # Ensure the height does not exceed 50% of the screen height
        if new_height > screen_height * screen_fraction:
            new_height = screen_height * screen_fraction
            new_width = new_height * image_aspect_ratio

        # Calculate position to center the window
        x = (screen_width - new_width) / 2
        y = (screen_height - new_height) / 2

        self.setGeometry(x, y, new_width, new_height)

    def eventFilter(self, source, event):
        # Check for the FocusOut event
        if event.type() in [QEvent.FocusOut, QEvent.WindowDeactivate]:
            # Close the widget if it loses focus
            if source is self:
                self.close()
        return super().eventFilter(source, event)

    def mousePressEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
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
        self.svg_renderers = []
        self.current_index = 0
        self.enlarged_image = None
        self.clickable = clickable
        self.always_animate = always_animate
        self.is_hovered = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        if clickable:
            self.setCursor(Qt.PointingHandCursor)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_svg)

    def set_data_list(self, data_list):
        self.svg_renderers = [
            QSvgRenderer(QByteArray(create_qr_svg(data).encode("utf-8"))) for data in data_list
        ]
        self.current_index = 0
        self.manage_animation()

    def set_always_animate(self, always_animate):
        self.always_animate = always_animate
        self.manage_animation()

    def set_images(self, image_list):
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

    def paintEvent(self, event):
        if not self.svg_renderers:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        widget_width, widget_height = self.width(), self.height()
        side = min(widget_width, widget_height)
        x = (widget_width - side) // 2
        y = (widget_height - side) // 2

        self.svg_renderers[self.current_index].render(painter, QRectF(x, y, side, side))

    def enterEvent(self, event):
        self.is_hovered = True
        self.manage_animation()

    def leaveEvent(self, event):
        self.is_hovered = False
        self.manage_animation()

    def enlarge_image(self):
        if not self.svg_renderers:
            return

        if not self.enlarged_image:
            self.is_hovered = False
            self.enlarged_image = EnlargedSVG(self.svg_renderers[self.current_index])

        self.enlarged_image.show()
        self.enlarged_image.update_image(self.svg_renderers[self.current_index])
        self.manage_animation()

    def mousePressEvent(self, event):
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
        pixmap.fill(Qt.white)
        painter = QPainter(pixmap)

        if antialias:
            painter.setRenderHint(QPainter.Antialiasing)

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


class EnlargedSVG(QWidget):
    def __init__(self, svg_renderer, parent=None):
        super().__init__(parent)
        self.svg_renderer = svg_renderer

        self.setWindowFlags(Qt.FramelessWindowHint)
        screen_resolution = QApplication.desktop().screenGeometry()
        screen_fraction = 3 / 4
        width = height = min(screen_resolution.width(), screen_resolution.height()) * screen_fraction
        self.setGeometry(
            (screen_resolution.width() - width) / 2,
            (screen_resolution.height() - height) / 2,
            width,
            height,
        )

    def update_image(self, new_renderer):
        self.svg_renderer = new_renderer
        self.update()

    def paintEvent(self, event):
        if not self.svg_renderer:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        widget_width, widget_height = self.width(), self.height()
        side = min(widget_width, widget_height)
        x = (widget_width - side) // 2
        y = (widget_height - side) // 2

        self.svg_renderer.render(painter, QRectF(x, y, side, side))

    def mousePressEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
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

    sys.exit(app.exec_())

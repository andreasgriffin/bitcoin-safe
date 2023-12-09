from tkinter import E
import segno
import logging
from io import BytesIO
from PIL import Image

logger = logging.getLogger(__name__)


def create_qr(data: str, scale=10, color="black", background="white"):
    """
    Generate a QR Code from the provided data and return it as an SVG string.

    :param data: The data to encode in the QR Code.
    :param scale: The scaling factor for the QR Code.
    :param color: Color of the QR code.
    :param background: Background color of the QR code (None for transparent).
    :return: QR Code as SVG string.
    """
    qr = segno.make(data)
    buffer = BytesIO()
    qr.save(
        buffer, kind="png", scale=scale, dark=color, light=background
    )  # Save QR code to buffer
    buffer.seek(0)  # Reset buffer's position to the beginning
    img = Image.open(buffer)  # Open the image using PIL
    return img


def create_qr_svg(data: str, scale=1, color="black", background="white"):
    """
    Generate a QR Code from the provided data and return it as an SVG string.

    :param data: The data to encode in the QR Code.
    :param scale: The scaling factor for the QR Code.
    :param color: Color of the QR code.
    :param background: Background color of the QR code (None for transparent).
    :return: QR Code as SVG string.
    """
    try:
        qr = segno.make(data)
        svg = qr.svg_inline(scale=scale, dark=color, border=2, light=background)
    except Exception as e:
        logger.error(str(e))
        return
    return svg


if __name__ == "__main__":
    example_data = "Hello, QR Code!" * 50
    qr_image = create_qr(example_data)
    if qr_image:
        qr_image.show()  # Display the image
        qr_image.save("example_qr_code.png")  # Save the image to a file
    else:
        logger.error("Failed to create an example QR code.")

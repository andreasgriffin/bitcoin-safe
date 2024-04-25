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
from io import BytesIO

import segno
from PIL import Image

logger = logging.getLogger(__name__)


def create_qr(data: str, scale=10, color="black", background="white"):
    """Generate a QR Code from the provided data and return it as an SVG
    string.

    :param data: The data to encode in the QR Code.
    :param scale: The scaling factor for the QR Code.
    :param color: Color of the QR code.
    :param background: Background color of the QR code (None for
        transparent).
    :return: QR Code as SVG string.
    """
    qr = segno.make(data)
    buffer = BytesIO()
    qr.save(buffer, kind="png", scale=scale, dark=color, light=background)  # Save QR code to buffer
    buffer.seek(0)  # Reset buffer's position to the beginning
    img = Image.open(buffer)  # Open the image using PIL
    return img


def create_qr_svg(content: str, scale=1, color="black", background="white", encoding=None):
    """Generate a QR Code from the provided data and return it as an SVG
    string.

    :param content [str, int, bytes ]: The data to encode. Either a Unicode string, an integer or
            bytes. If bytes are provided, the `encoding` parameter should be
            used to specify the used encoding.
    :param encoding [str or None]: Indicates the encoding in mode "byte". By default
            (`encoding` is ``None``) the implementation tries to use the
            standard conform ISO/IEC 8859-1 encoding and if it does not fit, it
            will use UTF-8. Note that no ECI mode indicator is inserted by
            default (see :paramref:`eci <segno.make.eci>`).
            The `encoding` parameter is case insensitive.
    :param scale: The scaling factor for the QR Code.
    :param color: Color of the QR code.
    :param background: Background color of the QR code (None for transparent).
    :return: QR Code as SVG string.
    """
    try:
        qr = segno.make(content, encoding=encoding)
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

from asyncio.log import logger
import qrcode
import bdkpython as bdk


def create_qr(data: str):

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    try:
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        return img

    except:
        logger.error(f"Could not create qr code of size {len(data)}")
        return None

import qrcode
import bdkpython as bdk


def create_psbt_qr(psbt:bdk.PartiallySignedTransaction):

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4, 
    )
    qr.add_data(psbt.serialize())
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    return img
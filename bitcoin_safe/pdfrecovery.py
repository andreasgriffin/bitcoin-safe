from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import os, io
import webbrowser
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.pdfgen import canvas
from .qr import create_qr
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer


class BitcoinWalletRecoveryPDF:
    def __init__(self):
        styles = getSampleStyleSheet()
        self.style_paragraph = ParagraphStyle(
            name="Centered", parent=styles["BodyText"], alignment=TA_CENTER
        )
        self.style_heading = ParagraphStyle(
            "centered_heading", parent=styles["Heading1"], alignment=TA_CENTER
        )
        self.elements = []

    def create_pdf(self, title, wallet_descriptor_string, keystore_descriptions):
        self.elements.append(
            Paragraph(f"<font size=12><b>{title}</b></font>", self.style_heading)
        )

        # Small subtitle
        self.elements.append(
            Paragraph(f"Created with Bitcoin Safe", self.style_paragraph)
        )
        self.elements.append(
            Paragraph(
                f"https://github.com/andreasgriffin/bitcoin-safe", self.style_paragraph
            )
        )

        # Wallet descriptor (QR code and the string)
        qr_code_buffer = io.BytesIO()
        qr_code_img = create_qr(wallet_descriptor_string)
        qr_code_img.save(qr_code_buffer, format="PNG")
        qr_code_buffer.seek(0)
        qr_code_image = Image(qr_code_buffer, width=200, height=200)
        self.elements.append(qr_code_image)

        self.elements.append(Paragraph(wallet_descriptor_string, self.style_paragraph))
        self.elements.append(Spacer(1, 10))

        # Add a horizontal line as an element
        line = Paragraph(
            "________________________________________________________________________________",
            self.style_paragraph,
        )
        line.keepWithNext = True  # Ensure line and text stay together on the same page
        self.elements.append(line)
        # Add text at the line as an element
        text = "Please fold here!&nbsp;&nbsp;&nbsp;&nbsp;Please fold here!&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Please fold here!&nbsp;&nbsp;&nbsp;&nbsp;Please fold here!&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Please fold here!"
        text_paragraph = Paragraph(text, style=getSampleStyleSheet()["Normal"])
        text_paragraph.spaceBefore = -10  # Adjust the space before the text if needed
        self.elements.append(text_paragraph)

        self.elements.append(Spacer(1, 10))
        # Additional subtitle
        self.elements.append(
            Paragraph(
                "Write the secret 24 words (Seed) onto this paper or onto steel.",
                self.style_paragraph,
            )
        )
        self.elements.append(
            Paragraph(
                "Put the secret 24 words (Seed) AND this QrCode in a secure location",
                self.style_paragraph,
            )
        )
        self.elements.append(Spacer(1, 5))

        for get_keystore_description in keystore_descriptions:
            description_text = Paragraph(get_keystore_description, self.style_paragraph)
            self.elements.append(description_text)
            self.elements.append(Spacer(1, 10))

        # Table title
        table_title = "Secret seed words for a Hardware wallet: Never type into a computer. Never make a picture."

        # 24 words placeholder in three columns
        data = [[""] * 3 for _ in range(9)]  # 9 rows, including the title row
        data[0] = [table_title, "", ""]  # First row is the title
        for i in range(1, 9):
            data[i][0] = f"{i} ___________________"
            data[i][1] = f"{i + 8} ___________________"
            data[i][2] = f"{i + 16} ___________________"

        table = Table(data)

        # Table styling with border and title formatting
        table_style = TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("SPAN", (0, 0), (2, 0)),  # Merging the cells of the title row
                (
                    "BACKGROUND",
                    (0, 0),
                    (2, 0),
                    colors.grey,
                ),  # Background color for the title
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (2, 0),
                    colors.whitesmoke,
                ),  # Text color for the title
                ("FONTNAME", (0, 0), (2, 0), "Helvetica-Bold"),  # Font for the title
            ]
        )

        table.setStyle(table_style)
        table.hAlign = "CENTER"
        self.elements.append(table)

        self.elements.append(Spacer(1, 20))

        # Message to the loved ones
        message_field = Paragraph(
            "Message to the loved ones in case of death:", self.style_paragraph
        )
        self.elements.append(message_field)

    def save_pdf(self, filename):
        document = SimpleDocTemplate(filename, pagesize=letter)
        document.build(self.elements)

    def open_pdf(self, filename):
        if os.path.exists(filename):
            file_uri = Path(filename).absolute().as_uri()
            webbrowser.open_new_tab(file_uri)
        else:
            print("File not found!")


# # Example Usage
# wallet_name = "My Wallet Name"
# wallet_descriptor_qr_code = Image("../bitcoin_safe/gui/icons/qrcode.png")  # Replace with path to your QR code image
# wallet_descriptor_string = "Your wallet descriptor string here"
# wallet_description = "Your wallet description here"

# pdf_creator = BitcoinWalletRecoveryPDF(wallet_name, wallet_descriptor_qr_code, wallet_descriptor_string, wallet_description)
# pdf_creator.create_pdf()
# pdf_filename = "wallet_recovery.pdf"
# pdf_creator.save_pdf(pdf_filename)
# pdf_creator.open_pdf(pdf_filename)

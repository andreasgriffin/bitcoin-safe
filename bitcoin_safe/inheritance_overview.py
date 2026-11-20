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

"""Print a graph of public wallet and signer metadata."""

from dataclasses import dataclass, field
from io import BytesIO
from math import atan2, degrees, hypot
from pathlib import Path
from statistics import mean

import bdkpython as bdk
import networkx as nx
from PIL import Image
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, NextPageTemplate, PageBreak, PageTemplate

from bitcoin_safe.constants import APP_NAME, APP_WEBSITE
from bitcoin_safe.hardware_signers import HardwareSigners
from bitcoin_safe.i18n import translate
from bitcoin_safe.pdf_footer import draw_pdf_footer, pdf_timestamp
from bitcoin_safe.pdf_statement import PdfStatement, create_pdf_statement
from bitcoin_safe.pdfrecovery import BasePDF
from bitcoin_safe.util import resource_path
from bitcoin_safe.wallet import Wallet

INK = HexColor("#222222")
MUTED = HexColor("#535353")
PALE = HexColor("#f3f3f3")
BORDER = HexColor("#9c9c9c")


@dataclass
class SignerDetails:
    label: str
    fingerprint: str
    hardware_signer_id: str
    notes: list[tuple[str, str]] = field(default_factory=list)


def wallet_graph(wallets: list[Wallet]) -> nx.Graph:
    """Connect wallets sharing a fingerprint and device type, retaining distinct notes."""
    graph = nx.Graph()
    for index, wallet in enumerate(wallets):
        wallet_node = ("wallet", index)
        graph.add_node(wallet_node, wallet=wallet)
        for signer_index, signer in enumerate(wallet.keystores):
            fingerprint = signer.fingerprint.strip().lower()
            if fingerprint == "00000000":
                fingerprint = ""
            # An absent fingerprint cannot identify a shared signer.
            identity: tuple[str, str] | tuple[int, int] = (
                (fingerprint, signer.hardware_signer_id) if fingerprint else (index, signer_index)
            )
            signer_node = ("signer", identity)
            if signer_node not in graph:
                graph.add_node(
                    signer_node,
                    signer=SignerDetails(
                        signer.hardware_signer_label(), fingerprint, signer.hardware_signer_id
                    ),
                )
            details: SignerDetails = graph.nodes[signer_node]["signer"]
            note = signer.description.strip()
            if note and all(existing != note for _, existing in details.notes):
                details.notes.append((wallet.id, note))
            graph.add_edge(signer_node, wallet_node)
    return graph


def _signer_icon(signer_id: str) -> ImageReader | None:
    """Render the existing signer SVG in black, independently of the application theme."""
    signer = HardwareSigners.from_id(signer_id) or HardwareSigners.generic
    path = Path(resource_path("gui", "icons", "hardware_signers", signer.icon_name))
    if not path.is_file():
        return None
    svg = path.read_bytes().replace(b"currentColor", b"#222222")
    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        return None
    image = QImage(128, 128, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, 128, 128))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        return None
    return ImageReader(Image.open(BytesIO(buffer.data().data())))


def _wrapped_lines(text: str, font: str, width: float, font_size: float = 8.5) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        for line in simpleSplit(paragraph, font, font_size, width) or [""]:
            while pdfmetrics.stringWidth(line, font, font_size) > width:
                low, high = 1, len(line)
                while low < high:
                    middle = (low + high + 1) // 2
                    if pdfmetrics.stringWidth(line[:middle], font, font_size) <= width:
                        low = middle
                    else:
                        high = middle - 1
                lines.append(line[:low])
                line = line[low:]
            lines.append(line)
    return lines


def _fit_title(text: str, font: str, width: float) -> str:
    if pdfmetrics.stringWidth(text, font, 11) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "...", font, 11) > width:
        text = text[:-1]
    return text + "..."


def _draw_page_title(pdf: Canvas, title: str, font: str, width: float, y: float, font_size: float) -> None:
    title_width = pdfmetrics.stringWidth(title, font, font_size)
    pdf.setFont(font, min(font_size, font_size * (width - 72) / max(title_width, 1)))
    pdf.drawCentredString(width / 2, y, title)


def _card(pdf: Canvas, x: float, y: float, width: float, height: float, signer: bool = False) -> None:
    pdf.setFillColor(HexColor("#f7f7f7") if signer else HexColor("#ffffff"))
    pdf.setStrokeColor(BORDER)
    pdf.setLineWidth(0.8)
    pdf.roundRect(x, y, width, height, 9, fill=1, stroke=1)


def _qr(pdf: Canvas, value: str, x: float, y: float, size: float) -> None:
    qr = QrCodeWidget(value, barLevel="L")
    x1, y1, x2, y2 = qr.getBounds()
    drawing = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    drawing.add(qr)
    renderPDF.draw(drawing, pdf, x, y)


def _descriptor_lines(wallet: Wallet) -> list[str]:
    return _wrapped_lines(str(wallet.multipath_descriptor), "Courier", 214, 4)


def _wallet_height(wallet: Wallet) -> float:
    return 191 + 4.5 * len(_descriptor_lines(wallet))


def _page_wallet_height(graph: nx.Graph, page: "GraphPage") -> float:
    return sum(_wallet_height(graph.nodes[node]["wallet"]) + 14 for node in page.wallets)


MAX_SIGNER_NOTE_LINES = 5


def _signer_note_lines(details: SignerDetails, font: str) -> list[str]:
    return [
        line
        for wallet_name, note in details.notes
        for line in _wrapped_lines(
            f"{wallet_name} note: {note}" if len(details.notes) > 1 else note, font, 260, 7.5
        )
    ]


def _card_note_lines(details: SignerDetails, font: str) -> list[str]:
    lines = _signer_note_lines(details, font)
    if len(lines) > MAX_SIGNER_NOTE_LINES:
        return lines[: MAX_SIGNER_NOTE_LINES - 1] + ["More notes follow the graph."]
    return lines


def _signer_height(lines: list[str]) -> float:
    return max(116, 101 + 8.5 * (len(lines) - 1))


def _page_signer_height(page: "GraphPage") -> float:
    return sum(_signer_height(lines) + 6 for _, lines in page.signers) - 6 if page.signers else 0


@dataclass
class GraphPage:
    signers: list[tuple[object, list[str]]] = field(default_factory=list)
    wallets: list[object] = field(default_factory=list)


def _graph_pages(graph: nx.Graph, font: str) -> list[GraphPage]:
    """Pack connected groups together, splitting a group only when necessary."""
    pages: list[GraphPage] = []
    order = {node: i for i, node in enumerate(graph)}
    for component in nx.connected_components(graph):
        wallets = sorted((node for node in component if node[0] == "wallet"), key=order.__getitem__)
        signers = sorted((node for node in component if node[0] == "signer"), key=order.__getitem__)
        if wallets:
            # Visit related signers together when an oversized component needs splitting.
            root = max(wallets, key=graph.degree)
            traversal = list(nx.bfs_tree(graph, root))
            signers = [node for node in traversal if node[0] == "signer"]
        signer_cards: list[tuple[object, list[str]]] = []
        for node in signers:
            details: SignerDetails = graph.nodes[node]["signer"]
            signer_cards.append((node, _card_note_lines(details, font)))
        for node in wallets:
            if _wallet_height(graph.nodes[node]["wallet"]) > 420:
                raise ValueError("Wallet descriptor is too long to fit in a printable graph node")

        group = GraphPage(signers=signer_cards, wallets=list(wallets))
        if (
            len(signer_cards) <= 3
            and _page_signer_height(group) <= 420
            and len(wallets) <= 2
            and _page_wallet_height(graph, group) - 14 <= 420
        ):
            # A whole connected component can share a sheet with other complete components.
            for page in pages:
                if (
                    len(page.signers) + len(signer_cards) <= 3
                    and _page_signer_height(page)
                    + _page_signer_height(group)
                    + (6 if page.signers and group.signers else 0)
                    <= 420
                    and len(page.wallets) + len(wallets) <= 2
                    and _page_wallet_height(graph, page) + _page_wallet_height(graph, group) - 14 <= 420
                ):
                    page.signers.extend(signer_cards)
                    page.wallets.extend(wallets)
                    break
            else:
                pages.append(group)
            continue

        # The group cannot fit on one sheet. Give its wallets the pages with the most
        # connected signers; cross-page edges receive explicit continuation markers.
        group_pages = [GraphPage()]
        for signer_card in signer_cards:
            current = group_pages[-1]
            if len(current.signers) == 3 or (
                _page_signer_height(current) + (6 if current.signers else 0) + _signer_height(signer_card[1])
                > 420
            ):
                current = GraphPage()
                group_pages.append(current)
            current.signers.append(signer_card)

        def matches(wallet: object, page: GraphPage) -> int:
            return len({node for node, _ in page.signers if graph.has_edge(node, wallet)})

        wallets.sort(key=lambda wallet: max(matches(wallet, page) for page in group_pages), reverse=True)
        for wallet in wallets:
            wallet_height = _wallet_height(graph.nodes[wallet]["wallet"])
            available = [
                page
                for page in group_pages
                if len(page.wallets) < 2 and _page_wallet_height(graph, page) + wallet_height <= 420
            ]
            if not available:
                available = [GraphPage()]
                group_pages.extend(available)
            max(available, key=lambda page: (matches(wallet, page), -len(page.wallets))).wallets.append(
                wallet
            )
        pages.extend(group_pages)
    return pages or [GraphPage()]


def _wallet_positions(
    graph: nx.Graph, page: GraphPage, signer_y: list[float], page_height: float
) -> dict[object, float]:
    """Place wallet cards near their connected signers without overlap."""
    if not page.wallets:
        return {}
    top_limit, bottom_limit, gap = page_height - 100, 75.0, 14.0
    heights = {node: _wallet_height(graph.nodes[node]["wallet"]) for node in page.wallets}
    desired: dict[object, float] = {}
    for wallet in page.wallets:
        anchors = [
            y + _signer_height(lines) - 4
            for (signer, lines), y in zip(page.signers, signer_y, strict=True)
            if graph.has_edge(signer, wallet)
        ]
        desired[wallet] = mean(anchors) if anchors else (top_limit + bottom_limit + heights[wallet]) / 2
    ordered = sorted(page.wallets, key=desired.__getitem__, reverse=True)
    first = ordered[0]
    if len(ordered) == 1:
        top = max(bottom_limit + heights[first], min(top_limit, desired[first]))
        return {first: top - heights[first]}

    second = ordered[1]
    first_top = desired[first]
    if desired[second] > first_top - heights[first] - gap:
        first_top = (first_top + desired[second] + heights[first] + gap) / 2
    first_top = max(bottom_limit + heights[second] + gap + heights[first], min(top_limit, first_top))
    second_top = max(bottom_limit + heights[second], min(first_top - heights[first] - gap, desired[second]))
    return {first: first_top - heights[first], second: second_top - heights[second]}


@dataclass(frozen=True)
class CrossPageConnection:
    signer: object
    wallet: object
    signer_page: int
    signer_position: int
    wallet_page: int


def _cross_page_connections(
    graph: nx.Graph, pages: list[GraphPage], page_offset: int = 0
) -> list[CrossPageConnection]:
    """Identify edges which need matching continuation markers on two sheets."""
    signer_pages: dict[object, list[tuple[int, int]]] = {}
    wallet_pages: dict[object, int] = {}
    for number, page in enumerate(pages, 1 + page_offset):
        for position, (signer, _) in enumerate(page.signers, 1):
            signer_pages.setdefault(signer, []).append((number, position))
        for wallet in page.wallets:
            wallet_pages[wallet] = number
    connections: list[CrossPageConnection] = []
    for wallet, wallet_page in wallet_pages.items():
        for signer in graph.neighbors(wallet):
            if any(page == wallet_page for page, _ in signer_pages[signer]):
                continue
            signer_page, signer_position = signer_pages[signer][0]
            connections.append(CrossPageConnection(signer, wallet, signer_page, signer_position, wallet_page))
    return connections


@dataclass(frozen=True)
class PageCrossing:
    connection: CrossPageConnection
    x: float
    y: float
    fingerprint: str
    other_page: int


def _page_crossings(
    graph: nx.Graph,
    page: GraphPage,
    page_number: int,
    connections: list[CrossPageConnection],
    left_x: float,
    right_x: float,
    left_y: list[float],
    right_y: list[float],
) -> list[PageCrossing]:
    """Locate all off-page edges at the border of their corresponding node."""
    crossings: list[PageCrossing] = []
    for position, ((node, lines), y) in enumerate(zip(page.signers, left_y, strict=True), 1):
        edges = [
            edge
            for edge in connections
            if edge.signer == node and edge.signer_page == page_number and edge.signer_position == position
        ]
        for index, edge in enumerate(edges):
            details: SignerDetails = graph.nodes[edge.signer]["signer"]
            crossings.append(
                PageCrossing(
                    edge,
                    left_x + 300,
                    y + 30 + (_signer_height(lines) - 85) * (index + 1) / (len(edges) + 1),
                    details.fingerprint,
                    edge.wallet_page,
                )
            )
    for node, y in zip(page.wallets, right_y, strict=True):
        edges = [edge for edge in connections if edge.wallet == node and edge.wallet_page == page_number]
        for index, edge in enumerate(edges):
            details = graph.nodes[edge.signer]["signer"]
            node_height = _wallet_height(graph.nodes[node]["wallet"])
            crossings.append(
                PageCrossing(
                    edge,
                    right_x,
                    y + 30 + (node_height - 85) * (index + 1) / (len(edges) + 1),
                    details.fingerprint,
                    edge.signer_page,
                )
            )
    return crossings


def _draw_page_crossings(
    pdf: Canvas, crossings: list[PageCrossing], left_x: float, right_x: float, font: str, page_number: int
) -> None:
    """Draw cross-page lines towards the page where their other endpoint appears."""
    midpoint = (left_x + 300 + right_x) / 2
    for goes_up in (True, False):
        group = [crossing for crossing in crossings if (crossing.other_page < page_number) == goes_up]
        group.sort(
            key=lambda crossing: (
                crossing.x,
                (-1 if goes_up else 1) * crossing.y * (1 if crossing.x < midpoint else -1),
            )
        )
        for index, crossing in enumerate(group):
            edge_x = left_x + 315 + (right_x - left_x - 330) * (index + 1) / (len(group) + 1)
            edge_y = landscape(A4)[1] - 74 if goes_up else 44.0
            x1, y1, x2, y2 = crossing.x, crossing.y, edge_x, edge_y
            pdf.setStrokeColor(MUTED)
            pdf.setLineWidth(1)
            pdf.line(x1, y1, x2, y2)
            # Rotate only the caption, keeping its baseline just above the line.
            if x1 > x2:
                x1, y1, x2, y2 = x2, y2, x1, y1
            length = hypot(x2 - x1, y2 - y1)
            label = f"{crossing.fingerprint.upper() or 'unknown fingerprint'}  see page {crossing.other_page}"
            font_size = max(
                4.0, min(7.0, 7.0 * (length - 14) / max(pdfmetrics.stringWidth(label, font, 7), 1))
            )
            label_width = pdfmetrics.stringWidth(label, font, font_size)
            distance = min(length / 2, 7 + label_width / 2)
            # Place the caption near the page edge, keeping it inside the line segment.
            caption_x = edge_x + (crossing.x - edge_x) * distance / length
            caption_y = edge_y + (crossing.y - edge_y) * distance / length
            pdf.saveState()
            pdf.translate(caption_x, caption_y)
            pdf.rotate(degrees(atan2(y2 - y1, x2 - x1)))
            pdf.setFillColor(INK)
            pdf.setFont(font, font_size)
            pdf.drawCentredString(0, 3, label)
            pdf.restoreState()


class RecoveryGuideSheet(Flowable):
    """A short, printable guide for the person using the overview."""

    def __init__(self, font: str, created_with: str, title: str, created_date: str) -> None:
        super().__init__()
        self.font, self.created_with, self.title, self.created_date = font, created_with, title, created_date
        width, height = landscape(A4)
        self.width, self.height = width - 72, height - 72

    def draw(self) -> None:
        pdf = self.canv
        pdf.translate(-36, -36)
        width, height = landscape(A4)
        pdf.setFillColor(INK)
        _draw_page_title(pdf, self.title, self.font, width, height - 46, 18)
        pdf.setFillColor(MUTED)
        pdf.setFont(self.font, 9)
        pdf.drawCentredString(width / 2, height - 65, f"{self.created_with} {APP_NAME}:  {APP_WEBSITE}")
        pdf.setStrokeColor(BORDER)
        pdf.line(75, height - 82, width - 75, height - 82)
        pdf.setFillColor(INK)
        pdf.setFont(self.font, 14)
        pdf.drawString(95, height - 125, "HOW TO RECOVER A WALLET")
        pdf.setFont(self.font, 11)
        steps = [
            "1. Choose a wallet on the right of the following pages.",
            "2. Find the required signers by following the lines to the left.",
            "3. Locate the signing devices or seed backups using the location fields.",
            "4. Restore the wallet using its QR code in compatible Bitcoin wallet software.",
            "5. Use the required signers to authorize transactions.",
        ]
        for index, step in enumerate(steps):
            pdf.drawString(105, height - 160 - index * 29, step)
        pdf.setFillColor(MUTED)
        pdf.setFont(self.font, 10)
        clarification = (
            "A signing device and its seed backup are two ways of accessing the same signer. "
            "A seed backup can restore access if the original device is lost. "
            "An additional passphrase may also be required."
        )
        for index, line in enumerate(_wrapped_lines(clarification, self.font, width - 210, 10)):
            pdf.drawString(105, height - 334 - index * 15, line)
        pdf.setFillColor(INK)
        pdf.setFont(self.font, 11)
        pdf.drawString(
            105, height - 410, "Never share seed words or passphrases, or enter them into a website."
        )
        pdf.setFillColor(MUTED)
        pdf.setFont(self.font, 8)
        pdf.drawString(36, 24, "Includes currently open wallets only. Other wallets may exist.")
        draw_pdf_footer(pdf, width, self.font, self.created_date)


class GraphSheet(Flowable):
    """A full graph sheet that can share a document with statement flowables."""

    def __init__(
        self,
        graph: nx.Graph,
        page: GraphPage,
        page_number: int,
        font: str,
        created_with: str,
        title: str,
        created_date: str,
        connections: list[CrossPageConnection],
    ) -> None:
        super().__init__()
        self.graph = graph
        self.page = page
        self.page_number = page_number
        self.font = font
        self.created_with = created_with
        self.title = title
        self.created_date = created_date
        self.connections = connections
        width, height = landscape(A4)
        self.width, self.height = width - 72, height - 72

    def draw(self) -> None:
        pdf = self.canv
        pdf.translate(-36, -36)
        width, height = landscape(A4)
        graph, page, page_number = self.graph, self.page, self.page_number
        font, created_with = self.font, self.created_with
        connections = self.connections
        pdf.setFillColor(INK)
        _draw_page_title(pdf, self.title, font, width, height - 32, 15)
        pdf.setFillColor(MUTED)
        pdf.setFont(font, 9)
        pdf.drawCentredString(width / 2, height - 48, f"{created_with} {APP_NAME}:  {APP_WEBSITE}")
        pdf.setFont(font, 8)
        pdf.drawCentredString(
            width / 2,
            height - 63,
            "Follow the lines to see which signing devices or seed backups can be used for each wallet.",
        )
        pdf.setStrokeColor(BORDER)
        pdf.line(36, height - 70, width - 36, height - 70)
        left_x, right_x = 36, width - 274
        left_y: list[float] = []
        cursor = height - 94
        for _, lines in page.signers:
            cursor -= _signer_height(lines)
            left_y.append(cursor)
            cursor -= 6
        positions = _wallet_positions(graph, page, left_y, height)
        right_y = [positions[node] for node in page.wallets]
        pdf.setFillColor(MUTED)
        pdf.setFont(font, 8)
        pdf.drawString(left_x, height - 85, "SIGNING DEVICES & SEED BACKUPS")
        pdf.drawString(right_x, height - 85, "BITCOIN WALLETS")
        # Draw connections first so they remain behind the cards.
        pdf.setStrokeColor(MUTED)
        pdf.setLineWidth(1.1)
        for (node, lines), y in zip(page.signers, left_y, strict=True):
            for wallet_node, wy in zip(page.wallets, right_y, strict=True):
                if graph.has_edge(node, wallet_node):
                    pdf.line(
                        left_x + 300,
                        y + _signer_height(lines) - 24,
                        right_x,
                        wy + _wallet_height(graph.nodes[wallet_node]["wallet"]) - 20,
                    )
        crossings = _page_crossings(graph, page, page_number, connections, left_x, right_x, left_y, right_y)
        _draw_page_crossings(pdf, crossings, left_x, right_x, font, page_number)
        for (node, lines), y in zip(page.signers, left_y, strict=True):
            signer = graph.nodes[node]["signer"]
            top = y + _signer_height(lines)
            _card(pdf, left_x, y, 300, _signer_height(lines), signer=True)
            pdf.setFillColor(PALE)
            pdf.roundRect(left_x + 10, top - 32, 24, 24, 5, fill=1, stroke=0)
            icon = _signer_icon(signer.hardware_signer_id)
            if icon:
                pdf.drawImage(icon, left_x + 12, top - 30, 20, 20, mask="auto")
            pdf.setFillColor(INK)
            pdf.setFont(font, 11)
            shared_count = graph.degree[node]
            title = _fit_title(signer.label, font, 145 if shared_count > 1 else 240)
            pdf.drawString(left_x + 42, top - 17, title)
            pdf.setFillColor(MUTED)
            if shared_count > 1:
                pdf.setFont(font, 7)
                pdf.drawRightString(left_x + 288, top - 17, f"Used by {shared_count} wallets")
            pdf.setFont(font, 8.5)
            fingerprint = signer.fingerprint.upper() if signer.fingerprint else "Not available"
            pdf.drawString(left_x + 42, top - 30, f"Fingerprint: {fingerprint}")
            pdf.setFont(font, 7.5)
            for i, line in enumerate(lines):
                pdf.drawString(left_x + 12, top - 42 - i * 8.5, line)
            pdf.setFont(font, 7)
            signer_location = "Signing device location:"
            pdf.drawString(left_x + 12, y + 34, signer_location)
            pdf.drawString(left_x + 12, y + 10, "Seed backup location:")
            pdf.setStrokeColor(MUTED)
            pdf.line(
                left_x + 20 + pdfmetrics.stringWidth(signer_location, font, 7), y + 33, left_x + 287, y + 33
            )
            pdf.line(left_x + 91, y + 9, left_x + 287, y + 9)
        for node, y in zip(page.wallets, right_y, strict=True):
            wallet: Wallet = graph.nodes[node]["wallet"]
            threshold, count = wallet.get_mn_tuple()
            card_height = _wallet_height(wallet)
            top = y + card_height
            _card(pdf, right_x, y, 238, card_height)
            pdf.setFillColor(INK)
            pdf.setFont(font, 11)
            pdf.drawString(right_x + 12, top - 17, _fit_title(wallet.id, font, 210))
            pdf.setFillColor(MUTED)
            pdf.setFont(font, 8.5)
            policy = (
                f"Requires any {threshold} of these {count} signers" if count > 1 else "Requires 1 signer"
            )
            pdf.drawString(right_x + 12, top - 30, policy)
            amount = wallet.get_balance().total
            whole, fraction = divmod(abs(amount), 100_000_000)
            balance = f"{'-' if amount < 0 else ''}{whole}.{fraction:08d} BTC"
            if wallet.network != bdk.Network.BITCOIN:
                balance += " (test coins)"
            pdf.drawString(right_x + 12, top - 42, f"Balance: {balance}")
            _qr(pdf, str(wallet.multipath_descriptor), right_x + 56, top - 171, 125)
            pdf.setFont(font, 7.5)
            pdf.drawCentredString(right_x + 119, top - 181, "Scan to restore wallet information.")
            pdf.setFillColor(INK)
            pdf.setFont("Courier", 4)
            for i, line in enumerate(_descriptor_lines(wallet)):
                pdf.drawString(right_x + 12, top - 190 - i * 4.5, line)
        pdf.setFillColor(MUTED)
        pdf.setFont(font, 8)
        pdf.drawString(36, 24, "Includes currently open wallets only. Other wallets may exist.")
        draw_pdf_footer(pdf, width, font, self.created_date)
        if connections:
            pdf.drawRightString(width - 36, 38, "Lines at page edges continue on the indicated page.")


class SignerNotesSheet(Flowable):
    """Continue unusually long signer notes without creating another signer card."""

    def __init__(self, signer: SignerDetails, lines: list[str], font: str, created_date: str) -> None:
        super().__init__()
        self.signer, self.lines, self.font, self.created_date = signer, lines, font, created_date
        width, height = landscape(A4)
        self.width, self.height = width - 72, height - 72

    def draw(self) -> None:
        pdf = self.canv
        pdf.translate(-36, -36)
        width, height = landscape(A4)
        pdf.setFillColor(INK)
        pdf.setFont(self.font, 15)
        pdf.drawString(36, height - 40, "Signer notes continued")
        pdf.setFont(self.font, 10)
        fingerprint = self.signer.fingerprint.upper() or "Not available"
        pdf.drawString(36, height - 60, f"{self.signer.label}  |  Fingerprint: {fingerprint}")
        pdf.setFont(self.font, 8.5)
        for i, line in enumerate(self.lines):
            pdf.drawString(36, height - 85 - i * 11, line)
        pdf.setFont(self.font, 8)
        pdf.drawString(36, 24, "Includes currently open wallets only. Other wallets may exist.")
        draw_pdf_footer(pdf, width, self.font, self.created_date)


def _graph_title(wallets: list[Wallet]) -> str:
    networks = sorted({wallet.network.name for wallet in wallets})
    title = "Inheritance overview - " + ", ".join(networks)
    if any(wallet.network != bdk.Network.BITCOIN for wallet in wallets):
        title += " (test coins have no monetary value)"
    return title


def export_inheritance_overview(
    wallets: list[Wallet],
    path: Path,
    font: str = "Helvetica",
    created_with: str = "Created with",
    lang_code: str = "en_US",
) -> None:
    """Render the graph followed by the existing wallet balance statements."""
    graph = wallet_graph(wallets)
    pages = _graph_pages(graph, font)
    connections = _cross_page_connections(graph, pages, page_offset=1)
    width, height = landscape(A4)
    created_date = pdf_timestamp()
    title = _graph_title(wallets)
    sheets: list[Flowable] = [RecoveryGuideSheet(font, created_with, title, created_date)]
    sheets.extend(
        GraphSheet(graph, page, i, font, created_with, title, created_date, connections)
        for i, page in enumerate(pages, 2)
    )
    for node in graph:
        if node[0] != "signer":
            continue
        signer: SignerDetails = graph.nodes[node]["signer"]
        lines = _signer_note_lines(signer, font)
        if len(lines) > MAX_SIGNER_NOTE_LINES:
            remaining = lines[MAX_SIGNER_NOTE_LINES - 1 :]
            sheets.extend(
                SignerNotesSheet(signer, remaining[i : i + 40], font, created_date)
                for i in range(0, len(remaining), 40)
            )
    story: list[Flowable] = []
    for sheet in sheets:
        if story:
            story.append(PageBreak())
        story.append(sheet)
    statements: list[PdfStatement] = []
    for wallet in wallets:
        statement = create_pdf_statement(wallet, lang_code, created_at=created_date)
        statements.append(statement)
        story.extend([NextPageTemplate("statements"), PageBreak(), *statement.elements])
    document = BaseDocTemplate(str(path), pagesize=(width, height))
    graph_frame = Frame(
        36, 36, width - 72, height - 72, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0
    )
    statement_width, statement_height = letter
    statement_frame = Frame(
        36,
        36,
        statement_width - 72,
        statement_height - 72,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    document.addPageTemplates([PageTemplate(id="graph", frames=graph_frame, pagesize=(width, height))])
    if statements:
        document.addPageTemplates(
            [
                PageTemplate(
                    id="statements", frames=statement_frame, pagesize=letter, onPage=statements[0].draw_footer
                )
            ]
        )
    document.build(story)


class InheritanceOverviewPDF(BasePDF):
    """Adapter for the application's temporary PDF viewer flow."""

    def __init__(self, wallets: list[Wallet], lang_code: str) -> None:
        super().__init__(lang_code)
        self.wallets = wallets
        self.lang_code = lang_code

    def save_pdf(self, filename: str) -> None:
        export_inheritance_overview(
            self.wallets,
            Path(filename),
            self.font_name,
            translate("pdf", "Created with", no_translate=self.no_translate),
            self.lang_code,
        )

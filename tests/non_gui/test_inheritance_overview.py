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

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import bdkpython as bdk

from bitcoin_safe.inheritance_overview import (
    MAX_SIGNER_NOTE_LINES,
    CrossPageConnection,
    GraphPage,
    PageCrossing,
    _cross_page_connections,
    _descriptor_lines,
    _draw_page_crossings,
    _graph_pages,
    _graph_title,
    _page_signer_height,
    _signer_height,
    _signer_note_lines,
    _wallet_height,
    _wallet_positions,
    export_inheritance_overview,
    wallet_graph,
)
from bitcoin_safe.wallet import Wallet


def wallet(name: str, fingerprints: list[str]) -> Wallet:
    signers = [
        SimpleNamespace(
            fingerprint=fingerprint,
            xpub=f"xpub-{fingerprint.lower()}" if fingerprint and fingerprint != "00000000" else "",
            description="",
            key_origin="m/84h/1h/0h",
            derivation_path="/<0;1>/*",
            hardware_signer_id="generic",
            hardware_signer_label=lambda: "Signer",
        )
        for fingerprint in fingerprints
    ]
    return cast(
        Wallet,
        SimpleNamespace(
            id=name,
            network=bdk.Network.SIGNET,
            keystores=signers,
            get_mn_tuple=lambda: (1, len(signers)),
            multipath_descriptor="wpkh([5aa39a43/84'/1'/0']tpubDD2ww8jti4Xc8vkaJH2yC1r7C9TVb9bG3kTi6BFm5w3aAZmtFHktK6Mv2wfyBvSPqV9QeH1QXrmHzabuNh1sgRtAsUoG7dzVjc9WvGm78PD/<0;1>/*)#xaf9qzlf",
            get_balance=lambda: SimpleNamespace(total=125000),
            get_addresses=lambda: ["tb1qexample"],
            get_addr_balance=lambda address: SimpleNamespace(total=125000),
            get_label_for_address=lambda address: "Gift & savings <family>",
            get_address_info_min=lambda address: SimpleNamespace(index=0),
            labels=SimpleNamespace(get_category=lambda address: "Savings"),
        ),
    )


def test_shared_and_missing_fingerprints() -> None:
    graph = wallet_graph([wallet("First", ["AABBCCDD", "00000000"]), wallet("Second", ["aabbccdd", ""])])
    assert len(graph) == 5
    assert set(graph.neighbors(("wallet", 0))) & set(graph.neighbors(("wallet", 1))) == {
        ("signer", ("aabbccdd", "generic"))
    }


def test_pdf_export_with_multiple_pages(tmp_path: Path) -> None:
    wallets = [wallet("First", [f"{i:08x}" for i in range(1, 9)]), wallet("Second", ["00000001"])]
    path = tmp_path / "wallets.pdf"
    from bitcoin_safe.pdf_statement import create_pdf_statement

    with patch(
        "bitcoin_safe.inheritance_overview.create_pdf_statement", wraps=create_pdf_statement
    ) as create:
        export_inheritance_overview(wallets, path)
    assert [call.args[0].id for call in create.call_args_list] == ["First", "Second"]
    pdf = path.read_bytes()
    assert pdf.startswith(b"%PDF-")
    # Three graph pages and two balance statements.
    assert pdf.count(b"/Type /Page\n") == 5


def test_wallet_name_with_markup_is_literal_in_combined_pdf(tmp_path: Path) -> None:
    from reportlab.platypus import Paragraph

    from bitcoin_safe.pdf_statement import create_pdf_statement

    name = "Family <b> & <unclosed"
    named_wallet = wallet(name, ["00000001"])
    statement = create_pdf_statement(named_wallet, "en_US")
    title = statement.elements[0]
    assert isinstance(title, Paragraph)
    assert name in title.getPlainText()

    path = tmp_path / "overview.pdf"
    export_inheritance_overview([named_wallet], path)
    assert path.read_bytes().startswith(b"%PDF-")


def test_shared_signer_keeps_notes_without_derivation_paths() -> None:
    first = wallet("First", ["AABBCCDD"])
    second = wallet("Second", ["AABBCCDD"])
    first.keystores[0].description = "Stored securely"
    second.keystores[0].key_origin = "m/48h/1h/0h/2h"
    graph = wallet_graph([first, second])
    details = graph.nodes[("signer", ("aabbccdd", "generic"))]["signer"].notes
    assert details == [("First", "Stored securely")]


def test_long_note_continues_on_another_page(tmp_path: Path) -> None:
    from reportlab.pdfbase import pdfmetrics

    from bitcoin_safe.inheritance_overview import _wrapped_lines

    note = "x" * 1500
    lines = _wrapped_lines(note, "Helvetica", 260)
    assert "".join(lines) == note
    assert all(pdfmetrics.stringWidth(line, "Helvetica", 8.5) <= 260 for line in lines)
    first = wallet("First", ["aabbccdd"])
    first.keystores[0].description = note
    path = tmp_path / "long-note.pdf"
    export_inheritance_overview([first], path)
    assert path.read_bytes().count(b"/Type /Page\n") > 1


def test_wallets_appear_once_on_pages_with_their_signers() -> None:
    graph = wallet_graph(
        [wallet("Multisig", ["00000001", "00000002", "00000003"]), wallet("Solo", ["00000004"])]
    )
    pages = _graph_pages(graph, "Helvetica")
    assert len(pages) == 2
    assert pages[0].wallets == [("wallet", 0)]
    assert pages[1].wallets == [("wallet", 1)]
    assert _cross_page_connections(graph, pages) == []


def test_cross_page_edges_are_listed_without_repeating_wallets() -> None:
    graph = wallet_graph([wallet("Large", [f"{i:08x}" for i in range(1, 5)])])
    pages = _graph_pages(graph, "Helvetica")
    assert sum(page.wallets.count(("wallet", 0)) for page in pages) == 1
    connections = _cross_page_connections(graph, pages)
    assert len(connections) == 1
    assert connections[0].signer_page == 2
    assert connections[0].wallet_page == 1
    assert graph.nodes[connections[0].signer]["signer"].fingerprint == "00000004"
    assert graph.nodes[connections[0].wallet]["wallet"].id == "Large"


def test_title_and_descriptor_contents() -> None:
    first = wallet("First", ["00000001"])
    assert _graph_title([first]).startswith("Inheritance overview - ")
    assert "SIGNET" in _graph_title([first])
    assert "no monetary value" in _graph_title([first])
    assert "".join(_descriptor_lines(first)) == first.multipath_descriptor
    first.network = bdk.Network.BITCOIN
    assert "BITCOIN" in _graph_title([first])
    assert "no monetary value" not in _graph_title([first])


def test_balance_statement_contains_funded_address_and_total() -> None:
    from bitcoin_safe.pdf_statement import create_pdf_statement

    statement = create_pdf_statement(wallet("First", ["00000001"]), "en_US")
    table = statement.elements[-1]
    assert "tBTC" in table._cellvalues[0][3].getPlainText()
    assert table._cellvalues[1][1].getPlainText() == "tb1qexample"
    assert table._cellvalues[1][2].getPlainText() == "Gift & savings <family>"
    assert "125" in table._cellvalues[1][3].getPlainText()
    assert table._cellvalues[1][3].getPlainText() == table._cellvalues[2][3].getPlainText()


def test_related_wallets_remain_together_despite_interleaved_input() -> None:
    # The third wallet shares a signer with the first; the second is unrelated.
    graph = wallet_graph(
        [
            wallet("Related A", ["00000001", "00000002"]),
            wallet("Unrelated", ["00000003", "00000004"]),
            wallet("Related B", ["00000001", "00000005"]),
        ]
    )
    pages = _graph_pages(graph, "Helvetica")
    assert len(pages) == 2
    assert set(pages[0].wallets) == {("wallet", 0), ("wallet", 2)}
    assert pages[1].wallets == [("wallet", 1)]
    assert _cross_page_connections(graph, pages) == []


def test_cross_page_connection_draws_labeled_lines_on_both_pages(tmp_path: Path) -> None:
    wallets = [wallet("Large", [f"{i:08x}" for i in range(1, 5)])]
    from reportlab.pdfgen.canvas import Canvas

    original_rotate = Canvas.rotate
    with (
        patch(
            "bitcoin_safe.inheritance_overview._draw_page_crossings", wraps=_draw_page_crossings
        ) as draw_crossings,
        patch.object(Canvas, "rotate", autospec=True, side_effect=original_rotate) as rotate,
    ):
        export_inheritance_overview(wallets, tmp_path / "graph.pdf")
    assert len(rotate.call_args_list) >= 2
    assert all(abs(call.args[1]) > 1 for call in rotate.call_args_list)
    crossings = [crossing for call in draw_crossings.call_args_list for crossing in call.args[1]]
    assert len(crossings) == 2
    assert {crossing.fingerprint for crossing in crossings} == {"00000004"}
    assert {crossing.other_page for crossing in crossings} == {1, 2}
    assert len({crossing.connection for crossing in crossings}) == 1


def test_seed_boxes_include_handwritten_backup_location(tmp_path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas

    original = Canvas.drawString
    first = wallet("First", ["00000001", "00000002"])
    first.keystores[0].hardware_signer_label = lambda: "Jade Plus"
    with patch.object(Canvas, "drawString", autospec=True, side_effect=original) as draw_string:
        export_inheritance_overview([first], tmp_path / "graph.pdf")
    labels = [call.args[3] for call in draw_string.call_args_list]
    assert labels.count("Seed backup location:") == 2
    assert "Jade Plus location:" in labels
    assert "Signer location:" in labels
    jade_y = next(
        call.args[2] for call in draw_string.call_args_list if call.args[3] == "Jade Plus location:"
    )
    backup_y = next(
        call.args[2] for call in draw_string.call_args_list if call.args[3] == "Seed backup location:"
    )
    assert jade_y - backup_y >= 22


def test_long_signer_notes_leave_space_for_location_lines() -> None:
    first = wallet("First", ["00000001"])
    first.keystores[0].description = "first\nsecond\nthird\nfourth"
    graph = wallet_graph([first])
    fragments = [lines for page in _graph_pages(graph, "Helvetica") for _, lines in page.signers]
    assert [len(lines) for lines in fragments] == [4]
    assert "fourth" in fragments[0][3]
    assert _signer_height(fragments[0]) > _signer_height([])


def test_datetime_and_page_numbers_on_graph_and_statement_pages(tmp_path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas

    expected = "2026-11-19 12:34:56 UTC"
    original_centered = Canvas.drawCentredString
    original_right = Canvas.drawRightString
    with (
        patch("bitcoin_safe.inheritance_overview.pdf_timestamp", return_value=expected),
        patch.object(Canvas, "drawCentredString", autospec=True, side_effect=original_centered) as centered,
        patch.object(Canvas, "drawRightString", autospec=True, side_effect=original_right) as right,
    ):
        export_inheritance_overview(
            [wallet("Large", [f"{i:08x}" for i in range(1, 5)])], tmp_path / "graph.pdf"
        )
    dates = [call.args[3] for call in centered.call_args_list if call.args[3].startswith("Date: ")]
    pages = [call.args[3] for call in right.call_args_list if call.args[3].startswith("Page ")]
    assert dates == [f"Date: {expected}"] * 3
    assert pages == ["Page 1", "Page 2", "Page 3"]


def test_standalone_balance_statement_has_datetime_and_page_number(tmp_path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas

    from bitcoin_safe.pdf_statement import create_pdf_statement

    statement = create_pdf_statement(
        wallet("First", ["00000001"]), "en_US", created_at="2026-11-19 12:34:56 UTC"
    )
    with (
        patch.object(
            Canvas, "drawCentredString", autospec=True, side_effect=Canvas.drawCentredString
        ) as centered,
        patch.object(Canvas, "drawRightString", autospec=True, side_effect=Canvas.drawRightString) as right,
    ):
        statement.save_pdf(str(tmp_path / "statement.pdf"))
    assert any(call.args[3] == "Date: 2026-11-19 12:34:56 UTC" for call in centered.call_args_list)
    assert any(call.args[3] == "Page 1" for call in right.call_args_list)


def test_cross_page_lines_point_to_other_page_and_caption_is_near_edge() -> None:
    from math import hypot

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen.canvas import Canvas

    connection = CrossPageConnection(("signer", 1), ("wallet", 1), 1, 1, 2)
    for page, other_page, edge_y in [(1, 2, 44.0), (2, 1, landscape(A4)[1] - 74)]:
        canvas = cast(Canvas, Mock(spec=Canvas))
        crossing = PageCrossing(connection, 336, 250, "aabbccdd", other_page)
        _draw_page_crossings(canvas, [crossing], 36, 568, "Helvetica", page)
        line = canvas.line.call_args.args
        caption = canvas.translate.call_args.args
        assert line[3] == edge_y
        assert (
            hypot(caption[0] - line[2], caption[1] - line[3])
            < hypot(line[0] - line[2], line[1] - line[3]) / 2
        )
        assert canvas.rotate.call_args.args[0] != 0


def test_balance_statement_footer_on_every_page(tmp_path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas

    from bitcoin_safe.pdf_statement import create_pdf_statement

    first = wallet("First", ["00000001"])
    first.get_addresses = lambda: [f"tb1qexample{i}" for i in range(90)]
    statement = create_pdf_statement(first, "en_US", created_at="2026-11-19 12:34:56 UTC")
    with (
        patch.object(
            Canvas, "drawCentredString", autospec=True, side_effect=Canvas.drawCentredString
        ) as centered,
        patch.object(Canvas, "drawRightString", autospec=True, side_effect=Canvas.drawRightString) as right,
    ):
        statement.save_pdf(str(tmp_path / "statement.pdf"))
    dates = [call.args[3] for call in centered.call_args_list if call.args[3].startswith("Date: ")]
    pages = [call.args[3] for call in right.call_args_list if call.args[3].startswith("Page ")]
    assert len(pages) > 1
    assert pages == [f"Page {i}" for i in range(1, len(pages) + 1)]
    assert dates == ["Date: 2026-11-19 12:34:56 UTC"] * len(pages)


def test_wallet_cards_use_multisig_and_single_signature_labels(tmp_path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas

    wallets = [wallet("Shared", ["00000001", "00000002", "00000003"]), wallet("Single", ["00000004"])]
    wallets[0].get_mn_tuple = lambda: (2, 3)
    with patch.object(Canvas, "drawString", autospec=True, side_effect=Canvas.drawString) as draw_string:
        export_inheritance_overview(wallets, tmp_path / "graph.pdf")
    labels = [call.args[3] for call in draw_string.call_args_list]
    assert any("2 of 3 Multisig" in label for label in labels)
    assert any("Single signature" in label for label in labels)


def test_wallet_positions_follow_signers_instead_of_input_order() -> None:
    graph = wallet_graph([wallet("Top", ["00000001"]), wallet("Bottom", ["00000002"])])
    top_wallet, bottom_wallet = ("wallet", 0), ("wallet", 1)
    top_signer = next(iter(graph.neighbors(top_wallet)))
    bottom_signer = next(iter(graph.neighbors(bottom_wallet)))
    page = GraphPage(signers=[(top_signer, []), (bottom_signer, [])], wallets=[bottom_wallet, top_wallet])
    positions = _wallet_positions(graph, page, [360, 80], 595)
    assert (
        positions[top_wallet]
        >= positions[bottom_wallet] + _wallet_height(graph.nodes[bottom_wallet]["wallet"]) + 14
    )
    assert positions[bottom_wallet] >= 75
    assert positions[top_wallet] + _wallet_height(graph.nodes[top_wallet]["wallet"]) <= 495


def test_single_wallet_aligns_with_lower_signer() -> None:
    graph = wallet_graph([wallet("Lower", ["00000001"])])
    node = ("wallet", 0)
    signer = next(iter(graph.neighbors(node)))
    page = GraphPage(signers=[(signer, [])], wallets=[node])
    positions = _wallet_positions(graph, page, [100], 595)
    assert positions[node] + _wallet_height(graph.nodes[node]["wallet"]) < 495


def test_balance_statement_table_fits_page_with_long_labels_and_addresses(tmp_path: Path) -> None:
    from bitcoin_safe.pdf_statement import create_pdf_statement

    first = wallet("First", ["00000001"])
    first.get_addresses = lambda: ["tb1q" + "x" * 180]
    first.get_label_for_address = lambda address: "Long label with & <special> text " * 30
    statement = create_pdf_statement(first, "en_US")
    table = statement.elements[-1]
    assert table._cellvalues[1][2].getPlainText().startswith("Long label with & <special> text")
    width, height = table.wrap(528, 720)
    assert width <= 528
    assert height > 100  # The long address and label wrap inside their cells.
    statement.save_pdf(str(tmp_path / "statement.pdf"))
    assert (tmp_path / "statement.pdf").read_bytes().startswith(b"%PDF-")


def test_signers_are_deduplicated_by_fingerprint_not_xpub() -> None:
    first = wallet("First", ["aabbccdd", "aabbccdd"])
    first.keystores[0].xpub = "xpub-one"
    first.keystores[1].xpub = "xpub-two"
    second = wallet("Second", ["11223344"])
    second.keystores[0].xpub = "xpub-one"
    graph = wallet_graph([first, second])
    assert len(graph) == 4
    assert set(graph.neighbors(("wallet", 0))) == {("signer", ("aabbccdd", "generic"))}
    assert set(graph.neighbors(("wallet", 1))) == {("signer", ("11223344", "generic"))}


def test_shared_fingerprint_preserves_distinct_notes_and_omits_duplicates() -> None:
    wallets = [wallet(name, ["aabbccdd"]) for name in ("First", "Second", "Third")]
    wallets[0].keystores[0].description = "Shared note"
    wallets[1].keystores[0].description = "Shared note"
    wallets[2].keystores[0].description = "Another note"
    graph = wallet_graph(wallets)
    details = graph.nodes[("signer", ("aabbccdd", "generic"))]["signer"].notes
    assert details == [("First", "Shared note"), ("Third", "Another note")]


def test_two_multisig_wallets_are_placed_near_their_own_signers() -> None:
    first = wallet("First", ["00000001", "00000002", "00000003"])
    second = wallet("Second", ["00000001", "00000004", "00000005"])
    graph = wallet_graph([first, second])
    pages = _graph_pages(graph, "Helvetica")
    assert len(pages) == 2
    assert pages[0].wallets == [("wallet", 0)]
    assert pages[1].wallets == [("wallet", 1)]
    assert len(_cross_page_connections(graph, pages)) == 1


def test_same_fingerprints_merge_even_with_different_xpubs() -> None:
    first = wallet("First", ["00000001", "00000002", "00000003"])
    second = wallet("Second", ["00000001", "00000002", "00000003"])
    for signer in second.keystores:
        signer.xpub += "-different-account"
    graph = wallet_graph([first, second])
    pages = _graph_pages(graph, "Helvetica")
    assert len(pages) == 1
    assert set(pages[0].wallets) == {("wallet", 0), ("wallet", 1)}
    assert len(pages[0].signers) == 3
    assert not _cross_page_connections(graph, pages)


def test_missing_fingerprints_stay_separate_even_with_matching_xpubs() -> None:
    first = wallet("First", [""])
    second = wallet("Second", ["00000000"])
    first.keystores[0].xpub = second.keystores[0].xpub = "same-xpub"
    graph = wallet_graph([first, second])
    assert len(graph) == 4
    assert set(graph.neighbors(("wallet", 0))).isdisjoint(graph.neighbors(("wallet", 1)))


def test_same_fingerprint_on_different_devices_stays_separate() -> None:
    coldcard = wallet("Multisig 1", ["aabbccdd", "00000001", "00000002"])
    bitbox = wallet("Multisig 2", ["aabbccdd", "00000003", "00000004"])
    coldcard.keystores[0].hardware_signer_id = "coldcard"
    coldcard.keystores[0].description = "Coldcard note"
    bitbox.keystores[0].hardware_signer_id = "bitbox02"
    bitbox.keystores[0].description = "BitBox note"
    graph = wallet_graph([coldcard, bitbox])
    coldcard_node = ("signer", ("aabbccdd", "coldcard"))
    bitbox_node = ("signer", ("aabbccdd", "bitbox02"))
    assert graph.has_edge(("wallet", 0), coldcard_node)
    assert not graph.has_edge(("wallet", 1), coldcard_node)
    assert graph.has_edge(("wallet", 1), bitbox_node)
    assert not graph.has_edge(("wallet", 0), bitbox_node)
    pages = _graph_pages(graph, "Helvetica")
    assert len(pages) == 2
    assert not _cross_page_connections(graph, pages)
    assert graph.nodes[coldcard_node]["signer"].notes == [("Multisig 1", "Coldcard note")]
    assert graph.nodes[bitbox_node]["signer"].notes == [("Multisig 2", "BitBox note")]


def test_matching_fingerprint_and_device_deduplicate() -> None:
    first = wallet("First", ["aabbccdd"])
    second = wallet("Second", ["aabbccdd"])
    first.keystores[0].hardware_signer_id = second.keystores[0].hardware_signer_id = "coldcard"
    graph = wallet_graph([first, second])
    shared = ("signer", ("aabbccdd", "coldcard"))
    assert set(graph.neighbors(("wallet", 0))) == {shared}
    assert set(graph.neighbors(("wallet", 1))) == {shared}


def test_merged_signer_notes_use_one_card(tmp_path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas

    first, second = [wallet(name, ["aabbccdd"]) for name in ("First", "Second")]
    first.keystores[0].description = "First note line one\nFirst note line two"
    second.keystores[0].description = "Second note line one\nSecond note line two"
    graph = wallet_graph([first, second])
    cards = [card for page in _graph_pages(graph, "Helvetica") for card in page.signers]
    assert len(cards) == 1
    assert len(cards[0][1]) == 4
    original = Canvas.drawString
    with patch.object(Canvas, "drawString", autospec=True, side_effect=original) as draw_string:
        export_inheritance_overview([first, second], tmp_path / "graph.pdf")
    labels = [call.args[3] for call in draw_string.call_args_list]
    assert labels.count("Seed backup location:") == 1
    assert "First note: First note line one" in labels
    assert "Second note: Second note line one" in labels
    assert "First note line two" in labels
    assert "Second note line two" in labels


def test_very_long_notes_continue_without_another_signer_card(tmp_path: Path) -> None:
    from collections import Counter

    from reportlab.pdfgen.canvas import Canvas

    first = wallet("First", ["aabbccdd"])
    first.keystores[0].description = "x" * 5000
    graph = wallet_graph([first])
    signer = next(node for node in graph if node[0] == "signer")
    notes = _signer_note_lines(graph.nodes[signer]["signer"], "Helvetica")
    assert len(notes) > MAX_SIGNER_NOTE_LINES
    assert len([card for page in _graph_pages(graph, "Helvetica") for card in page.signers]) == 1
    with patch.object(Canvas, "drawString", autospec=True, side_effect=Canvas.drawString) as draw_string:
        export_inheritance_overview([first], tmp_path / "graph.pdf")
    labels = [call.args[3] for call in draw_string.call_args_list]
    assert labels.count("Seed backup location:") == 1
    assert "Signer notes continued" in labels
    assert not (Counter(notes) - Counter(labels))


def test_three_signers_with_notes_fit_on_one_graph_page() -> None:
    first = wallet("Multisig", ["00000001", "00000002", "00000003"])
    for signer in first.keystores:
        signer.description = "one\ntwo\nthree\nfour\nfive"
    graph = wallet_graph([first])
    pages = _graph_pages(graph, "Helvetica")
    assert len(pages) == 1
    assert len(pages[0].signers) == 3
    assert all(len(lines) == 5 for _, lines in pages[0].signers)
    assert _page_signer_height(pages[0]) <= 420


def test_single_distinct_note_has_no_wallet_label() -> None:
    first, second = [wallet(name, ["aabbccdd"]) for name in ("First", "Second")]
    first.keystores[0].description = second.keystores[0].description = "Stored securely"
    graph = wallet_graph([first, second])
    details = graph.nodes[("signer", ("aabbccdd", "generic"))]["signer"]
    assert _signer_note_lines(details, "Helvetica") == ["Stored securely"]


def test_multiple_distinct_notes_keep_wallet_labels() -> None:
    first, second = [wallet(name, ["aabbccdd"]) for name in ("First", "Second")]
    first.keystores[0].description = "At home"
    second.keystores[0].description = "At the office"
    graph = wallet_graph([first, second])
    details = graph.nodes[("signer", ("aabbccdd", "generic"))]["signer"]
    assert _signer_note_lines(details, "Helvetica") == ["First note: At home", "Second note: At the office"]

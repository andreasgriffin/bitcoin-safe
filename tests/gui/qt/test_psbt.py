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

from __future__ import annotations

import inspect
import logging
from datetime import datetime

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.address_comparer import AddressComparer
from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer

from .helpers import Shutter, main_window_context

logger = logging.getLogger(__name__)


@pytest.mark.marker_qt_2
def test_psbt_warning_poision_mainnet(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config_main_chain: UserConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:  # bitcoin_core: Path,
    """Test psbt warning poision mainnet."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config_main_chain)
    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe"

        shutter.save(main_window)

        def do_tx(tx, expected_fragments: list[str] = []):
            """Do tx."""
            main_window.open_tx_like_in_tab(tx)
            shutter.save(main_window)

            node = main_window.tab_wallets.root.child_nodes[1]
            tab = node.data
            assert isinstance(tab, UITx_Viewer)

            assert tab.address_poisoning_warning_bar.isVisible()
            assert (
                "Warning! This transaction involves deceptively similar addresses. It may be an address poisoning attack."
                in tab.address_poisoning_warning_bar.icon_label.textLabel.text()
            )
            for expected_fragment in expected_fragments:
                assert expected_fragment in tab.address_poisoning_warning_bar.icon_label.textLabel.text()
            # end
            shutter.save(main_window)
            node.removeNode()

        # https://mempool.space/tx/152a5dea805f95d6f83e50a9fd082630f542a52a076ebabdb295723eaf53fa30
        do_tx(
            "020000000001046586c81c9b643f0c3f05a9ffa6b13beb612b485b3c1096d3007b00bb270cb98b0100000000fdffffff5837c3850d30b10944e4bded7f1b105673bfaab62a8ff5949d70e79fc93d070e0100000000fdffffffcf8fa241b7f94f21192aef6bbc59ce69e56343ef5a152f55398c7cd46df0ba3b0100000000fdffffff5df54ec9743285160f1b8b3bf2a3948ede1b2ae142a5b0a24b4b798abad713160100000000fdffffff082b020000000000001976a914026c0be5c05bbbf4e66779700a2bec60313c72a688ac78030000000000001976a914a0b0d60e5991578ed37cbda2b17d8b2ce23ab29588ac2b020000000000001976a914026c0be5c05bbbf4e65a807ae644f1f5b1cdae0788ac2b020000000000002200209760928a37f3a32806d75a3ab4048c60901ea9ce6abe37e6f459ab51e49355bd2b020000000000001600143924fbe46da8ea43404e8cec962e91ac62bbd9e92b020000000000001976a9146d57097a904ea9a39337d44d0254a9a36bff0f9d88ac2b020000000000002200206d490c8afb205cb251b377b0798094bd26643cc0833b94b5e09d2c08a98e9b804b05000000000000225120edc521a9934826077df73c830577b51032a2b8069aa7d431b4ea8453aade5ada01401bef5818b01d9a010498456b2daa372cb3e1cd6ad686c0f97e688120ca9c0b4c0c0a315b2376baddb9c299c512092ff594075a76220637724cfa22d1e52c09cf01404a8d9df8eea18891453217660f27726554ec4074da5eef6b9fae04130552ef2f64e2b8cee9c4a921a4cbb783200385afdeb01035a28e86d19b306abd2783ef690140b72e893fc908caa86174d263f0ca1d0e08b6a542af700bbb45c3df5ff8443a3274668c0597bf8472ffd74bdf188d3003487a08c4aaf93e6488061acde2d22c4b0140a110fb7ed766b938ad2194e1a0821213e0692305dea0fb3b74c6973a083f3aa31a0f82ce94f5d5d8828284d489fa083554a08f295c4d1938c2ca61bd5b64911900000000",
            expected_fragments=[
                "1<u>D</u><u>o</u><u>n</u><u>a</u><u>t</u><u>e</u><u>P</u><u>L</u><u>e</u><u>a</u><u>s</u><u>e</u>5btcToSenderXXWBoKhB",
                "1<u>D</u><u>o</u><u>n</u><u>a</u><u>t</u><u>e</u><u>P</u><u>L</u><u>e</u><u>a</u><u>s</u><u>e</u>SenderAddressXVXCmAY",
            ],
        )

        # https://mempool.space/tx/401681fe8aaa33f049956c2d07171a2662935b952c45e3cd8cf896213d9be8e5
        do_tx(
            "0100000000010100e9d9d57f7a6904a3ce4234b57c4ae3eb3baa53317b2a852ae92e25a0c8df740000000000ffffffff0c58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac58020000000000001976a9142fc701e2049ee4957b07134b6c1d771dd5a96b2188ac58020000000000001976a9142fc72f3626ff956755592fdf8e607d9e16d5a10a88ac02483045022100a440cb9f72dca79715541bcb2c858e6524484a1294cec24b8c735e3d2357b57002201a0a039de64bd9d5a5a174a8ab94a3c998120965d17b494f6fe61de725680ef601210202d3b87d5f4b692f8e9cafbbb00095893cd0e6866414fb050defc1bceb2d0eba00000000",
            expected_fragments=[
                "1<u>5</u><u>M</u><u>d</u>AHnkxt9TMC2Rj595hsg8Hnv693<u>p</u><u>P</u><u>B</u><u>B</u>",
                "1<u>5</u><u>M</u><u>d</u>NbM2Hi43JoGQ55SzsNC5RRuojX<u>p</u><u>P</u><u>B</u><u>B</u>",
            ],
        )

        # https://mempool.space/tx/f486965a719a3bb99cc3ca4440290dd186cff0695c619399b5fbd97941ec5998
        do_tx(
            "01000000000101d5a289918f3d6711f94913d9404a2810f364d61c022164eb0b866c60c09627f90000000017160014ad878330140b6824b42b4111d854ab918527645effffffff0c580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e487580200000000000017a91469405cdb948aae39df337af7c269eba9be960bc587580200000000000017a91469403f4a5eaa6cb5bbf48501f42781d8a06eb0e48702483045022100b90f3b779af725efab86a2431f1bd354130602db65b5648549d8af743f16929d0220509e9fd117ba36aeff864ad6c6776a859c29aa205919526234fbb8d920549481012102b43877a29485f3408d619bfbb98d1e1a216060fe2eb89729f1dc87ab348c3eaf00000000"
        )

        # https://mempool.space/tx/285a933772c91d5202225015ed6fc9f8a24f3140042a0893dead42ce140e4e14
        do_tx(
            "02000000011a04f11cad15e3a59a43e317f7a151c041492aeafa00e8676701531bc53e5eda0d0000006a4730440220159de295cbf296ced45b1de93846c819e6797d06b7405e35a9e72d92c3a2ab40022053880cc8f7d5add1c68fd836ba1f51d748957cdbc1df9ce484cbeeb15121056f0121032c7548a44527ed0e1805c0ecf53f9dbe6f2c121b5a4e1f9d39ddcba805a71268feffffff0401000000000000001976a914e0b8a2baee1b77dbf02a2ba190c5e81da7fc7b1088ac01000000000000001976a914e0b8a2baee1b77fc703455f39d51477451fc8cfc88ac01000000000000001976a914e0b8a2baee1b780f3e521abe89d327d9b40529dc88ac0b4b0000000000001600144ccda46c27de045a8651b4a07e0eba901785d09f26970d00"
        )

        # https://mempool.space/tx/5be41d92b4a9829e2555cf7389dfc8f62209a1ff7f60bae5634518f5287d881f
        do_tx(
            "02000000016cea390700d5d82936afd7c85c712060ec635e4587394103639011c4b47055c7030000006a473044022032c115c072f9a316d5a450282fceb09698f6a498291e3d9a0865368d2c49a79e0220318456d7ce426a4c587f6b42bda190ba7b648434acc4d5ef5867da2d6b9a0f8a0121021102ce74b961d8a81720ecca6a481be2c56d0f4edb96dfb723e6af9b7c13b9fdfdffffff0301000000000000001976a914e0b8a2baee1b77fc7014c18a3eb4565b0fadbfd688ac01000000000000001976a914e0b8a2baee1b77fc703455f39d51477451fc8cfc88ac70590000000000001976a914fa31d001213e228109e29aa93632b47e255ec98a88aca18c0d00"
        )

        # https://mempool.space/tx/735565dbabf223caf0fe7bb668b481ebb3022028cdfa96e65a7fe0c7ca5c93e9
        do_tx(
            "020000000347fcfa326b1ad3662a39febca0346ebaea42af34426844d0609568a244691d12010000006a47304402206b0f4d6ae7bd1048ad8abcb0f72517b74aff9414da5bdf18019393630b11524002201ce3bf347f39940188d8d12a322e0033944e33f7ad9df60780b613fd862c6f70012102679a681d9b5bf5c672e0413997762664a17009038674b806bf27dd6b368d9b67feffffffbebdc9a53d53d9189256f1bf5c7b9a1fce8e32e5d0de238be9d052508cf043e5000000006b483045022100c4f16e1dabca85d69c5758bac44db2f75a6c9d52f91aeb806b45e71b95fade95022040d318df4ac46d4ec33b89d7dcfb61d9cdeed8984edc49ee605c57995cf844ce012102679a681d9b5bf5c672e0413997762664a17009038674b806bf27dd6b368d9b67feffffffc08e90c5bab7950d7a9b2f5a5129f110472bc7da881487afacde89b5b2ce70b4000000006b4830450221009756f680a24ddf8ddc33d2c226b1bf049333e91f76828729a869f45b366afa6a022018720615a5a141243d8df54a2c22aa6c117baf9245b93a56ebd568285b8bc4b4012102679a681d9b5bf5c672e0413997762664a17009038674b806bf27dd6b368d9b67feffffff395aa01700000000001976a914262a9436110fbda65240ba69f267dd1e59231ea688ac30a322000000000017a9146f8adc53afebf838a4e3e12d4d2a6d3b66f0424a87d09a26000000000017a9142bc1366126e736029daca569c18d86785ee2bbc48740061900000000001976a91418d7f2a15213fafd4964c47bc936def843458d4e88acdbef0600000000001976a9149a1445c2d8aeaaa2cc6b82edf12928f919e3c8e388ac48a21c000000000017a914268d2ddad7ccf885304c2afe9d5e9af908ced7298700093d00000000001976a9148b476a56a26a838aa88f9f87cfb7c8dee91d4ad188aca9950e000000000017a914f58d1946646fff2e83b29e6eeba9a7ac6362f6eb874b2303000000000017a91451f45084372a25648117eecfca779d3c5ab396128790d00300000000001976a914de78911c03ce6f54b545d4a2d705a7e323f0adcc88ac02d31e000000000017a914dbafe4bc1af7e134e3c286dc5ab445e83c740d08873098c4000000000017a914984a78537f6e20cd4c9e91beddf6221e9c547dc087b9440e000000000017a914afd489a81ab94fd6118eff448ad5be341fbf28798742ee45010000000017a914311b47685a8c82f09c05674324813e5481da006b87346e51000000000017a91469f377165708c692766314f333467eb48acc35d687bf63fb0f0000000017a914c576b6f6ac51222a0952c6c7b2b39cc35dd0378d87a0140e010000000017a91459e59c6868046ceaae59357f75cb2c7dd698b8bb879472a1000000000017a91469f3767680d11507d91e2dc51288fb1a353a75f987fd7cea01000000001976a914415aef5356963d97e18f78663b4e9e4cf4e8dfa888ac9849e800000000001976a9146f1b68f1b8dddf8f199764bda19d94682e7a2db288acc1e6f5010000000017a91469f373b485a2c05b59328df9f4d6b6123d0a92e78786c10b00000000001976a914e2db5fb9fdafa1bcfc879650917d10c564d9951288acc0c62d000000000017a91469f376804d2961ffc97d477d96a4dbcbdd227a9187f18c18040000000017a9140fa42fc6a76a7bea7fd0efc1184685b9fadfa92387d7b505000000000017a914017ad649761392f37cc655d3f9a77ebb3709606e8747241b010000000017a91416a1b1e6fb9c40a291b4e876cca297396f0367d3874cd41000000000001976a9147bb8b467ecbec68be61da655a355efefcce4ba1188ac80be64ca0000000017a91408042cd98f50b2f458bdc281de20b8483719a10087222e1e000000000017a9146f8212ff82aa73dcb214dbf89f998911fb5c05e2871277ff000000000017a91445a20a034ac60ea18dc0c800d68fe7bfa5fe9cd28700c2eb0b000000001976a914caf619ac78fbff61da7c8c3e9d155f54ab36cb1f88ac80a314020000000017a91469f374c2a812bbaf41a2c310df920a589ce1b43587380f07000000000017a914c016280677cb93c91c705422247de1967cf8dc6e87da364b030000000017a9147cadb0b0951bf92ba4ad523ae1362022529bc74d87e79421000000000017a914e0f6c8b0603ff529b6a742e1c41b60bfcf668b578785e22506000000001976a9148daffc95563edc6f653fc39cdb20b114e5e0ecc788ac3000c9010000000017a914ecc01f115a7cabff30f69de0a156c55fa4779c8b87c8850700000000001976a9143cdb50197d5af599ac9beb4b4243f28c6e6d355788aca09ca400000000001976a91499485157143a59c8e34152d00835128489aaecef88acc0c62d000000000017a91469f3771519559a2e424ce3660f5f594690bd955a8710936b00000000001976a9144f4519803d9f4edd9014f31b542556953f8bdfaf88ac61b44a000000000017a9141c237a12f9ae5e560ffb2c129d7498bff422adc0874a9ab502000000001976a9148db86f2df55a29ab53b1ad51c42d3bd41203e58088ac2c7f0e000000000017a914b697404a96fc46f0c255e4f4ee7a3ffd9e3a11348770a577040000000017a9144c677260eb60b2b425258c7348dbc4c60c53b5c487804f1200000000001976a914f2429297a4c50fff28670b1f63f2aa83804b76f488acc4127408000000001976a9141963d134c47e951418a045ead0ae120eb649665b88ac6ddf8e010000000017a914de880c6116eaa40f733e92e830aabfc513ab55e08760ae0a00000000001976a9147eeca5dc3d257bdd6317f9267f420ef8a3fce08988acb01df505000000001976a91424e2a0eb16d95e827b4920e82afd297d643d8f9988ac002d31010000000017a914860c4f04edad92622f5ae77f9b8afb5cb002c6b08767b3ec040000000017a914fe8d987450ca4b593b591b2e76a7553a7531c80a8730c11d000000000017a91402f05670903d9587f494fc0f2c64e02875c39c6a87a0be39030000000017a914d564708e73300f2d7468f23880893103008bc13387819fc902000000001976a914f88251c31946cf83ceb215a25487473e700038d388ac326d1003000000001976a914bbcd1f66a09dde8a2fc60cfa3a2518256f1b022588ac04c9ec000000000017a9144212c8995d0627ab2fef99013d4ab034a5e5261f87b51a0800"
        )

        # https://mempool.space/tx/622df89d59a965465c7d65acf1f7e95012f6bd7a7dfc2dd8a2b3081fb5b7fe24
        do_tx(
            "0200000001ba64daa7de9e001696789670f0f9de438ed31ae3274f47bb7ee4a1e903e9ee6c000000006a47304402205fc09aeead1af8f8478a352180df87df1243ab1917889d818a38f3a6916cf93102201890aeb23cb21c2d5b871916d2f565350c11764bbcf45d830c598d0d1033ebd801210375856aa46dd5fe1c543e4642adbb068d721df272c6c8866aca4e5efafca3e27dfdffffff0223020000000000001976a914592fc3990026334c8c6fb2b9da457179cdb5c68888acbe080000000000001976a914592fc398e2ed00009ced6b055e3dcb1bcfd8741088ac3ac70a00"
        )


@pytest.mark.marker_qt_2
def test_psbt_warning_poision(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: UserConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:  # bitcoin_core: Path,
    """Test psbt warning poision."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        def do_psbt():
            """Do psbt."""
            org_ADDRESS_SIMILARITY_THRESHOLD = AddressComparer.ADDRESS_SIMILARITY_THRESHOLD
            AddressComparer.ADDRESS_SIMILARITY_THRESHOLD = 32_000

            psbt = "cHNidP8BAKgBAAAAAcgPfvBnxr9qF0o5tGN7Yi700GJKITISfTB25evv/et7AQAAAAD9////A6APAAAAAAAAFgAUXCz4WFk4ANrLn8kusAPQ2+Ic0ZCgDwAAAAAAACIAIP5+mYK492G9BpTSXRVmlsINAPyeZ+BbswhLDxCS61v/JtmXAAAAAAAiACDYrIlFGPEykE16uVcbeRxB4aCyhbhitXY1kRc4GvpHtfMLAABPAQQ1h88EApdQj4AAAAI3TSBpfcsjErxWbW7+K4tU2p6/TnBriteYduNbUJ4O9wItTl11LzxH4f2/d0TTjLmN6zrPREFoE9yEg+S9AkX/qRSVryXvMAAAgAEAAIAAAACAAgAAgE8BBDWHzwQbRllDgAAAAkitfn+2yQwdQ8dXOXV6vO2Zso8C/2H+MtXw9ZjOtW1WAtJLqqIQmSaIaMWNj8lf7HaeNEncI+kU/ECkQ+KFjKmGFGFVKWQwAACAAQAAgAAAAIACAACAAAEA/VoBAQAAAAABAakvWHNzJ17xblA9QOL0EXRcUYAwL4qjZuq0ovU9ioHsAAAAAAD9////AkCcAAAAAAAAFgAUbY8H0Xk7T37O+Uz0G7jWzhzT2z+L+ZcAAAAAACIAIHQluxNKgjKW9D1pcYrVFUulolDSot2cB2+nUyyc5XK0BABHMEQCIAhwYcTRjfvFqv0Z9uUpI4ZWz42enHyGV1CCFiEUQ5WeAiBK0zCWUm1evI/OaK3Xx/eb2rkTOGtS42EbBLLv9u5oGwFIMEUCIQDd7J3nbwYAs24cRvDjK7nadvF4OcadRbwivFzwVzn0VQIgKMykT3UdEJV2vSPwq4LdyMogPulVaPYgwHgYeJXiapoBR1IhAjdvV2a9+BkCJM/rKvWQfBgp2AvgfUDFFZkWkSXrduuqIQKURqBDnTV3cMVo9wuihKiT3YEsJFKW1sT4U6/rhzwCklKu8wsAAAEBK4v5lwAAAAAAIgAgdCW7E0qCMpb0PWlxitUVS6WiUNKi3ZwHb6dTLJzlcrQBBUdSIQKG5xW3iX3O0l5O7NasvqoxCpW63kvjxQTt+o4Qhj1mECECqav5dMbFkm0qsC0ADq0s5CDRXj2Jrut4L4US/4W4TUpSriIGAobnFbeJfc7SXk7s1qy+qjEKlbreS+PFBO36jhCGPWYQHJWvJe8wAACAAQAAgAAAAIACAACAAQAAAAAAAAAiBgKpq/l0xsWSbSqwLQAOrSzkINFePYmu63gvhRL/hbhNShxhVSlkMAAAgAEAAIAAAACAAgAAgAEAAAAAAAAAAAABAUdSIQLZyBMiiLsHGtSx2nyq9ABzY2Yhu901nOxzXuEMaw0jNSEDMFDbnxOXNQTw+yBcmixX/oY5qVDF/J0LedWagKWU2bVSriICAtnIEyKIuwca1LHafKr0AHNjZiG73TWc7HNe4QxrDSM1HJWvJe8wAACAAQAAgAAAAIACAACAAAAAAAEAAAAiAgMwUNufE5c1BPD7IFyaLFf+hjmpUMX8nQt51ZqApZTZtRxhVSlkMAAAgAEAAIAAAACAAgAAgAAAAAABAAAAAAEBR1IhAuUSbT2a+i0iwnGfhNMFh2aPA9s5MgYjfVA1zf5Gky6fIQMeMhD8WBfUF++O4Yw1pWTzfNT3GmIfHkJcRilAfrcR1VKuIgIC5RJtPZr6LSLCcZ+E0wWHZo8D2zkyBiN9UDXN/kaTLp8cYVUpZDAAAIABAACAAAAAgAIAAIABAAAAAQAAACICAx4yEPxYF9QX747hjDWlZPN81PcaYh8eQlxGKUB+txHVHJWvJe8wAACAAQAAgAAAAIACAACAAQAAAAEAAAAA"
            main_window.open_tx_like_in_tab(psbt)
            shutter.save(main_window)

            tab = main_window.tab_wallets.root.findNodeByTitle("PSBT 8109...a65a").data
            assert isinstance(tab, UITx_Viewer)

            assert tab.address_poisoning_warning_bar.isVisible()
            assert (
                "Warning! This transaction involves deceptively similar addresses. It may be an address poisoning attack."
                in tab.address_poisoning_warning_bar.icon_label.textLabel.text()
            )
            assert (
                "bcrt1<u>q</u>lelfnq4c7asm6p556fw32e5kcgxsply7vls9hvcgfv83pyhtt0l<u>s</u><u>c</u><u>s</u><u>6</u><u>q</u><u>a</u><u>0</u>"
                in tab.address_poisoning_warning_bar.icon_label.textLabel.text()
            )
            assert (
                "bcrt1<u>q</u>tsk0skze8qqd4juleyhtqq7sm03pe5v<u>s</u><u>7</u><u>s</u><u>6</u><u>q</u><u>a</u><u>0</u>"
                in tab.address_poisoning_warning_bar.icon_label.textLabel.text()
            )

            # end
            shutter.save(main_window)
            AddressComparer.ADDRESS_SIMILARITY_THRESHOLD = org_ADDRESS_SIMILARITY_THRESHOLD

        do_psbt()

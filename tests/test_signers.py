import logging
from dataclasses import dataclass
from typing import List, Literal
from uuid import uuid4

import bdkpython as bdk
import pytest
from _pytest.logging import LogCaptureFixture
from bitcoin_qrreader import bitcoin_qr
from pytestqt.qtbot import QtBot

from bitcoin_safe.signer import SignatureImporterClipboard
from bitcoin_safe.util import hex_to_serialized, serialized_to_hex

logger = logging.getLogger(__name__)
from test_setup_bitcoin_code import BITCOIN_PORT, RPC_PASSWORD, RPC_USER

test_seeds = """peanut all ghost appear daring exotic choose disease bird ready love salad
chair useful hammer word edge hat title drastic priority chalk city gentle
expand text improve perfect sponsor gesture flush wolf poem blouse kangaroo lesson
base episode pyramid share teach degree ocean copper merit auto source noble
scout clarify assist brain moon canvas rack memory coast gauge short child
client tiny thing glory day music captain employ reflect alpha borrow adjust
city fault intact define pizza sponsor gauge box tattoo horse bench bonus
scatter shop segment agent vague ability laugh zero general exercise ensure onion
clever more leopard since floor today talk ship purchase neutral fantasy leader
shield profit primary symptom matter behave monster actor chronic correct crunch security
plug tissue prison random hedgehog tone slim balcony faint squirrel sight under
acquire party matrix coach grunt whip spend spin answer mask liquid hurt
choice scare parrot path nut master diary bring dragon page flush moral
ridge glare zebra friend meat hedgehog pass stable world enough woman blind
lunch clarify you keep riot industry crazy medal fiction despair actual antique
ensure diet bench scale future thumb holiday wild erupt cancel paper system
wood series wool know clever way vacuum vital nature rebuild bomb satisfy
gold mail gown ignore sibling utility planet team number hour viable ring
quick human icon lonely combine garbage vehicle raise grace ketchup burden assault
sense rebel virus tilt drop town comic pepper unaware doll title claim
render paper melt tragic lizard ahead expand swamp voyage response suffer regular
soap thing badge energy ice banana fashion crouch ladder achieve link barely
dial vehicle word limit tunnel equal thought make snap attend area power
project design nurse crunch despair top usage pudding aunt meadow bread alcohol
clip machine tunnel weekend power peace dragon recall case quote switch provide
amateur forest already wine upper keen cherry confirm resist sponsor nerve speed
calm isolate pumpkin come network also sting zone age opera portion problem
cube arch evil day word happy hair ensure cousin coffee super melody
stool monitor three canyon vote main clog write plunge primary half pretty
again dismiss auto effort approve crystal border settle soldier oil panic wheel
garlic brand baby drama feature garage gaze milk chapter run field ski
exact impact squirrel uniform apart episode century silent grocery load music peace
quote mixture record endorse equal cost battle utility blouse badge jelly zebra
usual venue notable people gun toast stock lend vote trust culture similar
script negative mail chronic shrimp grape uphold spike symptom border dismiss combine
alley grief lonely tube cinnamon exclude provide rocket amused matter nurse uniform
blade engage coil weekend earn thumb cinnamon stool impact click garment midnight
ranch wrist banner cave correct you problem floor dove train student laugh
announce nurse rare gown verify sample unfold skill bulk tackle nominee what
health combine violin spy gloom loud thunder island under random hire earn
arrest candy pair popular remember guitar verb region ramp number verify raise
laundry wing distance giraffe girl close brave cause eternal derive evil coconut
provide cushion topple logic dismiss crunch spike success arctic prosper giraffe submit
example wealth metal family wasp certain culture elephant master quit unaware disease
crunch notable doll crowd response churn charge safe little infant fantasy island
youth cable initial maximum follow woman three comfort spell electric spend knock
divert rich tumble truck dust finish medal exile burden sorry order rival
middle wool alley lion duty attract room entire cabbage capital reject cluster
seek peace allow tortoise pattern skull brief time castle hard sudden scorpion
baby pave choice snap laptop warm shuffle honey system assume romance invest
fashion wet property congress vibrant property easy cable kit accuse impose weather
lounge proud enough tongue major embark wife pencil rubber sea bless huge
life resist peace soldier merry you garden average shadow piano want element
token mixture any beyond service news ancient erode idea salt demise approve
beauty teach devote fame matter aware main mosquito manual mule truly cat
service artist final jealous dragon bird city cupboard kite loyal regret skull
answer hidden hero derive lyrics either private knock salt wink twelve game
orange void future proud junk journey material decline alert shine noble skirt
hurdle page nation lake small tragic rent utility law chapter love festival
dragon spawn friend rigid verb field digital merry oak diamond adjust shrug
poverty bicycle wall cigar tide salon ready cinnamon scene giggle scrub cancel
armed decade exclude echo grocery lift that love chaos energy burst assist
demand profit simple remove deny rate mesh tail tackle empower post like
fiber section click source knee ozone they fuel wave badge border betray
sauce never warm motion blind example globe cloud predict announce energy utility
flight day please because girl proud subway price fame soup noble path
collect museum trip island little gain surface bless tower try monster tip
bleak accuse fluid anger control mercy rapid short decide drum scrap caution
direct sun combine trap state riot upon laugh grant visual bubble crumble
clap grape suit congress blue wheel put dance donor river twist rubber
horse unique goose style risk morning search noise orange fix senior sphere
draw joy aware salt deer code veteran curious equip boil magic above
hunt limit poem gallery spend outdoor shoot profit portion damp payment remember
comfort abandon choose north report school hamster teach learn glad future section
trust become caught path coach casino quality canoe employ bone what tongue
then repeat olive picnic random drastic advance affair slow pulp seed defy
toddler joke outside rare pelican palm yard dutch weasel mother snap come
spice globe shadow injury exact envelope celery rough off enroll rice bounce
early museum myth casino hammer avoid business enrich fly valve calm bread
diet fit top differ grab pulp scare drink cannon tortoise mirror help
cart panic wear left parent enhance post eye exit turkey cable lottery
space attract field pioneer supreme quick tackle spend sadness barrel require angry
boy theory soap fragile grass pumpkin race grow narrow abstract cotton planet
foil uniform sniff grant pony category devote nominee dilemma release bulk sell
accuse drip machine border card anchor popular boost wise flat miracle right
pass elegant burger list school spare dilemma turkey raw upon list belt
lucky tired happy before kiwi latin resource piano kangaroo matrix whisper twin
pledge calm abstract artist marble punch visa aisle exile satoshi uncover tragic
fox resource tribe insect lake remain oak ecology oyster purse arm ordinary
file dismiss convince duty tilt awful rabbit jazz member excess toddler bitter
stove calm recipe roof bottom charge trophy life list group goat cargo
case normal library frozen already mom leaf announce water wrap juice renew
sell donkey draft cash humble age hunt grass category theory crop sudden
now snow recipe still local tip evoke orphan harsh chapter palm fatal
athlete giggle save always skull ancient execute betray kitten endless weasel turn
neglect pig resist pill buffalo order debris art birth empty dance alert
evil resemble crush tenant ridge elder castle cloth cereal start sweet empower
resource frequent color unknown sibling oxygen grocery fiction foil over awkward shallow
music problem march blind power train found shadow ostrich raven brain injury
romance slush habit speed type also grace coffee grape inquiry receive filter""".splitlines()


@dataclass
class PyTestBDKSetup:
    network: bdk.Network
    blockchain: bdk.Blockchain
    descriptors: List[bdk.Descriptor]
    wallets: List[bdk.Wallet]


def get_blockchain_config(network: bdk.Network):
    return bdk.BlockchainConfig.RPC(
        bdk.RpcConfig(
            f"127.0.0.1:{BITCOIN_PORT}",
            bdk.Auth.USER_PASS(RPC_USER, RPC_PASSWORD),
            network,
            str(uuid4()),
            bdk.RpcSyncParams(0, 0, False, 10),
        )
    )


def pytest_bdk_setup_multisig(m=2, n=3, network=bdk.Network.REGTEST) -> PyTestBDKSetup:
    blockchain_config = get_blockchain_config(network=network)

    blockchain = bdk.Blockchain(blockchain_config)

    def create_single_sig_descriptor(seed):
        mnemonic = bdk.Mnemonic.from_string(seed)

        return bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(network, mnemonic, ""),
            keychain=bdk.KeychainKind.EXTERNAL,
            network=network,
        )

    def create_wallet(descriptor: bdk.Descriptor):

        wallet = bdk.Wallet(
            descriptor=descriptor,
            change_descriptor=None,
            network=network,
            database_config=bdk.DatabaseConfig.MEMORY(),
        )

        return wallet

    def gen_multisig_descriptor_str(
        descriptor_strings, threshold, type: Literal["p2wsh", "p2sh_p2wsh", "p2sh"] = "p2wsh"
    ) -> str:
        new_strings = []
        for descriptor_string in descriptor_strings:
            s = descriptor_string
            s = s.split("#")[0]
            s = s.replace("wpkh(", "").replace(")", "")
            new_strings.append(s)
        if type == "p2wsh":
            return f"wsh(sortedmulti({threshold},{','.join(new_strings)}))"
        elif type == "p2sh_p2wsh":
            return f"sh(wsh(sortedmulti({threshold},{','.join(new_strings)})))"
        elif type == "p2sh":
            return f"sh(sortedmulti({threshold},{','.join(new_strings)}))"

    single_sig_descriptors = [create_single_sig_descriptor(seed) for seed in test_seeds[:n]]

    wallets = []
    multisig_descripors = []
    for i in range(len(single_sig_descriptors)):
        descriptor_strings = [
            descriptor.as_string_private() if i == j else descriptor.as_string()
            for j, descriptor in enumerate(single_sig_descriptors)
        ]
        multisig_descripor = bdk.Descriptor(
            gen_multisig_descriptor_str(descriptor_strings, threshold=m, type="p2wsh"), network
        )
        multisig_descripors.append(multisig_descripor)
        wallets.append(create_wallet(multisig_descripor))

    return PyTestBDKSetup(
        network=network, blockchain=blockchain, descriptors=multisig_descripors, wallets=wallets
    )


def pytest_bdk_setup_single_sig(network=bdk.Network.REGTEST) -> PyTestBDKSetup:

    blockchain_config = get_blockchain_config(network=network)

    blockchain = bdk.Blockchain(blockchain_config)

    mnemonic = bdk.Mnemonic.from_string(test_seeds[0])

    descriptor = bdk.Descriptor.new_bip84(
        secret_key=bdk.DescriptorSecretKey(network, mnemonic, ""),
        keychain=bdk.KeychainKind.EXTERNAL,
        network=network,
    )

    wallet = bdk.Wallet(
        descriptor=descriptor,
        change_descriptor=None,
        network=network,
        database_config=bdk.DatabaseConfig.MEMORY(),
    )

    return PyTestBDKSetup(network=network, blockchain=blockchain, descriptors=[descriptor], wallets=[wallet])


@pytest.fixture
def pytest_2_of_3_multisig_wallets() -> PyTestBDKSetup:
    return pytest_bdk_setup_multisig(m=2, n=3, network=bdk.Network.REGTEST)


@pytest.fixture
def pytest_siglesig_wallet() -> PyTestBDKSetup:
    return pytest_bdk_setup_single_sig(network=bdk.Network.REGTEST)


def test_signer_finalizes_ofn_final_sig_receive(
    pytest_siglesig_wallet: PyTestBDKSetup, caplog: LogCaptureFixture, qtbot: QtBot
):

    signer = SignatureImporterClipboard(
        network=pytest_siglesig_wallet.network,
        blockchain=pytest_siglesig_wallet.blockchain,
    )

    psbt_1_sig_2_of_3 = "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"
    psbt_second_signature_2_of_3 = "cHNidP8BAIkBAAAAATuuOwH+YN3lM9CHZuaxhXU+P/xWQQUpwldxTxng2/NWAAAAAAD9////AhAnAAAAAAAAIgAgbnxIFWJ84RPQEHQJIBWYVALEGgr6e99xVLT2DDykpha+kQ0AAAAAACIAIH+2seEetNM9J6mtfXwz2EwP7E1gqjpvr0HHI97D3b5IcwAAAAABASuYuQ0AAAAAACIAIKteOph2G5lDpTD98oWJkrif3i6FX/eHTr2kmU4KN1w1IgICov3eEPPwwA+7S2NpB1FCBk3wZDu+EXBOrtIJi8IgI1lHMEQCIFuO9cKoLEM1v3juKeV+D9yotGzHONOlHdmXaA4qsa7PAiBNN4i+JleuHBXl3NFV8rQIgwCmTJkx4yykF5qnkvtJvAEBBWlSIQKi/d4Q8/DAD7tLY2kHUUIGTfBkO74RcE6u0gmLwiAjWSEDFMD9m9xxfSIcwmc3SXiciTV6v10693MSc79LQ15SBZEhA1yfr6rS8pPMIosS+UxZXBtL8+7OVVVuwZ8xyhC3o6NSU64AAAA="

    with qtbot.waitSignal(signer.signal_final_tx_received, timeout=1000) as blocker:
        signer.scan_result_callback(
            original_psbt=bdk.PartiallySignedTransaction(psbt_1_sig_2_of_3),
            data=bitcoin_qr.Data(
                bdk.PartiallySignedTransaction(psbt_second_signature_2_of_3), bitcoin_qr.DataType.PSBT
            ),
        )

    # Now check the argument with which the signal was emitted

    returned_tx = blocker.args[0]
    assert isinstance(returned_tx, bdk.Transaction)

    fully_signed_tx = "010000000001013bae3b01fe60dde533d08766e6b185753e3ffc56410529c257714f19e0dbf3560000000000fdffffff0210270000000000002200206e7c4815627ce113d01074092015985402c41a0afa7bdf7154b4f60c3ca4a616be910d00000000002200207fb6b1e11eb4d33d27a9ad7d7c33d84c0fec4d60aa3a6faf41c723dec3ddbe48040047304402205b8ef5c2a82c4335bf78ee29e57e0fdca8b46cc738d3a51dd997680e2ab1aecf02204d3788be2657ae1c15e5dcd155f2b4088300a64c9931e32ca4179aa792fb49bc0147304402207442239fc7278fbfd61f3de747dc69311cdc7d3090ab3cc26012a1c18298968d02202769a6c4fe6d09b592dad10090a973c7a77c672371a4bdda631b443bc23a8e6a0169522102a2fdde10f3f0c00fbb4b6369075142064df0643bbe11704eaed2098bc2202359210314c0fd9bdc717d221cc2673749789c89357abf5d3af7731273bf4b435e52059121035c9fafaad2f293cc228b12f94c595c1b4bf3eece55556ec19f31ca10b7a3a35253ae73000000"
    assert serialized_to_hex(returned_tx.serialize()) == fully_signed_tx


def test_signer_recognizes_finalized_tx_received(
    pytest_siglesig_wallet: PyTestBDKSetup, caplog: LogCaptureFixture, qtbot: QtBot
):

    signer = SignatureImporterClipboard(
        network=pytest_siglesig_wallet.network,
        blockchain=pytest_siglesig_wallet.blockchain,
    )

    psbt_1_sig_2_of_3 = "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"
    fully_signed_tx = "010000000001013bae3b01fe60dde533d08766e6b185753e3ffc56410529c257714f19e0dbf3560000000000fdffffff0210270000000000002200206e7c4815627ce113d01074092015985402c41a0afa7bdf7154b4f60c3ca4a616be910d00000000002200207fb6b1e11eb4d33d27a9ad7d7c33d84c0fec4d60aa3a6faf41c723dec3ddbe48040047304402205b8ef5c2a82c4335bf78ee29e57e0fdca8b46cc738d3a51dd997680e2ab1aecf02204d3788be2657ae1c15e5dcd155f2b4088300a64c9931e32ca4179aa792fb49bc0147304402207442239fc7278fbfd61f3de747dc69311cdc7d3090ab3cc26012a1c18298968d02202769a6c4fe6d09b592dad10090a973c7a77c672371a4bdda631b443bc23a8e6a0169522102a2fdde10f3f0c00fbb4b6369075142064df0643bbe11704eaed2098bc2202359210314c0fd9bdc717d221cc2673749789c89357abf5d3af7731273bf4b435e52059121035c9fafaad2f293cc228b12f94c595c1b4bf3eece55556ec19f31ca10b7a3a35253ae73000000"

    with qtbot.waitSignal(signer.signal_final_tx_received, timeout=1000) as blocker:
        signer.scan_result_callback(
            original_psbt=bdk.PartiallySignedTransaction(psbt_1_sig_2_of_3),
            data=bitcoin_qr.Data(bdk.Transaction(hex_to_serialized(fully_signed_tx)), bitcoin_qr.DataType.Tx),
        )

    # Now check the argument with which the signal was emitted

    returned_tx = blocker.args[0]
    assert isinstance(returned_tx, bdk.Transaction)

    assert serialized_to_hex(returned_tx.serialize()) == fully_signed_tx

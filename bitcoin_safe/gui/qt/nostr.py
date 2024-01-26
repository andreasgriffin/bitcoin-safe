import base64
import logging
import queue
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import bdkpython as bdk
import cbor2
import requests
from bitcoin_qrreader.bitcoin_qr import Data
from nostr_sdk import (
    Client,
    ClientSigner,
    Event,
    Filter,
    HandleNotification,
    Keys,
    Relay,
    RelayStatus,
    SecretKey,
    nip04_decrypt,
)
from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QApplication, QPushButton, QTextEdit, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


def fetch_and_parse_json(url):
    """
    Fetches data from the given URL and parses it as JSON.

    Args:
    url (str): The URL to fetch the data from.

    Returns:
    dict or None: Parsed JSON data if successful, None otherwise.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
        return response.json()
    except requests.RequestException as e:
        print(f"An error occurred: {e}")
        return None


def get_relays(nip="4"):
    result = fetch_and_parse_json(f"https://api.nostr.watch/v1/nip/{nip}")
    logger.debug(f"fetch_and_parse_json returned {result}")
    if result:
        return result
    logger.debug(f"Return default list")
    return [
        "wss://relay.damus.io",
        "wss://nostr.mom",
        "wss://nostr.slothy.win",
        "wss://nos.lol",
        "wss://nostr.massmux.com",
        "wss://nostr-relay.schnitzel.world",
        "wss://knostr.neutrine.com",
        "wss://nostr.vulpem.com",
        "wss://relay.nostr.com.au",
        "wss://e.nos.lol",
        "wss://relay.orangepill.dev",
        "wss://nostr.data.haus",
        "wss://nostr.koning-degraaf.nl",
        "wss://nostr-relay.texashedge.xyz",
        "wss://nostr.wine",
        "wss://nostr-1.nbo.angani.co",
        "wss://nostr.easydns.ca",
        "wss://nostr.cheeserobot.org",
        "wss://nostr.inosta.cc",
        "wss://relay.nostrview.com",
        "wss://relay.nostromo.social",
        "wss://arc1.arcadelabs.co",
        "wss://nostr.zkid.social",
        "wss://bitcoinmaximalists.online",
        "wss://private.red.gb.net",
        "wss://nostr21.com",
        "wss://offchain.pub",
        "wss://relay.nostrcheck.me",
        "wss://relay.nostr.vet",
        "wss://relay.hamnet.io",
        "wss://jp-relay-nostr.invr.chat",
        "wss://relay.nostr.wirednet.jp",
        "wss://nostrelay.yeghro.site",
        "wss://nostr.topeth.info",
        "wss://relay.nostrati.com",
        "wss://nostr.danvergara.com",
        "wss://nostr.roundrockbitcoiners.com",
        "wss://nostr.shawnyeager.net",
        "wss://relay.orange-crush.com",
        "wss://nostr.bitcoiner.social",
        "wss://relay.snort.social",
        "wss://nostr.bch.ninja",
        "wss://relay.nostriches.org",
        "wss://atlas.nostr.land",
        "wss://brb.io",
        "wss://relay.roli.social",
        "wss://global-relay.cesc.trade",
        "wss://relay.reeve.cn",
        "wss://relay.nostrid.com",
        "wss://nostr.noones.com",
        "wss://relay.nostr.nu",
        "wss://eden.nostr.land",
        "wss://nostr.sebastix.dev",
        "wss://nostr.fmt.wiz.biz",
        "wss://nostr.ownbtc.online",
        "wss://nostr.bitcoinplebs.de",
        "wss://tmp-relay.cesc.trade",
        "wss://bitcoiner.social",
        "wss://nostr.easify.de",
        "wss://xmr.usenostr.org",
        "wss://nostr-relay.nokotaro.com",
        "wss://nostr.naut.social",
        "wss://nostrsatva.net",
        "wss://at.nostrworks.com",
        "wss://nostr01.vida.dev",
        "wss://nostr.sovbit.host",
        "wss://nostr.plebchain.org",
        "wss://relay.nostr.bg",
        "wss://nostr.primz.org",
        "wss://relay.nostrified.org",
        "wss://nostr.decentony.com",
        "wss://relay.primal.net",
        "wss://nostr.orangepill.dev",
        "wss://puravida.nostr.land",
        "wss://nostr.1sat.org",
        "wss://nostr.oxtr.dev",
        "wss://nostr-relay.derekross.me",
        "wss://relay.s3x.social",
        "wss://nostrrelay.com",
        "wss://nostr-pub.semisol.dev",
        "wss://nostr.semisol.dev",
        "wss://relay.nostr.wf",
        "wss://nostr.land",
        "wss://relay.mostr.pub",
        "wss://relay.nostrplebs.com",
        "wss://purplepag.es",
        "wss://paid.nostrified.org",
        "wss://relayable.org",
        "wss://btc-italia.online",
        "wss://yestr.me",
        "wss://relay.nostr.sc",
        "wss://nostr.portemonero.com",
        "wss://adult.18plus.social",
        "wss://nostr.zbd.gg",
        "wss://ca.orangepill.dev",
        "wss://nostr-02.dorafactory.org",
        "wss://relay.chicagoplebs.com",
        "wss://relay.hodl.ar",
        "wss://therelayofallrelays.nostr1.com",
        "wss://nostr.carlostkd.ch",
        "wss://rly.nostrkid.com",
        "wss://welcome.nostr.wine",
        "wss://nostr.maximacitadel.org",
        "wss://nostr-relay.app",
        "wss://ithurtswhenip.ee",
        "wss://stealth.wine",
        "wss://nostr.thesamecat.io",
        "wss://nostr.zenon.info",
        "wss://yabu.me",
        "wss://relay.deezy.io",
        "wss://nrelay.c-stellar.net",
        "wss://africa.nostr.joburg",
        "wss://nostrja-kari.heguro.com",
        "wss://paid.nostr.lc",
        "wss://nostr.ingwie.me",
        "wss://relay2.nostrchat.io",
        "wss://ln.weedstr.net/nostrrelay/weedstr",
        "wss://relay1.nostrchat.io",
        "wss://nostr2.sanhauf.com",
        "wss://nostr.otc.sh",
        "wss://freerelay.xyz",
        "wss://nostrua.com",
        "wss://relay.devstr.org",
        "wss://nostr.dakukitsune.ca",
        "wss://relay2.nostr.vet",
        "wss://nostr.debancariser.com",
        "wss://nostrpub.yeghro.site",
        "wss://nostr.schorsch.fans",
        "wss://ca.relayable.org",
        "wss://nostr.hexhex.online",
        "wss://nostr.reelnetwork.eu",
        "wss://relay.nostr.directory",
        "wss://booger.pro",
        "wss://relay.stpaulinternet.net",
        "wss://nostr.donky.social",
        "wss://nostr.438b.net",
        "wss://nostr.impervious.live",
        "wss://nostr.bolt.fun",
        "wss://nostr.btc-library.com",
        "wss://sats.lnaddy.com/nostrclient/api/v1/relay",
        "wss://relay.mutinywallet.com",
        "wss://nostr.sagaciousd.com",
        "wss://nostrools.nostr1.com",
        "wss://nostrja-world-relays-test.heguro.com",
        "wss://ryan.nostr1.com",
        "wss://satdow.relaying.io",
        "wss://relay.bitcoinpark.com",
        "wss://la.relayable.org",
        "wss://nostr-01.yakihonne.com",
        "wss://nostr.fort-btc.club",
        "wss://test.relay.report",
        "wss://relay.nostrcn.com",
        "wss://nostr.sathoarder.com",
        "wss://christpill.nostr1.com",
        "wss://relap.orzv.workers.dev",
        "wss://nostr.sixteensixtyone.com",
        "wss://relay.danvergara.com",
        "wss://nostr.heliodex.cf",
        "wss://wbc.nostr1.com",
        "wss://filter.stealth.wine?broadcast=true",
        "wss://lnbits.michaelantonfischer.com/nostrrelay/michaelantonf",
        "wss://pater.nostr1.com",
        "wss://lnbits.eldamar.icu/nostrrelay/relay",
        "wss://butcher.nostr1.com",
        "wss://tictac.nostr1.com",
        "wss://relay.relayable.org",
        "wss://relay.hrf.org",
        "wss://fiatdenier.nostr1.com",
        "wss://relay.ingwie.me",
        "wss://nostr.codingarena.de",
        "wss://fistfistrelay.nostr1.com",
        "wss://au.relayable.org",
        "wss://relay.kamp.site",
        "wss://nostr.stakey.net",
        "wss://a.nos.lol",
        "wss://eu.purplerelay.com",
        "wss://relay.nostrassets.com",
        "wss://hodlbod.nostr1.com",
        "wss://nostr-relay.psfoundation.info",
        "wss://nostr.fractalized.net",
        "wss://21ideas.nostr1.com",
        "wss://hotrightnow.nostr1.com",
        "wss://verbiricha.nostr1.com",
        "wss://rly.bopln.com",
        "wss://teemie1-relay.duckdns.org",
        "wss://relay.ohbe.me",
        "wss://relay.nquiz.io",
        "wss://zh.nostr1.com",
        "wss://bevo.nostr1.com",
        "wss://gardn.nostr1.com",
        "wss://feedstr.nostr1.com",
        "wss://supertestnet.nostr1.com",
        "wss://relay-jp.shino3.net",
        "wss://sakhalin.nostr1.com",
        "wss://adre.su",
        "wss://nostr.kungfu-g.rip",
        "wss://pay21.nostr1.com",
        "wss://testrelay.nostr1.com",
        "wss://nostr-dev.zbd.gg",
        "wss://za.purplerelay.com",
        "wss://in.purplerelay.com",
        "wss://nostr.openordex.org",
        "wss://relay.cxcore.net",
        "wss://vitor.relaying.io",
        "wss://agora.nostr1.com",
        "wss://nostr.hashi.sbs",
        "wss://nostr.lbdev.fun",
        "wss://relay.crimsonleaf363.com",
        "wss://pablof7z.nostr1.com",
        "wss://zyro.nostr1.com",
        "wss://relay.satoshidnc.com",
        "wss://strfry.nostr.lighting",
        "wss://frens.nostr1.com",
        "wss://vitor.nostr1.com",
        "wss://chefstr.nostr1.com",
        "wss://relay.siamstr.com",
        "wss://ae.purplerelay.com",
        "wss://umami.nostr1.com",
        "wss://prism.nostr1.com",
        "wss://sfr0.nostr1.com",
        "wss://n.ok0.org",
        "wss://relay.nostr.wien",
        "wss://relay.nostr.pt",
        "wss://relay.piazza.today",
        "wss://relay.exit.pub",
        "wss://testnet.plebnet.dev/nostrrelay/1",
        "wss://studio314.nostr1.com",
        "wss://ch.purplerelay.com",
        "wss://legend.lnbits.com/nostrclient/api/v1/relay",
        "wss://us.nostr.land",
        "wss://fl.purplerelay.com",
        "wss://relay.minibits.cash",
        "wss://us.nostr.wine",
        "wss://frjosh.nostr1.com",
        "wss://cellar.nostr.wine",
        "wss://inbox.nostr.wine",
        "wss://nostr.hubmaker.io",
        "wss://shawn.nostr1.com",
        "wss://relay.gems.xyz",
        "wss://nostr-02.yakihonne.com",
        "wss://obiurgator.thewhall.com",
        "wss://relay.nos.social",
        "wss://nostr.psychoet.nexus",
        "wss://nostr.1661.io",
        "wss://nostr.tavux.tech",
        "wss://lnbits.aruku.kro.kr/nostrrelay/private",
        "wss://relay.artx.market",
        "wss://lnbits.btconsulting.nl/nostrrelay/nostr",
        "wss://nostr-03.dorafactory.org",
        "wss://nostr.atlbitlab.com",
        "wss://nostr.zoel.network",
        "wss://lnbits.papersats.io/nostrclient/api/v1/relay",
        "wss://yondar.nostr1.com",
        "wss://creatr.nostr.wine",
        "wss://riray.nostr1.com",
        "wss://nostr.pklhome.net",
        "wss://relay.tunestr.io",
        "wss://ren.nostr1.com",
        "wss://theforest.nostr1.com",
        "wss://nostrdevs.nostr1.com",
        "wss://nostr.cahlen.org",
        "wss://nostr.papanode.com",
        "wss://milwaukie.nostr1.com",
        "wss://strfry.chatbett.de",
        "wss://relay.bitmapstr.io",
        "wss://directory.yabu.me",
        "wss://nostr.reckless.dev",
        "wss://srtrelay.c-stellar.net",
        "wss://nostr.lopp.social",
        "wss://vanderwarker.dev/nostrclient/api/v1/relay",
        "wss://relay.notoshi.win",
        "wss://lnbits.satoshibox.io/nostrclient/api/v1/relay",
        "wss://relay.zhoushen929.com",
        "wss://relay.moinsen.com",
        "wss://hayloo88.nostr1.com",
        "wss://140.f7z.io",
        "wss://jumpy-bamboo-euhyboma.scarab.im",
        "wss://beijing.scarab.im",
        "wss://mnl.v0l.io",
        "wss://staging.yabu.me",
        "wss://nostr.notribe.net",
        "wss://rnostr.onrender.com",
        "wss://nostr.ra-willi.com",
        "wss://relay.swisslightning.net",
        "wss://xxmmrr.shogatsu.ovh",
        "wss://relay.agorist.space",
        "wss://relay.lightningassets.art",
        "wss://dev-relay.nostrassets.com",
        "wss://nostr.jfischer.org",
        "wss://frogathon.nostr1.com",
        "wss://marmot.nostr1.com",
        "wss://island.nostr1.com",
        "wss://relay.angor.io",
        "wss://relay.earthly.land",
        "wss://jmoose.rocks",
        "wss://test2.relay.report",
        "wss://relay.strfront.com",
        "wss://relay01.karma.svaha-chain.online",
        "wss://nostr.cyberveins.eu",
        "wss://relay.nostr.net",
        "wss://beta.1661.io",
        "wss://nostr.8k-lab.com",
        "wss://relay.lawallet.ar",
        "wss://relay.timechaindex.com",
        "wss://relay.13room.space",
        "wss://relay.westernbtc.com",
        "wss://nostr.nobkslave.site",
        "wss://fiatjaf.nostr1.com",
        "wss://relay2.denostr.com",
        "wss://relay.nip05.social",
        "wss://bbb.santos.lol",
        "wss://relay.cosmicbolt.net",
    ]


@dataclass
class NostrDM:
    label: str
    description: str
    data: Optional[Data] = None
    event: Optional[Event] = None

    def dump(self) -> Dict:
        d = self.__dict__.copy()
        if self.data:
            d["data"] = self.data.data_as_string()
            d["data_type_name"] = self.data.data_type.name
        return d

    def serialize(self) -> str:
        d = self.dump()

        encoded_data = cbor2.dumps(d)

        base64_encoded_data = base64.b64encode(encoded_data).decode()
        return base64_encoded_data

    @classmethod
    def from_dump(cls, decoded_dict: Dict, network: bdk.Network) -> "NostrDM":
        # decode the data from the string and ensure the type is unchanged
        if decoded_dict["data"]:
            data: Data = Data.from_str(decoded_dict["data"], network=network)
            decoded_dict["data"] = data
            assert decoded_dict["data_type_name"] == data.data_type.name
            del decoded_dict["data_type_name"]

        return NostrDM(**decoded_dict)

    @classmethod
    def from_serialized(cls, base64_encoded_data, network: bdk.Network) -> "NostrDM":
        decoded_data = base64.b64decode(base64_encoded_data)
        decoded_dict = cbor2.loads(decoded_data)
        return cls.from_dump(decoded_dict, network=network)

    def __str__(self) -> str:
        return str(self.dump())


class NotificationHandler(HandleNotification):
    def __init__(self, keys: Keys, queue: queue.Queue, signal_nostr_dm: Signal) -> None:
        super().__init__()
        self.queue = queue
        self.keys = keys
        self.signal_nostr_dm = signal_nostr_dm

    def handle_own_dm_event(self, event):
        public_key = event.public_keys()[0]
        assert public_key.to_bech32() == self.keys.public_key().to_bech32()

        base64_encoded_data = nip04_decrypt(self.keys.secret_key(), public_key, event.content())
        nostr_dm = NostrDM.from_serialized(
            base64_encoded_data=base64_encoded_data, network=bdk.Network.REGTEST
        )
        self.queue.put(nostr_dm)
        self.signal_nostr_dm.emit(nostr_dm)

        logger.debug(f"Received own dm: {nostr_dm}")

    def handle(self, relay_url, event):
        # print(f"Received new event from {relay_url}: {event.as_json()}")
        if event.kind() == 4:
            # print("Decrypting event")
            try:
                public_key = event.public_keys()[0]
                if public_key.to_bech32() == self.keys.public_key().to_bech32():
                    self.handle_own_dm_event(event)
            except Exception as e:
                print(f"Error during content decryption: {e}")

    def handle_msg(self, relay_url, msg):
        pass
        # print(f"Received direct message: {msg}")


from PySide2.QtCore import QTimer


class NostrMemory(QObject):
    signal_nostr_dm = Signal(NostrDM)

    def __init__(self, secret_bytes) -> None:
        super().__init__()

        self.keys = Keys(sk=SecretKey.from_bytes(secret_bytes))
        self.client: Client = None
        self.queue: queue.Queue = queue.Queue(maxsize=10000)
        self.events: List[Event] = []
        self.timer = QTimer()

        # Initialize the client with the private key
        signer = ClientSigner.keys(self.keys)
        self.client = Client(signer)

        relays = get_relays()
        relays = relays[: min(5, len(relays))]
        for relay in relays:
            self.client.add_relay(relay)

    def get_connected_relays(self) -> Relay:
        connected_relays: List[Relay] = [
            relay for relay in self.client.relays().values() if relay.status == RelayStatus.CONNECTED
        ]
        logger.debug(f"connected_relays = {connected_relays} of all relays {self.client.relays()}")
        return connected_relays

    def send(self, nostr_dm: NostrDM) -> bool:
        try:
            print(f"send {nostr_dm}")
            self.client.send_direct_msg(self.keys.public_key(), nostr_dm.serialize(), reply=None)
            return True  # Message sent successfully
        except Exception as e:
            logger.error(f"Error sending direct message: {e}")
            return False  # Message sending failed

    def subscribe(self):
        if not self.client.is_running() or not self.get_connected_relays():
            self.ensure_connected()

        self._start_timer()

        self.client.handle_notifications(NotificationHandler(self.keys, self.queue, self.signal_nostr_dm))

        # Get dms, sent from me
        filter = Filter().authors([self.keys.public_key()]).kind(4)
        self.events = self.client.subscribe([filter])

    def _start_timer(self, delay_retry_connect=5):
        if self.timer.isActive():
            return
        self.timer.setInterval(delay_retry_connect * 1000)
        self.timer.timeout.connect(self.ensure_connected)
        self.timer.start()

    def ensure_connected(self):
        if self.get_connected_relays():
            return

        logger.debug("Trying to connect")

        self.client.connect()


if __name__ == "__main__":

    class SimpleChatApp(QWidget):
        def __init__(self):
            super().__init__()

            self.memory = NostrMemory("stupid_password_just_for_testing".encode())

            # Layout
            layout = QVBoxLayout()

            # TextEdit for received messages
            self.received_messages = QTextEdit()
            self.received_messages.setReadOnly(True)
            layout.addWidget(self.received_messages)

            # TextEdit for writing a message
            self.message_to_send = QTextEdit()
            layout.addWidget(self.message_to_send)

            # Send button
            self.send_button = QPushButton("Send")
            self.send_button.clicked.connect(self.send_message)
            layout.addWidget(self.send_button)

            # Set the layout
            self.setLayout(layout)

            def on_message(nostr_dm: NostrDM):
                print(f"Received {nostr_dm}")
                self.received_messages.append(str(nostr_dm))

            self.memory.signal_nostr_dm.connect(on_message)
            self.memory.subscribe()

        def send_message(self):
            # Get the message text
            message = self.message_to_send.toPlainText()

            data = None
            try:
                data = Data.from_str(message, bdk.Network.REGTEST)
            except:
                print(f"{message} could not be recognized as bitcoin data")
            self.memory.send(NostrDM(f"label of {message}", message, data=data))

            # Clear the message input
            self.message_to_send.clear()

    logging.basicConfig(level=logging.DEBUG)

    app = QApplication(sys.argv)

    chat_app = SimpleChatApp()
    chat_app.show()

    sys.exit(app.exec_())

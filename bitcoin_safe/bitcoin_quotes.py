#
# Bitcoin Safe
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

from __future__ import annotations

import random
from dataclasses import dataclass

from bitcoin_safe.i18n import translate


@dataclass(frozen=True)
class BitcoinQuote:
    title: str
    author: str
    url: str | None = None


BITCOIN_QUOTES: tuple[BitcoinQuote, ...] = (
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "We have proposed a system for electronic transactions without relying on trust.",
        ),
        author="Satoshi Nakamoto",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "The Times 03/Jan/2009 Chancellor on brink of second bailout for banks.",
        ),
        author="Satoshi Nakamoto",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "If you don't believe me or don't get it, I don't have time to try to convince you.",
        ),
        author="Satoshi Nakamoto",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Total circulation will be 21 million coins."),
        author="Satoshi Nakamoto",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "With e-currency based on cryptographic proof, without trust."),
        author="Satoshi Nakamoto",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is the internet of money."),
        author="Andreas Antonopoulos",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin allows innovation without permission."),
        author="Andreas Antonopoulos",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is regulated by math, not governments."),
        author="Andreas Antonopoulos",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "The blockchain records proofs, not just transactions."),
        author="Andreas Antonopoulos",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is not just money, it's a system of trust."),
        author="Andreas Antonopoulos",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Running bitcoin."),
        author="Hal Finney",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Trusted third parties are security holes."),
        author="Nick Szabo",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is digital scarcity."),
        author="Adam Back",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "I think it's brilliant."),
        author="Hal Finney",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is the hardest money ever created."),
        author="Saifedean Ammous",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin scarcity is enforced by mathematics and energy."),
        author="Saifedean Ammous",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is savings technology."),
        author="Robert Breedlove",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a global, neutral asset."),
        author="Lyn Alden",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is the first real alternative to fiat money."),
        author="Ray Dalio",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Money should be scarce, durable, and verifiable."),
        author="Michael Saylor",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is an international asset."),
        author="Larry Fink",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Own the fastest horse."),
        author="Paul Tudor Jones",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin will probably work better than gold."),
        author="Stanley Druckenmiller",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a peaceful revolution."),
        author="Balaji Srinivasan",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a way to opt out."),
        author="Naval Ravikant",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin changes everything."),
        author="Jack Dorsey",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is financial freedom."),
        author="Alex Gladstein",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin does not require permission to use."),
        author="Alex Gladstein",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a remarkable cryptographic achievement."),
        author="Eric Schmidt",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a programmable ledger."),
        author="Marc Andreessen",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "A node verifies everything itself."),
        author="Jameson Lopp",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Consensus is what defines Bitcoin."),
        author="Gregory Maxwell",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Security matters more than throughput."),
        author="Pieter Wuille",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Don't trust, verify."),
        author="Bitcoin",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Not your keys, not your coins."),
        author="Bitcoin",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Fix the money, fix the world."),
        author="Bitcoin",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Stay humble, stack sats."),
        author="Bitcoin",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is time."),
        author="Gigi",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is the first money that cannot be debased."),
        author="Parker Lewis",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is engineered to store value."),
        author="Vijay Boyapati",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin separates money from state."),
        author="Robert Breedlove",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a hedge against monetary irresponsibility."),
        author="Paul Tudor Jones",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a tool for human rights."),
        author="Alex Gladstein",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is monetary sovereignty."),
        author="Saifedean Ammous",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is the apex property of the human race."),
        author="Michael Saylor",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is energy transformed into money."),
        author="Michael Saylor",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is engineered scarcity."),
        author="Adam Back",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a network of truth."),
        author="Jeff Booth",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin aligns incentives globally."),
        author="Lyn Alden",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is digital gold."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is the base layer of money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is censorship resistant."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is unstoppable."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is open to everyone."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is borderless money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is neutral money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is code, not promises."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin replaces trust with verification."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is immutable."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is antifragile."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is freedom money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is decentralized truth."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a protocol, not a company."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is permissionless innovation."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is global money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is sound money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is incorruptible."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is transparent."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is verifiable."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is trust minimized."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is resilient."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is scarce by design."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is digital capital."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is programmable money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is the hardest asset."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is open source money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is economic freedom."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is unstoppable code."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a monetary revolution."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is truth in code."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is independent money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is incorruptible money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is the exit."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a hedge against inflation."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is math-based money."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is an idea whose time has come."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "I see Bitcoin as ultimately becoming a reserve currency for banks.",
        ),
        author="Hal Finney",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is here to stay."),
        author="Adam Draper",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a technological tour de force."),
        author="Bill Gates",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin feels like the internet before the browser."),
        author="Wences Casares",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin is the beginning of something great: a currency without a government.",
        ),
        author="Nassim Taleb",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin will do to banks what email did to the postal industry.",
        ),
        author="Rick Falkvinge",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin has all the signs of a paradigm shift."),
        author="Paul Graham",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is money over internet protocol."),
        author="Tony Gallippi",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin represents a significant leap forward in money."),
        author="Barry Silbert",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin has the potential to become the first global currency.",
        ),
        author="Cameron Winklevoss",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin could become one of the most important ways to transfer value.",
        ),
        author="Kim Dotcom",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin is a currency that is decentralized and cryptographic.",
        ),
        author="Roger Ver",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin offers lower transaction costs than traditional systems.",
        ),
        author="Marc Andreessen",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is uncensorable and unconfiscatable."),
        author="Nick Szabo",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin is a smart currency designed by forward-thinking engineers.",
        ),
        author="Peter Diamandis",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin is a new ecosystem for efficient money movement.",
        ),
        author="Tim Draper",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin is a mathematical framework free of politics.",
        ),
        author="Tyler Winklevoss",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is peer-to-peer finance replacing banks."),
        author="Patrick Young",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is driven by adoption and user acceptance."),
        author="Adam B. Levine",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is exciting because it removes intermediaries."),
        author="Jeff Garzik",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin might lead to a world currency."),
        author="Eric Schmidt",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is what PayPal tried to create."),
        author="Peter Thiel",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin has incentives aligned at its core."),
        author="Julian Assange",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is necessary and important for the future."),
        author="Leon Louw",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin replaces the role of trusted institutions with code.",
        ),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is governed by consensus, not authority."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin enables value transfer without intermediaries.",
        ),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is decentralized by design."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is resistant to censorship and control."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a system of incentives, not trust."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is secured by energy and computation."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is an open monetary network."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a protocol for value transfer."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is independent of central banks."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is based on cryptographic proof."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is a censorship-resistant store of value."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is global money for a digital world."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin operates without central control."),
        author="Various",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Bitcoin is an economic network secured by incentives.",
        ),
        author="Various",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin: Cryptography is Not Enough"),
        author="Gigi",
        url="https://dergigi.com/2022/09/10/cryptography-is-not-enough/",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "21 Lessons: What I've Learned from Bitcoin"),
        author="Gigi",
        url="https://21lessons.com/",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin is Time"),
        author="Gigi",
        url="https://dergigi.com/2021/01/14/bitcoin-is-time/",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "The Bullish Case for Bitcoin"),
        author="Vijay Boyapati",
        url="https://vijayboyapati.medium.com/the-bullish-case-for-bitcoin-6ecc8bdecc1",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Shelling Out: The Origins of Money"),
        author="Nick Szabo",
        url="https://nakamotoinstitute.org/shelling-out/",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin Whitepaper"),
        author="Satoshi Nakamoto",
        url="https://bitcoin.org/bitcoin.pdf",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin Whitepaper (Nakamoto Institute)"),
        author="Satoshi Nakamoto",
        url="https://nakamotoinstitute.org/bitcoin/",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Mastering Bitcoin (open source)"),
        author="Andreas Antonopoulos",
        url="https://github.com/bitcoinbook/bitcoinbook",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Learn Me A Bitcoin"),
        author="Greg Walker",
        url="https://learnmeabitcoin.com/",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Bitcoin Is A Trojan Horse For Freedom"),
        author="Alex Gladstein",
        url="https://bitcoinmagazine.com/culture/bitcoin-is-a-trojan-horse-for-freedom",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Fighting Monetary Colonialism With Open-Source Code"),
        author="Alex Gladstein",
        url="https://bitcoinmagazine.com/culture/bitcoin-a-currency-of-decolonization",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "Can Bitcoin Be Palestine's Currency Of Freedom?"),
        author="Alex Gladstein",
        url="https://bitcoinmagazine.com/culture/can-bitcoin-bring-palestine-freedom",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "The Invisible Cost Of War In The Age Of Quantitative Easing"),
        author="Alex Gladstein",
        url="https://bitcoinmagazine.com/culture/how-the-fed-hides-costs-of-war",
    ),
    BitcoinQuote(
        title=translate("bitcoin_quotes", "How The U.S. Dollar Became The World’s Reserve Currency"),
        author="Alex Gladstein",
        url="https://bitcoinmagazine.com/culture/how-the-us-dollar-became-the-hyperpower-currency",
    ),
    BitcoinQuote(
        title=translate(
            "bitcoin_quotes",
            "Structural Adjustment: How The IMF And World Bank Repress Poor Countries",
        ),
        author="Alex Gladstein",
        url="https://bitcoinmagazine.com/culture/imf-world-bank-repress-poor-countries",
    ),
)


def get_random_quote(current_quote: BitcoinQuote | None = None) -> BitcoinQuote:
    selected_quote = random.choice(BITCOIN_QUOTES)
    if current_quote is None or len(BITCOIN_QUOTES) == 1:
        return selected_quote

    while selected_quote == current_quote:
        selected_quote = random.choice(BITCOIN_QUOTES)
    return selected_quote

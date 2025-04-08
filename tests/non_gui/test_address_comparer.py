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


import random
import time

from bitcoin_safe.address_comparer import AddressComparer


def test_identical_addresses():
    addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    assert not AddressComparer.poisonous({addr, addr})


def test_similar_poisonous_base58():
    addr1 = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    # Slight difference at the end.
    addr2 = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"
    # With a high enough similarity, this pair should be flagged as poisonous.
    assert AddressComparer.poisonous({addr1, addr2})


def test_different_addresses():
    addr1 = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    addr2 = "1A1atSLRHtKNngkdXEeobR76b53LETtpNa"  # Only 2 matching characters  (can be coincidence)
    assert not AddressComparer.poisonous({addr1, addr2})


def test_similar_poisonous_bech32():
    # Two bech32 addresses that differ only slightly.
    addr1 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080"
    addr2 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt081"

    assert AddressComparer.poisonous({addr1, addr2})

    # real example not similar enough
    addr1 = "bcrt1qlelfnq4c7asm6p556fw32e5kcgxsply7vls9hvcgfv83pyhtt0lscs6qa0"
    addr2 = "bcrt1qtsk0skze8qqd4juleyhtqq7sm03pe5vs7s6qa0"

    assert not AddressComparer.poisonous({addr1, addr2})

    # real example made more similar (not valid address)
    addr1 = "bcrt1qlelfnq4c7asm6p556fw32e5kcgxsply7vls9hvcgfv83pyhtt0lscs6qa0"
    addr2 = "bcrt1qlel0skze8qqd4juleyhtqq7sm03pe5vs7s6qa0"

    assert AddressComparer.poisonous({addr1, addr2})


def test_base58_vs_bech32():
    # Compare a base58 address with a bech32 address.
    # Since the strings are very different, the similarity score should be low.
    addr1 = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    addr2 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080"
    assert not AddressComparer.poisonous({addr1, addr2})


def test_poisonous_bech32():
    # source https://github.com/jlopp/bitcoin-utils/tree/master/addressPoisonAttacks?ref=blog.lopp.net
    poision_tuples = [
        ("bc1qr9wuw4zkjflet80lr9cr5ec8620c4fg52wua0h", "bc1qr9xkxanfstzqpfd5ce0t3evwc45pnmsr2wua0h"),
        ("18V7xnpitbSwpiQ5RbxhCbnLvxwvNM8BeU", "18VUR5V2cpU7NF8ZaVe8eP1h9nwMhB8BeU"),
        ("1J18yAMYYL6peNSqLwxQnM4HCLrEvs8FuV", "1J1F3U7gHrCjsEsRimDJ3oYBiV24wA8FuV"),
        ("19NQULPvvjJUA3v2EQp6LtS4VHhfzMQauz", "19NioZynkRkN8Jcu3C1LyqExWyfgygQauz"),
        ("bc1qtq33mqfrkxnprwzexkdyhvcjsz03nuv6a343m7", "bc1qtqaryccgxasxg376k8p6ug0rjv9hvhr90343m7"),
    ]

    combined_set = set()
    for addr1, addr2 in poision_tuples:

        assert AddressComparer.poisonous({addr1, addr2})
        combined_set.add(addr1)
        combined_set.add(addr2)

    poisonous = AddressComparer.poisonous(combined_set)
    assert len(poisonous) == len(poision_tuples)


def test_non_poisonous_bech32():
    random.seed(22)
    # Allowed characters for base58 (excluding 0, O, I, and l)
    base58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

    # Helper to generate a fake base58 address of length 34 (first char is "1" for mainnet p2pkh)
    def generate_address():
        return "1" + "".join(random.choices(base58_chars, k=33))

    # Generate addresses  (increasing this a little more WILL generate fals positives)
    addresses = {generate_address() for _ in range(2000)}

    print("Starting compare_of_tx with:")
    print(f"  {len(addresses)}   addresses")

    start_time = time.perf_counter()
    results = AddressComparer.poisonous(addresses)
    assert not results
    end_time = time.perf_counter()
    elapsed = end_time - start_time

    print(f"Completed in {elapsed:.3f} seconds.")


def test_compare_all_similar():
    """
    For two very similar base58 addresses, check that compare_all returns a similarity that is
    nearly equal to the result of compare_address_info.
    """
    addr1 = "1A1zPaaaeP5QGefi2DMPTfTL5SLmv7DivfNa"
    addr2 = "1A1zPbbb5QGefi2DMPTfTL5SLmv7DivfNb"

    addresses = {addr1, addr2}
    all_results = AddressComparer.compare_all(addresses)
    # There should be exactly one candidate pair.
    pair = frozenset(addresses)
    sim_all = all_results[pair]
    sim_info = AddressComparer.compare_address_info(addr1, addr2)
    # The two similarity scores should match (or be extremely close).
    assert abs(sim_all.score - sim_info.score) < 1e-6
    assert sim_info.matches == [
        ("A1zP", "A1zP"),
        ("5QGefi2DMPTfTL5SLmv7DivfNa", "5QGefi2DMPTfTL5SLmv7DivfNb"),
    ]
    assert AddressComparer.poisonous(addresses)


def test_fuzzy_prefix_match_exact():
    # For two identical strings, the match score should equal the string length.
    a = "A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNbabcdef"
    b = "A1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaabcdef"
    result = AddressComparer.fuzzy_prefix_match(a, b)
    assert result.score == 2
    assert result.matches[0][0] == "A1"
    assert result.matches[0][1] == "A1"

    result = AddressComparer.fuzzy_prefix_match(a, b, rtl=True)
    assert result.score == 6
    assert result.matches[0][0] == "abcdef"
    assert result.matches[0][1] == "abcdef"


def test_fuzzy_prefix_match_gap():
    # Example where a gap is allowed.
    # a = "abcdef", b = "abcxef"
    # Expected behavior (based on our implementation):
    #   - Characters 0-2 match: "abc"
    #   - At index 3, a[3]="d" vs b[3]="x": gap is used.
    #   - Then indices 4 and 5 match: "ef"
    # Total fuzzy score = 3 (from indices 0-2) + 2 (from indices 4-5) = 5.
    a = "abcdef"
    b = "abcxef"
    result = AddressComparer.fuzzy_prefix_match(a, b)
    assert result.score == 5, f"Expected score 5 but got {result.score}"
    # For this implementation, matchA should be "abcdef" and matchB "abcxef"
    # (Even though the gap is used, the entire string is returned for illustrative purposes.)
    assert result.matches[0][0] == "abcdef"
    assert result.matches[0][1] == "abcxef"


# below is a psbt with similar addresses.
# You must set ADDRESS_SIMILARITY_THRESHOLD = 32768
# otherwise it is not recognized, since the difficulty is too low
#  cHNidP8BAKgBAAAAAcgPfvBnxr9qF0o5tGN7Yi700GJKITISfTB25evv/et7AQAAAAD9////A6APAAAAAAAAFgAUXCz4WFk4ANrLn8kusAPQ2+Ic0ZCgDwAAAAAAACIAIP5+mYK492G9BpTSXRVmlsINAPyeZ+BbswhLDxCS61v/JtmXAAAAAAAiACDYrIlFGPEykE16uVcbeRxB4aCyhbhitXY1kRc4GvpHtfMLAABPAQQ1h88EApdQj4AAAAI3TSBpfcsjErxWbW7+K4tU2p6/TnBriteYduNbUJ4O9wItTl11LzxH4f2/d0TTjLmN6zrPREFoE9yEg+S9AkX/qRSVryXvMAAAgAEAAIAAAACAAgAAgE8BBDWHzwQbRllDgAAAAkitfn+2yQwdQ8dXOXV6vO2Zso8C/2H+MtXw9ZjOtW1WAtJLqqIQmSaIaMWNj8lf7HaeNEncI+kU/ECkQ+KFjKmGFGFVKWQwAACAAQAAgAAAAIACAACAAAEA/VoBAQAAAAABAakvWHNzJ17xblA9QOL0EXRcUYAwL4qjZuq0ovU9ioHsAAAAAAD9////AkCcAAAAAAAAFgAUbY8H0Xk7T37O+Uz0G7jWzhzT2z+L+ZcAAAAAACIAIHQluxNKgjKW9D1pcYrVFUulolDSot2cB2+nUyyc5XK0BABHMEQCIAhwYcTRjfvFqv0Z9uUpI4ZWz42enHyGV1CCFiEUQ5WeAiBK0zCWUm1evI/OaK3Xx/eb2rkTOGtS42EbBLLv9u5oGwFIMEUCIQDd7J3nbwYAs24cRvDjK7nadvF4OcadRbwivFzwVzn0VQIgKMykT3UdEJV2vSPwq4LdyMogPulVaPYgwHgYeJXiapoBR1IhAjdvV2a9+BkCJM/rKvWQfBgp2AvgfUDFFZkWkSXrduuqIQKURqBDnTV3cMVo9wuihKiT3YEsJFKW1sT4U6/rhzwCklKu8wsAAAEBK4v5lwAAAAAAIgAgdCW7E0qCMpb0PWlxitUVS6WiUNKi3ZwHb6dTLJzlcrQBBUdSIQKG5xW3iX3O0l5O7NasvqoxCpW63kvjxQTt+o4Qhj1mECECqav5dMbFkm0qsC0ADq0s5CDRXj2Jrut4L4US/4W4TUpSriIGAobnFbeJfc7SXk7s1qy+qjEKlbreS+PFBO36jhCGPWYQHJWvJe8wAACAAQAAgAAAAIACAACAAQAAAAAAAAAiBgKpq/l0xsWSbSqwLQAOrSzkINFePYmu63gvhRL/hbhNShxhVSlkMAAAgAEAAIAAAACAAgAAgAEAAAAAAAAAAAABAUdSIQLZyBMiiLsHGtSx2nyq9ABzY2Yhu901nOxzXuEMaw0jNSEDMFDbnxOXNQTw+yBcmixX/oY5qVDF/J0LedWagKWU2bVSriICAtnIEyKIuwca1LHafKr0AHNjZiG73TWc7HNe4QxrDSM1HJWvJe8wAACAAQAAgAAAAIACAACAAAAAAAEAAAAiAgMwUNufE5c1BPD7IFyaLFf+hjmpUMX8nQt51ZqApZTZtRxhVSlkMAAAgAEAAIAAAACAAgAAgAAAAAABAAAAAAEBR1IhAuUSbT2a+i0iwnGfhNMFh2aPA9s5MgYjfVA1zf5Gky6fIQMeMhD8WBfUF++O4Yw1pWTzfNT3GmIfHkJcRilAfrcR1VKuIgIC5RJtPZr6LSLCcZ+E0wWHZo8D2zkyBiN9UDXN/kaTLp8cYVUpZDAAAIABAACAAAAAgAIAAIABAAAAAQAAACICAx4yEPxYF9QX747hjDWlZPN81PcaYh8eQlxGKUB+txHVHJWvJe8wAACAAQAAgAAAAIACAACAAQAAAAEAAAAA

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

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FuzzyMatch:
    identical: bool
    score: int
    matches: list[tuple[str, str]]


class AddressComparer:
    # The similarity threshold (1 false positive per ~10 million comparisons)
    ADDRESS_SIMILARITY_THRESHOLD = 10_000_000

    @classmethod
    def detect_network_and_type(cls, address: str) -> tuple[str, str]:
        """Detect network and type."""
        if address and address[0] in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz":
            if address[0] == "1":
                return ("mainnet", "p2pkh")
            elif address[0] == "3":
                return ("mainnet", "p2sh")
            elif address[0] in ["m", "n"]:
                return ("testnet", "p2pkh")
            elif address[0] == "2":
                return ("testnet", "p2sh")
        if "1" in address:
            hrp: str = address.split("1", 1)[0].lower()
            if hrp == "bc":
                network: str = "mainnet"
            elif hrp == "tb":
                network = "testnet"
            elif hrp == "bcrt":
                network = "regtest"
            else:
                network = "unknown"
            remainder: str = address[len(hrp) + 1 :]
            if not remainder:
                return (network, "unknown")
            if remainder[0] == "q":
                return (network, "v0_p2wpkh")
            elif remainder[0] == "p":
                return (network, "v1_p2tr")
            else:
                return (network, "unknown")
        return ("unknown", "unknown")

    @classmethod
    def strip_prefix(cls, address: str) -> str:
        """Strip prefix."""
        network, addr_type = cls.detect_network_and_type(address)
        if addr_type in ["p2pkh", "p2sh"]:
            return address[1:] if len(address) > 1 else ""
        elif addr_type in ["v0_p2wpkh", "v1_p2tr"]:
            parts: list[str] = address.split("1", 1)
            return parts[1] if len(parts) > 1 else address
        else:
            return address

    @classmethod
    def extract_trigrams_numpy(
        cls,
        address: str,
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Extract overlapping 3-character sequences (trigrams) from the stripped
        address and assign weights. The first `n_begin` and last `m_end` trigrams
        receive higher weights.

        For example, if the stripped address is "ABCDEFG", then the trigrams produced are:
            ["ABC", "BCD", "CDE", "DEF", "EFG"]
        And if n_begin and m_end are set to 2, then:
            - The first two trigrams ("ABC", "BCD") get weight_begin (e.g. 5.0),
            - The last two trigrams ("DEF", "EFG") get weight_end (e.g. 5.0),
            - The remaining trigrams (if any) get default_weight (e.g. 1.0).
        """
        # Strip the address of its network-specific prefix (e.g. remove "1" for base58 addresses)
        s: str = cls.strip_prefix(address)
        # Convert the stripped string into an array of individual characters
        chars: np.ndarray = np.array(list(s))
        L: int = len(chars)
        # If the address (after stripping) is too short to form a trigram, return empty arrays.
        if L < 3:
            return np.empty(0, dtype="<U3"), np.empty(0, dtype=float)
        # Generate an array of trigrams by sliding a window of 3 characters across the string.
        # For example, if s = "ABCDEFG", then trigrams will be:
        # ["ABC", "BCD", "CDE", "DEF", "EFG"]
        trigrams: np.ndarray = np.array(["".join(chars[i : i + 3]) for i in range(L - 2)], dtype="<U3")
        # Create an array of weights with the default weight for each trigram.
        weights: np.ndarray = np.full(L - 2, default_weight, dtype=float)
        # For the first n_begin trigrams, assign the higher weight (weight_begin).
        # E.g., if n_begin = 2, then the first 2 trigrams get weight_begin.
        if n_begin > 0:
            weights[: min(n_begin, L - 2)] = weight_begin
        # For the last m_end trigrams, assign the higher weight (weight_end).
        # E.g., if m_end = 2, then the last 2 trigrams get weight_end.
        if m_end > 0:
            weights[-min(m_end, L - 2) :] = weight_end
        # Return the arrays of trigrams and their corresponding weights.
        return trigrams, weights

    @classmethod
    def build_trigram_dict(
        cls,
        address: str,
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
    ) -> dict[str, float]:
        """Builds a dictionary mapping each trigram to its total weight for a given
        address."""
        trigrams, weights = cls.extract_trigrams_numpy(
            address, n_begin, m_end, weight_begin, weight_end, default_weight
        )
        trigram_dict: dict[str, float] = {}
        for tg, wt in zip(trigrams, weights, strict=False):
            trigram_dict[tg] = trigram_dict.get(tg, 0.0) + wt
        return trigram_dict

    @classmethod
    def precompute_trigram_dicts(
        cls,
        addresses: set[str],
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
    ) -> dict[str, dict[str, float]]:
        """Precomputes the trigram dictionary for each address in the set."""
        precomputed: dict[str, dict[str, float]] = {}
        for addr in addresses:
            precomputed[addr] = cls.build_trigram_dict(
                addr, n_begin, m_end, weight_begin, weight_end, default_weight
            )
        logger.debug(f"Finished precompute_trigram_dicts of {len(addresses)} addresses")
        return precomputed

    @classmethod
    def find_neighbors(
        cls,
        addresses: set[str],
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
        candidate_threshold: float = 2.0,
    ) -> dict[str, list[tuple[str, float]]]:
        """For each address in the given set, finds neighboring addresses that share
        similar trigrams, using an inverted index built from the precomputed trigram
        dictionaries.

        For each trigram in an address's precomputed dictionary, each candidate address that shares the trigram
        gets its candidate score incremented by min(weight_in_address, weight_in_candidate).
        Only candidates accumulating a total candidate score >= candidate_threshold are returned.

        Returns:
            A dictionary mapping each address to a list of tuples (neighbor_address, candidate_score).
        """
        # Precompute the trigram dictionaries for all addresses.
        # For each address, build a dictionary mapping trigrams (e.g., "ABC") to a cumulative weight.
        # Example: For address "ABCDEF", after stripping, the trigrams might be:
        #           "ABC": weight 5.0, "BCD": weight 1.0, "CDE": weight 1.0, "DEF": weight 5.0.
        precomputed: dict[str, dict[str, float]] = cls.precompute_trigram_dicts(
            addresses, n_begin, m_end, weight_begin, weight_end, default_weight
        )

        # Build an inverted index that maps each trigram to the set of addresses containing that trigram.
        # This allows us to quickly find candidates that share a given trigram.
        # For example, if "ABC" appears in addresses "addr1" and "addr2", then
        # inverted_index["ABC"] = { "addr1", "addr2" }.
        inverted_index: dict[str, set[str]] = {}
        for addr, tg_dict in precomputed.items():
            for trigram in tg_dict.keys():
                inverted_index.setdefault(trigram, set()).add(addr)

        # Initialize a dictionary to hold neighbor candidate scores for each address.
        # Here, "neighbors" will map an address to a list of (candidate_address, candidate_score) tuples.
        neighbors: dict[str, list[tuple[str, float]]] = {}
        for addr in addresses:
            candidate_scores: dict[str, float] = {}
            # Get the trigram dictionary for the current address.
            # Example: For "addr1", tg_dict might be {"ABC": 5.0, "BCD": 1.0, "CDE": 1.0, "DEF": 5.0}.
            tg_dict = precomputed[addr]
            # Process each trigram of the current address.
            for trigram, weight_a in tg_dict.items():
                # Look up all addresses that also contain this trigram.
                for candidate in inverted_index.get(trigram, set()):
                    if candidate == addr:
                        continue  # Skip comparing the address with itself.
                    # Get the candidate's weight for the same trigram.
                    # Example: For candidate "addr2", if the weight for "ABC" is 5.0 too, then:
                    # min(weight_a, weight_candidate) = min(5.0, 5.0) = 5.0.
                    weight_candidate = precomputed[candidate].get(trigram, 0.0)
                    # Increment the candidate's score by the minimum weight (reflecting the shared feature strength).
                    candidate_scores[candidate] = candidate_scores.get(candidate, 0.0) + min(
                        weight_a, weight_candidate
                    )
            # After processing all trigrams for the current address,
            # filter candidates that have a cumulative score above candidate_threshold.
            # Example: Only if candidate_scores for a candidate is >= candidate_threshold, it is kept.
            neighbors[addr] = [
                (cand, score) for cand, score in candidate_scores.items() if score >= candidate_threshold
            ]
        logger.debug(f"Finished find_neighbors of {len(addresses)} addresses")
        return neighbors

    @classmethod
    def fuzzy_prefix_match(cls, a: str, b: str, rtl: bool = False) -> FuzzyMatch:
        """Performs a fuzzy prefix match between two strings, a and b, allowing one gap
        (i.e. skipping a mismatch once).

        Returns a FuzzyMatch object with:
          - score: the total count of matching characters,
          - matches: a list of tuples; each tuple contains the matching segments extracted from a and b,
          - identical: a boolean indicating whether a and b are identical (after any reversals, if used).

        Example:
          Given a = "abcdef" and b = "abcxef":
            - Characters at positions 0,1,2 match ("abc").
            - At position 3, 'd' vs 'x' do not match, so the algorithm allows one gap.
            - Then positions 4 and 5 match ("ef").
            - The final score would be 3 (for "abc") + 2 (for "ef") = 5.
          The method would return a FuzzyMatch with score=5 and matches=[("abcdef", "abcxef")].
        """
        # Initialize the match score, a flag for whether the gap has been used, and a done flag.
        score: int = 0
        gap: bool = False
        done: bool = False

        # Pointers for iterating over string a and b.
        ai: int = 0
        bi: int = 0

        # These strings will accumulate the matched segments of a and b.
        prefixA: str = ""
        prefixB: str = ""

        # If rtl (right-to-left) is True, reverse the strings.
        # This allows matching starting from the end of the strings.
        if rtl:
            a = a[::-1]
            b = b[::-1]

        # Loop until we reach the end of either string or we decide to stop.
        while ai < len(a) and bi < len(b) and not done:
            # If current characters match, record them and increase the score.
            if a[ai] == b[bi]:
                prefixA += a[ai]
                prefixB += b[bi]
                score += 1
                ai += 1
                bi += 1
            # If current characters differ but we have not yet used our gap allowance:
            elif not gap:
                # Check if by skipping a character in one string we can restore alignment.
                next_match_a: bool = (ai + 1 < len(a)) and (a[ai + 1] == b[bi])
                next_match_b: bool = (bi + 1 < len(b)) and (a[ai] == b[bi + 1])
                next_match_both: bool = (ai + 1 < len(a)) and (bi + 1 < len(b)) and (a[ai + 1] == b[bi + 1])

                # If both strings could realign by skipping one character in each (i.e. both look ahead match),
                # assume a single-character discrepancy and treat the current characters as matched.
                if next_match_both:
                    prefixA += a[ai]
                    prefixB += b[bi]
                    ai += 1
                    bi += 1
                # Else if skipping a character in a realigns the match, then skip in a.
                elif next_match_a:
                    prefixA += a[ai]
                    ai += 1
                # Else if skipping a character in b realigns the match, then skip in b.
                elif next_match_b:
                    prefixB += b[bi]
                    bi += 1
                else:
                    # If no lookahead match is found, skip one character in both.
                    ai += 1
                    bi += 1
                # Mark that the allowed gap has been used.
                gap = True
            else:
                # If a mismatch occurs and we've already used our gap, stop matching.
                done = True

        # If we were matching right-to-left, reverse the matched segments to restore original order.
        if rtl:
            prefixA = prefixA[::-1]
            prefixB = prefixB[::-1]

        # Return a FuzzyMatch instance with the computed score, matched segments, and an identical flag.
        # The identical flag checks if the strings are exactly the same (if reversed, this is after reversal).
        return FuzzyMatch(score=score, matches=[(prefixA, prefixB)], identical=(a == b))

    @classmethod
    def compare_address_info(cls, a: str, b: str) -> FuzzyMatch:
        """Compares two addresses using fuzzy matching. It applies fuzzy_prefix_match in
        both left-to-right and right-to-left directions, subtracts a prefix score (1 for
        base58 addresses; or the length of the HRP for Bech32 addresses),

        and then computes an exponential scaling:
            normalized_score = base ** (left_score + right_score - prefix_score).
        Here, base is 58 for base58 addresses and 32 for Bech32 addresses.
        Returns a float representing the similarity score.
        """
        if a == b:
            return FuzzyMatch(identical=True, score=-1, matches=[(a, b)])

        # Determine address type based on the first address.
        net_a, type_a = cls.detect_network_and_type(a)
        is_base58: bool = type_a in ["p2pkh", "p2sh"]

        a_stripped: str = cls.strip_prefix(a)
        b_stripped: str = cls.strip_prefix(b)
        left = cls.fuzzy_prefix_match(a_stripped, b_stripped, rtl=False)
        right = cls.fuzzy_prefix_match(a_stripped, b_stripped, rtl=True)

        # For base58 addresses, we expect at least 1 matching character; for Bech32, use the HRP length.
        if is_base58:
            prefix_score: int = 1
        else:
            # For example, for a mainnet Bech32 address, the HRP "bc" has length 2.
            hrp: str = a.split("1", 1)[0]
            prefix_score = len(hrp)

        total_score: int = left.score + right.score - prefix_score
        base: int = 58 if is_base58 else 32
        normalized_score: float = base**total_score
        return FuzzyMatch(identical=a == b, score=int(normalized_score), matches=left.matches + right.matches)

    @classmethod
    def compare_all(
        cls,
        addresses: set[str],
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
        candidate_threshold: float = 2.0,
    ) -> dict[tuple[str, str], FuzzyMatch]:
        """Precomputes the trigram dictionaries and uses find_neighbors to restrict the
        full similarity comparisons only to candidate pairs (neighbors). For each
        candidate pair, computes the similarity using compare_address_info.

        Returns a dictionary mapping each candidate pair (an ordered tuple (a, b), where a < b
        lexicographically) to a FuzzyMatch.
        """
        # Use find_neighbors to get candidate addresses.
        neighbor_dict: dict[str, list[tuple[str, float]]] = cls.find_neighbors(
            addresses, n_begin, m_end, weight_begin, weight_end, default_weight, candidate_threshold
        )
        # Use an ordered tuple as key, so that the comparison order is consistent.
        results: dict[tuple[str, str], FuzzyMatch] = {}
        for addr, cand_list in neighbor_dict.items():
            for candidate, _ in cand_list:
                # If the addresses are the same, skip.
                if addr == candidate:
                    continue
                # Create an ordered tuple based on lexicographical order.
                ordered_pair: tuple[str, str] = tuple(sorted([addr, candidate]))  # type: ignore
                if ordered_pair not in results:
                    # Always compare in the same order using compare_address_info.
                    sim = cls.compare_address_info(ordered_pair[0], ordered_pair[1])
                    results[ordered_pair] = sim
        return results

    @classmethod
    def _list_poisonous_pairs(
        cls, results: dict[tuple[str, str], FuzzyMatch]
    ) -> list[tuple[str, str, FuzzyMatch]]:
        """Given a results dictionary (mapping frozenset({address1, address2}) to a
        similarity float), returns a list of tuples (address1, address2, similarity) for
        all pairs whose similarity is greater than or equal to THRESHOLD_POISONOUS."""
        poisonous_pairs: list[tuple[str, str, FuzzyMatch]] = []
        for pair, sim in results.items():
            if sim.score >= cls.ADDRESS_SIMILARITY_THRESHOLD:
                pair_list: list[str] = list(pair)
                if len(pair_list) == 2:
                    poisonous_pairs.append((pair_list[0], pair_list[1], sim))
        return poisonous_pairs

    @classmethod
    def poisonous(
        cls,
        addresses: set[str],
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
        candidate_threshold: float = 2.0,
    ) -> list[tuple[str, str, FuzzyMatch]]:
        """Returns   a list of tuples (address1, address2, similarity) for all pairs
        considered poisonous."""
        result_dict = AddressComparer.compare_all(
            addresses, n_begin, m_end, weight_begin, weight_end, default_weight, candidate_threshold
        )

        return AddressComparer._list_poisonous_pairs(result_dict)

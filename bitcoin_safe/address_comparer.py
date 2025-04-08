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

import logging
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FuzzyMatch:
    identical: bool
    score: int
    matches: List[Tuple[str, str]]


class AddressComparer:
    # The similarity threshold (1 false positive per ~10 million comparisons)
    ADDRESS_SIMILARITY_THRESHOLD = 10_000_000

    @classmethod
    def detect_network_and_type(cls, address: str) -> Tuple[str, str]:
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
        network, addr_type = cls.detect_network_and_type(address)
        if addr_type in ["p2pkh", "p2sh"]:
            return address[1:] if len(address) > 1 else ""
        elif addr_type in ["v0_p2wpkh", "v1_p2tr"]:
            parts: List[str] = address.split("1", 1)
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
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extract overlapping 3-character sequences (trigrams) from the stripped address
        and assign weights. The first n_begin and last m_end trigrams get higher weights.
        """
        s: str = cls.strip_prefix(address)
        chars: np.ndarray = np.array(list(s))
        L: int = len(chars)
        if L < 3:
            return np.empty(0, dtype="<U3"), np.empty(0, dtype=float)
        trigrams: np.ndarray = np.array(["".join(chars[i : i + 3]) for i in range(L - 2)], dtype="<U3")
        weights: np.ndarray = np.full(L - 2, default_weight, dtype=float)
        if n_begin > 0:
            weights[: min(n_begin, L - 2)] = weight_begin
        if m_end > 0:
            weights[-min(m_end, L - 2) :] = weight_end
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
    ) -> Dict[str, float]:
        """
        Builds a dictionary mapping each trigram to its total weight for a given address.
        """
        trigrams, weights = cls.extract_trigrams_numpy(
            address, n_begin, m_end, weight_begin, weight_end, default_weight
        )
        trigram_dict: Dict[str, float] = {}
        for tg, wt in zip(trigrams, weights):
            trigram_dict[tg] = trigram_dict.get(tg, 0.0) + wt
        return trigram_dict

    @classmethod
    def precompute_trigram_dicts(
        cls,
        addresses: Set[str],
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
    ) -> Dict[str, Dict[str, float]]:
        """
        Precomputes the trigram dictionary for each address in the set.
        """
        precomputed: Dict[str, Dict[str, float]] = {}
        for addr in addresses:
            precomputed[addr] = cls.build_trigram_dict(
                addr, n_begin, m_end, weight_begin, weight_end, default_weight
            )
        logger.debug(f"Finished precompute_trigram_dicts of {len(addresses)} addresses")
        return precomputed

    @classmethod
    def find_neighbors(
        cls,
        addresses: Set[str],
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
        candidate_threshold: float = 2.0,
    ) -> Dict[str, List[Tuple[str, float]]]:
        """
        For each address in the given set, finds neighboring addresses that share similar trigrams,
        using an inverted index built from the precomputed trigram dictionaries.

        For each trigram in an address's precomputed dictionary, each candidate address that shares the trigram
        gets its candidate score incremented by min(weight_in_address, weight_in_candidate).
        Only candidates accumulating a total candidate score >= candidate_threshold are returned.

        Returns:
            A dictionary mapping each address to a list of tuples (neighbor_address, candidate_score).
        """
        precomputed: Dict[str, Dict[str, float]] = cls.precompute_trigram_dicts(
            addresses, n_begin, m_end, weight_begin, weight_end, default_weight
        )
        inverted_index: Dict[str, Set[str]] = {}
        for addr, tg_dict in precomputed.items():
            for trigram in tg_dict.keys():
                inverted_index.setdefault(trigram, set()).add(addr)

        neighbors: Dict[str, List[Tuple[str, float]]] = {}
        for addr in addresses:
            candidate_scores: Dict[str, float] = {}
            tg_dict = precomputed[addr]
            for trigram, weight_a in tg_dict.items():
                for candidate in inverted_index.get(trigram, set()):
                    if candidate == addr:
                        continue
                    weight_candidate = precomputed[candidate].get(trigram, 0.0)
                    candidate_scores[candidate] = candidate_scores.get(candidate, 0.0) + min(
                        weight_a, weight_candidate
                    )
            neighbors[addr] = [
                (cand, score) for cand, score in candidate_scores.items() if score >= candidate_threshold
            ]
        logger.debug(f"Finished find_neighbors of {len(addresses)} addresses")
        return neighbors

    @classmethod
    def fuzzy_prefix_match(cls, a: str, b: str, rtl: bool = False) -> FuzzyMatch:
        """
        Performs a fuzzy prefix match between strings a and b, allowing one gap.
        Returns a dict containing:
          - "score": the number of matching characters (int),
          - "matchA": matched segment from a,
          - "matchB": matched segment from b.
        """
        score: int = 0
        gap: bool = False
        done: bool = False
        ai: int = 0
        bi: int = 0
        prefixA: str = ""
        prefixB: str = ""
        if rtl:
            a = a[::-1]
            b = b[::-1]
        while ai < len(a) and bi < len(b) and not done:
            if a[ai] == b[bi]:
                prefixA += a[ai]
                prefixB += b[bi]
                score += 1
                ai += 1
                bi += 1
            elif not gap:
                next_match_a: bool = (ai + 1 < len(a)) and (a[ai + 1] == b[bi])
                next_match_b: bool = (bi + 1 < len(b)) and (a[ai] == b[bi + 1])
                next_match_both: bool = (ai + 1 < len(a)) and (bi + 1 < len(b)) and (a[ai + 1] == b[bi + 1])
                if next_match_both:
                    prefixA += a[ai]
                    prefixB += b[bi]
                    ai += 1
                    bi += 1
                elif next_match_a:
                    prefixA += a[ai]
                    ai += 1
                elif next_match_b:
                    prefixB += b[bi]
                    bi += 1
                else:
                    ai += 1
                    bi += 1
                gap = True
            else:
                done = True
        if rtl:
            prefixA = prefixA[::-1]
            prefixB = prefixB[::-1]
        return FuzzyMatch(score=score, matches=[(prefixA, prefixB)], identical=a == b)

    @classmethod
    def compare_address_info(cls, a: str, b: str) -> FuzzyMatch:
        """
        Compares two addresses using fuzzy matching.
        It applies fuzzy_prefix_match in both left-to-right and right-to-left directions,
        subtracts a prefix score (1 for base58 addresses; or the length of the HRP for Bech32 addresses),
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
        addresses: Set[str],
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
        candidate_threshold: float = 2.0,
    ) -> Dict[FrozenSet[str], FuzzyMatch]:
        """
        Precomputes the trigram dictionaries and uses find_neighbors to restrict full comparisons
        only to candidate pairs (neighbors). For each candidate pair, computes the similarity using
        compare_address_info.

        Returns a dictionary mapping each candidate pair (as a frozenset of two addresses) to a similarity float.
        """
        neighbor_dict: Dict[str, List[Tuple[str, float]]] = cls.find_neighbors(
            addresses, n_begin, m_end, weight_begin, weight_end, default_weight, candidate_threshold
        )
        results: Dict[FrozenSet[str], FuzzyMatch] = {}
        for addr, cand_list in neighbor_dict.items():
            for candidate, _ in cand_list:
                pair = frozenset({addr, candidate})
                if len(pair) <= 1:
                    # do not allow identical ones
                    continue
                if pair not in results:
                    # Use the updated compare_address_info for the candidate pair.
                    sim = cls.compare_address_info(addr, candidate)
                    results[pair] = sim
        return results

    @classmethod
    def _list_poisonous_pairs(
        cls, results: Dict[FrozenSet[str], FuzzyMatch]
    ) -> List[Tuple[str, str, FuzzyMatch]]:
        """
        Given a results dictionary (mapping frozenset({address1, address2}) to a similarity float),
        returns a list of tuples (address1, address2, similarity) for all pairs whose similarity is
        greater than or equal to THRESHOLD_POISONOUS.
        """
        poisonous_pairs: List[Tuple[str, str, FuzzyMatch]] = []
        for pair, sim in results.items():
            if sim.score >= cls.ADDRESS_SIMILARITY_THRESHOLD:
                pair_list: List[str] = list(pair)
                if len(pair_list) == 2:
                    poisonous_pairs.append((pair_list[0], pair_list[1], sim))
        return poisonous_pairs

    @classmethod
    def poisonous(
        cls,
        addresses: Set[str],
        n_begin: int = 3,
        m_end: int = 3,
        weight_begin: float = 5.0,
        weight_end: float = 5.0,
        default_weight: float = 1.0,
        candidate_threshold: float = 2.0,
    ) -> List[Tuple[str, str, FuzzyMatch]]:
        """
        Returns   a list of tuples (address1, address2, similarity) for all pairs considered poisonous
        """
        result_dict = AddressComparer.compare_all(
            addresses, n_begin, m_end, weight_begin, weight_end, default_weight, candidate_threshold
        )

        return AddressComparer._list_poisonous_pairs(result_dict)

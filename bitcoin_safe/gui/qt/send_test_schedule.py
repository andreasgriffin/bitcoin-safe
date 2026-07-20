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

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from bitcoin_safe.keystore import KeyStore


def build_send_test_signer_groups(items: list[str], mn_tuple: tuple[int, int]) -> list[list[str]]:
    """Group ordered signers into send tests using the tutorial overlap rules."""
    m, n = mn_tuple
    groups: list[list[str]] = []
    for i_send_tests in range(ceil(n / m)):
        start_signer = m * i_send_tests
        end_signer = min(m * i_send_tests + m, n)

        missing_signers = m - (end_signer - start_signer)
        start_signer -= missing_signers
        groups.append([items[j] for j in range(start_signer, end_signer)])
    return groups


def build_send_test_fingerprint_groups(
    fingerprints: list[str | None],
    mn_tuple: tuple[int, int],
) -> list[list[str]]:
    """Normalize signer fingerprints and group them by send test."""
    normalized_fingerprints: list[str] = []
    for fingerprint in fingerprints:
        if not fingerprint or not KeyStore.is_fingerprint_valid(fingerprint):
            continue
        normalized_fingerprints.append(KeyStore.format_fingerprint(fingerprint))
    if not normalized_fingerprints:
        return []
    return build_send_test_signer_groups(normalized_fingerprints, (mn_tuple[0], len(normalized_fingerprints)))


@dataclass
class SendTestStepPlan:
    current_group: tuple[str, ...] = ()
    previously_verified: tuple[str, ...] = ()
    required_new_signers: tuple[str, ...] = ()
    preferred_verified_signers: tuple[str, ...] = ()
    fallback_verified_signers: tuple[str, ...] = ()
    verified_candidates: tuple[str, ...] = ()
    overlap_slots_total: int = 0
    future_signers: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_groups(
        cls,
        groups: list[list[str]],
        current_index: int | None,
    ) -> SendTestStepPlan:
        """Build the overlap-aware signing plan for one send test."""
        if current_index is None or not (0 <= current_index < len(groups)):
            return cls()

        current_group = tuple(groups[current_index])
        current_group_set = set(current_group)

        previously_verified: list[str] = []
        seen_previously_verified: set[str] = set()
        for group in groups[:current_index]:
            for signer in group:
                if signer in seen_previously_verified:
                    continue
                seen_previously_verified.add(signer)
                previously_verified.append(signer)

        previously_verified_set = set(previously_verified)
        required_new_signers = tuple(
            signer for signer in current_group if signer not in previously_verified_set
        )
        preferred_verified_signers = tuple(
            signer for signer in current_group if signer in previously_verified_set
        )
        preferred_verified_set = set(preferred_verified_signers)
        fallback_verified_signers = tuple(
            signer for signer in previously_verified if signer not in preferred_verified_set
        )
        overlap_slots_total = len(current_group_set & previously_verified_set)

        future_signers: dict[str, int] = {}
        for index, group in enumerate(groups):
            if index <= current_index:
                continue
            for signer in group:
                future_signers.setdefault(signer, index + 1)

        return cls(
            current_group=current_group,
            previously_verified=tuple(previously_verified),
            required_new_signers=required_new_signers,
            preferred_verified_signers=preferred_verified_signers,
            fallback_verified_signers=fallback_verified_signers,
            verified_candidates=tuple(previously_verified),
            overlap_slots_total=overlap_slots_total,
            future_signers=future_signers,
        )

    def signed_verified_count(self, signed_fingerprints: set[str]) -> int:
        """Return how many verified-candidate slots are already filled in this PSBT."""
        return len(set(self.verified_candidates) & signed_fingerprints)

    def remaining_overlap_slots(self, signed_fingerprints: set[str]) -> int:
        """Return how many overlap slots are still open in this PSBT."""
        return max(0, self.overlap_slots_total - self.signed_verified_count(signed_fingerprints))

    def signer_should_sign_now(self, fingerprint: str, signed_fingerprints: set[str]) -> bool:
        """Return whether this signer should be recommended in the current send test."""
        return fingerprint in self.required_new_signers or (
            fingerprint in self.preferred_verified_signers
            and self.remaining_overlap_slots(signed_fingerprints) > 0
        )

    def verified_candidate_can_sign(self, fingerprint: str, signed_fingerprints: set[str]) -> bool:
        """Return whether this verified signer may still fill an overlap slot."""
        return (
            fingerprint in self.verified_candidates and self.remaining_overlap_slots(signed_fingerprints) > 0
        )

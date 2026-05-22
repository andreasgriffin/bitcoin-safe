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

from bitcoin_safe.gui.qt.send_test_schedule import SendTestStepPlan, build_send_test_signer_groups


def test_build_send_test_signer_groups_1_of_5() -> None:
    assert build_send_test_signer_groups(["A", "B", "C", "D", "E"], (1, 5)) == [
        ["A"],
        ["B"],
        ["C"],
        ["D"],
        ["E"],
    ]


def test_build_send_test_signer_groups_6_of_6() -> None:
    assert build_send_test_signer_groups(["A", "B", "C", "D", "E", "F"], (6, 6)) == [
        ["A", "B", "C", "D", "E", "F"]
    ]


def test_build_send_test_signer_groups_5_of_6() -> None:
    assert build_send_test_signer_groups(["A", "B", "C", "D", "E", "F"], (5, 6)) == [
        ["A", "B", "C", "D", "E"],
        ["B", "C", "D", "E", "F"],
    ]


def test_build_send_test_signer_groups_4_of_6() -> None:
    assert build_send_test_signer_groups(["A", "B", "C", "D", "E", "F"], (4, 6)) == [
        ["A", "B", "C", "D"],
        ["C", "D", "E", "F"],
    ]


def test_send_test_step_plan_1_of_5_has_no_overlap_slots() -> None:
    groups = build_send_test_signer_groups(["A", "B", "C", "D", "E"], (1, 5))

    plan = SendTestStepPlan.from_groups(groups=groups, current_index=1)

    assert plan.current_group == ("B",)
    assert plan.previously_verified == ("A",)
    assert plan.required_new_signers == ("B",)
    assert plan.preferred_verified_signers == ()
    assert plan.fallback_verified_signers == ("A",)
    assert plan.verified_candidates == ("A",)
    assert plan.overlap_slots_total == 0
    assert plan.future_signers == {"C": 3, "D": 4, "E": 5}
    assert plan.remaining_overlap_slots(set()) == 0
    assert plan.signer_should_sign_now("B", signed_fingerprints=set())
    assert not plan.verified_candidate_can_sign("A", signed_fingerprints=set())


def test_send_test_step_plan_6_of_6_requires_all_signers_once() -> None:
    groups = build_send_test_signer_groups(["A", "B", "C", "D", "E", "F"], (6, 6))

    plan = SendTestStepPlan.from_groups(groups=groups, current_index=0)

    assert plan.current_group == ("A", "B", "C", "D", "E", "F")
    assert plan.previously_verified == ()
    assert plan.required_new_signers == ("A", "B", "C", "D", "E", "F")
    assert plan.preferred_verified_signers == ()
    assert plan.fallback_verified_signers == ()
    assert plan.verified_candidates == ()
    assert plan.overlap_slots_total == 0
    assert plan.future_signers == {}
    assert plan.signer_should_sign_now("A", signed_fingerprints=set())


def test_send_test_step_plan_5_of_6_allows_any_previous_signer_until_overlap_is_filled() -> None:
    groups = build_send_test_signer_groups(["A", "B", "C", "D", "E", "F"], (5, 6))

    plan = SendTestStepPlan.from_groups(groups=groups, current_index=1)

    assert plan.current_group == ("B", "C", "D", "E", "F")
    assert plan.previously_verified == ("A", "B", "C", "D", "E")
    assert plan.required_new_signers == ("F",)
    assert plan.preferred_verified_signers == ("B", "C", "D", "E")
    assert plan.fallback_verified_signers == ("A",)
    assert plan.verified_candidates == ("A", "B", "C", "D", "E")
    assert plan.overlap_slots_total == 4
    assert plan.remaining_overlap_slots(set()) == 4
    assert plan.signer_should_sign_now("E", signed_fingerprints=set())
    assert plan.signer_should_sign_now("F", signed_fingerprints=set())
    assert not plan.signer_should_sign_now("A", signed_fingerprints=set())
    assert plan.verified_candidate_can_sign("A", signed_fingerprints=set())
    assert plan.verified_candidate_can_sign("E", signed_fingerprints=set())
    assert not plan.verified_candidate_can_sign("E", signed_fingerprints={"A", "B", "C", "D"})


def test_send_test_step_plan_4_of_6_limits_verified_alternatives_to_two_slots() -> None:
    groups = build_send_test_signer_groups(["A", "B", "C", "D", "E", "F"], (4, 6))

    plan = SendTestStepPlan.from_groups(groups=groups, current_index=1)

    assert plan.current_group == ("C", "D", "E", "F")
    assert plan.previously_verified == ("A", "B", "C", "D")
    assert plan.required_new_signers == ("E", "F")
    assert plan.preferred_verified_signers == ("C", "D")
    assert plan.fallback_verified_signers == ("A", "B")
    assert plan.verified_candidates == ("A", "B", "C", "D")
    assert plan.overlap_slots_total == 2
    assert plan.signer_should_sign_now("C", signed_fingerprints=set())
    assert plan.signer_should_sign_now("F", signed_fingerprints=set())
    assert not plan.signer_should_sign_now("A", signed_fingerprints=set())
    assert plan.verified_candidate_can_sign("A", signed_fingerprints=set())
    assert plan.verified_candidate_can_sign("D", signed_fingerprints={"A"})
    assert not plan.verified_candidate_can_sign("C", signed_fingerprints={"A", "B"})

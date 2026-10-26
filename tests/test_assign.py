"""Unit + property tests for greedy_assign: the contract is one-to-one matching
with every pair under max_dist. The swap-on-crossing behaviour is documented,
not asserted against."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from track import ASSIGNERS, auction_assign, greedy_assign


def test_empty_inputs():
    assert greedy_assign(np.zeros((0, 2)), np.zeros((0, 2)), 10) == []
    assert greedy_assign(np.zeros((0, 2)), np.array([[1.0, 1.0]]), 10) == []
    assert greedy_assign(np.array([[1.0, 1.0]]), np.zeros((0, 2)), 10) == []


def test_exact_match_and_distance_cutoff():
    preds = np.array([[0.0, 0.0], [100.0, 100.0]])
    dets = np.array([[1.0, 0.0], [100.0, 150.0]])
    assert greedy_assign(preds, dets, 5.0) == [(0, 0)]
    assert sorted(greedy_assign(preds, dets, 60.0)) == [(0, 0), (1, 1)]


def test_closest_pair_wins_ties_resolved_once():
    # Two predictions near one detection: only the nearer prediction gets it.
    preds = np.array([[0.0, 0.0], [3.0, 0.0]])
    dets = np.array([[2.0, 0.0]])
    assert greedy_assign(preds, dets, 10.0) == [(1, 0)]


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_nonpositive_or_nan_max_dist_assigns_nothing(bad):
    preds = np.array([[0.0, 0.0]])
    dets = np.array([[0.0, 0.0]])
    assert greedy_assign(preds, dets, bad) == []


def test_nan_and_inf_coordinates_never_match():
    preds = np.array([[np.nan, 0.0], [np.inf, 0.0], [1.0, 1.0]])
    dets = np.array([[0.0, 0.0], [np.nan, np.nan]])
    assert greedy_assign(preds, dets, 1e9) == [(2, 0)]


def test_crossing_swimmers_swap_is_the_documented_weakness():
    # Prediction A heading right is now at 10,0; B heading left is at 12,0.
    # Detections at 11,0 and 11.5,0: greedy pairs by raw distance, not identity.
    preds = np.array([[10.0, 0.0], [12.0, 0.0]])
    dets = np.array([[11.0, 0.0], [11.5, 0.0]])
    pairs = greedy_assign(preds, dets, 5.0)
    assert len(pairs) == 2
    assert len({i for i, _ in pairs}) == 2
    assert len({j for _, j in pairs}) == 2


points = hnp.arrays(
    dtype=np.float64,
    shape=st.tuples(st.integers(0, 12), st.just(2)),
    elements=st.floats(-1e4, 1e4, allow_nan=False, allow_infinity=False),
)


@settings(max_examples=300, deadline=None)
@given(preds=points, dets=points, max_dist=st.floats(1e-3, 1e5))
def test_assignment_is_one_to_one_and_within_max_dist(preds, dets, max_dist):
    pairs = greedy_assign(preds, dets, max_dist)
    assert len({i for i, _ in pairs}) == len(pairs)
    assert len({j for _, j in pairs}) == len(pairs)
    for i, j in pairs:
        assert 0 <= i < len(preds) and 0 <= j < len(dets)
        assert np.linalg.norm(preds[i] - dets[j]) < max_dist


@settings(max_examples=200, deadline=None)
@given(preds=points, dets=points, max_dist=st.floats(1e-3, 1e5))
def test_assignment_is_maximal(preds, dets, max_dist):
    """No unmatched prediction/detection pair is left that could have been matched."""
    pairs = greedy_assign(preds, dets, max_dist)
    used_p = {i for i, _ in pairs}
    used_d = {j for _, j in pairs}
    for i in range(len(preds)):
        if i in used_p:
            continue
        for j in range(len(dets)):
            if j in used_d:
                continue
            assert not (np.linalg.norm(preds[i] - dets[j]) < max_dist), (i, j, pairs)


@settings(max_examples=100, deadline=None)
@given(preds=points, dets=points, max_dist=st.floats(1e-3, 1e5))
def test_assignment_is_deterministic(preds, dets, max_dist):
    assert greedy_assign(preds, dets, max_dist) == greedy_assign(preds, dets, max_dist)


# ---------------------------------------------------------------------------
# auction_assign: same contract, plus a global optimum


def _total_benefit(preds, dets, pairs, max_dist):
    return sum(2 * max_dist - np.linalg.norm(preds[i] - dets[j]) for i, j in pairs)


def _brute_force_best(preds, dets, max_dist):
    """Max total benefit over every one-to-one matching (tiny instances only)."""
    from itertools import permutations

    n, m = len(preds), len(dets)
    best = 0.0
    k = min(n, m)
    rows = range(n)
    for size in range(1, k + 1):
        from itertools import combinations

        for ps in combinations(rows, size):
            for ds in permutations(range(m), size):
                pairs = list(zip(ps, ds, strict=True))
                if all(np.linalg.norm(preds[i] - dets[j]) < max_dist for i, j in pairs):
                    best = max(best, _total_benefit(preds, dets, pairs, max_dist))
    return best


def test_auction_registry_and_empty_inputs():
    assert set(ASSIGNERS) == {"auction", "greedy"}
    assert auction_assign(np.zeros((0, 2)), np.zeros((0, 2)), 10) == []
    assert auction_assign(np.zeros((0, 2)), np.array([[1.0, 1.0]]), 10) == []
    assert auction_assign(np.array([[1.0, 1.0]]), np.zeros((0, 2)), 10) == []


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_auction_rejects_bad_max_dist(bad):
    assert auction_assign(np.array([[0.0, 0.0]]), np.array([[0.0, 0.0]]), bad) == []


def test_auction_nan_and_inf_coordinates_never_match():
    preds = np.array([[np.nan, 0.0], [np.inf, 0.0], [1.0, 1.0]])
    dets = np.array([[0.0, 0.0], [np.nan, np.nan]])
    assert auction_assign(preds, dets, 1e6) == [(2, 0)]


def test_auction_does_not_let_one_track_steal_and_strand_its_neighbour():
    # Greedy grabs the 1 px pair and strands prediction 0 (its only other option is 5 px
    # away, over the gate). The auction takes two 2 px pairs instead.
    preds = np.array([[0.0, 0.0], [3.0, 0.0]])
    dets = np.array([[2.0, 0.0], [5.0, 0.0]])
    assert greedy_assign(preds, dets, 4.0) == [(1, 0)]
    assert sorted(auction_assign(preds, dets, 4.0)) == [(0, 0), (1, 1)]


def test_auction_prefers_the_shorter_total_among_full_matchings():
    preds = np.array([[0.0, 0.0], [10.0, 0.0]])
    dets = np.array([[1.0, 0.0], [9.0, 0.0]])
    assert sorted(auction_assign(preds, dets, 50.0)) == [(0, 0), (1, 1)]
    # mirror: the crossing case greedy would get wrong only if raw distance misleads it
    preds = np.array([[0.0, 0.0], [4.0, 0.0], [8.0, 0.0]])
    dets = np.array([[3.0, 0.0], [5.0, 0.0], [12.0, 0.0]])
    # greedy: (1,0) at 1 px, (2,2) at 4 px, then pred 0 has only d1 at 5 px > gate: stranded
    assert len(greedy_assign(preds, dets, 4.5)) == 2
    assert sorted(auction_assign(preds, dets, 4.5)) == [(0, 0), (1, 1), (2, 2)]


small = hnp.arrays(
    dtype=np.float64,
    shape=st.tuples(st.integers(0, 5), st.just(2)),
    elements=st.floats(-100, 100, allow_nan=False, allow_infinity=False),
)


@settings(max_examples=150, deadline=None)
@given(preds=small, dets=small, max_dist=st.floats(0.5, 300))
def test_auction_is_within_eps_of_the_brute_force_optimum(preds, dets, max_dist):
    pairs = auction_assign(preds, dets, max_dist)
    assert len({i for i, _ in pairs}) == len(pairs) == len({j for _, j in pairs})
    for i, j in pairs:
        assert np.linalg.norm(preds[i] - dets[j]) < max_dist
    got = _total_benefit(preds, dets, pairs, max_dist)
    best = _brute_force_best(preds, dets, max_dist)
    slack = len(preds) * max_dist / 256 + 1e-9
    assert got >= best - slack, (got, best, pairs)


@settings(max_examples=200, deadline=None)
@given(preds=points, dets=points, max_dist=st.floats(1e-3, 1e5))
def test_auction_is_one_to_one_gated_maximal_and_deterministic(preds, dets, max_dist):
    pairs = auction_assign(preds, dets, max_dist)
    assert pairs == auction_assign(preds, dets, max_dist)
    assert len({i for i, _ in pairs}) == len(pairs) == len({j for _, j in pairs})
    used_p = {i for i, _ in pairs}
    used_d = {j for _, j in pairs}
    for i, j in pairs:
        assert np.linalg.norm(preds[i] - dets[j]) < max_dist
    for i in range(len(preds)):
        for j in range(len(dets)):
            if i not in used_p and j not in used_d:
                assert not (np.linalg.norm(preds[i] - dets[j]) < max_dist), (i, j, pairs)


@pytest.mark.parametrize("assign", [greedy_assign, auction_assign])
def test_feasible_mask_forbids_pairs_and_alt_anchor_rescues_them(assign):
    preds = np.array([[0.0, 0.0], [50.0, 0.0]])
    dets = np.array([[1.0, 0.0], [51.0, 0.0]])
    assert sorted(assign(preds, dets, 10.0)) == [(0, 0), (1, 1)]
    feasible = np.array([[False, True], [True, True]])
    assert assign(preds, dets, 10.0, feasible) == [(1, 1)]
    # prediction ran off to 100,0 but the last measured position (alt) is at 2,0
    far = np.array([[100.0, 0.0], [50.0, 0.0]])
    assert assign(far, dets, 10.0) == [(1, 1)]
    alt = np.array([[2.0, 0.0], [50.0, 0.0]])
    assert sorted(assign(far, dets, 10.0, None, alt)) == [(0, 0), (1, 1)]


def test_auction_handles_a_crowd_quickly():
    rng = np.random.default_rng(0)
    preds = rng.uniform(0, 1000, (150, 2))
    dets = preds + rng.normal(0, 3, preds.shape)
    dets = np.concatenate([dets, rng.uniform(0, 1000, (60, 2))])
    import time

    t0 = time.perf_counter()
    pairs = auction_assign(preds, dets, 40.0)
    dt = time.perf_counter() - t0
    assert len(pairs) == 150 and all(i == j for i, j in pairs), pairs[:5]
    assert dt < 1.0, dt

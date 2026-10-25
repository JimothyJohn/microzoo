"""Unit + property tests for greedy_assign: the contract is one-to-one matching
with every pair under max_dist. The swap-on-crossing behaviour is documented,
not asserted against."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from track import greedy_assign


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

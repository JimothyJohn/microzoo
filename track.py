#!/usr/bin/env python3
"""track.py: v1 multi-target tracker for darkfield pond footage.

Pipeline: background subtraction -> morphology -> contours -> per-track
constant-velocity Kalman -> global assignment (pure-numpy auction; --assign
greedy for the old nearest-neighbour matching).

Background: --bg mog2 (default) or --bg hold. MOG2 forgets a swimmer that stops
within seconds; hold seeds from a median, never learns under a track that has
proven it moves, and relearns fast after a focus jump. On real brightfield
footage (a rotifer pausing in debris) hold keeps one ID where MOG2 makes five.

Two passes over the video. Pass 1 builds tracks (optionally on a downscaled
frame, --scale). Pass 2 re-reads the full-resolution video and writes:

    <stem>_tracks.mp4         boxes, IDs and trails for every confirmed track
    <stem>_tracks.csv         frame, t, track_id, x, y, area, w, h (full-res px)
    <stem>_follow_<id>.mp4    fixed-size crop riding the chosen track
    <stem>_tracks.json        parameters, video metadata, per-track summary,
                              plus <stem>.json (the clip sidecar) if present

Runtime deps: numpy, opencv (headless). No scipy, so the Pi can run it.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

__all__ = [
    "DEFAULT_THRESH",
    "Detection",
    "HoldBackground",
    "Track",
    "Tracker",
    "ASSIGNERS",
    "auction_assign",
    "detect",
    "greedy_assign",
    "run",
    "main",
    "travel",
]

# Squared-sigma foreground threshold per background model: MOG2's varThreshold,
# and for hold |frame - bg|^2 > thresh * var (3 sigma; its variance is per pixel
# and includes edge jitter, so open water can carry a low bar). On compression-
# smoothed footage (phone or YouTube H.264) --thresh 36 cuts more debris-mat tracks.
DEFAULT_THRESH = {"mog2": 16.0, "hold": 9.0}


@dataclass(frozen=True)
class Detection:
    """One blob in one frame. Coordinates are full-resolution pixels."""

    x: float
    y: float
    area: float
    w: int
    h: int


@dataclass
class Track:
    id: int
    first_frame: int
    last_frame: int
    kf: cv2.KalmanFilter = field(repr=False)
    missed: int = 0
    # (frame, x, y, area, w, h) for every frame with a measurement. While the
    # track shares one blob with another (``merged``), x, y are its own
    # extrapolated position and area, w, h are the shared blob's.
    points: list[tuple[int, float, float, float, int, int]] = field(default_factory=list)
    merged: bool = False
    group: int = 0  # which merge group, while merged
    own_area: float = 0.0  # last area measured before the merge
    own_extent: float = 0.0  # max(w, h) before the merge

    @property
    def hits(self) -> int:
        return len(self.points)

    @property
    def life(self) -> int:
        """Frames spanned, inclusive."""
        return self.last_frame - self.first_frame + 1

    def predicted_xy(self) -> tuple[float, float]:
        s = self.kf.statePre if self.missed else self.kf.statePost
        return float(s[0, 0]), float(s[1, 0])


def _make_kalman(x: float, y: float, process_noise: float, measurement_noise: float):
    kf = cv2.KalmanFilter(4, 2, 0, cv2.CV_32F)
    kf.transitionMatrix = np.array(
        [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float32
    )
    kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
    kf.processNoiseCov = np.eye(4, dtype=np.float32) * process_noise
    kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * measurement_noise
    kf.errorCovPost = np.eye(4, dtype=np.float32)
    kf.statePost = np.array([[x], [y], [0.0], [0.0]], dtype=np.float32)
    kf.statePre = kf.statePost.copy()
    return kf


def detect(
    mask: np.ndarray, min_area: float, max_area: float, inv_scale: float = 1.0
) -> list[Detection]:
    """Blobs in a binary foreground mask, mapped back to full-res coordinates.

    ``min_area``/``max_area`` are in full-res px^2. ``inv_scale`` is 1/scale of
    the mask relative to the full frame.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[Detection] = []
    area_scale = inv_scale * inv_scale
    for c in contours:
        area = float(cv2.contourArea(c)) * area_scale
        if area < min_area or area > max_area:
            continue
        m = cv2.moments(c)
        if m["m00"] <= 0:
            continue
        cx = m["m10"] / m["m00"] * inv_scale
        cy = m["m01"] / m["m00"] * inv_scale
        _, _, w, h = cv2.boundingRect(c)
        out.append(
            Detection(
                x=cx,
                y=cy,
                area=area,
                w=max(1, int(round(w * inv_scale))),
                h=max(1, int(round(h * inv_scale))),
            )
        )
    return out


def travel(points: list[tuple], n: int = 10) -> float:
    """How far a track has really gone: median of its first ``n`` positions to
    median of its last ``n``. A fragment's centroid can jump 25 px between frames
    without the body moving; a median over ten frames does not. 0 until ``n`` points."""
    if len(points) < n:
        return 0.0
    head = np.median(np.array([p[1:3] for p in points[:n]], dtype=np.float64), axis=0)
    tail = np.median(np.array([p[1:3] for p in points[-n:]], dtype=np.float64), axis=0)
    return float(np.hypot(*(tail - head)))


class HoldBackground:
    """Running-average background that does not forget a swimmer that stops.

    MOG2 learns every pixel at 1/min(frame, history): a rotifer that pauses is
    background within ~25 frames early in a clip, and its ghost and its fresh body
    become two new tracks when it swims off. Here the background is seeded from the
    median of the first ``seed_frames`` frames (anything that moves meanwhile is voted
    out) and then learns everywhere *except* under tracks that have proven they move
    (``travel`` >= ``hold_px``, ever). A swimmer that pauses keeps its hold; debris
    that never moved is relearned. Foreground is |frame - bg|^2 > ``thresh`` * var,
    and var is per pixel: the sensor noise measured over the seed, plus
    (|grad bg| * ``edge_px``)^2. The second term is what an edge does under a
    sub-pixel shift or focus breathing; without it a debris edge needs a 6-sigma bar
    that also hides a defocused Paramecium. A jump in frame sharpness (focus, Z step)
    relearns everything not held, fast, for a few frames.

    Blind spot, by construction: an animal that never moves its own length (an
    anchored Stentor) is background from the seed on. That needs appearance, not motion.
    """

    def __init__(
        self,
        seed_frames: int = 60,
        thresh: float = 9.0,
        floor: float = 12.0,
        alpha: float = 0.01,
        alpha_still: float = 0.03,
        hold_px: float = 20.0,
        focus_jump: float = 0.15,
        boost_alpha: float = 0.1,
        boost_frames: int = 10,
        edge_px: float = 2.0,
    ):
        if seed_frames < 1:
            raise ValueError("seed_frames must be >= 1")
        self.seed_frames = seed_frames
        self.thresh = thresh
        self.floor = floor  # grey levels; below this nothing is foreground
        self.alpha = alpha  # learning rate of open background
        self.alpha_still = alpha_still  # under foreground no moving track claims
        self.hold_px = hold_px
        self.focus_jump = focus_jump
        self.boost_alpha = boost_alpha
        self.boost_frames = boost_frames
        self.edge_px = edge_px
        self.bg: np.ndarray | None = None
        self.var: np.ndarray | None = None
        self._seed: list[np.ndarray] = []
        self._sharp: list[float] = []
        self._boost = 0
        self._proven: set[int] = set()

    @property
    def ready(self) -> bool:
        return self.bg is not None

    def add_seed(self, gray: np.ndarray) -> bool:
        """Buffer one seed frame; True once the background is built from them."""
        self._seed.append(gray)
        if len(self._seed) >= self.seed_frames:
            self.build()
        return self.ready

    def build(self) -> None:
        """Build the background from whatever seed frames there are (a short clip ends early)."""
        if not self._seed:
            raise ValueError("no seed frames")
        st = np.stack(self._seed).astype(np.float32)
        self.bg = np.median(st, axis=0).astype(np.float32)
        # robust per-pixel sigma (MAD) over the seed, at least one grey level
        mad = np.median(np.abs(st - self.bg), axis=0)
        self.var = np.maximum((1.4826 * mad) ** 2, 1.0).astype(np.float32)
        self._seed = []

    def _model(self, gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.bg is None or self.var is None:
            raise RuntimeError("background not built yet: add_seed() or build() first")
        if gray.shape != self.bg.shape:
            raise ValueError(f"frame {gray.shape} does not match background {self.bg.shape}")
        return self.bg, self.var

    def foreground(self, gray: np.ndarray) -> np.ndarray:
        bg, var = self._model(gray)
        d = gray.astype(np.float32) - bg
        d2 = d * d
        if self.edge_px > 0:
            # grey levels per px of background slope (Sobel's 3x3 kernel sums to 8)
            gx = cv2.Sobel(bg, cv2.CV_32F, 1, 0, ksize=3) / 8.0
            gy = cv2.Sobel(bg, cv2.CV_32F, 0, 1, ksize=3) / 8.0
            var = var + (gx * gx + gy * gy) * (self.edge_px * self.edge_px)
        fg = (d2 > self.thresh * var) & (d2 > self.floor * self.floor)
        return fg.astype(np.uint8) * 255

    def holding(self, live: list[Track]) -> set[int]:
        """Ids of live tracks that have proven they move. Once proven, always: a swimmer
        that comes back to where it was born keeps its hold."""
        for t in live:
            if t.id not in self._proven and travel(t.points) >= self.hold_px:
                self._proven.add(t.id)
        return {t.id for t in live if t.id in self._proven}

    def learn(
        self, gray: np.ndarray, fg: np.ndarray, live: list[Track], frame_idx: int, scale: float
    ) -> None:
        """Update the background after this frame's tracker step. ``live`` positions are
        full-res; ``scale`` maps them onto ``gray``."""
        bg, var = self._model(gray)
        g = gray.astype(np.float32)
        sharp = float(cv2.Laplacian(g, cv2.CV_32F).var())
        if len(self._sharp) >= 10:
            ref = float(np.median(self._sharp[-30:]))
            if abs(sharp - ref) > self.focus_jump * ref:
                self._boost = self.boost_frames
        self._sharp.append(sharp)

        held = self.holding(live)
        hold = np.zeros(g.shape, np.uint8)
        for t in live:
            f, x, y, _area, w, h = t.points[-1]
            if t.id not in held or f != frame_idx:
                continue
            hw, hh = w * scale / 2 + 6, h * scale / 2 + 6
            sx, sy = x * scale, y * scale
            cv2.rectangle(hold, (int(sx - hw), int(sy - hh)), (int(sx + hw), int(sy + hh)), 255, -1)
        base = self.boost_alpha if self._boost > 0 else self.alpha
        self._boost = max(0, self._boost - 1)
        rate = np.full(g.shape, base, np.float32)
        on = fg > 0
        rate[on] = max(base, self.alpha_still)
        # The whole held box is frozen, not just its foreground: a focus jump that dims
        # the animal drops its rim under threshold, and a rim that learns at the boost
        # rate shrinks the blob, then the box, until the body is gone (water flea clip).
        rate[hold > 0] = 0.0
        d = g - bg
        # The variance learns wherever the mean does, foreground included: that is how a
        # flickering debris edge raises its own bar. Gating it to background pixels was
        # tried and tripled the debris tracks on real brightfield footage.
        var += rate * (d * d - var)
        np.maximum(var, 1.0, out=var)
        bg += rate * d


def _distances(
    preds: np.ndarray,
    dets: np.ndarray,
    feasible: np.ndarray | None,
    alt: np.ndarray | None,
) -> np.ndarray:
    """(N, M) distances; the smaller of prediction->det and ``alt``->det when
    ``alt`` (N, 2, e.g. last measured positions) is given; inf where forbidden."""
    d = np.linalg.norm(preds[:, None, :] - dets[None, :, :], axis=2)
    if alt is not None:
        alt = np.asarray(alt, dtype=np.float64).reshape(-1, 2)
        d = np.fmin(d, np.linalg.norm(alt[:, None, :] - dets[None, :, :], axis=2))
    d = np.where(np.isfinite(d), d, np.inf)
    if feasible is not None:
        d = np.where(np.asarray(feasible, dtype=bool).reshape(d.shape), d, np.inf)
    return d


def greedy_assign(
    preds: np.ndarray,
    dets: np.ndarray,
    max_dist: float,
    feasible: np.ndarray | None = None,
    alt: np.ndarray | None = None,
) -> list[tuple[int, int]]:
    """Greedy nearest-neighbour matching.

    ``preds`` is (N, 2), ``dets`` is (M, 2). Returns (pred_index, det_index)
    pairs, each index used at most once, every pair closer than ``max_dist``.
    ``feasible`` (N, M) bool forbids pairs outright (the size gate); ``alt``
    (N, 2) gives each prediction a second anchor, the last measured position,
    so a swimmer that reverses stays within reach while the velocity catches up.
    Pairs are taken in increasing distance order, which is what makes one
    prediction steal its neighbour's detection; ``auction_assign`` fixes that.
    """
    preds = np.asarray(preds, dtype=np.float64).reshape(-1, 2)
    dets = np.asarray(dets, dtype=np.float64).reshape(-1, 2)
    if preds.shape[0] == 0 or dets.shape[0] == 0 or not max_dist > 0:
        return []
    d = _distances(preds, dets, feasible, alt)
    order = np.argsort(d, axis=None, kind="stable")
    used_p = np.zeros(preds.shape[0], dtype=bool)
    used_d = np.zeros(dets.shape[0], dtype=bool)
    pairs: list[tuple[int, int]] = []
    n_d = dets.shape[0]
    for flat in order:
        dist = d.flat[flat]
        if not dist < max_dist:
            break
        i, j = divmod(int(flat), n_d)
        if used_p[i] or used_d[j]:
            continue
        used_p[i] = used_d[j] = True
        pairs.append((i, j))
        if used_p.all() or used_d.all():
            break
    return pairs


def auction_assign(
    preds: np.ndarray,
    dets: np.ndarray,
    max_dist: float,
    feasible: np.ndarray | None = None,
    alt: np.ndarray | None = None,
) -> list[tuple[int, int]]:
    """Global one-to-one matching by Bertsekas' auction algorithm, pure numpy.

    Same contract as ``greedy_assign`` (pairs under ``max_dist`` and allowed by
    ``feasible``, each index once) but it maximises the *total* benefit, where a pair is worth
    ``2*max_dist - distance``: at least ``max_dist``, so a matching with one
    more pair always beats a shorter one, and among equal-length matchings the
    shortest total distance wins. That is what keeps a prediction from stealing
    its neighbour's detection and leaving the neighbour unmatched.

    Tracks bid for detections; a detection goes to the highest bidder and its
    price rises by at least ``eps = max_dist / 256``; a track whose best value
    drops below zero stays unmatched for good (prices only rise). The result is
    within ``n * eps`` of optimal, which keeps the cardinality argument above
    intact for up to 256 tracks. Deterministic. No eps-scaling: the usual
    scaled variant clears assignments between phases, which with an "unmatched"
    option worth 0 leaves every bidder priced out of the second phase.
    """
    preds = np.asarray(preds, dtype=np.float64).reshape(-1, 2)
    dets = np.asarray(dets, dtype=np.float64).reshape(-1, 2)
    n, m = preds.shape[0], dets.shape[0]
    if n == 0 or m == 0 or not max_dist > 0 or not np.isfinite(max_dist):
        return []
    d = _distances(preds, dets, feasible, alt)
    benefit = np.where(d < max_dist, 2.0 * max_dist - d, -np.inf)
    bidders = [i for i in range(n) if np.isfinite(benefit[i]).any()]
    price = np.zeros(m)
    owner = np.full(m, -1)
    assigned = np.full(n, -1)
    eps = max_dist / 256
    queue = bidders
    while queue:
        i = queue.pop()
        value = benefit[i] - price
        j = int(np.argmax(value))
        best = float(value[j])
        if not best > 0:  # staying unmatched (worth 0) beats every detection now
            continue
        value[j] = -np.inf
        second = max(float(value.max()), 0.0)
        price[j] += best - second + eps
        if owner[j] >= 0:
            assigned[owner[j]] = -1
            queue.append(int(owner[j]))
        owner[j] = i
        assigned[i] = j
    return [(i, int(j)) for i, j in enumerate(assigned) if j >= 0]


ASSIGNERS = {"auction": auction_assign, "greedy": greedy_assign}


class Tracker:
    """Owns the live tracks; call ``step`` once per frame in order."""

    def __init__(
        self,
        max_dist: float,
        max_missed: int,
        birth_dist: float | None = None,
        process_noise: float = 1e-2,
        measurement_noise: float = 1.0,
        assign: str = "auction",
        fragment_scale: float = 0.6,
        area_ratio: float = 6.0,
        anchor_last: bool = True,
        merge_ratio: float = 1.5,
    ):
        # A matched blob at least this many times its track's own area, with another
        # track's prediction inside it, is two bodies overlapping (0 disables).
        self.merge_ratio = merge_ratio
        # Gate on the nearer of the Kalman prediction and the last measured position.
        # A Paramecium's avoiding reaction reverses it in one frame; the constant-
        # velocity prediction keeps going and would be out of reach three frames later.
        self.anchor_last = anchor_last
        # A track and a detection may only pair if their areas are within this
        # factor of each other (0 disables). Fragments of one body stay within it;
        # a debris speck and a Paramecium do not.
        self.area_ratio = area_ratio
        if assign not in ASSIGNERS:
            raise ValueError(f"assign must be one of {sorted(ASSIGNERS)}, got {assign!r}")
        self._assign = ASSIGNERS[assign]
        # Birth suppression also scales with the blob: a 50 px body whose dim interior
        # splits the mask sheds fragments 25 px from its centre, well past birth_dist.
        self.fragment_scale = fragment_scale
        self.max_dist = max_dist
        self.max_missed = max_missed
        # An unmatched detection closer than this to any live track's prediction
        # is a fragment of that track's blob (MOG2 splits slow swimmers), not a
        # new organism. Without this the fragment spawns a track that out-competes
        # and kills the established one on the next frame.
        self.birth_dist = max_dist / 2 if birth_dist is None else birth_dist
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
        self.live: list[Track] = []
        self.dead: list[Track] = []
        self._next_id = 1
        self._next_group = 0

    @staticmethod
    def _inside(d: Detection, xy: np.ndarray, pad: float) -> bool:
        """Is ``xy`` inside detection ``d``'s box grown by ``pad`` on every side?"""
        return bool(abs(xy[0] - d.x) <= d.w / 2 + pad and abs(xy[1] - d.y) <= d.h / 2 + pad)

    def _coast(self, t: Track, xy: np.ndarray, d: Detection, frame_idx: int) -> None:
        """Advance a merged track on its own prediction; record the shared blob."""
        t.missed = 0
        t.last_frame = frame_idx
        t.points.append((frame_idx, float(xy[0]), float(xy[1]), d.area, d.w, d.h))

    def _measure(self, t: Track, d: Detection, frame_idx: int) -> None:
        t.kf.correct(np.array([[d.x], [d.y]], dtype=np.float32))
        t.missed = 0
        t.last_frame = frame_idx
        t.points.append((frame_idx, d.x, d.y, d.area, d.w, d.h))

    def step(self, frame_idx: int, dets: list[Detection]) -> None:
        for t in self.live:
            t.kf.predict()
        live = self.live
        preds = np.array([t.predicted_xy() for t in live], dtype=np.float64).reshape(-1, 2)
        # each live track's last blob extent: a body that splits sheds fragments this far out
        extent = np.array(
            [t.own_extent if t.merged else max(t.points[-1][4], t.points[-1][5]) for t in live],
            dtype=np.float64,
        )
        last_area = np.array(
            [t.own_area if t.merged else t.points[-1][3] for t in live], dtype=np.float64
        )
        # last measured position: the second anchor for gating (reversals). A merged
        # track has no measurement of its own; its anchor is the extrapolation.
        last_xy = np.array(
            [preds[i] if t.merged else t.points[-1][1:3] for i, t in enumerate(live)],
            dtype=np.float64,
        ).reshape(-1, 2)
        pts = np.array([(d.x, d.y) for d in dets], dtype=np.float64).reshape(-1, 2)
        feasible = None
        if self.area_ratio > 0 and preds.shape[0] and pts.shape[0]:
            # a 9 px debris speck may not claim a 60 px body that swam past it
            now = np.array([d.area for d in dets], dtype=np.float64)
            ratio = np.maximum(last_area[:, None] / now[None, :], now[None, :] / last_area[:, None])
            feasible = ratio <= self.area_ratio
        pairs = self._assign(
            preds, pts, self.max_dist, feasible, last_xy if self.anchor_last else None
        )
        owner = {j: i for i, j in pairs}
        matched_t = set(owner.values())
        matched_d = set(owner)

        # Two bodies overlapping read as one blob. When a matched blob has grown past
        # merge_ratio times its track's own area and an unmatched track's prediction
        # falls inside it, both tracks enter the blob: neither is corrected with the
        # shared centroid, both carry their velocity through, and at the split the
        # assignment above (anchored on the extrapolations) hands each its own body.
        if self.merge_ratio > 0:
            for j, i in owner.items():
                d = dets[j]
                if live[i].merged or d.area < self.merge_ratio * last_area[i]:
                    continue
                joiners = [
                    k
                    for k, t in enumerate(live)
                    if k not in matched_t
                    and not t.merged
                    and self._inside(d, preds[k], extent[k] / 2)
                ]
                if not joiners:
                    continue
                self._next_group += 1
                for k in (i, *joiners):
                    t = live[k]
                    t.merged, t.group = True, self._next_group
                    t.own_area, t.own_extent = last_area[k], extent[k]

        # Resolve every group: it holds together while exactly one blob, big enough to
        # be both bodies, is where the members are (matched by a member, or holding a
        # member's extrapolation). Membership does not depend on where the extrapolation
        # drifts meanwhile; it ends only when the shared blob splits or shrinks.
        coast: dict[int, Detection] = {}
        groups: dict[int, list[int]] = {}
        for i, t in enumerate(live):
            if t.merged:
                groups.setdefault(t.group, []).append(i)
        for members in groups.values():
            blobs = {
                owner_j
                for owner_j in (self._det_of(i, owner) for i in members)
                if owner_j is not None
            }
            for j in range(len(dets)):
                if j in matched_d or j in blobs:
                    continue
                if any(self._inside(dets[j], preds[i], extent[i] / 2) for i in members):
                    blobs.add(j)
            floor = self.merge_ratio * min(live[i].own_area for i in members)
            if len(blobs) == 1 and dets[next(iter(blobs))].area >= floor > 0:
                for i in members:
                    coast[i] = dets[next(iter(blobs))]
            else:
                for i in members:
                    live[i].merged = False

        still_live: list[Track] = []
        for i, t in enumerate(live):
            if i in coast:
                self._coast(t, preds[i], coast[i], frame_idx)
                still_live.append(t)
                continue
            j = self._det_of(i, owner)
            if j is not None:
                self._measure(t, dets[j], frame_idx)
                still_live.append(t)
                continue
            t.missed += 1
            if t.missed > self.max_missed:
                self.dead.append(t)
            else:
                still_live.append(t)
        self.live = still_live

        for j, d in enumerate(dets):
            if j in matched_d:
                continue
            if preds.shape[0] and self.birth_dist > 0:
                dist = np.linalg.norm(preds - pts[j], axis=1)
                if self.anchor_last:
                    dist = np.fmin(dist, np.linalg.norm(last_xy - pts[j], axis=1))
                thr = np.maximum(self.birth_dist, self.fragment_scale * extent)
                if (dist < thr).any():
                    continue
            kf = _make_kalman(d.x, d.y, self.process_noise, self.measurement_noise)
            t = Track(id=self._next_id, first_frame=frame_idx, last_frame=frame_idx, kf=kf)
            t.points.append((frame_idx, d.x, d.y, d.area, d.w, d.h))
            self._next_id += 1
            self.live.append(t)

    @staticmethod
    def _det_of(i: int, owner: dict[int, int]) -> int | None:
        for j, k in owner.items():
            if k == i:
                return j
        return None

    def all_tracks(self) -> list[Track]:
        return sorted(self.dead + self.live, key=lambda t: t.id)


# ----------------------------------------------------------------------------
# Video I/O helpers


class VideoError(RuntimeError):
    pass


def _open(path: Path) -> tuple[cv2.VideoCapture, int, int, float, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise VideoError(f"cannot open video: {path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if w <= 0 or h <= 0:
        cap.release()
        raise VideoError(f"video reports no frame size: {path}")
    return cap, w, h, fps, n


def _writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    fourcc = cv2.VideoWriter.fourcc(*"mp4v")
    wr = cv2.VideoWriter(str(path), fourcc, fps if fps > 0 else 30.0, size)
    if not wr.isOpened():
        raise VideoError(f"cannot open writer: {path}")
    return wr


def _color(track_id: int, bright_background: bool = False) -> tuple[int, int, int]:
    """Stable per-id hue. Full value on a dark field; darker on a bright one so the
    overlay stays legible on backlit (brightfield) footage."""
    rng = np.random.default_rng(track_id)
    value = 150 if bright_background else 255
    hsv = np.array([[[int(rng.integers(0, 180)), 220, value]]], dtype=np.uint8)
    b, g, r = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


def _follow_path(track: Track, alpha: float) -> dict[int, tuple[float, float]]:
    """Per-frame crop centre for a track: linear interpolation across missed
    frames, then an exponential moving average so the window doesn't jitter."""
    frames = np.array([p[0] for p in track.points])
    xs = np.array([p[1] for p in track.points])
    ys = np.array([p[2] for p in track.points])
    all_frames = np.arange(track.first_frame, track.last_frame + 1)
    xi = np.interp(all_frames, frames, xs)
    yi = np.interp(all_frames, frames, ys)
    out: dict[int, tuple[float, float]] = {}
    sx, sy = xi[0], yi[0]
    for f, x, y in zip(all_frames, xi, yi, strict=True):
        sx += alpha * (x - sx)
        sy += alpha * (y - sy)
        out[int(f)] = (float(sx), float(sy))
    return out


def _crop(frame: np.ndarray, cx: float, cy: float, size: int) -> np.ndarray:
    h, w = frame.shape[:2]
    half = size // 2
    x0 = int(round(cx)) - half
    y0 = int(round(cy)) - half
    x0 = min(max(x0, 0), max(w - size, 0))
    y0 = min(max(y0, 0), max(h - size, 0))
    crop = frame[y0 : y0 + size, x0 : x0 + size]
    if crop.shape[0] != size or crop.shape[1] != size:
        # Frame smaller than the window: pad with black.
        pad = np.zeros((size, size, 3), dtype=frame.dtype)
        pad[: crop.shape[0], : crop.shape[1]] = crop
        crop = pad
    return crop


# ----------------------------------------------------------------------------
# Main pipeline


def _pass1(args: argparse.Namespace, path: Path) -> tuple[Tracker, dict]:
    cap, w, h, fps, n_reported = _open(path)
    scale = args.scale
    inv = 1.0 / scale
    frame_area = w * h
    max_area = args.max_area if args.max_area is not None else 0.05 * frame_area
    thresh = args.thresh if args.thresh is not None else DEFAULT_THRESH[args.bg]
    mog = None
    hold = None
    if args.bg == "hold":
        hold = HoldBackground(
            seed_frames=args.bg_seed, thresh=thresh, hold_px=args.hold_px, edge_px=args.hold_edge
        )
    else:
        mog = cv2.createBackgroundSubtractorMOG2(
            history=args.history, varThreshold=thresh, detectShadows=False
        )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    tracker = Tracker(
        max_dist=args.max_dist,
        max_missed=args.max_missed,
        birth_dist=args.birth_dist,
        assign=args.assign,
        fragment_scale=args.fragment_scale,
        area_ratio=args.area_ratio,
        process_noise=args.process_noise,
        anchor_last=not args.no_anchor_last,
        merge_ratio=args.merge_ratio,
    )

    def process(i: int, gray: np.ndarray, learn: bool) -> None:
        if mog is not None:
            fg = mog.apply(gray)
            if i < args.warmup:
                tracker.step(i, [])
                return
        else:
            assert hold is not None
            fg = hold.foreground(gray)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
        tracker.step(i, detect(fg, args.min_area, max_area, inv))
        if hold is not None and learn:
            hold.learn(gray, fg, tracker.live, i, scale)

    def replay(frames: list[np.ndarray], first: int) -> None:
        # The seed window is tracked too, once the background exists: detection
        # starts at frame 0, not at --bg-seed. Live, that is a seed-length delay.
        for j, g in enumerate(frames):
            process(first + j, g, learn=False)

    idx = 0
    t0 = time.monotonic()
    median_gray = 0.0
    pending: list[np.ndarray] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = (
            frame
            if scale == 1.0
            else cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        )
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if idx == 0:
            # Polarity of the illumination. The background models do not care
            # (foreground is any deviation from the background); the overlay colours do.
            median_gray = float(np.median(gray))
        if hold is not None and not hold.ready:
            pending.append(gray)
            if hold.add_seed(gray):
                replay(pending, idx - len(pending) + 1)
                pending = []
        else:
            process(idx, gray, learn=True)
        idx += 1
    cap.release()
    if hold is not None and pending:
        hold.build()
        replay(pending, idx - len(pending))
    if idx == 0:
        raise VideoError(f"video has no decodable frames: {path}")
    meta = {
        "width": w,
        "height": h,
        "fps": fps,
        "frames": idx,
        "frames_reported": n_reported,
        "median_gray": median_gray,
        "background": "bright" if median_gray > 127 else "dark",
        "pass1_seconds": round(time.monotonic() - t0, 3),
        "max_area": max_area,
        "bg": args.bg,
        "thresh": thresh,
    }
    return tracker, meta


def _pass2(
    args: argparse.Namespace,
    path: Path,
    stem: Path,
    tracks: list[Track],
    follow: Track | None,
    meta: dict,
) -> dict[str, str]:
    """Render overlay video and follow clip. Returns {kind: filename}."""
    outputs: dict[str, str] = {}
    cap, w, h, fps, _ = _open(path)
    by_frame: dict[int, list[Track]] = {}
    for t in tracks:
        for f in range(t.first_frame, t.last_frame + 1):
            by_frame.setdefault(f, []).append(t)
    # Per-track measured points indexed by frame, for boxes and trails.
    pts_by_track = {t.id: {p[0]: p for p in t.points} for t in tracks}

    overlay = None
    if not args.no_video:
        overlay_path = stem.with_name(stem.name + "_tracks.mp4")
        overlay = _writer(overlay_path, fps, (w, h))
        outputs["tracks_video"] = overlay_path.name

    follow_wr = None
    follow_path: dict[int, tuple[float, float]] = {}
    if follow is not None:
        follow_path = _follow_path(follow, args.follow_smooth)
        follow_out = stem.with_name(f"{stem.name}_follow_{follow.id}.mp4")
        follow_wr = _writer(follow_out, fps, (args.follow_size, args.follow_size))
        outputs["follow_video"] = follow_out.name

    trail = args.trail
    bright = meta.get("background") == "bright"
    hud = (0, 0, 0) if bright else (255, 255, 255)
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if follow_wr is not None and idx in follow_path:
            cx, cy = follow_path[idx]
            follow_wr.write(_crop(frame, cx, cy, args.follow_size))
        if overlay is not None:
            for t in by_frame.get(idx, ()):
                col = _color(t.id, bright)
                pts = pts_by_track[t.id]
                hist = [pts[f] for f in range(max(t.first_frame, idx - trail), idx + 1) if f in pts]
                for a, b in zip(hist, hist[1:], strict=False):
                    cv2.line(
                        frame,
                        (int(a[1]), int(a[2])),
                        (int(b[1]), int(b[2])),
                        col,
                        1,
                        cv2.LINE_AA,
                    )
                p = pts.get(idx)
                if p is not None:
                    _, x, y, _, bw, bh = p
                    x0, y0 = int(x - bw / 2), int(y - bh / 2)
                    cv2.rectangle(frame, (x0, y0), (x0 + bw, y0 + bh), col, 1)
                    cv2.putText(
                        frame,
                        str(t.id),
                        (x0, max(y0 - 3, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        col,
                        1,
                        cv2.LINE_AA,
                    )
            cv2.putText(
                frame,
                f"f{idx} tracks={len(by_frame.get(idx, ()))}",
                (6, 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                hud,
                1,
                cv2.LINE_AA,
            )
            overlay.write(frame)
        idx += 1
    cap.release()
    if overlay is not None:
        overlay.release()
    if follow_wr is not None:
        follow_wr.release()
    return outputs


def _write_csv(path: Path, tracks: list[Track], fps: float) -> int:
    rows = 0
    with path.open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["frame", "t", "track_id", "x", "y", "area", "w", "h"])
        for t in tracks:
            for f, x, y, area, w, h in t.points:
                ts = f / fps if fps > 0 else ""
                wr.writerow(
                    [
                        f,
                        f"{ts:.4f}" if ts != "" else "",
                        t.id,
                        f"{x:.2f}",
                        f"{y:.2f}",
                        f"{area:.1f}",
                        w,
                        h,
                    ]
                )
                rows += 1
    return rows


def _track_summary(t: Track, fps: float) -> dict:
    xy = np.array([(p[1], p[2]) for p in t.points])
    step = np.linalg.norm(np.diff(xy, axis=0), axis=1) if len(xy) > 1 else np.zeros(0)
    frames_between = np.diff([p[0] for p in t.points]) if len(xy) > 1 else np.ones(0)
    speed = step / np.maximum(frames_between, 1) if len(step) else np.zeros(0)
    return {
        "id": t.id,
        "first_frame": t.first_frame,
        "last_frame": t.last_frame,
        "life_frames": t.life,
        "hits": t.hits,
        "duration_s": round(t.life / fps, 3) if fps > 0 else None,
        "mean_speed_px_per_frame": round(float(speed.mean()), 3) if len(speed) else 0.0,
        "mean_area": round(float(np.mean([p[3] for p in t.points])), 1),
    }


def _load_sidecar(stem: Path) -> tuple[dict | None, str | None]:
    sc = stem.with_suffix(".json")
    if not sc.exists():
        return None, None
    try:
        with sc.open() as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return None, f"sidecar {sc.name} unreadable: {e}"
    if not isinstance(data, dict):
        return None, f"sidecar {sc.name} is not a JSON object"
    return data, None


def run(args: argparse.Namespace) -> int:
    path = Path(args.video)
    if not path.is_file():
        print(f"track: no such file: {path}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / path.stem

    try:
        tracker, meta = _pass1(args, path)
    except VideoError as e:
        print(f"track: {e}", file=sys.stderr)
        return 2

    confirmed = [t for t in tracker.all_tracks() if t.life >= args.min_life and t.hits >= 2]
    fps = meta["fps"]

    follow: Track | None = None
    warnings: list[str] = []
    if confirmed:
        if args.follow is None:
            follow = max(confirmed, key=lambda t: (t.hits, -t.id))
        else:
            follow = next((t for t in confirmed if t.id == args.follow), None)
            if follow is None:
                warnings.append(f"--follow {args.follow}: no confirmed track with that id")
    elif args.follow is not None:
        warnings.append("no confirmed tracks; nothing to follow")

    csv_path = stem.with_name(stem.name + "_tracks.csv")
    rows = _write_csv(csv_path, confirmed, fps)
    outputs = {"csv": csv_path.name}

    try:
        outputs.update(_pass2(args, path, stem, confirmed, follow, meta))
    except VideoError as e:
        print(f"track: {e}", file=sys.stderr)
        return 2

    sidecar, sc_warn = _load_sidecar(path.parent / path.stem)
    if sc_warn:
        warnings.append(sc_warn)

    summary = {
        "video": path.name,
        "params": {k: v for k, v in vars(args).items() if k not in {"video", "out_dir"}},
        "meta": meta,
        "n_tracks_total": len(tracker.all_tracks()),
        "n_tracks_confirmed": len(confirmed),
        "csv_rows": rows,
        "follow_id": follow.id if follow else None,
        "outputs": outputs,
        "tracks": [_track_summary(t, fps) for t in confirmed],
        "warnings": warnings,
        "sidecar": sidecar,
    }
    json_path = stem.with_name(stem.name + "_tracks.json")
    with json_path.open("w") as fh:
        json.dump(summary, fh, indent=2)

    for wmsg in warnings:
        print(f"track: warning: {wmsg}", file=sys.stderr)
    print(
        f"{path.name}: {meta['frames']} frames, {len(confirmed)} confirmed tracks "
        f"({len(tracker.all_tracks())} total), {rows} rows -> {csv_path.name}"
        + (f", follow id {follow.id}" if follow else ""),
    )
    return 0


def _positive_fraction(s: str) -> float:
    v = float(s)
    if not 0 < v <= 1:
        raise argparse.ArgumentTypeError("must be in (0, 1]")
    return v


def _positive_float(s: str) -> float:
    v = float(s)
    if not v > 0 or not np.isfinite(v):
        raise argparse.ArgumentTypeError("must be a finite number > 0")
    return v


def _nonneg_float(s: str) -> float:
    v = float(s)
    if not v >= 0 or not np.isfinite(v):
        raise argparse.ArgumentTypeError("must be a finite number >= 0")
    return v


def _positive_int(s: str) -> int:
    v = int(s)
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def _nonneg_int(s: str) -> int:
    v = int(s)
    if v < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return v


def _even_int(s: str) -> int:
    v = int(s)
    if v < 16 or v % 2:
        raise argparse.ArgumentTypeError("must be an even integer >= 16")
    return v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("video", help="input clip (anything OpenCV can decode)")
    p.add_argument("--out-dir", help="write outputs here instead of next to the input")
    p.add_argument(
        "--min-area",
        type=float,
        default=30.0,
        help="min blob area, full-res px^2 (the knob you'll actually turn)",
    )
    p.add_argument(
        "--max-area",
        type=float,
        default=None,
        help="max blob area, full-res px^2 (default 5%% of frame)",
    )
    p.add_argument(
        "--bg",
        choices=sorted(DEFAULT_THRESH),
        default="mog2",
        help="background model: mog2, or hold (keeps swimmers that pause; see HoldBackground)",
    )
    p.add_argument(
        "--thresh",
        type=_positive_float,
        default=None,
        help="foreground threshold in squared sigmas (default: 16 for mog2, 9 for hold)",
    )
    p.add_argument(
        "--history", type=_positive_int, default=500, help="MOG2 history frames (mog2 only)"
    )
    p.add_argument(
        "--bg-seed",
        type=_positive_int,
        default=60,
        help="hold: frames in the median seed; longer than a swimmer takes to clear its own "
        "length (hold only)",
    )
    p.add_argument(
        "--hold-px",
        type=_positive_float,
        default=20.0,
        help="hold: a track that has travelled this far (full-res px, median of first vs last "
        "10 positions) keeps the background from learning it (hold only)",
    )
    p.add_argument(
        "--hold-edge",
        type=_nonneg_float,
        default=2.0,
        help="hold: px of sub-pixel shift / focus breathing an edge may show before it reads "
        "as foreground; raises the bar on debris edges only (0 disables; hold only)",
    )
    p.add_argument(
        "--max-dist", type=float, default=40.0, help="max assignment distance, full-res px"
    )
    p.add_argument(
        "--assign",
        choices=sorted(ASSIGNERS),
        default="auction",
        help="track/detection matching: auction (global optimum, default) or greedy "
        "(nearest first; swaps IDs when swimmers cross)",
    )
    p.add_argument(
        "--birth-dist",
        type=float,
        default=None,
        help="unmatched blobs closer than this to a live track are fragments, not new tracks "
        "(default: half of --max-dist; 0 disables)",
    )
    p.add_argument(
        "--fragment-scale",
        type=float,
        default=0.6,
        help="also treat unmatched blobs within this fraction of a live track's blob extent "
        "(max of w, h) as fragments; large bodies with dim interiors split in the mask",
    )
    p.add_argument(
        "--area-ratio",
        type=float,
        default=6.0,
        help="a track may only take a blob whose area is within this factor of its last one "
        "(keeps debris tracks from stealing a swimmer that passes; 0 disables)",
    )
    p.add_argument(
        "--merge-ratio",
        type=float,
        default=1.5,
        help="a blob this many times a track's own area with another track's prediction "
        "inside it is two bodies overlapping: both carry their velocity through and "
        "split by extrapolation (0 disables)",
    )
    p.add_argument(
        "--no-anchor-last",
        action="store_true",
        help="gate only on the Kalman prediction, not also on the last measured position "
        "(the default keeps reversing swimmers; this is the v1 behaviour)",
    )
    p.add_argument(
        "--process-noise",
        type=float,
        default=1e-2,
        help="Kalman process noise; higher lets the velocity estimate turn faster after a "
        "reversal, lower trusts the straight-line prediction more",
    )
    p.add_argument(
        "--max-missed",
        type=_nonneg_int,
        default=10,
        help="frames a track survives without a detection",
    )
    p.add_argument(
        "--min-life", type=_positive_int, default=15, help="min frames spanned for a track to count"
    )
    p.add_argument(
        "--scale",
        type=_positive_fraction,
        default=1.0,
        help="detect on a downscaled frame (0.5 on the Pi at 1080p); outputs stay full-res",
    )
    p.add_argument(
        "--warmup",
        type=_nonneg_int,
        default=2,
        help="frames to let MOG2 settle before detecting (mog2 only)",
    )
    p.add_argument(
        "--follow", type=int, default=None, help="track id for the follow clip (default: most hits)"
    )
    p.add_argument("--follow-size", type=_even_int, default=256, help="follow crop size, px")
    p.add_argument(
        "--follow-smooth",
        type=_positive_fraction,
        default=0.2,
        help="EMA factor for the follow window (1 = no smoothing)",
    )
    p.add_argument(
        "--trail", type=_nonneg_int, default=30, help="trail length in frames on the overlay"
    )
    p.add_argument(
        "--no-video",
        action="store_true",
        help="skip the overlay video (CSV, JSON and follow clip still written)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

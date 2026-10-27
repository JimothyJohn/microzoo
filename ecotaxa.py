#!/usr/bin/env python3
"""ecotaxa.py: make microzoo tracks speak EcoTaxa.

EcoTaxa (ecotaxa.obs-vlfr.fr) is the annotation platform every plankton imager
feeds, the PlanktoScope included: one object = one or more images + a row of
morphometric features, labelled by people and by a classifier trained on the
features. microzoo's v4 species layer (~500 labelled crops) needs exactly that
labelling loop, and EcoTaxa already runs it. Same deps as track.py: numpy and
OpenCV, no scipy, no pandas, so the Pi can do all of it.

    morphometrics(mask)  the PlanktoScope / ZooProcess shape features, with the
                         scikit-image regionprops semantics the PlanktoScope
                         segmenter uses, reimplemented on OpenCV (perimeter and
                         Euler number are bit-for-bit the skimage algorithms).
    export               <stem>_tracks.csv + clip -> EcoTaxa import bundle:
                         ecotaxa_<stem>.tsv (two header rows) + JPEG crops. One
                         object per track, up to --images frames per object
                         (img_rank 1 = sharpest), features measured on the
                         sharpest frame, plus motion columns no plankton imager
                         has (speed, turn, tortuosity from trackstats.py). An
                         ecosim clip exports pre-annotated from its truth CSV.
    pull                 public EcoTaxa project -> CSV of validated objects with
                         taxon names and features, a per-taxon size summary,
                         optional vignettes. Project 2748 is the original
                         PlanktoScope dataset (Pollina, Lombard, Prakash;
                         Villefranche, Jan 2020, 20 um net, 1.19 um/px).

    python ecotaxa.py export data/eco_tracks.csv --images 5
    python ecotaxa.py pull 2748 --out data/ecotaxa --taxa Ciliophora --images 20
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling module under python -I
import trackstats  # noqa: E402

__all__ = [
    "API",
    "FEATURES",
    "INTENSITY",
    "TAXON_FOR_SPECIES",
    "convex_hull_mask",
    "euler_number",
    "export",
    "fill_holes",
    "main",
    "morphometrics",
    "perimeter",
    "pull",
    "segment",
    "sharpness",
    "write_tsv",
]

API = "https://ecotaxa.obs-vlfr.fr"
USER_AGENT = "microzoo-ecotaxa/0.1 (+https://github.com/JimothyJohn/microzoo)"

# The PlanktoScope segmenter's per-object fields, in its order. Names are kept
# verbatim ("circ.", "%area") because EcoTaxa projects already carry them.
FEATURES = (
    "label",
    "width",
    "height",
    "bx",
    "by",
    "circ.",
    "area_exc",
    "area",
    "%area",
    "major",
    "minor",
    "y",
    "x",
    "convex_area",
    "perim.",
    "elongation",
    "perimareaexc",
    "perimmajor",
    "circex",
    "angle",
    "bounding_box_area",
    "eccentricity",
    "equivalent_diameter",
    "euler_number",
    "extent",
    "local_centroid_col",
    "local_centroid_row",
    "solidity",
)
# Grey-level statistics under the mask. The 2020 PlanktoScope data (project
# 2748) carries these names; the current segmenter source does not define
# them, so this is our definition: 8-bit grey values of the mask pixels.
INTENSITY = ("min", "max", "mean", "intden", "range")

# ecosim species -> EcoTaxa taxon names, each verified to resolve on
# ecotaxa.obs-vlfr.fr/api/taxon_set/search (2026-10-26). Species missing here
# export without an annotation category.
TAXON_FOR_SPECIES: dict[str, str] = {
    "paramecium": "Paramecium",
    "didinium": "Didinium",
    "stentor": "Stentor",
    "rotifer": "Rotifera",
    "lacrymaria": "Lacrymaria",
    "dileptus": "Dileptus",
    "amoeba": "Amoeba",
    "daphnia": "Daphnia",
    "debris": "detritus",
    "bacteria": "Bacteria",
    "chlamydomonas": "Chlamydomonas",
    "euglena": "Euglena",
    "tetrahymena": "Tetrahymena",
    "coleps": "Coleps",
    "euplotes": "Euplotes",
    "vorticella": "Vorticella",
    "spirostomum": "Spirostomum",
    "actinosphaerium": "Actinosphaerium",
    "volvox": "Volvox",
    "hydra": "Hydra",
    "cyclops": "Cyclops",
    "ostracod": "Ostracoda",
    "nematode": "Nematoda",
    "tardigrade": "Tardigrada",
    "gastrotrich": "Gastrotricha",
    # No genus entry on EcoTaxa: nearest verified rank.
    "halteria": "Ciliophora",
    "blepharisma": "Ciliophora",
    "diatom": "Bacillariophyta<Chromista",
    "planaria": "Tricladida",
}


# ----------------------------------------------------------------------------
# Morphometrics: skimage.measure.regionprops semantics on OpenCV + numpy.

_STREL4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
_PERIM_KERNEL = np.array([[10, 2, 10], [2, 1, 2], [10, 2, 10]], dtype=np.float32)
_PERIM_WEIGHTS = np.zeros(50)
_PERIM_WEIGHTS[[5, 7, 15, 17, 25, 27]] = 1.0
_PERIM_WEIGHTS[[21, 33]] = math.sqrt(2)
_PERIM_WEIGHTS[[13, 23]] = (1 + math.sqrt(2)) / 2
# skimage euler_number, 2D, connectivity 2 (the regionprops default: ndim).
_EULER_COEFS8 = np.array([0, 0, 0, 0, 0, 0, -1, 0, 1, 0, 0, 0, 0, 0, -1, 0], dtype=np.int64)
# scipy.ndimage.convolve flips the kernel; cv2.filter2D correlates, so flip here.
_EULER_KERNEL = np.array([[0, 0, 0], [0, 1, 4], [0, 2, 8]], dtype=np.float32)[::-1, ::-1].copy()


def _binary(mask: np.ndarray) -> np.ndarray:
    m = np.asarray(mask)
    if m.ndim != 2:
        raise ValueError(f"mask must be 2-D, got shape {m.shape}")
    return (m > 0).astype(np.uint8)


def perimeter(mask: np.ndarray) -> float:
    """skimage.measure.perimeter(mask, neighborhood=4): weighted count of
    border-pixel configurations. Exact match, not cv2.arcLength."""
    img = _binary(mask)
    eroded = cv2.erode(img, _STREL4, borderType=cv2.BORDER_CONSTANT, borderValue=0)
    border = (img - eroded).astype(np.float32)
    conv = cv2.filter2D(border, -1, _PERIM_KERNEL, borderType=cv2.BORDER_CONSTANT)
    hist = np.bincount(np.rint(conv).astype(np.int64).ravel(), minlength=50)[:50]
    return float(hist @ _PERIM_WEIGHTS)


def euler_number(mask: np.ndarray) -> int:
    """skimage.measure.euler_number(mask, connectivity=2): objects minus holes."""
    img = np.pad(_binary(mask).astype(np.float32), 1)
    conv = cv2.filter2D(img, -1, _EULER_KERNEL, borderType=cv2.BORDER_CONSTANT)
    hist = np.bincount(np.rint(conv).astype(np.int64).ravel(), minlength=16)[:16]
    return int(_EULER_COEFS8 @ hist)


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """scipy.ndimage.binary_fill_holes with the default cross structure:
    background 4-connected to the frame edge stays, the rest becomes object."""
    img = np.pad(_binary(mask), 1)
    bg = (img == 0).astype(np.uint8)
    _, labels = cv2.connectedComponents(bg, connectivity=4)
    outside = labels[0, 0]
    filled = img | ((bg == 1) & (labels != outside)).astype(np.uint8)
    return filled[1:-1, 1:-1].astype(bool)


def convex_hull_mask(mask: np.ndarray) -> np.ndarray:
    """skimage.morphology.convex_hull_image: every pixel gets a vertex at the
    middle of each of its four edges (the diamond offsets); the hull of those
    is rasterised the way skimage's grid_points_in_poly does it (O'Rourke's
    left/right ray crossings, rows as x and columns as y, vertices and edge
    points included), so boundary ties agree pixel for pixel."""
    img = _binary(mask)
    out = np.zeros(img.shape, dtype=bool)
    rows, cols = np.nonzero(img)
    if len(rows) == 0:
        return out
    # The hull of the border pixels' vertices is the hull of all vertices.
    inner = cv2.erode(img, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
    br, bc = np.nonzero(img - inner)
    pts = np.stack([br, bc], axis=1).astype(np.float64)  # (row, col)
    offsets = ((-0.5, 0.0), (0.5, 0.0), (0.0, -0.5), (0.0, 0.5))
    verts = np.concatenate([pts + d for d in offsets]).astype(np.float32)
    hull = cv2.convexHull(verts).reshape(-1, 2).astype(np.float64)
    xp, yp = hull[:, 0], hull[:, 1]  # x = row, y = col, as skimage passes them
    r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    x, y = np.mgrid[r0:r1, c0:c1].astype(np.float64)
    eps = 1e-12
    vertex = np.zeros(x.shape, dtype=bool)
    r_cross = np.zeros(x.shape, dtype=np.int64)
    l_cross = np.zeros(x.shape, dtype=np.int64)
    x1, y1 = xp[-1] - x, yp[-1] - y
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(len(hull)):
            x0, y0 = xp[i] - x, yp[i] - y
            vertex |= (np.abs(x0) < eps) & (np.abs(y0) < eps)
            cross = (x0 * y1 - x1 * y0) / (y1 - y0)
            r_cross += ((y0 > 0) != (y1 > 0)) & (cross > 0)
            l_cross += ((y0 < 0) != (y1 < 0)) & (cross < 0)
            x1, y1 = x0, y0
    edge = (r_cross & 1) != (l_cross & 1)
    out[r0:r1, c0:c1] = vertex | edge | ((r_cross & 1) == 1)
    return out


def morphometrics(
    mask: np.ndarray,
    um_per_px: float | None = None,
    origin: tuple[int, int] = (0, 0),
    gray: np.ndarray | None = None,
    label: int = 1,
) -> dict[str, float]:
    """The PlanktoScope feature row for one blob.

    ``mask`` is a binary image of a single object (its bounding box is taken
    from the mask). Lengths are multiplied by ``um_per_px`` when given, areas by
    its square, exactly as the PlanktoScope segmenter does; ``bx``/``by``/``x``/
    ``y`` stay in pixels and are offset by ``origin`` (x, y) so a mask cut from
    a crop reports full-frame coordinates. ``gray`` adds the INTENSITY fields.
    """
    img = _binary(mask)
    rows, cols = np.nonzero(img)
    if len(rows) == 0:
        raise ValueError("empty mask")
    px = float(um_per_px) if um_per_px else 1.0
    px2 = px * px
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    crop = img[r0:r1, c0:c1]
    area_px = float(len(rows))  # skimage area: pixel count, holes excluded
    filled_px = float(fill_holes(crop).sum())
    perim_px = perimeter(crop)
    hull_px = float(convex_hull_mask(crop).sum())
    bbox_px = float((r1 - r0) * (c1 - c0))

    m = cv2.moments(crop, binaryImage=True)
    mu0 = m["m00"]
    a = m["mu20"] / mu0  # skimage inertia tensor: T[0,0] = mu[0,2]/mu0 = column variance
    c = m["mu02"] / mu0
    b = -m["mu11"] / mu0
    eig = np.linalg.eigvalsh(np.array([[a, b], [b, c]]))
    l1, l2 = float(max(eig[1], 0.0)), float(max(eig[0], 0.0))
    major_px, minor_px = 4 * math.sqrt(l1), 4 * math.sqrt(l2)
    if a - c == 0:
        orientation = math.pi / 4 if b < 0 else -math.pi / 4
    else:
        orientation = 0.5 * math.atan2(-2 * b, c - a)
    eccentricity = math.sqrt(1 - l2 / l1) if l1 > 0 else 0.0
    row_c, col_c = float(rows.mean()), float(cols.mean())

    with np.errstate(divide="ignore", invalid="ignore"):
        out: dict[str, float] = {
            "label": float(label),
            "width": (c1 - c0) * px,
            "height": (r1 - r0) * px,
            "bx": float(c0 + origin[0]),
            "by": float(r0 + origin[1]),
            "circ.": float(np.divide(4 * math.pi * filled_px, perim_px**2)),
            "area_exc": area_px * px2,
            "area": filled_px * px2,
            "%area": 1 - area_px / filled_px,
            "major": major_px * px,
            "minor": minor_px * px,
            "y": row_c + origin[1],
            "x": col_c + origin[0],
            "convex_area": hull_px * px2,
            "perim.": perim_px * px,
            "elongation": float(np.divide(major_px, minor_px)),
            "perimareaexc": perim_px / area_px / px,
            "perimmajor": float(np.divide(perim_px, major_px)),
            "circex": float(np.divide(4 * math.pi * area_px, perim_px**2)),
            "angle": orientation / math.pi * 180 + 90,
            "bounding_box_area": bbox_px * px2,
            "eccentricity": eccentricity,
            "equivalent_diameter": math.sqrt(4 * area_px / math.pi) * px,
            "euler_number": float(euler_number(crop)),
            "extent": area_px / bbox_px,
            "local_centroid_col": col_c - c0,
            "local_centroid_row": row_c - r0,
            "solidity": float(np.divide(area_px, hull_px)),
        }
    if gray is not None:
        g = np.asarray(gray)
        if g.shape != img.shape:
            raise ValueError("gray must have the mask's shape")
        vals = g[img > 0].astype(np.float64)
        out.update(
            {
                "min": float(vals.min()),
                "max": float(vals.max()),
                "mean": float(vals.mean()),
                "intden": float(vals.sum()),
                "range": float(vals.max() - vals.min()),
            }
        )
    return out


# ----------------------------------------------------------------------------
# Segmenting a crop around a tracked blob.


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def sharpness(img: np.ndarray) -> float:
    """Variance of the Laplacian, the autofocus metric from CLAUDE.md."""
    return float(cv2.Laplacian(_gray(img), cv2.CV_64F).var())


def segment(
    crop: np.ndarray, dark_object: bool | None = None, point: tuple[int, int] | None = None
) -> np.ndarray:
    """Binary mask of the blob in a crop: Otsu threshold against the crop's
    border (the background), then the connected component under ``point``
    (default: the crop centre), else the one nearest to it.

    ``dark_object`` says which side of the threshold the organism is on
    (backlit brightfield = True, darkfield = False); None decides from the
    centre versus the border.
    """
    g = _gray(crop)
    h, w = g.shape
    if h < 3 or w < 3:
        raise ValueError("crop too small to segment")
    if point is None:
        point = (w // 2, h // 2)
    if dark_object is None:
        border = np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]]).astype(np.float64)
        cy, cx = h // 2, w // 2
        centre = g[max(cy - 2, 0) : cy + 3, max(cx - 2, 0) : cx + 3].astype(np.float64)
        dark_object = bool(centre.mean() < np.median(border))
    kind = cv2.THRESH_BINARY_INV if dark_object else cv2.THRESH_BINARY
    _, binary = cv2.threshold(g, 0, 255, kind + cv2.THRESH_OTSU)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return np.zeros(g.shape, dtype=bool)
    px, py = min(max(point[0], 0), w - 1), min(max(point[1], 0), h - 1)
    pick = int(labels[py, px])
    if pick == 0:
        # The point sits on background (hollow or thin organism): take the
        # component with the nearest pixel, specks discounted by their size.
        ys, xs = np.nonzero(labels)
        d = np.hypot(xs - px, ys - py)
        nearest = np.full(n, np.inf)
        np.minimum.at(nearest, labels[ys, xs].astype(np.intp), d)
        sizes = stats[:, cv2.CC_STAT_AREA].astype(np.float64)
        score = nearest[1:] / np.sqrt(sizes[1:])
        pick = int(np.argmin(score)) + 1
    return labels == pick


# ----------------------------------------------------------------------------
# EcoTaxa TSV.


def _cell(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return "" if not math.isfinite(v) else repr(v)
    return str(v)


def write_tsv(rows: Sequence[Mapping[str, Any]], fh) -> list[str]:
    """EcoTaxa TSV: a header row, then a type row ([t] text / [f] number),
    then the data. Every row must carry the same columns. Returns the columns."""
    if not rows:
        raise ValueError("no rows")
    cols = list(rows[0].keys())
    for r in rows:
        if list(r.keys()) != cols:
            raise ValueError("rows must share one column set in one order")
    types = []
    for c in cols:
        sample = next((r[c] for r in rows if r[c] is not None), None)
        types.append(
            "[f]" if isinstance(sample, int | float) and not isinstance(sample, bool) else "[t]"
        )
    wr = csv.writer(fh, delimiter="\t", lineterminator="\n")
    wr.writerow(cols)
    wr.writerow(types)
    for r in rows:
        wr.writerow([_cell(r[c]) for c in cols])
    return cols


def _date_token(s: object) -> str | None:
    """'2026-10-25' / '20261025' -> '20261025' (EcoTaxa object_date)."""
    digits = re.sub(r"\D", "", str(s or ""))
    return digits if re.fullmatch(r"\d{8}", digits) else None


def _time_token(s: object) -> str | None:
    """'15:00:00' / '1500' / '150000' -> 'HHMMSS' (EcoTaxa object_time)."""
    digits = re.sub(r"\D", "", str(s or ""))
    if re.fullmatch(r"\d{4}", digits):
        digits += "00"
    return digits if re.fullmatch(r"\d{6}", digits) else None


# ----------------------------------------------------------------------------
# export


@dataclass
class _Obj:
    track_id: int
    frames: list[int]  # sampled frames, in time order
    boxes: dict[int, tuple[float, float, int, int]]  # frame -> x, y, w, h (full-res px)
    crops: dict[int, tuple[np.ndarray, int, int]] = field(
        default_factory=dict
    )  # frame -> img, x0, y0


def _load_boxes(path: Path) -> dict[int, dict[int, tuple[float, float, int, int]]]:
    out: dict[int, dict[int, tuple[float, float, int, int]]] = defaultdict(dict)
    with path.open(newline="") as fh:
        r = csv.DictReader(fh)
        need = {"frame", "track_id", "x", "y", "w", "h"}
        if r.fieldnames is None or not need <= set(r.fieldnames):
            raise ValueError(f"{path}: expected columns {sorted(need)}, got {r.fieldnames}")
        for row in r:
            out[int(row["track_id"])][int(row["frame"])] = (
                float(row["x"]),
                float(row["y"]),
                int(float(row["w"])),
                int(float(row["h"])),
            )
    return out


def _sidecar_and_meta(tracks_csv: Path) -> tuple[dict, dict]:
    """(clip sidecar, track.py meta) from <stem>.json and <stem>_tracks.json."""
    stem = tracks_csv.name.removesuffix("_tracks.csv")
    sidecar: dict = {}
    meta: dict = {}
    sc = tracks_csv.with_name(stem + ".json")
    if sc.exists():
        try:
            data = json.loads(sc.read_text())
            if isinstance(data, dict):
                sidecar = data
        except (OSError, ValueError):
            pass
    tj = tracks_csv.with_name(stem + "_tracks.json")
    if tj.exists():
        try:
            data = json.loads(tj.read_text())
            if isinstance(data, dict):
                meta = data.get("meta") or {}
                if not sidecar and isinstance(data.get("sidecar"), dict):
                    sidecar = data["sidecar"]
        except (OSError, ValueError):
            pass
    return sidecar, meta


def _find_video(tracks_csv: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    stem = tracks_csv.name.removesuffix("_tracks.csv")
    for ext in (".mp4", ".avi", ".mov", ".mkv"):
        cand = tracks_csv.with_name(stem + ext)
        if cand.is_file():
            return cand
    return None


def _sample_frames(frames: list[int], k: int) -> list[int]:
    if k >= len(frames):
        return list(frames)
    idx = np.linspace(0, len(frames) - 1, k)
    return [frames[int(round(i))] for i in idx]


def _crop_box(
    frame: np.ndarray, x: float, y: float, w: int, h: int, margin: float, min_size: int
) -> tuple[np.ndarray, int, int]:
    fh, fw = frame.shape[:2]
    cw = max(int(round(w * (1 + 2 * margin))), min_size)
    ch = max(int(round(h * (1 + 2 * margin))), min_size)
    x0 = int(round(x - cw / 2))
    y0 = int(round(y - ch / 2))
    x0 = min(max(x0, 0), max(fw - cw, 0))
    y0 = min(max(y0, 0), max(fh - ch, 0))
    return frame[y0 : y0 + ch, x0 : x0 + cw], x0, y0


def export(args: argparse.Namespace) -> int:
    tracks_csv = Path(args.tracks)
    try:
        boxes = _load_boxes(tracks_csv)
        tracks = trackstats.load_tracks(tracks_csv)
    except (OSError, ValueError, KeyError) as e:
        print(f"ecotaxa: {e}", file=sys.stderr)
        return 2
    if not tracks:
        print("ecotaxa: no tracks in file", file=sys.stderr)
        return 1
    video = _find_video(tracks_csv, args.video)
    if video is None:
        print("ecotaxa: clip not found next to the tracks; pass --video", file=sys.stderr)
        return 2
    sidecar, meta = _sidecar_and_meta(tracks_csv)
    um_per_px = args.um_per_px or sidecar.get("um_per_px")
    fps = args.fps or sidecar.get("fps") or meta.get("fps")
    if not fps or fps <= 0:
        print("ecotaxa: need --fps (no sidecar or _tracks.json found)", file=sys.stderr)
        return 2
    if not um_per_px or um_per_px <= 0:
        um_per_px = None
        print(
            "ecotaxa: no um_per_px; features are in pixels (process_pixel left blank)",
            file=sys.stderr,
        )
    stem = tracks_csv.name.removesuffix("_tracks.csv")

    # Motion, convection removed, the same way trackstats does it.
    n_frames = int(max(t[-1, 0] for t in tracks.values())) + 1
    win = max(1, int(round(args.window * fps)))
    drift = trackstats.common_motion(tracks, n_frames, win)
    stats = {
        tid: trackstats.track_stats(t, drift, um_per_px or 1.0, fps, win)
        for tid, t in tracks.items()
    }

    # Labels from an ecosim truth file, if the clip has one.
    labels: dict[int, str] = {}
    truth_path = args.truth or tracks_csv.with_name(stem + "_truth.csv")
    if truth_path.exists():
        truth = trackstats.load_truth(truth_path)
        for tid, t in tracks.items():
            sp, frac = trackstats.match_species(t, truth, args.match_px)
            if frac >= 0.5 and sp in TAXON_FOR_SPECIES:
                labels[tid] = TAXON_FOR_SPECIES[sp]
            elif frac >= 0.5:
                print(
                    f"ecotaxa: no EcoTaxa taxon for species {sp!r}; track {tid} unlabelled",
                    file=sys.stderr,
                )

    objs: list[_Obj] = []
    for tid in sorted(tracks):
        frames = sorted(boxes[tid])
        if len(frames) < args.min_frames:
            continue
        objs.append(_Obj(tid, _sample_frames(frames, args.images), boxes[tid]))
    if not objs:
        print(f"ecotaxa: no track has {args.min_frames}+ frames", file=sys.stderr)
        return 1
    wanted: dict[int, list[_Obj]] = defaultdict(list)
    for o in objs:
        for f in o.frames:
            wanted[f].append(o)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"ecotaxa: cannot open {video}", file=sys.stderr)
        return 1
    last = max(wanted)
    idx = 0
    while idx <= last:
        ok, frame = cap.read()
        if not ok:
            break
        for o in wanted.get(idx, ()):
            x, y, w, h = o.boxes[idx]
            o.crops[idx] = _crop_box(frame, x, y, w, h, args.margin, args.min_crop)
        idx += 1
    cap.release()

    bright = meta.get("background") == "bright" if meta else None
    dark_object = bright if bright is not None else None
    if sidecar.get("illumination") == "brightfield":
        dark_object = True
    elif sidecar.get("illumination") == "darkfield":
        dark_object = False

    date_tok = _date_token(sidecar.get("date"))
    time_tok = _time_token(sidecar.get("time"))
    sample_id = str(sidecar.get("source_jar") or stem)
    acq_id = stem
    instrument = str(
        sidecar.get("instrument") or ("ecosim" if sidecar.get("source") == "ecosim" else "microzoo")
    )
    process_id = "microzoo_track"

    out_dir = Path(args.out) if args.out else tracks_csv.parent
    bundle = f"ecotaxa_{stem}"
    rows: list[dict[str, object]] = []
    images: list[tuple[str, bytes]] = []
    n_unsegmented = 0
    for o in objs:
        have = [f for f in o.frames if f in o.crops]
        if not have:
            continue
        ranked = sorted(have, key=lambda f: -sharpness(o.crops[f][0]))
        best = ranked[0]
        crop, x0, y0 = o.crops[best]
        bx, by, bw, bh = o.boxes[best]
        mask = segment(crop, dark_object, (int(round(bx)) - x0, int(round(by)) - y0))
        feats: dict[str, float]
        if mask.any():
            feats = morphometrics(mask, um_per_px, (x0, y0), _gray(crop), label=o.track_id)
        else:
            n_unsegmented += 1
            feats = dict.fromkeys(FEATURES + INTENSITY, float("nan"))
            feats["label"] = float(o.track_id)
        s = stats[o.track_id]
        object_id = f"{stem}_t{o.track_id:04d}"
        base: dict[str, object] = {
            "object_id": object_id,
            "object_lat": sidecar.get("lat"),
            "object_lon": sidecar.get("lon"),
            "object_date": date_tok,
            "object_time": time_tok,
            "object_annotation_category": labels.get(o.track_id),
            "object_annotation_status": "predicted" if o.track_id in labels else None,
        }
        base.update({f"object_{k}": feats[k] for k in FEATURES + INTENSITY})
        base.update(
            {
                "object_track_id": o.track_id,
                "object_frame": best,
                "object_track_frames": s["frames"],
                "object_life_s": s["life_s"],
                "object_speed_mean": s["speed_mean"],
                "object_speed_p50": s["speed_p50"],
                "object_speed_p90": s["speed_p90"],
                "object_moving_frac": s["moving_frac"],
                "object_turn_sigma": s["turn_sigma"],
                "object_tortuosity": s["tortuosity"],
                "object_blur_laplacian": sharpness(crop),
                "object_n_images": len(ranked),
                "sample_id": sample_id,
                "sample_chamber_depth_um": sidecar.get("chamber_depth_um"),
                "sample_notes": sidecar.get("notes"),
                "acq_id": acq_id,
                "acq_instrument": instrument,
                "acq_objective": sidecar.get("objective"),
                "acq_illumination": sidecar.get("illumination"),
                "acq_exposure_ms": sidecar.get("exposure_ms"),
                "acq_fps": fps,
                "process_id": process_id,
                "process_software": "microzoo track.py + ecotaxa.py",
                "process_pixel": um_per_px,
                "process_speed_unit": "um/s" if um_per_px else "px/s",
            }
        )
        for rank, f in enumerate(ranked, start=1):
            img = o.crops[f][0]
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
            if not ok:
                print(
                    f"ecotaxa: JPEG encode failed for track {o.track_id} frame {f}", file=sys.stderr
                )
                return 1
            name = f"{object_id}_f{f:06d}.jpg"
            images.append((name, buf.tobytes()))
            rows.append({"img_file_name": name, "img_rank": rank, **base})

    # Columns with no value anywhere are dropped (EcoTaxa dislikes empty predefined fields).
    empty = [c for c in rows[0] if all(r[c] is None for r in rows)]
    rows = [{k: v for k, v in r.items() if k not in empty} for r in rows]

    tsv = io.StringIO()
    cols = write_tsv(rows, tsv)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.folder:
        dest = out_dir / bundle
        dest.mkdir(exist_ok=True)
        (dest / f"{bundle}.tsv").write_text(tsv.getvalue(), encoding="utf-8")
        for name, data in images:
            (dest / name).write_bytes(data)
        target = dest
    else:
        target = out_dir / f"{bundle}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{bundle}.tsv", tsv.getvalue().encode("utf-8"))
            for name, data in images:
                zf.writestr(name, data, compress_type=zipfile.ZIP_STORED)
    n_objects = len({r["object_id"] for r in rows})
    print(
        f"{target}: {n_objects} objects, {len(images)} images, {len(cols)} columns, "
        f"{len(labels)} labelled" + (f", {n_unsegmented} unsegmented" if n_unsegmented else "")
    )
    return 0


# ----------------------------------------------------------------------------
# pull


class ApiError(RuntimeError):
    pass


def _api(base: str, path: str, body: dict | None = None, timeout: float = 60.0) -> object:
    url = base.rstrip("/") + "/api" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise ApiError(f"{e.code} {e.reason} for {path}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ApiError(f"{e} for {path}") from e


def _fetch_bytes(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise ApiError(f"{e} for {url}") from e


def _taxon_names(base: str, ids: list[int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i : i + 200]
        res = _api(base, "/taxon_set/query?ids=" + ",".join(map(str, chunk)))
        if not isinstance(res, list):
            raise ApiError("taxon_set/query returned no list")
        for t in res:
            out[int(t["id"])] = t
    return out


def _resolve_taxa(base: str, names: list[str]) -> list[int]:
    ids = []
    for name in names:
        if name.isdigit():
            ids.append(int(name))
            continue
        res = _api(base, "/taxon_set/search?query=" + urllib.parse.quote(name))
        if not isinstance(res, list):
            raise ApiError("taxon_set/search returned no list")
        exact = [t for t in res if str(t.get("text", "")).split("<")[0].lower() == name.lower()]
        if not exact:
            hint = ", ".join(str(t.get("text")) for t in res[:5])
            raise ApiError(
                f"no EcoTaxa taxon named {name!r}" + (f" (near: {hint})" if hint else "")
            )
        ids.append(int(exact[0]["id"]))
    return ids


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "x"


def _quantiles(vals: list[float]) -> dict[str, float]:
    a = np.array([v for v in vals if v is not None and math.isfinite(v)], dtype=np.float64)
    if len(a) == 0:
        return {}
    p10, p50, p90 = np.percentile(a, [10, 50, 90])
    return {"p10": round(float(p10), 3), "p50": round(float(p50), 3), "p90": round(float(p90), 3)}


SUMMARY_FEATURES = (
    "equivalent_diameter",
    "major",
    "minor",
    "elongation",
    "circ.",
    "solidity",
    "%area",
)
LENGTH_FEATURES = {"equivalent_diameter", "major", "minor", "width", "height", "perim."}
AREA_FEATURES = {"area", "area_exc", "convex_area", "bounding_box_area"}


def pull(args: argparse.Namespace) -> int:
    base = args.api
    pid = args.project
    try:
        proj = _api(base, f"/projects/{pid}")
        if not isinstance(proj, dict):
            raise ApiError("project query returned no object")
        free = list((proj.get("obj_free_cols") or {}).keys())
        stats = _api(base, f"/project_set/taxo_stats?ids={pid}")
        taxo_ids = args.taxa and _resolve_taxa(base, args.taxa)
        fields = ["obj.orig_id", "obj.classif_id", "obj.classif_qual", "img.file_name"] + [
            "fre." + f for f in free
        ]
        body: dict[str, str] = {"statusfilter": args.status}
        if taxo_ids:
            body["taxo"] = ",".join(map(str, taxo_ids))
            body["taxochild"] = "Y"
        q = "?fields=" + urllib.parse.quote(",".join(fields)) + "&order_field=obj.orig_id"
        objects: list[dict] = []
        acq_of: dict[int, int] = {}
        start, total = 0, None
        while True:
            size = args.page if args.limit is None else min(args.page, args.limit - len(objects))
            if size <= 0:
                break
            res = _api(
                base, f"/object_set/{pid}/query{q}&window_start={start}&window_size={size}", body
            )
            if not isinstance(res, dict):
                raise ApiError("object query returned no object")
            total = int(res.get("total_ids", 0))
            ids = res.get("object_ids") or []
            for oid, acq, det in zip(
                ids, res.get("acquisition_ids") or [], res.get("details") or [], strict=True
            ):
                rec = dict(zip(fields, det, strict=True))
                rec["objid"] = int(oid)
                acq_of[int(oid)] = int(acq) if acq is not None else -1
                objects.append(rec)
            start += len(ids)
            if not ids or start >= total:
                break
        pixel_of: dict[int, float | None] = {}
        for acq in sorted(set(acq_of.values())):
            if acq < 0:
                continue
            try:
                proc = _api(base, f"/process/{acq}")
                px = (
                    (proc.get("free_columns") or {}).get("pixel")
                    if isinstance(proc, dict)
                    else None
                )
                pixel_of[acq] = float(px) if px not in (None, "") else None
            except (ApiError, ValueError):
                pixel_of[acq] = None
        names = _taxon_names(
            base, sorted({int(o["obj.classif_id"]) for o in objects if o["obj.classif_id"]})
        )
    except ApiError as e:
        print(f"ecotaxa: {e}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    title = str(proj.get("title", ""))
    used = stats[0] if isinstance(stats, list) and stats else {}
    csv_path = out / f"ecotaxa_{pid}_objects.csv"
    with csv_path.open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(
            [
                "objid",
                "orig_id",
                "taxon_id",
                "taxon",
                "lineage",
                "status",
                "img",
                "acquisition",
                "pixel_um",
            ]
            + free
        )
        for o in objects:
            tid = o["obj.classif_id"]
            t = names.get(int(tid), {}) if tid else {}
            acq = acq_of[o["objid"]]
            wr.writerow(
                [
                    o["objid"],
                    o["obj.orig_id"],
                    tid,
                    t.get("display_name", ""),
                    " > ".join(reversed(t.get("lineage") or [])),
                    o["obj.classif_qual"],
                    o["img.file_name"],
                    acq,
                    pixel_of.get(acq, ""),
                ]
                + [o["fre." + f] for f in free]
            )

    per_taxon: dict[int, list[dict]] = defaultdict(list)
    for o in objects:
        if o["obj.classif_id"]:
            per_taxon[int(o["obj.classif_id"])].append(o)
    summary = {
        "project": pid,
        "title": title,
        "api": base,
        "status_filter": args.status,
        "objects": len(objects),
        "project_counts": {
            k: used.get(k)
            for k in ("nb_validated", "nb_dubious", "nb_predicted", "nb_unclassified")
        },
        "pixel_um": sorted({v for v in pixel_of.values() if v is not None}),
        "features_in": "um where pixel_um is known, else px",
        "taxa": {},
    }
    for tid, objs in sorted(per_taxon.items(), key=lambda kv: -len(kv[1])):
        if len(objs) < args.min_count:
            continue
        t = names.get(tid, {})
        entry: dict[str, object] = {
            "taxon_id": tid,
            "lineage": " > ".join(reversed(t.get("lineage") or [])),
            "n": len(objs),
        }
        for f in SUMMARY_FEATURES:
            if f not in free:
                continue
            vals = []
            for o in objs:
                v = o["fre." + f]
                if v is None:
                    continue
                v = float(v)
                px = pixel_of.get(acq_of[o["objid"]])
                if px:
                    if f in LENGTH_FEATURES:
                        v *= px
                    elif f in AREA_FEATURES:
                        v *= px * px
                vals.append(v)
            entry[f] = _quantiles(vals)
        summary["taxa"][t.get("display_name", str(tid))] = entry
    json_path = out / f"ecotaxa_{pid}_summary.json"
    json_path.write_text(json.dumps(summary, indent=1) + "\n")

    n_img = 0
    if args.images:
        for tid, objs in per_taxon.items():
            t = names.get(tid, {})
            folder = out / str(pid) / _slug(t.get("display_name", str(tid)))
            folder.mkdir(parents=True, exist_ok=True)
            for o in objs[: args.images]:
                dest = folder / f"{o['objid']}.jpg"
                if dest.exists():
                    continue
                try:
                    dest.write_bytes(_fetch_bytes(f"{base.rstrip('/')}/vault/{o['img.file_name']}"))
                    n_img += 1
                except ApiError as e:
                    print(f"ecotaxa: {e}", file=sys.stderr)
    print(
        f"{title!r} (project {pid}): {len(objects)} objects, {len(per_taxon)} taxa -> "
        f"{csv_path.name}, {json_path.name}" + (f", {n_img} vignettes" if n_img else "")
    )
    return 0


# ----------------------------------------------------------------------------
# CLI


def _positive_int(s: str) -> int:
    v = int(s)
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def _nonneg_float(s: str) -> float:
    v = float(s)
    if not math.isfinite(v) or v < 0:
        raise argparse.ArgumentTypeError("must be a finite number >= 0")
    return v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="tracked clip -> EcoTaxa import bundle")
    e.add_argument("tracks", type=Path, help="<stem>_tracks.csv from track.py")
    e.add_argument("--video", type=Path, help="the clip (default: <stem>.mp4 next to the tracks)")
    e.add_argument("--out", type=Path, help="output directory (default: next to the tracks)")
    e.add_argument("--folder", action="store_true", help="write a folder instead of a zip")
    e.add_argument(
        "--images", type=_positive_int, default=5, help="frames per object (EcoTaxa shows < 10)"
    )
    e.add_argument("--min-frames", type=_positive_int, default=10, help="skip shorter tracks")
    e.add_argument(
        "--margin", type=_nonneg_float, default=0.35, help="crop margin, fraction of the box"
    )
    e.add_argument("--min-crop", type=_positive_int, default=48, help="minimum crop side, px")
    e.add_argument("--quality", type=int, default=92, help="JPEG quality")
    e.add_argument("--um-per-px", type=float, help="scale (default: from the sidecar)")
    e.add_argument("--fps", type=float, help="frame rate (default: from the sidecar)")
    e.add_argument("--truth", type=Path, help="<stem>_truth.csv (default: next to the tracks)")
    e.add_argument("--match-px", type=float, default=25.0, help="truth match radius, px")
    e.add_argument("--window", type=float, default=0.2, help="seconds per velocity sample")
    e.set_defaults(func=export)

    g = sub.add_parser("pull", help="public EcoTaxa project -> reference CSV + summary")
    g.add_argument(
        "project", type=int, help="EcoTaxa project id (2748 = the PlanktoScope reference)"
    )
    g.add_argument("--out", type=Path, default=Path("data/ecotaxa"), help="output directory")
    g.add_argument("--taxa", nargs="*", help="taxon names or ids; children included")
    g.add_argument(
        "--status", default="V", help="EcoTaxa status filter (V validated, PV, PVD, ...)"
    )
    g.add_argument("--limit", type=_positive_int, help="stop after this many objects")
    g.add_argument("--page", type=_positive_int, default=1000, help="objects per request")
    g.add_argument("--images", type=int, default=0, help="vignettes to download per taxon")
    g.add_argument(
        "--min-count",
        type=_positive_int,
        default=10,
        help="taxa below this stay out of the summary",
    )
    g.add_argument("--api", default=API, help="EcoTaxa instance")
    g.set_defaults(func=pull)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return int(a.func(a))


if __name__ == "__main__":
    sys.exit(main())

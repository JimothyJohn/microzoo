"""ecotaxa.py: PlanktoScope morphometrics with scikit-image semantics, the EcoTaxa
TSV contract, segmentation on real EcoTaxa vignettes, and the export CLI end to
end on an ecosim clip. The live API test runs only with ``pytest --network``."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest
from conftest import REPO, run_cli
from hypothesis import given, settings
from hypothesis import strategies as st

import ecotaxa
from species import SPECIES

FIX = Path(__file__).parent / "fixtures" / "ecotaxa"
ECOSIM = REPO / "ecosim.py"
TRACK = REPO / "track.py"
ECOTAXA = REPO / "ecotaxa.py"


def _disc(r: int, pad: int = 6, hole: int = 0) -> np.ndarray:
    n = 2 * (r + pad) + 1
    yy, xx = np.mgrid[0:n, 0:n] - (r + pad)
    m = xx * xx + yy * yy <= r * r
    if hole:
        m &= xx * xx + yy * yy > hole * hole
    return m


# ----------------------------------------------------------------------------
# Morphometrics against scikit-image (fixtures made by a skimage cross-check).


def _skimage_cases():
    masks = np.load(FIX / "skimage_blobs.npz")
    expected = json.loads((FIX / "skimage_blobs.json").read_text())
    return [(masks[f"m{i}"], e) for i, e in enumerate(expected)]


@pytest.mark.parametrize("mask,expected", _skimage_cases())
def test_features_match_skimage_regionprops(mask, expected):
    got = ecotaxa.morphometrics(mask, expected["px"])
    for k, v in expected.items():
        if k == "px":
            continue
        assert got[k] == pytest.approx(v, rel=1e-9, abs=1e-9), k
    assert got["euler_number"] == int(got["euler_number"])


def test_disc_is_round_and_solid():
    f = ecotaxa.morphometrics(_disc(40))
    # skimage's 4-neighbourhood perimeter overestimates a rasterised circle by ~5 %.
    assert 0.85 < f["circ."] <= 1.0
    assert f["eccentricity"] < 0.05
    assert f["elongation"] == pytest.approx(1.0, abs=0.02)
    assert f["equivalent_diameter"] == pytest.approx(80, rel=0.02)
    assert f["extent"] == pytest.approx(math.pi / 4, rel=0.03)
    assert f["solidity"] > 0.98
    assert f["%area"] == 0.0 and f["euler_number"] == 1
    assert f["area"] == f["area_exc"]


def test_ring_counts_its_hole():
    f = ecotaxa.morphometrics(_disc(30, hole=10))
    assert f["euler_number"] == 0
    assert f["area"] > f["area_exc"]
    assert f["%area"] == pytest.approx(100 / 900, rel=0.1)
    assert f["circ."] > f["circex"]


def test_rectangle_axes_and_angle():
    m = np.zeros((40, 100), bool)
    m[10:30, 20:80] = True  # 60 wide, 20 tall, axis along the columns
    f = ecotaxa.morphometrics(m)
    assert f["width"] == 60 and f["height"] == 20
    assert f["bx"] == 20 and f["by"] == 10
    # discrete second moment of 60 pixel positions: (60^2 - 1) / 12
    assert f["major"] == pytest.approx(4 * math.sqrt((60**2 - 1) / 12), rel=1e-9)
    assert f["elongation"] == pytest.approx(math.sqrt((60**2 - 1) / (20**2 - 1)), rel=1e-9)
    assert f["x"] == pytest.approx(49.5) and f["y"] == pytest.approx(19.5)
    assert f["local_centroid_col"] == pytest.approx(29.5)
    assert f["angle"] % 180 == pytest.approx(0.0, abs=1e-9)
    assert f["extent"] == 1.0 and f["solidity"] == 1.0


def test_pixel_size_scales_lengths_areas_and_nothing_else():
    m = _disc(25, hole=5)
    a, b = ecotaxa.morphometrics(m), ecotaxa.morphometrics(m, 2.5)
    for k in ("width", "height", "major", "minor", "perim.", "equivalent_diameter"):
        assert b[k] == pytest.approx(a[k] * 2.5), k
    for k in ("area", "area_exc", "convex_area", "bounding_box_area"):
        assert b[k] == pytest.approx(a[k] * 6.25), k
    assert b["perimareaexc"] == pytest.approx(a["perimareaexc"] / 2.5)
    for k in ("circ.", "circex", "elongation", "eccentricity", "solidity", "extent", "%area"):
        assert b[k] == pytest.approx(a[k]), k
    for k in ("bx", "by", "x", "y", "local_centroid_col", "local_centroid_row"):
        assert b[k] == a[k], k


def test_origin_offsets_only_positions():
    m = _disc(10)
    a, b = ecotaxa.morphometrics(m), ecotaxa.morphometrics(m, origin=(100, 50))
    assert b["bx"] == a["bx"] + 100 and b["by"] == a["by"] + 50
    assert b["x"] == a["x"] + 100 and b["y"] == a["y"] + 50
    assert b["area"] == a["area"] and b["local_centroid_col"] == a["local_centroid_col"]


def test_intensity_fields_come_from_the_mask_pixels():
    m = _disc(5)
    g = np.full(m.shape, 200, np.uint8)
    g[m] = 40
    g[m.shape[0] // 2, m.shape[1] // 2] = 60
    f = ecotaxa.morphometrics(m, gray=g)
    assert f["min"] == 40 and f["max"] == 60 and f["range"] == 20
    assert f["intden"] == 40 * (m.sum() - 1) + 60
    assert f["mean"] == pytest.approx(f["intden"] / m.sum())


def test_empty_or_bad_masks_are_rejected():
    with pytest.raises(ValueError):
        ecotaxa.morphometrics(np.zeros((5, 5), bool))
    with pytest.raises(ValueError):
        ecotaxa.morphometrics(np.zeros((5, 5, 3), bool))
    with pytest.raises(ValueError):
        ecotaxa.morphometrics(_disc(3), gray=np.zeros((2, 2), np.uint8))


def test_single_pixel_has_no_perimeter_and_stays_finite_or_inf():
    m = np.zeros((3, 3), bool)
    m[1, 1] = True
    f = ecotaxa.morphometrics(m)
    assert f["perim."] == 0 and f["area"] == 1 and f["euler_number"] == 1
    assert math.isinf(f["circ."]) and f["major"] == f["minor"] == 0
    assert math.isnan(f["elongation"])  # 0 / 0, as skimage reports it
    assert f["eccentricity"] == 0.0


@st.composite
def random_masks(draw):
    h = draw(st.integers(8, 40))
    w = draw(st.integers(8, 40))
    n = draw(st.integers(1, 4))
    yy, xx = np.mgrid[0:h, 0:w]
    m = np.zeros((h, w), bool)
    for _ in range(n):
        cx = draw(st.integers(0, w - 1))
        cy = draw(st.integers(0, h - 1))
        r = draw(st.integers(1, 8))
        m |= (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    # keep one connected component, as regionprops would
    _, lab = cv2.connectedComponents(m.astype(np.uint8), connectivity=8)
    return lab == 1


@settings(max_examples=60, deadline=None)
@given(random_masks())
def test_feature_invariants_hold_on_random_blobs(mask):
    f = ecotaxa.morphometrics(mask)
    assert f["area"] >= f["area_exc"] > 0
    assert 0.0 <= f["%area"] < 1.0
    assert f["area_exc"] <= f["convex_area"] <= f["bounding_box_area"] + 1e-9
    assert 0 < f["extent"] <= 1.0 and 0 < f["solidity"] <= 1.0 + 1e-9
    assert f["major"] >= f["minor"] >= 0
    assert 0.0 <= f["eccentricity"] <= 1.0
    assert f["euler_number"] == int(f["euler_number"]) and f["euler_number"] <= 1
    assert f["perim."] >= 0 and f["equivalent_diameter"] > 0
    assert 0 <= f["local_centroid_col"] < f["width"] and 0 <= f["local_centroid_row"] < f["height"]


# ----------------------------------------------------------------------------
# Segmentation on real EcoTaxa vignettes (project 2748, validated objects).


def _vignettes():
    meta = json.loads((FIX / "vignettes.json").read_text())
    return meta["objects"]


@pytest.mark.parametrize("obj", _vignettes(), ids=lambda o: str(o["objid"]))
def test_real_vignettes_segment_to_the_organism(obj):
    img = cv2.imread(str(FIX / f"{obj['objid']}.jpg"))
    assert img is not None
    mask = ecotaxa.segment(img, dark_object=True)
    f = ecotaxa.morphometrics(mask, gray=cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    # The 2020 PlanktoScope mask was more inclusive than Otsu (it closed the
    # outline and kept thin appendages), so areas and extents are smaller
    # here; the body must still be found: never a speck, never the whole crop.
    assert 0.3 * obj["area"] <= f["area"] <= obj["width"] * obj["height"]
    assert f["width"] >= 0.35 * obj["width"] and f["height"] >= 0.35 * obj["height"]
    assert f["mean"] < 200  # the organism is the dark part of a ~230 background


def test_segment_auto_polarity_and_point():
    img = np.full((60, 80), 30, np.uint8)
    cv2.circle(img, (55, 30), 10, 220, -1)  # bright blob off centre, dark field
    m = ecotaxa.segment(img)  # auto polarity, centre point on background
    assert m.sum() == pytest.approx(math.pi * 100, rel=0.1)
    assert m[30, 55] and not m[30, 10]
    m2 = ecotaxa.segment(img, dark_object=False, point=(55, 30))
    assert (m2 == m).all()
    with pytest.raises(ValueError):
        ecotaxa.segment(np.zeros((2, 2), np.uint8))


def test_sharpness_orders_blur():
    img = np.zeros((64, 64), np.uint8)
    cv2.circle(img, (32, 32), 12, 255, -1)
    assert ecotaxa.sharpness(img) > ecotaxa.sharpness(cv2.GaussianBlur(img, (0, 0), 3))


# ----------------------------------------------------------------------------
# The EcoTaxa TSV contract.


def test_tsv_has_header_and_type_rows_and_blanks_non_finite():
    rows = [
        {"img_file_name": "a.jpg", "img_rank": 1, "object_id": "o1", "object_x": 1.5, "n": None},
        {
            "img_file_name": "b.jpg",
            "img_rank": 2,
            "object_id": "o1",
            "object_x": float("inf"),
            "n": 3,
        },
    ]
    buf = io.StringIO()
    cols = ecotaxa.write_tsv(rows, buf)
    lines = buf.getvalue().splitlines()
    assert (
        lines[0].split("\t") == cols == ["img_file_name", "img_rank", "object_id", "object_x", "n"]
    )
    assert lines[1].split("\t") == ["[t]", "[f]", "[t]", "[f]", "[f]"]
    assert lines[2].split("\t") == ["a.jpg", "1", "o1", "1.5", ""]
    assert lines[3].split("\t") == ["b.jpg", "2", "o1", "", "3"]
    with pytest.raises(ValueError):
        ecotaxa.write_tsv([], io.StringIO())
    with pytest.raises(ValueError):
        ecotaxa.write_tsv([{"a": 1}, {"b": 2}], io.StringIO())


@pytest.mark.parametrize(
    "raw,tok", [("2026-10-25", "20261025"), ("20261025", "20261025"), ("", None), ("2026", None)]
)
def test_date_tokens(raw, tok):
    assert ecotaxa._date_token(raw) == tok


@pytest.mark.parametrize(
    "raw,tok", [("15:00:00", "150000"), ("1500", "150000"), ("150000", "150000"), ("x", None)]
)
def test_time_tokens(raw, tok):
    assert ecotaxa._time_token(raw) == tok


def test_every_species_in_the_cast_has_an_ecotaxa_taxon():
    # Keep the two in step: a new species needs a taxon name that resolves on
    # ecotaxa.obs-vlfr.fr (see TAXON_FOR_SPECIES), or it exports unlabelled.
    assert set(SPECIES) <= set(ecotaxa.TAXON_FOR_SPECIES)


# ----------------------------------------------------------------------------
# export, end to end on an ecosim clip.


@pytest.fixture(scope="module")
def eco_bundle(tmp_path_factory):
    d = tmp_path_factory.mktemp("eco")
    out = d / "eco.mp4"
    args = ["--frames", "120", "--fps", "30", "--size", "400x300", "--um-per-px", "4"]
    r = run_cli(
        ECOSIM, "--out", str(out), *args, "--seed", "11", "--cast", "paramecium=4,debris=20"
    )
    assert r.returncode == 0, r.stderr
    r = run_cli(TRACK, str(out), "--min-area", "20", "--no-video")
    assert r.returncode == 0, r.stderr
    r = run_cli(ECOTAXA, "export", str(d / "eco_tracks.csv"), "--images", "4", "--min-frames", "8")
    assert r.returncode == 0, r.stderr
    return d, r.stdout


@pytest.mark.integration
def test_export_writes_an_importable_bundle(eco_bundle):
    d, stdout = eco_bundle
    z = d / "ecotaxa_eco.zip"
    assert z.exists() and z.name in stdout
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
        assert "ecotaxa_eco.tsv" in names  # must start with "ecotaxa" for the importer
        lines = zf.read("ecotaxa_eco.tsv").decode("utf-8").splitlines()
        header, types = lines[0].split("\t"), lines[1].split("\t")
        rows = list(csv.DictReader(lines[2:], fieldnames=header, delimiter="\t"))
        assert set(types) <= {"[t]", "[f]"} and len(types) == len(header)
        for must in ("img_file_name", "img_rank", "object_id", "sample_id", "acq_id", "process_id"):
            assert must in header, must
        for f in ecotaxa.FEATURES:
            assert f"object_{f}" in header, f
        assert "object_speed_mean" in header and "object_tortuosity" in header
        assert "process_pixel" in header and rows[0]["process_pixel"] == "4.0"
        assert "object_date" not in header  # the ecosim sidecar has no date: column dropped
        for r in rows:
            assert r["img_file_name"] in names, r["img_file_name"]
            buf = np.frombuffer(zf.read(r["img_file_name"]), np.uint8)
            assert cv2.imdecode(buf, cv2.IMREAD_COLOR) is not None
            assert re.fullmatch(r"eco_t\d{4}", r["object_id"])
        by_obj: dict[str, list[dict]] = {}
        for r in rows:
            by_obj.setdefault(r["object_id"], []).append(r)
        assert len(by_obj) >= 4
        for obj_rows in by_obj.values():
            ranks = sorted(int(r["img_rank"]) for r in obj_rows)
            assert ranks == list(range(1, len(ranks) + 1)) and len(ranks) <= 4
            first = obj_rows[0]
            for r in obj_rows[1:]:  # object columns repeat on every image row
                assert {k: v for k, v in r.items() if not k.startswith("img_")} == {
                    k: v for k, v in first.items() if not k.startswith("img_")
                }
        labelled = [r for r in rows if r["object_annotation_category"]]
        assert labelled, "ecosim truth should label most tracks"
        assert {r["object_annotation_category"] for r in labelled} <= {"Paramecium", "detritus"}
        assert all(r["object_annotation_status"] == "predicted" for r in labelled)
        # Every labelled Paramecium is bigger than every labelled debris, in µm.
        para = [
            float(r["object_equivalent_diameter"])
            for r in labelled
            if r["object_annotation_category"] == "Paramecium"
        ]
        deb = [
            float(r["object_equivalent_diameter"])
            for r in labelled
            if r["object_annotation_category"] == "detritus"
        ]
        if para and deb:
            assert min(para) > max(deb)
            assert 60 < np.median(para) < 300  # a Paramecium silhouette in µm


@pytest.mark.integration
def test_export_folder_mode_and_explicit_video(eco_bundle, tmp_path):
    d, _ = eco_bundle
    r = run_cli(
        ECOTAXA,
        "export",
        str(d / "eco_tracks.csv"),
        "--folder",
        "--out",
        str(tmp_path),
        "--images",
        "1",
    )
    assert r.returncode == 0, r.stderr
    folder = tmp_path / "ecotaxa_eco"
    tsv = folder / "ecotaxa_eco.tsv"
    assert tsv.exists()
    lines = tsv.read_text().splitlines()
    assert len(lines) - 2 == len(list(folder.glob("*.jpg")))  # one image per object
    r = run_cli(ECOTAXA, "export", str(d / "eco_tracks.csv"), "--video", str(tmp_path / "nope.mp4"))
    assert r.returncode == 2 and "clip not found" in r.stderr


@pytest.mark.integration
def test_export_rejects_bad_inputs(tmp_path):
    bad = tmp_path / "x_tracks.csv"
    bad.write_text("frame,track_id\n1,2\n")
    r = run_cli(ECOTAXA, "export", str(bad))
    assert r.returncode == 2 and "expected columns" in r.stderr
    r = run_cli(ECOTAXA, "export", str(tmp_path / "missing_tracks.csv"))
    assert r.returncode == 2
    r = run_cli(ECOTAXA, "export", str(bad), "--images", "0")
    assert r.returncode == 2  # argparse
    r = run_cli(ECOTAXA)
    assert r.returncode == 2


@pytest.mark.integration
def test_pull_reports_an_unreachable_api(tmp_path):
    r = run_cli(ECOTAXA, "pull", "2748", "--api", "http://127.0.0.1:1", "--out", str(tmp_path))
    assert r.returncode == 1 and "ecotaxa:" in r.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.network
def test_pull_the_planktoscope_reference_project(tmp_path):
    r = run_cli(
        ECOTAXA,
        "pull",
        "2748",
        "--out",
        str(tmp_path),
        "--taxa",
        "Ciliophora",
        "--limit",
        "30",
        "--page",
        "20",
        "--images",
        "2",
        "--min-count",
        "1",
    )
    assert r.returncode == 0, r.stderr
    rows = list(csv.DictReader((tmp_path / "ecotaxa_2748_objects.csv").open()))
    assert len(rows) == 30 and all(r["status"] == "V" for r in rows)
    assert all("Ciliophora" in r["lineage"] for r in rows)
    assert all(r["pixel_um"] == "1.19" for r in rows)
    summary = json.loads((tmp_path / "ecotaxa_2748_summary.json").read_text())
    assert summary["title"].startswith("Planktoscope Pollina")
    assert summary["pixel_um"] == [1.19] and summary["objects"] == 30
    assert sum(t["n"] for t in summary["taxa"].values()) == 30
    assert len(list((tmp_path / "2748").rglob("*.jpg"))) >= 2

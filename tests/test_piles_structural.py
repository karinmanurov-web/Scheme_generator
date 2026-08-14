from __future__ import annotations

import math
from pathlib import Path

import ezdxf

from algo_piles_structural import _remove_all_hatches, _shrink_pile_axes, _source_pile_orientations
from grillage_detector import detect_grillage


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Свайный фундамент" / "сваи.dxf"


def test_mirrored_wing_piles_keep_their_true_affine_axis() -> None:
    assert SOURCE.exists(), f"Pile fixture is missing: {SOURCE}"
    doc = ezdxf.readfile(SOURCE)

    orientations = _source_pile_orientations(doc)
    assert len(orientations) == 140

    angles = [round(math.degrees(item["angle"]) % 360.0) for item in orientations]
    assert angles.count(0) == 96
    assert angles.count(30) == 11
    assert angles.count(150) == 11
    assert angles.count(210) == 11
    assert angles.count(330) == 11


def test_current_grillage_is_detected_as_two_structural_members() -> None:
    assert SOURCE.exists(), f"Pile fixture is missing: {SOURCE}"
    doc = ezdxf.readfile(SOURCE)

    pile_centers = [item["center"] for item in _source_pile_orientations(doc)]

    candidates = detect_grillage(doc, pile_centers)
    assert len(candidates) == 2

    sizes = sorted(
        (
            round(candidate.length),
            round(candidate.width),
            len(candidate.segments),
        )
        for candidate in candidates
    )
    assert sizes == [(25930, 800, 4), (25930, 800, 4)]


def test_line_only_rotated_grillage_is_supported() -> None:
    doc = ezdxf.new()
    msp = doc.modelspace()
    angle = math.radians(30.0)
    ux = (math.cos(angle), math.sin(angle))
    nx = (-ux[1], ux[0])

    def point(along: float, lateral: float) -> tuple[float, float]:
        return (
            ux[0] * along + nx[0] * lateral,
            ux[1] * along + nx[1] * lateral,
        )

    for lateral in (-400.0, 400.0):
        msp.add_line(point(-5000.0, lateral), point(5000.0, lateral))

    pile_centers = [
        point(along, lateral)
        for along in (-4000.0, -2000.0, 0.0, 2000.0, 4000.0)
        for lateral in (-550.0, 550.0)
    ]

    candidates = detect_grillage(doc, pile_centers)
    assert len(candidates) == 1
    assert len(candidates[0].segments) == 2
    assert abs((math.degrees(candidates[0].angle) % 180.0) - 30.0) < 0.1


def test_pile_cross_axes_are_compacted_without_moving_the_pile_center() -> None:
    from algo_piles_structural import _COMPACT_CROSS_LENGTH

    doc = ezdxf.new()
    msp = doc.modelspace()
    center = (1000.0, 2000.0)
    msp.add_lwpolyline(
        [
            (825.0, 1825.0),
            (1175.0, 1825.0),
            (1175.0, 2175.0),
            (825.0, 2175.0),
        ],
        close=True,
        dxfattribs={"layer": "Сваи_Проект"},
    )
    msp.add_line((600.0, 2000.0), (1400.0, 2000.0), dxfattribs={"layer": "Оси_Проект"})
    msp.add_line((1000.0, 1600.0), (1000.0, 2400.0), dxfattribs={"layer": "Оси_Проект"})

    changed = _shrink_pile_axes(doc)
    assert changed == 2

    lines = [e for e in msp if e.dxf.layer == "Оси_Проект"]
    assert len(lines) == 2
    for line in lines:
        length = math.hypot(
            line.dxf.end.x - line.dxf.start.x,
            line.dxf.end.y - line.dxf.start.y,
        )
        assert round(length, 6) == _COMPACT_CROSS_LENGTH
        midpoint = (
            (line.dxf.start.x + line.dxf.end.x) / 2.0,
            (line.dxf.start.y + line.dxf.end.y) / 2.0,
        )
        assert math.hypot(midpoint[0] - center[0], midpoint[1] - center[1]) < 1e-6


def test_hatches_are_removed_from_pile_execution_output() -> None:
    doc = ezdxf.new()
    msp = doc.modelspace()
    hatch = msp.add_hatch(color=7)
    path = hatch.paths.add_polyline_path(
        [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)],
        is_closed=True,
    )
    assert path is not None
    assert len(list(msp.query("HATCH"))) == 1

    removed = _remove_all_hatches(doc)
    assert removed == 1
    assert len(list(msp.query("HATCH"))) == 0

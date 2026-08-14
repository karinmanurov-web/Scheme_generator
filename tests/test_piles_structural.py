from __future__ import annotations

import math
from pathlib import Path

import ezdxf

from algo_piles_structural import _source_pile_orientations
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

    # The production algorithm detects the pile INSERTs; for this fixture they
    # are the 0.35x0.35 geometric block repeated across the field.
    pile_block_name = "A$C11282C60"
    pile_centers = [
        (float(entity.dxf.insert.x), float(entity.dxf.insert.y))
        for entity in doc.modelspace()
        if entity.dxftype() == "INSERT" and entity.dxf.name == pile_block_name
    ]

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

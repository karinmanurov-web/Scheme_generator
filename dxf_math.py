"""Shared engineering math for all DXF-based as-built schemes.

Coordinate contract:
- source DXF coordinates are converted to millimetres first;
- sheet coordinates are physical millimetres on paper;
- drawing scale 1:N is represented by factor=1/N;
- geometry, dimensions and level positions must use the same factor;
- frame/stamp geometry is never scaled by the drawing scale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

A3_W_MM = 420.0
A3_H_MM = 297.0
STANDARD_SCALES = (1, 2, 5, 10, 15, 20, 25, 40, 50, 75, 100, 150, 200, 250, 400, 500, 1000)

# ezdxf $INSUNITS -> millimetres per source drawing unit.
UNIT_TO_MM = {
    0: 1.0,       # Unitless: legacy project convention is mm.
    1: 25.4,      # inch
    2: 304.8,     # foot
    3: 1609344.0, # mile
    4: 1.0,       # mm
    5: 10.0,      # cm
    6: 1000.0,    # m
    7: 1000000.0, # km
    8: 0.0000254, # microinch
    9: 0.0254,    # mil
    10: 914.4,    # yard
    14: 100.0,    # dm
    15: 10000.0,  # dam
    16: 100000.0, # hm
    17: 1000000.0,# gm
}

@dataclass(frozen=True)
class ScalePlan:
    denominator: float
    factor: float
    width_mm: float
    height_mm: float
    usable_width_mm: float
    usable_height_mm: float


def unit_to_mm_from_doc(doc) -> float:
    """Return source-unit -> mm conversion without mutating the source DXF."""
    try:
        units = int(doc.header.get("$INSUNITS", 0) or 0)
    except Exception:
        units = 0
    return UNIT_TO_MM.get(units, 1.0)


def to_mm_xy(point: Sequence[float], unit_factor: float) -> Tuple[float, float]:
    return float(point[0]) * unit_factor, float(point[1]) * unit_factor


def fit_standard_scale(width_mm: float, height_mm: float,
                       usable_width_mm: float, usable_height_mm: float,
                       scales: Iterable[float] = STANDARD_SCALES) -> ScalePlan:
    """Choose the smallest standard denominator that fits the geometry.

    Physical paper size is fixed. Source geometry is reduced by 1/N.
    No arbitrary minimum denominator is applied: small geometry may remain 1:1.
    """
    width_mm = max(0.0, float(width_mm))
    height_mm = max(0.0, float(height_mm))
    usable_width_mm = max(1e-9, float(usable_width_mm))
    usable_height_mm = max(1e-9, float(usable_height_mm))
    required = max(width_mm / usable_width_mm, height_mm / usable_height_mm, 1e-12)
    ordered = tuple(float(s) for s in scales)
    denominator = next((s for s in ordered if s >= required), ordered[-1])
    return ScalePlan(denominator, 1.0 / denominator, width_mm, height_mm,
                     usable_width_mm, usable_height_mm)


def translate_and_scale_xy(point: Sequence[float], min_x: float, min_y: float,
                           factor: float, padding_mm: float = 0.0) -> Tuple[float, float]:
    """Move source bbox minimum to padding, then apply 1:N paper scaling."""
    return ((float(point[0]) - min_x + padding_mm) * factor,
            (float(point[1]) - min_y + padding_mm) * factor)


def bbox_from_points(points: Iterable[Sequence[float]]) -> Tuple[float, float, float, float]:
    pts = [(float(p[0]), float(p[1])) for p in points]
    if not pts:
        raise ValueError("Cannot calculate bbox of empty geometry")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_size(bbox: Sequence[float]) -> Tuple[float, float]:
    return max(0.0, float(bbox[2]) - float(bbox[0])), max(0.0, float(bbox[3]) - float(bbox[1]))


def scaled_length(length_mm: float, factor: float) -> float:
    return float(length_mm) * float(factor)

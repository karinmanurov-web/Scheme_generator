"""Shared engineering math for all DXF-based as-built schemes.

Coordinate contract:
- source DXF coordinates are converted to millimetres first;
- sheet coordinates are physical millimetres on paper;
- drawing scale 1:N is represented by factor=1/N;
- geometry, dimensions and level positions use the same factor;
- frame/stamp geometry is never scaled by drawing scale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

import ezdxf
from ezdxf.math import Matrix44

A3_W_MM = 420.0
A3_H_MM = 297.0
A3_WIDTH_MM = A3_W_MM
A3_HEIGHT_MM = A3_H_MM
FRAME_MARGIN_MM = 10.0
STAMP_W_MM = 185.0
STAMP_H_MM = 55.0
STANDARD_SCALES = (1, 2, 5, 10, 15, 20, 25, 40, 50, 75, 100, 150, 200, 250, 400, 500, 1000)

UNIT_TO_MM = {
    0: 1.0, 1: 25.4, 2: 304.8, 3: 1609344.0, 4: 1.0, 5: 10.0,
    6: 1000.0, 7: 1000000.0, 8: 0.0000254, 9: 0.0254, 10: 914.4,
    14: 100.0, 15: 10000.0, 16: 100000.0, 17: 1000000.0,
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
    try:
        units = int(doc.header.get("$INSUNITS", 0) or 0)
    except Exception:
        units = 0
    return UNIT_TO_MM.get(units, 1.0)


def _transform_layout_entities(layout, transform: Matrix44) -> None:
    for entity in list(layout):
        try:
            entity.transform(transform)
        except Exception:
            continue


def normalize_to_mm(doc) -> float:
    """Normalize all DXF geometry to millimetres exactly once.

    Modelspace, paperspace and block definitions are transformed together.
    This is important because scaling only INSERT coordinates would leave the
    geometry stored inside block definitions in the old unit system.
    """
    factor = unit_to_mm_from_doc(doc)
    if abs(factor - 1.0) < 1e-12:
        try:
            doc.header["$INSUNITS"] = 4
            doc.header["$MEASUREMENT"] = 1
        except Exception:
            pass
        return 1.0

    transform = Matrix44.scale(factor, factor, 1.0)
    for layout in doc.layouts:
        _transform_layout_entities(layout, transform)
    try:
        for block in doc.blocks:
            # BlockTable contains definitions and may expose special *Model_Space
            # / *Paper_Space records already represented by layouts. Transforming
            # them twice would be wrong, so skip those layout-backed definitions.
            if block.name.lower() in {"*model_space", "*paper_space"}:
                continue
            _transform_layout_entities(block, transform)
    except Exception:
        pass
    try:
        doc.header["$INSUNITS"] = 4
        doc.header["$MEASUREMENT"] = 1
    except Exception:
        pass
    return factor


def to_mm_xy(point: Sequence[float], unit_factor: float) -> Tuple[float, float]:
    return float(point[0]) * unit_factor, float(point[1]) * unit_factor


def a3_work_area(frame_margin_mm: float = FRAME_MARGIN_MM, stamp_h_mm: float = STAMP_H_MM, top_margin_mm: float = 8.0, gap_mm: float = 5.0) -> Tuple[float, float]:
    width = A3_W_MM - 2.0 * frame_margin_mm - gap_mm
    height = A3_H_MM - 2.0 * frame_margin_mm - stamp_h_mm - top_margin_mm
    return max(width, 1.0), max(height, 1.0)


def fit_standard_scale(width_mm: float, height_mm: float, usable_width_mm: float, usable_height_mm: float, scales: Iterable[float] = STANDARD_SCALES) -> ScalePlan:
    width_mm = max(0.0, float(width_mm))
    height_mm = max(0.0, float(height_mm))
    usable_width_mm = max(1e-9, float(usable_width_mm))
    usable_height_mm = max(1e-9, float(usable_height_mm))
    required = max(width_mm / usable_width_mm, height_mm / usable_height_mm, 1e-12)
    ordered = tuple(sorted(float(s) for s in scales if float(s) > 0))
    if not ordered:
        raise ValueError("No valid drawing scales configured")
    denominator = next((s for s in ordered if s >= required), None)
    if denominator is None:
        raise ValueError(f"Geometry {width_mm:.1f}x{height_mm:.1f} mm does not fit the usable sheet area even at 1:{ordered[-1]:g}")
    return ScalePlan(denominator, 1.0 / denominator, width_mm, height_mm, usable_width_mm, usable_height_mm)


def choose_standard_scale(width_mm: float, height_mm: float, usable_width_mm: float = None, usable_height_mm: float = None) -> float:
    if usable_width_mm is None or usable_height_mm is None:
        usable_width_mm, usable_height_mm = a3_work_area()
    return fit_standard_scale(width_mm, height_mm, usable_width_mm, usable_height_mm).denominator


def fit_standard_scale_for_bbox(bbox: Sequence[float], usable_width_mm: float | None = None, usable_height_mm: float | None = None, scales: Iterable[float] = STANDARD_SCALES) -> ScalePlan:
    width, height = bbox_size(bbox)
    if usable_width_mm is None or usable_height_mm is None:
        usable_width_mm, usable_height_mm = a3_work_area()
    return fit_standard_scale(width, height, usable_width_mm, usable_height_mm, scales)


def translate_and_scale_xy(point: Sequence[float], min_x: float, min_y: float, factor: float, padding_mm: float = 0.0) -> Tuple[float, float]:
    return ((float(point[0]) - min_x) * float(factor) + float(padding_mm), (float(point[1]) - min_y) * float(factor) + float(padding_mm))


def bbox_from_points(points: Iterable[Sequence[float]]) -> Tuple[float, float, float, float]:
    pts = [(float(p[0]), float(p[1])) for p in points]
    if not pts:
        raise ValueError("Cannot calculate bbox of empty geometry")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_size(bbox: Sequence[float]) -> Tuple[float, float]:
    if hasattr(bbox, "extmin") and hasattr(bbox, "extmax"):
        return max(0.0, float(bbox.extmax.x - bbox.extmin.x)), max(0.0, float(bbox.extmax.y - bbox.extmin.y))
    return max(0.0, float(bbox[2]) - float(bbox[0])), max(0.0, float(bbox[3]) - float(bbox[1]))


def bbox_mm(bbox) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    if not bbox.has_data:
        raise ValueError("Cannot calculate bbox of empty geometry")
    return (float(bbox.extmin.x), float(bbox.extmin.y)), (float(bbox.extmax.x), float(bbox.extmax.y))


def scaled_length(length_mm: float, factor: float) -> float:
    return float(length_mm) * float(factor)


def scale_geometry_value(value: float, factor: float) -> float:
    return float(value) * float(factor)


def paper_point_from_source(point_mm: Sequence[float], source_bbox: Sequence[float], plan: ScalePlan, origin_mm: Sequence[float]) -> Tuple[float, float]:
    return (float(origin_mm[0]) + (float(point_mm[0]) - float(source_bbox[0])) * plan.factor, float(origin_mm[1]) + (float(point_mm[1]) - float(source_bbox[1])) * plan.factor)

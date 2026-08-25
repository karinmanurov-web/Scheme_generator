"""Common DXF engineering pipeline used by all scheme plugins.

This module deliberately contains no scheme-specific drawing logic. It defines
one coordinate contract so individual plugins cannot silently invent their own
unit conversion, scale direction, or paper-space transform.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

from dxf_math import (
    A3_H_MM,
    A3_W_MM,
    ScalePlan,
    bbox_from_points,
    bbox_size,
    fit_standard_scale,
    paper_point_from_source,
    unit_to_mm_from_doc,
)


@dataclass(frozen=True)
class SourceGeometry:
    """Normalized source extents in millimetres."""
    bbox: Tuple[float, float, float, float]
    unit_factor: float

    @property
    def width_mm(self) -> float:
        return bbox_size(self.bbox)[0]

    @property
    def height_mm(self) -> float:
        return bbox_size(self.bbox)[1]


def normalize_point(point: Sequence[float], unit_factor: float) -> Tuple[float, float]:
    return float(point[0]) * unit_factor, float(point[1]) * unit_factor


def normalize_points(points: Iterable[Sequence[float]], unit_factor: float):
    return [normalize_point(p, unit_factor) for p in points]


def source_geometry(points: Iterable[Sequence[float]], unit_factor: float) -> SourceGeometry:
    normalized = normalize_points(points, unit_factor)
    return SourceGeometry(bbox=bbox_from_points(normalized), unit_factor=unit_factor)


def source_geometry_from_doc(points: Iterable[Sequence[float]], doc) -> SourceGeometry:
    return source_geometry(points, unit_to_mm_from_doc(doc))


def make_a3_scale_plan(
    geometry: SourceGeometry,
    margin_left_mm: float = 20.0,
    margin_right_mm: float = 20.0,
    margin_bottom_mm: float = 20.0,
    margin_top_mm: float = 20.0,
    allow_rotation: bool = True,
) -> ScalePlan:
    usable_w = A3_W_MM - float(margin_left_mm) - float(margin_right_mm)
    usable_h = A3_H_MM - float(margin_bottom_mm) - float(margin_top_mm)
    return fit_standard_scale(
        geometry.width_mm,
        geometry.height_mm,
        usable_w,
        usable_h,
        allow_rotation=allow_rotation,
    )


def to_paper_point(
    point_mm: Sequence[float],
    geometry: SourceGeometry,
    plan: ScalePlan,
    origin_mm: Sequence[float],
) -> Tuple[float, float]:
    """Map a normalized source-mm point to physical A3 paper millimetres."""
    return paper_point_from_source(point_mm, geometry.bbox, plan, origin_mm)


def paper_size(geometry: SourceGeometry, plan: ScalePlan) -> Tuple[float, float]:
    """Return the actual drawing footprint on paper in millimetres."""
    if plan.rotated:
        return geometry.height_mm * plan.factor, geometry.width_mm * plan.factor
    return geometry.width_mm * plan.factor, geometry.height_mm * plan.factor

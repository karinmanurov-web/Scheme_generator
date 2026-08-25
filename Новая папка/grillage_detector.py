"""Geometry-based detection helpers for pile-foundation execution sheets.

The detector never relies on source layer/block names. It recognizes grillage
from geometry and its relationship to the detected pile field.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from ezdxf import bbox as ezdxf_bbox


@dataclass
class GeometrySegment:
    start: tuple[float, float]
    end: tuple[float, float]
    length: float
    angle: float
    center: tuple[float, float]
    source_entity: object


@dataclass
class GrillageCandidate:
    segments: list[GeometrySegment] = field(default_factory=list)
    hatch_boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    angle: float = 0.0
    confidence: float = 0.0
    reason: str = ""

    @property
    def width(self) -> float:
        if not self.bbox:
            return 0.0
        return min(self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1])

    @property
    def length(self) -> float:
        if not self.bbox:
            return 0.0
        return max(self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1])


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _angle_mod_pi(dx, dy):
    return math.atan2(dy, dx) % math.pi


def _angle_diff(a, b):
    d = abs((a - b) % math.pi)
    return min(d, math.pi - d)


def _point_segment_distance(point, seg):
    px, py = point
    ax, ay = seg.start
    bx, by = seg.end
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 1e-12:
        return _distance(point, seg.start)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom))
    q = (ax + t * dx, ay + t * dy)
    return _distance(point, q)


def _entity_segments(entity, transform=None):
    etype = entity.dxftype()
    if etype == "LINE":
        points = [
            (float(entity.dxf.start.x), float(entity.dxf.start.y)),
            (float(entity.dxf.end.x), float(entity.dxf.end.y)),
        ]
    elif etype == "LWPOLYLINE":
        raw = list(entity.get_points())
        points = [(float(p[0]), float(p[1])) for p in raw]
        if getattr(entity, "closed", False) and len(points) > 1:
            points.append(points[0])
    elif etype == "POLYLINE":
        points = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
        if getattr(entity, "is_closed", False) and len(points) > 1:
            points.append(points[0])
    else:
        return []

    result = []
    for a, b in zip(points, points[1:]):
        if transform:
            a, b = transform(a), transform(b)
        length = _distance(a, b)
        if length < 100.0:
            continue
        result.append(
            GeometrySegment(
                start=a,
                end=b,
                length=length,
                angle=_angle_mod_pi(b[0] - a[0], b[1] - a[1]),
                center=((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0),
                source_entity=entity,
            )
        )
    return result


def _world_transform(insert, parent_transform):
    ix, iy = float(insert.dxf.insert.x), float(insert.dxf.insert.y)
    sx = float(getattr(insert.dxf, "xscale", 1.0))
    sy = float(getattr(insert.dxf, "yscale", 1.0))
    rot = math.radians(float(getattr(insert.dxf, "rotation", 0.0)))
    c, s = math.cos(rot), math.sin(rot)

    def local(point):
        x, y = point
        x, y = x * sx, y * sy
        return (ix + c * x - s * y, iy + s * x + c * y)

    return lambda point: parent_transform(local(point))


def collect_world_segments(doc):
    segments = []

    def walk(entities, parent_transform=lambda p: p, stack=()):
        for entity in entities:
            etype = entity.dxftype()
            if etype in ("LINE", "LWPOLYLINE", "POLYLINE"):
                segments.extend(_entity_segments(entity, parent_transform))
            elif etype == "INSERT":
                name = str(entity.dxf.name)
                if name not in doc.blocks or name in stack:
                    continue
                walk(
                    doc.blocks[name],
                    _world_transform(entity, parent_transform),
                    stack + (name,),
                )

    walk(doc.modelspace())
    return segments


def collect_hatch_boxes(doc):
    boxes = []
    for hatch in doc.modelspace().query("HATCH"):
        try:
            box = ezdxf_bbox.extents([hatch])
            if box.has_data:
                boxes.append(
                    (
                        float(box.extmin.x),
                        float(box.extmin.y),
                        float(box.extmax.x),
                        float(box.extmax.y),
                    )
                )
        except Exception:
            continue
    return boxes


def _bbox_of_segments(segments):
    segs = list(segments)
    if not segs:
        return None
    xs = [p for s in segs for p in (s.start[0], s.end[0])]
    ys = [p for s in segs for p in (s.start[1], s.end[1])]
    return min(xs), min(ys), max(xs), max(ys)


def _dominant_segment_angle(segments):
    c = s = 0.0
    for seg in segments:
        weight = max(seg.length, 1.0)
        c += math.cos(2.0 * seg.angle) * weight
        s += math.sin(2.0 * seg.angle) * weight
    return 0.5 * math.atan2(s, c)


def _piles_near_corridor(pile_centers, segments, padding=700.0):
    if not segments:
        return []
    return [
        point
        for point in pile_centers
        if min(_point_segment_distance(point, seg) for seg in segments) <= padding
    ]


def _two_sided_pile_evidence(pile_centers, long_a, long_b):
    """Check that piles flank the member instead of merely lying along it."""
    dx = long_a.end[0] - long_a.start[0]
    dy = long_a.end[1] - long_a.start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return 0, 0, 0.0

    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    mx = (long_a.center[0] + long_b.center[0]) / 2.0
    my = (long_a.center[1] + long_b.center[1]) / 2.0
    separation = abs((long_b.center[0] - long_a.center[0]) * nx + (long_b.center[1] - long_a.center[1]) * ny)

    left = right = 0
    for px, py in pile_centers:
        along = (px - mx) * ux + (py - my) * uy
        lateral = (px - mx) * nx + (py - my) * ny
        if abs(along) > length * 0.60:
            continue
        if 0.15 * separation <= lateral <= 1.6 * separation:
            left += 1
        elif -1.6 * separation <= lateral <= -0.15 * separation:
            right += 1

    return left, right, separation


def _closed_polyline_candidates(doc, pile_centers):
    candidates = []
    for entity in doc.modelspace():
        if entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
            continue
        try:
            if entity.dxftype() == "LWPOLYLINE":
                if not entity.closed:
                    continue
            elif not entity.is_closed:
                continue

            segs = _entity_segments(entity)
            if len(segs) != 4:
                continue

            lengths = sorted((seg.length for seg in segs), reverse=True)
            long_side, short_side = lengths[0], lengths[-1]
            if long_side < 3000.0 or short_side > 2500.0 or long_side / max(short_side, 1.0) < 5.0:
                continue

            if _angle_diff(segs[0].angle, segs[2].angle) > math.radians(3):
                continue
            if _angle_diff(segs[1].angle, segs[3].angle) > math.radians(3):
                continue

            near = _piles_near_corridor(pile_centers, segs, padding=max(700.0, short_side * 0.9))
            if len(near) < 6:
                continue

            bbox = _bbox_of_segments(segs)
            angle = _dominant_segment_angle([segs[0], segs[2]])
            candidates.append(
                GrillageCandidate(
                    segments=segs,
                    bbox=bbox,
                    angle=angle,
                    confidence=0.94,
                    reason="closed elongated rectangular geometry + nearby pile field",
                )
            )
        except Exception:
            continue
    return candidates


def _line_pair_candidates(segments, pile_centers):
    candidates = []
    long_segments = [seg for seg in segments if seg.length >= 3000.0]

    for i, first in enumerate(long_segments):
        for second in long_segments[i + 1:]:
            if _angle_diff(first.angle, second.angle) > math.radians(3):
                continue

            dx = first.end[0] - first.start[0]
            dy = first.end[1] - first.start[1]
            length = math.hypot(dx, dy)
            if length <= 1e-6:
                continue
            ux, uy = dx / length, dy / length
            nx, ny = -uy, ux

            separation = abs((second.center[0] - first.center[0]) * nx + (second.center[1] - first.center[1]) * ny)
            if not (150.0 <= separation <= 2500.0):
                continue

            projections_second = [
                (second.start[0] - first.start[0]) * ux + (second.start[1] - first.start[1]) * uy,
                (second.end[0] - first.start[0]) * ux + (second.end[1] - first.start[1]) * uy,
            ]
            lo = max(0.0, min(projections_second))
            hi = min(length, max(projections_second))
            overlap = max(0.0, hi - lo)
            if overlap / min(first.length, second.length) < 0.60:
                continue

            left, right, _ = _two_sided_pile_evidence(pile_centers, first, second)
            if left < 3 or right < 3:
                continue

            bbox = _bbox_of_segments([first, second])
            candidates.append(
                GrillageCandidate(
                    segments=[first, second],
                    bbox=bbox,
                    angle=first.angle,
                    confidence=0.88,
                    reason="two parallel long members + two-sided pile field",
                )
            )
    return candidates


def _hatch_boundary_segments(hatch_box, segments):
    """Select the structural boundary represented by a hatch, not all nearby lines."""
    hx0, hy0, hx1, hy1 = hatch_box
    tol = 100.0

    inside = []
    for seg in segments:
        if (
            hx0 - tol <= seg.start[0] <= hx1 + tol
            and hy0 - tol <= seg.start[1] <= hy1 + tol
            and hx0 - tol <= seg.end[0] <= hx1 + tol
            and hy0 - tol <= seg.end[1] <= hy1 + tol
        ):
            inside.append(seg)

    if not inside:
        return []

    longest = max(inside, key=lambda s: s.length)
    dominant = longest.angle
    parallel = [
        seg for seg in inside
        if _angle_diff(seg.angle, dominant) <= math.radians(3.0)
    ]
    parallel.sort(key=lambda s: s.length, reverse=True)

    chosen = []
    for seg in parallel:
        if seg.length < 0.35 * parallel[0].length:
            continue
        if not any(
            _distance(seg.center, other.center) < max(seg.length, other.length) * 0.05
            for other in chosen
        ):
            chosen.append(seg)
        if len(chosen) == 2:
            break

    if len(chosen) < 2:
        chosen = parallel[:2]

    if len(chosen) >= 2:
        short = [
            seg for seg in inside
            if _angle_diff(seg.angle, chosen[0].angle) >= math.radians(80.0)
        ]
        for seg in sorted(short, key=lambda s: s.length):
            if any(
                min(
                    _distance(seg.start, long_seg.start),
                    _distance(seg.start, long_seg.end),
                    _distance(seg.end, long_seg.start),
                    _distance(seg.end, long_seg.end),
                ) <= 150.0
                for long_seg in chosen
            ):
                chosen.append(seg)
                if len(chosen) == 4:
                    break

    return chosen


def _hatch_candidates(doc, pile_centers, segments):
    candidates = []
    for hatch_box in collect_hatch_boxes(doc):
        boundary = _hatch_boundary_segments(hatch_box, segments)
        if len(boundary) < 2:
            continue

        near = _piles_near_corridor(pile_centers, boundary, padding=900.0)
        if len(near) < 6:
            continue

        angle = _dominant_segment_angle(boundary)
        candidates.append(
            GrillageCandidate(
                segments=boundary,
                hatch_boxes=[hatch_box],
                bbox=hatch_box,
                angle=angle,
                confidence=0.97,
                reason="hatch + detected boundary geometry + nearby pile field",
            )
        )
    return candidates


def _overlap(a, b, tolerance=100.0):
    if not a or not b:
        return False
    return not (
        a[2] < b[0] - tolerance
        or b[2] < a[0] - tolerance
        or a[3] < b[1] - tolerance
        or b[3] < a[1] - tolerance
    )


def detect_grillage(doc, pile_centers: Iterable[tuple[float, float]]):
    """Detect central grillage while rejecting diagonal wing geometry.

    Evidence is intentionally multi-factor:
    - hatch/closed elongated rectangle is strong evidence;
    - line-only grillage needs two long parallel members;
    - line-only members must have piles on both sides;
    - source layer/block names are never consulted.
    """
    pile_centers = list(pile_centers)
    segments = collect_world_segments(doc)

    candidates = []
    candidates.extend(_hatch_candidates(doc, pile_centers, segments))
    candidates.extend(_closed_polyline_candidates(doc, pile_centers))
    candidates.extend(_line_pair_candidates(segments, pile_centers))

    result = []
    for candidate in sorted(candidates, key=lambda c: c.confidence, reverse=True):
        if candidate.bbox and any(_overlap(candidate.bbox, other.bbox) for other in result):
            continue
        result.append(candidate)
    return result


def infer_pile_axis(point, segments):
    """Fallback axis inference for pile geometry that is not an INSERT block."""
    candidates = []
    for seg in segments:
        d = _point_segment_distance(point, seg)
        if d > 2500.0 or seg.length < 500.0:
            continue
        weight = seg.length / (1.0 + d / 500.0)
        candidates.append((seg.angle, weight))

    if not candidates:
        return 0.0, 0.0

    c = s = total = 0.0
    for angle, weight in candidates:
        c += math.cos(2.0 * angle) * weight
        s += math.sin(2.0 * angle) * weight
        total += weight

    angle = 0.5 * math.atan2(s, c)
    resultant = math.hypot(c, s) / total if total else 0.0
    return angle, resultant

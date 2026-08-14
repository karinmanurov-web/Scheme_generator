"""Geometry-based detection helpers for pile-foundation execution sheets.

The detector intentionally avoids source layer/block names. It uses geometry,
spatial relationships and (when available) hatch evidence.  It is conservative:
only high-confidence grillage candidates are returned for rendering.
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


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _angle_mod_pi(dx: float, dy: float) -> float:
    return math.atan2(dy, dx) % math.pi


def _point_segment_distance(point: tuple[float, float], seg: GeometrySegment) -> float:
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


def _entity_segments(entity, transform=None) -> list[GeometrySegment]:
    """Extract straight segments from LINE/LWPOLYLINE/POLYLINE entities."""
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

    result: list[GeometrySegment] = []
    for a, b in zip(points, points[1:]):
        if transform:
            a = transform(a)
            b = transform(b)
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
    """Return an affine point transform for an INSERT in a nested block."""
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


def collect_world_segments(doc) -> list[GeometrySegment]:
    """Collect straight structural geometry from modelspace and nested blocks."""
    segments: list[GeometrySegment] = []

    def walk(entities, parent_transform=lambda p: p, stack=()):
        for entity in entities:
            etype = entity.dxftype()
            if etype in ("LINE", "LWPOLYLINE", "POLYLINE"):
                segments.extend(_entity_segments(entity, parent_transform))
            elif etype == "INSERT":
                name = str(entity.dxf.name)
                if name not in doc.blocks or name in stack:
                    continue
                walk(doc.blocks[name], _world_transform(entity, parent_transform), stack + (name,))

    walk(doc.modelspace())
    return segments


def collect_hatch_boxes(doc) -> list[tuple[float, float, float, float]]:
    boxes = []
    for hatch in doc.modelspace().query("HATCH"):
        try:
            box = ezdxf_bbox.extents([hatch])
            if box.has_data:
                boxes.append((float(box.extmin.x), float(box.extmin.y), float(box.extmax.x), float(box.extmax.y)))
        except Exception:
            continue
    return boxes


def _bbox_of_segments(segments: Iterable[GeometrySegment]):
    segs = list(segments)
    if not segs:
        return None
    xs = [p for s in segs for p in (s.start[0], s.end[0])]
    ys = [p for s in segs for p in (s.start[1], s.end[1])]
    return min(xs), min(ys), max(xs), max(ys)


def _box_overlap(a, b, tolerance=250.0):
    return not (
        a[2] < b[0] - tolerance or b[2] < a[0] - tolerance or
        a[3] < b[1] - tolerance or b[3] < a[1] - tolerance
    )


def _candidate_from_hatch(hatch_box, segments, pile_centers):
    hx0, hy0, hx1, hy1 = hatch_box
    expanded = (hx0 - 700, hy0 - 700, hx1 + 700, hy1 + 700)
    matched = []
    for seg in segments:
        sb = (min(seg.start[0], seg.end[0]), min(seg.start[1], seg.end[1]), max(seg.start[0], seg.end[0]), max(seg.start[1], seg.end[1]))
        if _box_overlap(sb, expanded, tolerance=50):
            matched.append(seg)

    if not matched:
        return None

    near_piles = sum(
        1 for point in pile_centers
        if expanded[0] <= point[0] <= expanded[2] and expanded[1] <= point[1] <= expanded[3]
    )
    angle = _dominant_segment_angle(matched)
    confidence = 0.60
    if near_piles >= 6:
        confidence += 0.15
    if len(matched) >= 4:
        confidence += 0.10
    if max(hx1 - hx0, hy1 - hy0) >= 5 * max(1.0, min(hx1 - hx0, hy1 - hy0)):
        confidence += 0.10
    return GrillageCandidate(matched, [hatch_box], hatch_box, angle, min(confidence, 0.99), "hatch + elongated structural boundary + nearby piles")


def _dominant_segment_angle(segments):
    c = s = 0.0
    for seg in segments:
        weight = max(seg.length, 1.0)
        c += math.cos(2.0 * seg.angle) * weight
        s += math.sin(2.0 * seg.angle) * weight
    return 0.5 * math.atan2(s, c)


def detect_grillage(doc, pile_centers: Iterable[tuple[float, float]]) -> list[GrillageCandidate]:
    """Return only high-confidence grillage candidates.

    Hatches are strong evidence but not required.  For line-only grillage the
    detector accepts a closed, elongated line group with nearby piles.  Open
    pairs of lines are deliberately left as diagnostic-only candidates so a
    diagonal wing/abutment cannot be mistaken for a grillage.
    """
    pile_centers = list(pile_centers)
    segments = collect_world_segments(doc)
    candidates: list[GrillageCandidate] = []

    for hatch_box in collect_hatch_boxes(doc):
        candidate = _candidate_from_hatch(hatch_box, segments, pile_centers)
        if candidate:
            candidates.append(candidate)

    # Closed elongated polyline/line groups without hatch: conservative fallback.
    # We use a simple connected-component pass on segment endpoints.
    unused = set(range(len(segments)))
    while unused:
        seed = unused.pop()
        group = {seed}
        changed = True
        while changed:
            changed = False
            for idx in list(unused):
                seg = segments[idx]
                if any(
                    min(_distance(seg.start, segments[j].start), _distance(seg.start, segments[j].end),
                        _distance(seg.end, segments[j].start), _distance(seg.end, segments[j].end)) <= 5.0
                    for j in group
                ):
                    group.add(idx)
                    unused.remove(idx)
                    changed = True
        group_segments = [segments[i] for i in group]
        box = _bbox_of_segments(group_segments)
        if not box:
            continue
        w, h = box[2] - box[0], box[3] - box[1]
        long_side, short_side = max(w, h), max(1.0, min(w, h))
        if long_side / short_side < 5.0 or long_side < 3000.0 or len(group_segments) < 4:
            continue
        near_piles = sum(1 for p in pile_centers if box[0] - 700 <= p[0] <= box[2] + 700 and box[1] - 700 <= p[1] <= box[3] + 700)
        if near_piles < 6:
            continue
        angle = _dominant_segment_angle(group_segments)
        candidates.append(GrillageCandidate(group_segments, [], box, angle, 0.86, "closed elongated line group + nearby piles"))

    # Deduplicate overlapping candidates, keeping the strongest evidence.
    result: list[GrillageCandidate] = []
    for candidate in sorted(candidates, key=lambda c: c.confidence, reverse=True):
        if candidate.bbox and any(other.bbox and _box_overlap(candidate.bbox, other.bbox, tolerance=100) for other in result):
            continue
        result.append(candidate)
    return result


def infer_pile_axis(point: tuple[float, float], segments: list[GeometrySegment]) -> tuple[float, float]:
    """Infer local pile orientation from nearby structural geometry.

    Returns (angle_radians, confidence).  Long nearby members dominate, which
    makes diagonal wings follow their actual structural axis instead of relying
    on an arbitrary block rotation.
    """
    candidates = []
    for seg in segments:
        d = _point_segment_distance(point, seg)
        if d > 2500.0 or seg.length < 500.0:
            continue
        weight = seg.length / (1.0 + d / 500.0)
        candidates.append((seg.angle, weight, d, seg.length))
    if not candidates:
        return 0.0, 0.0

    c = s = 0.0
    total = 0.0
    for angle, weight, _d, _length in candidates:
        c += math.cos(2.0 * angle) * weight
        s += math.sin(2.0 * angle) * weight
        total += weight
    angle = 0.5 * math.atan2(s, c)
    resultant = math.hypot(c, s) / total if total else 0.0
    return angle, resultant

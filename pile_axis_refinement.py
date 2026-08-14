"""Refinement of pile-axis inference for diagonal structural wings."""

from __future__ import annotations

import math


def _point_segment_distance(point, seg):
    px, py = point
    ax, ay = seg.start
    bx, by = seg.end
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)


def infer_pile_axis(point, segments):
    """Prefer the nearest long structural member; fall back to base inference.

    This fixes the junction area of diagonal wings where a pile is close to a
    horizontal main member. The actual wing member is closer and is much longer
    than local annotation geometry, so its axis is the better structural cue.
    """
    long = []
    for seg in segments:
        if seg.length < 4000.0:
            continue
        distance = _point_segment_distance(point, seg)
        if distance <= 1800.0:
            long.append((distance, -seg.length, seg.angle))

    if long:
        distance, neg_length, angle = min(long)
        confidence = max(0.70, min(0.99, 1.0 - distance / 5000.0))
        return angle, confidence

    # No sufficiently long structural member nearby: use the conservative
    # weighted estimator from the general detector.
    candidates = []
    for seg in segments:
        if seg.length < 500.0:
            continue
        distance = _point_segment_distance(point, seg)
        if distance <= 2500.0:
            candidates.append((seg.angle, seg.length / (1.0 + distance / 500.0)))
    if not candidates:
        return 0.0, 0.0

    c = s = total = 0.0
    for angle, weight in candidates:
        c += math.cos(2.0 * angle) * weight
        s += math.sin(2.0 * angle) * weight
        total += weight
    angle = 0.5 * math.atan2(s, c)
    confidence = math.hypot(c, s) / total if total else 0.0
    return angle, confidence

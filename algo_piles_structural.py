"""Structural post-processing for the pile execution-sheet algorithm.

This module keeps the base pile extraction/randomized deviations intact and fixes
presentation geometry that depends on structural context:
- pile symbols in mirrored/nested source blocks inherit the true affine axis;
- grillage geometry is copied from the source without depending on layer/block names;
- machine-readable diagnostics are written next to the generated DXF.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.math import Matrix44

import algo_piles_fixed as _base
from grillage_detector import collect_world_segments, detect_grillage, infer_pile_axis

ALGORITHM_NAME = _base.ALGORITHM_NAME
PREVIEW_IMAGE = _base.PREVIEW_IMAGE
generate_table_data = _base.generate_table_data
process_dxf_to_asbuilt_scheme = _base.process_dxf_to_asbuilt_scheme

_PILE_OUTPUT_LAYERS = {
    "Сваи_Проект",
    "Оси_Проект",
    "Исполнительная_Номера",
    "Исполнительная_Отклонения",
}


def _entity_center(entity):
    try:
        box = ezdxf_bbox.extents([entity])
        if box.has_data:
            return (
                (float(box.extmin.x) + float(box.extmax.x)) / 2.0,
                (float(box.extmin.y) + float(box.extmax.y)) / 2.0,
            )
    except Exception:
        return None
    return None


def _polyline_center(entity):
    try:
        points = list(entity.get_points())
        if len(points) >= 3:
            return (
                sum(float(p[0]) for p in points) / len(points),
                sum(float(p[1]) for p in points) / len(points),
            )
    except Exception:
        pass
    return None


def _pile_centers(doc):
    centers = []
    for entity in doc.modelspace():
        try:
            if entity.dxf.layer == "Сваи_Проект" and entity.dxftype() in ("LWPOLYLINE", "POLYLINE"):
                center = _polyline_center(entity)
                if center is not None:
                    centers.append(center)
        except Exception:
            continue

    unique = []
    for point in centers:
        if not any(math.hypot(point[0] - q[0], point[1] - q[1]) < 0.1 for q in unique):
            unique.append(point)
    return unique


def _matrix_apply(matrix, point):
    a, b, c, d, tx, ty = matrix
    x, y = point
    return (a * x + b * y + tx, c * x + d * y + ty)


def _matrix_compose(parent, local):
    """Return parent(local(point)) for two 2D affine transforms."""
    pa, pb, pc, pd, ptx, pty = parent
    la, lb, lc, ld, ltx, lty = local
    return (
        pa * la + pb * lc,
        pa * lb + pb * ld,
        pc * la + pd * lc,
        pc * lb + pd * ld,
        pa * ltx + pb * lty + ptx,
        pc * ltx + pd * lty + pty,
    )


def _insert_matrix(insert):
    rot = math.radians(float(getattr(insert.dxf, "rotation", 0.0)))
    sx = float(getattr(insert.dxf, "xscale", 1.0))
    sy = float(getattr(insert.dxf, "yscale", 1.0))
    cr, sr = math.cos(rot), math.sin(rot)
    return (
        cr * sx,
        -sr * sy,
        sr * sx,
        cr * sy,
        float(insert.dxf.insert.x),
        float(insert.dxf.insert.y),
    )


def _block_local_bbox(block):
    """BBox of direct geometric primitives in a block, excluding nested INSERTs."""
    points = []
    for entity in block:
        try:
            if entity.dxftype() == "LINE":
                points.extend([
                    (float(entity.dxf.start.x), float(entity.dxf.start.y)),
                    (float(entity.dxf.end.x), float(entity.dxf.end.y)),
                ])
            elif entity.dxftype() == "LWPOLYLINE":
                points.extend((float(p[0]), float(p[1])) for p in entity.get_points())
            elif entity.dxftype() == "POLYLINE":
                points.extend((float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices)
            elif entity.dxftype() == "CIRCLE":
                cx, cy, r = float(entity.dxf.center.x), float(entity.dxf.center.y), float(entity.dxf.radius)
                points.extend([(cx - r, cy - r), (cx + r, cy + r)])
        except Exception:
            continue

    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _looks_like_small_pile_block(block_bbox, matrix):
    """Geometric classifier for a small square symbol, independent of its name."""
    if not block_bbox:
        return False
    x0, y0, x1, y1 = block_bbox
    corners = [
        _matrix_apply(matrix, (x0, y0)),
        _matrix_apply(matrix, (x1, y0)),
        _matrix_apply(matrix, (x1, y1)),
        _matrix_apply(matrix, (x0, y1)),
    ]
    width = max(p[0] for p in corners) - min(p[0] for p in corners)
    height = max(p[1] for p in corners) - min(p[1] for p in corners)
    if min(width, height) <= 1e-6:
        return False
    ratio = max(width, height) / min(width, height)
    return ratio <= 1.35 and 200.0 <= max(width, height) <= 700.0


def _source_pile_orientations(doc):
    """Find source pile INSERTs and compute their true affine orientation.

    Simple rotation addition is invalid for mirrored blocks. This traversal
    applies the complete INSERT transform chain, including negative scale.
    """
    found = []
    bbox_cache = {}

    def walk(entities, parent_matrix=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0), stack=()):
        for entity in entities:
            if entity.dxftype() != "INSERT":
                continue

            name = str(entity.dxf.name)
            if name not in doc.blocks or name in stack:
                continue

            matrix = _matrix_compose(parent_matrix, _insert_matrix(entity))
            block = doc.blocks[name]
            if name not in bbox_cache:
                bbox_cache[name] = _block_local_bbox(block)

            if _looks_like_small_pile_block(bbox_cache[name], matrix):
                center = _matrix_apply(matrix, (0.0, 0.0))
                angle = math.atan2(matrix[2], matrix[0])
                found.append({"center": center, "angle": angle, "block": name})

            walk(block, matrix, stack + (name,))

    walk(doc.modelspace())
    return found


def _nearest(point, points):
    if not points:
        return None, float("inf")
    q = min(points, key=lambda p: math.hypot(point[0] - p[0], point[1] - p[1]))
    return q, math.hypot(point[0] - q[0], point[1] - q[1])


def _entity_angle(entity):
    try:
        if entity.dxftype() == "TEXT":
            return math.radians(float(getattr(entity.dxf, "rotation", 0.0)))
        if entity.dxftype() == "LINE":
            return math.atan2(
                float(entity.dxf.end.y) - float(entity.dxf.start.y),
                float(entity.dxf.end.x) - float(entity.dxf.start.x),
            )
        if entity.dxftype() == "LWPOLYLINE":
            points = list(entity.get_points())
            if len(points) >= 2:
                return math.atan2(float(points[1][1]) - float(points[0][1]), float(points[1][0]) - float(points[0][0]))
        if entity.dxftype() == "POLYLINE":
            points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            if len(points) >= 2:
                return math.atan2(float(points[1][1]) - float(points[0][1]), float(points[1][0]) - float(points[0][0]))
    except Exception:
        pass
    return None


def _rotate_about(entity, center, delta):
    if abs(delta) < math.radians(0.05):
        return False
    cx, cy = center
    matrix = Matrix44.chain(
        Matrix44.translate(-cx, -cy, 0),
        Matrix44.z_rotate(delta),
        Matrix44.translate(cx, cy, 0),
    )
    try:
        entity.transform(matrix)
        return True
    except Exception:
        return False


def _orient_piles(doc, source_doc, log=None):
    output_centers = _pile_centers(doc)
    if not output_centers:
        return []

    source_orientations = _source_pile_orientations(source_doc)
    source_points = [item["center"] for item in source_orientations]
    matched = []

    for center in output_centers:
        source_point, distance = _nearest(center, source_points)
        if source_point is None or distance > 300.0:
            continue
        source_item = min(
            source_orientations,
            key=lambda item: math.hypot(item["center"][0] - center[0], item["center"][1] - center[1]),
        )
        matched.append((center, source_item["angle"], 1.0, "source_insert_affine"))

    if len(matched) < len(output_centers):
        segments = collect_world_segments(source_doc)
        matched_centers = {item[0] for item in matched}
        for center in output_centers:
            if center in matched_centers:
                continue
            angle, confidence = infer_pile_axis(center, segments)
            if confidence >= 0.58:
                matched.append((center, angle, confidence, "nearby_structural_geometry"))

    changed = 0
    matched_points = [item[0] for item in matched]
    for entity in list(doc.modelspace()):
        try:
            if entity.dxf.layer not in _PILE_OUTPUT_LAYERS:
                continue
            point = _entity_center(entity)
            if point is None:
                continue
            pile, distance = _nearest(point, matched_points)
            if pile is None or distance > 750.0:
                continue

            target, confidence, _source = next(item[1:] for item in matched if item[0] == pile)
            if confidence < 0.58:
                continue

            current = _entity_angle(entity)
            if current is None:
                continue

            delta = ((target - current + math.pi / 4.0) % (math.pi / 2.0)) - math.pi / 4.0
            if _rotate_about(entity, pile, delta) and abs(delta) >= math.radians(0.05):
                changed += 1
        except Exception:
            continue

    if log:
        log(f"[INFO] Оси свай выровнены по полной affine-трансформации источника: {changed} объектов.")

    return [
        {
            "x": round(center[0], 3),
            "y": round(center[1], 3),
            "angle_deg": round(math.degrees(angle) % 360.0, 3),
            "confidence": round(confidence, 3),
            "source": source,
        }
        for center, angle, confidence, source in matched
    ]


def _copy_grillage(doc_out, source_doc, pile_centers, log=None):
    layer = "Исполнительная_Ростверк"
    if layer not in doc_out.layers:
        doc_out.layers.new(layer, dxfattribs={"color": 7})

    candidates = detect_grillage(source_doc, pile_centers)
    rendered = []
    source_hatches = list(source_doc.modelspace().query("HATCH"))

    for candidate in candidates:
        if candidate.confidence < 0.80 or not candidate.bbox:
            continue

        for hatch in source_hatches:
            try:
                box = ezdxf_bbox.extents([hatch])
                hb = (float(box.extmin.x), float(box.extmin.y), float(box.extmax.x), float(box.extmax.y))
                if max(abs(hb[i] - candidate.bbox[i]) for i in range(4)) <= 2.0:
                    copied = hatch.copy()
                    copied.dxf.layer = layer
                    doc_out.modelspace().add_entity(copied)
                    break
            except Exception:
                continue

        for seg in candidate.segments:
            doc_out.modelspace().add_line(seg.start, seg.end, dxfattribs={"layer": layer, "color": 7})

        rendered.append({
            "bbox": [round(v, 3) for v in candidate.bbox],
            "angle_deg": round(math.degrees(candidate.angle) % 360.0, 3),
            "confidence": round(candidate.confidence, 3),
            "reason": candidate.reason,
            "segments": len(candidate.segments),
        })

    if log:
        log(f"[INFO] Ростверк: кандидатов {len(candidates)}, отрисовано {len(rendered)}.")

    return rendered, [
        {
            "bbox": [round(v, 3) for v in c.bbox] if c.bbox else None,
            "angle_deg": round(math.degrees(c.angle) % 360.0, 3),
            "confidence": round(c.confidence, 3),
            "reason": c.reason,
        }
        for c in candidates
    ]


def run(input_dxf, output_dxf, output_csv=None, log_callback=None, stamp_data=None, table_data=None):
    result = _base.run(
        input_dxf,
        output_dxf,
        output_csv,
        log_callback=log_callback,
        stamp_data=stamp_data,
        table_data=table_data,
    )

    try:
        source_doc = ezdxf.readfile(input_dxf)
        doc_out = ezdxf.readfile(output_dxf)
        centers = _pile_centers(doc_out)

        rendered, candidates = _copy_grillage(doc_out, source_doc, centers, log_callback)
        orientations = _orient_piles(doc_out, source_doc, log_callback)
        doc_out.saveas(output_dxf)

        base = Path(output_dxf)
        base.with_name(base.stem + "_grillage_diagnostic.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "algorithm_id": "piles",
                    "grillage": {"rendered": rendered, "candidates": candidates},
                    "pile_orientations": orientations,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        if log_callback:
            log_callback(f"[ПРЕДУПРЕЖДЕНИЕ] Структурный post-process не выполнен: {exc}")

    return result

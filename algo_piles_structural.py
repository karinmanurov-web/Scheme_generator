"""Structural post-processing for the pile execution-sheet algorithm.

The module deliberately stays geometry-driven: source layer/block names are not
used to identify the grillage, and source DIMENSION anchors are preserved.
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

_PILE_OUTPUT_LAYERS = {"Сваи_Проект", "Оси_Проект", "Исполнительная_Номера", "Исполнительная_Отклонения"}
_COMPACT_CROSS_LENGTH = 500.0
_MIN_EXECUTION_DIMENSION = 100.0
_GRILLAGE_LAYER = "Исполнительная_Ростверк"


def _entity_center(entity):
    try:
        box = ezdxf_bbox.extents([entity])
        if box.has_data:
            return ((box.extmin.x + box.extmax.x) / 2, (box.extmin.y + box.extmax.y) / 2)
    except Exception:
        pass
    return None


def _polyline_center(entity):
    try:
        pts = list(entity.get_points())
        if len(pts) >= 3:
            return (sum(float(p[0]) for p in pts) / len(pts), sum(float(p[1]) for p in pts) / len(pts))
    except Exception:
        pass
    return None


def _pile_centers(doc):
    result = []
    for entity in doc.modelspace():
        try:
            if entity.dxf.layer != "Сваи_Проект" or entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
                continue
            center = _polyline_center(entity)
            if center and not any(math.hypot(center[0]-p[0], center[1]-p[1]) < 0.1 for p in result):
                result.append(center)
        except Exception:
            continue
    return result


def _matrix_apply(matrix, point):
    a, b, c, d, tx, ty = matrix
    x, y = point
    return a*x + b*y + tx, c*x + d*y + ty


def _matrix_compose(parent, local):
    pa, pb, pc, pd, ptx, pty = parent
    la, lb, lc, ld, ltx, lty = local
    return (pa*la + pb*lc, pa*lb + pb*ld, pc*la + pd*lc, pc*lb + pd*ld, pa*ltx + pb*lty + ptx, pc*ltx + pd*lty + pty)


def _insert_matrix(insert):
    rotation = math.radians(float(getattr(insert.dxf, "rotation", 0.0)))
    sx = float(getattr(insert.dxf, "xscale", 1.0))
    sy = float(getattr(insert.dxf, "yscale", 1.0))
    c, s = math.cos(rotation), math.sin(rotation)
    return (c*sx, -s*sy, s*sx, c*sy, float(insert.dxf.insert.x), float(insert.dxf.insert.y))


def _block_bbox(block):
    points = []
    for entity in block:
        try:
            kind = entity.dxftype()
            if kind == "LINE":
                points += [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
            elif kind == "LWPOLYLINE":
                points += [(p[0], p[1]) for p in entity.get_points()]
            elif kind == "POLYLINE":
                points += [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            elif kind == "CIRCLE":
                x, y, r = entity.dxf.center.x, entity.dxf.center.y, entity.dxf.radius
                points += [(x-r, y-r), (x+r, y+r)]
        except Exception:
            continue
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _is_pile_bbox(bbox, matrix):
    if not bbox:
        return False
    x0, y0, x1, y1 = bbox
    corners = [_matrix_apply(matrix, p) for p in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
    width = max(p[0] for p in corners) - min(p[0] for p in corners)
    height = max(p[1] for p in corners) - min(p[1] for p in corners)
    return min(width, height) > 1e-6 and max(width, height)/min(width, height) <= 1.35 and 200 <= max(width, height) <= 700


def _source_pile_orientations(doc):
    found = []
    cache = {}
    def walk(entities, parent=(1,0,0,1,0,0), stack=()):
        for entity in entities:
            if entity.dxftype() != "INSERT":
                continue
            name = str(entity.dxf.name)
            if name not in doc.blocks or name in stack:
                continue
            matrix = _matrix_compose(parent, _insert_matrix(entity))
            block = doc.blocks[name]
            if name not in cache:
                cache[name] = _block_bbox(block)
            if _is_pile_bbox(cache[name], matrix):
                found.append({"center": _matrix_apply(matrix, (0,0)), "angle": math.atan2(matrix[2], matrix[0])})
            walk(block, matrix, stack + (name,))
    walk(doc.modelspace())
    return found


def _nearest(point, points):
    if not points:
        return None, float("inf")
    nearest = min(points, key=lambda p: math.hypot(point[0]-p[0], point[1]-p[1]))
    return nearest, math.hypot(point[0]-nearest[0], point[1]-nearest[1])


def _entity_angle(entity):
    try:
        if entity.dxftype() == "LINE":
            return math.atan2(entity.dxf.end.y-entity.dxf.start.y, entity.dxf.end.x-entity.dxf.start.x)
        if entity.dxftype() == "LWPOLYLINE":
            pts = list(entity.get_points())
            return math.atan2(pts[1][1]-pts[0][1], pts[1][0]-pts[0][0]) if len(pts) > 1 else None
        if entity.dxftype() == "POLYLINE":
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            return math.atan2(pts[1][1]-pts[0][1], pts[1][0]-pts[0][0]) if len(pts) > 1 else None
        if entity.dxftype() == "TEXT":
            return math.radians(float(getattr(entity.dxf, "rotation", 0.0)))
    except Exception:
        pass
    return None


def _rotate_about(entity, center, delta):
    if abs(delta) < math.radians(0.05):
        return False
    cx, cy = center
    try:
        entity.transform(Matrix44.chain(Matrix44.translate(-cx, -cy, 0), Matrix44.z_rotate(delta), Matrix44.translate(cx, cy, 0)))
        return True
    except Exception:
        return False


def _orient_piles(doc, source, log=None):
    centers = _pile_centers(doc)
    source_axes = _source_pile_orientations(source)
    source_points = [item["center"] for item in source_axes]
    matched = []
    for center in centers:
        nearest, distance = _nearest(center, source_points)
        if nearest is not None and distance <= 300:
            item = min(source_axes, key=lambda x: math.hypot(x["center"][0]-center[0], x["center"][1]-center[1]))
            matched.append((center, item["angle"], 1.0, "source_insert_affine"))
    if len(matched) < len(centers):
        segments = collect_world_segments(source)
        used = {item[0] for item in matched}
        for center in centers:
            if center in used:
                continue
            angle, confidence = infer_pile_axis(center, segments)
            if confidence >= 0.58:
                matched.append((center, angle, confidence, "nearby_structural_geometry"))
    matched_points = [item[0] for item in matched]
    changed = 0
    for entity in list(doc.modelspace()):
        try:
            if entity.dxf.layer not in _PILE_OUTPUT_LAYERS:
                continue
            center = _entity_center(entity)
            nearest, distance = _nearest(center, matched_points)
            if nearest is None or distance > 750:
                continue
            target, confidence, _ = next(item[1:] for item in matched if item[0] == nearest)
            if confidence < 0.58:
                continue
            current = _entity_angle(entity)
            if current is None:
                continue
            delta = ((target-current+math.pi/4) % (math.pi/2)) - math.pi/4
            if _rotate_about(entity, nearest, delta):
                changed += 1
        except Exception:
            continue
    if log:
        log(f"[INFO] Оси свай выровнены по affine-трансформации: {changed} объектов.")
    return [{"x": round(c[0],3), "y": round(c[1],3), "angle_deg": round(math.degrees(a)%360,3), "confidence": round(conf,3), "source": source_name} for c,a,conf,source_name in matched]


def _copy_grillage(doc, source, pile_centers, log=None):
    if _GRILLAGE_LAYER not in doc.layers:
        doc.layers.new(_GRILLAGE_LAYER, dxfattribs={"color": 7, "lineweight": 35})
    layer = doc.layers.get(_GRILLAGE_LAYER)
    layer.on(); layer.thaw(); layer.dxf.color = 7; layer.dxf.lineweight = 35
    candidates = detect_grillage(source, pile_centers)
    rendered = []
    for candidate in candidates:
        if candidate.confidence < 0.80 or not candidate.segments:
            continue
        for segment in candidate.segments:
            doc.modelspace().add_line(segment.start, segment.end, dxfattribs={"layer": _GRILLAGE_LAYER, "color": 7, "lineweight": 35})
        rendered.append({"bbox": [round(v,3) for v in candidate.bbox] if candidate.bbox else None, "angle_deg": round(math.degrees(candidate.angle)%360,3), "confidence": round(candidate.confidence,3), "reason": candidate.reason, "segments": len(candidate.segments)})
    actual = sum(1 for e in doc.modelspace() if getattr(e.dxf, "layer", "") == _GRILLAGE_LAYER and e.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE"))
    if log:
        log(f"[INFO] Ростверк: кандидатов {len(candidates)}, отрисовано {len(rendered)}, entities={actual}; hatch не переносится.")
    return rendered, [{"bbox": [round(v,3) for v in c.bbox] if c.bbox else None, "angle_deg": round(math.degrees(c.angle)%360,3), "confidence": round(c.confidence,3), "reason": c.reason} for c in candidates]


def _remove_all_hatches(doc):
    removed = 0
    for entity in list(doc.modelspace()):
        if entity.dxftype() == "HATCH":
            try:
                doc.modelspace().delete_entity(entity)
                removed += 1
            except Exception:
                pass
    return removed


def _shrink_pile_axes(doc, log=None):
    centers = _pile_centers(doc)
    half = _COMPACT_CROSS_LENGTH / 2
    changed = 0
    for entity in list(doc.modelspace()):
        try:
            if entity.dxf.layer != "Оси_Проект" or entity.dxftype() != "LINE":
                continue
            start = (entity.dxf.start.x, entity.dxf.start.y); end = (entity.dxf.end.x, entity.dxf.end.y)
            length = math.hypot(end[0]-start[0], end[1]-start[1])
            if length <= _COMPACT_CROSS_LENGTH:
                continue
            midpoint = ((start[0]+end[0])/2, (start[1]+end[1])/2)
            nearest, distance = _nearest(midpoint, centers)
            if nearest is None or distance > 100:
                continue
            ux, uy = (end[0]-start[0])/length, (end[1]-start[1])/length
            entity.dxf.start = (nearest[0]-ux*half, nearest[1]-uy*half, 0)
            entity.dxf.end = (nearest[0]+ux*half, nearest[1]+uy*half, 0)
            changed += 1
        except Exception:
            continue
    if log and changed:
        log(f"[INFO] Сокращены оси свай: {changed} линий до {_COMPACT_CROSS_LENGTH:.0f} мм.")
    return changed


def _dimension_filter(msp):
    dimensions = _base._piles.extract_source_dimensions(msp)
    return [item for item in dimensions if float(item.get("prj_val", 0)) >= _MIN_EXECUTION_DIMENSION]


# Compatibility names used by the structural regression tests.
_source_pile_axes = lambda doc: [(item["center"], item["angle"]) for item in _source_pile_orientations(doc)]
_remove_hatches = _remove_all_hatches
_shrink_axes = _shrink_pile_axes


def run(input_dxf, output_dxf, output_csv=None, log_callback=None, stamp_data=None, table_data=None):
    original_extract = _base._piles.extract_source_dimensions
    _base._piles.extract_source_dimensions = _dimension_filter
    try:
        result = _base.run(input_dxf, output_dxf, output_csv, log_callback=log_callback, stamp_data=stamp_data, table_data=table_data)
    finally:
        _base._piles.extract_source_dimensions = original_extract

    try:
        source = ezdxf.readfile(input_dxf)
        output = ezdxf.readfile(output_dxf)
        centers = _pile_centers(output)
        _remove_all_hatches(output)
        rendered, candidates = _copy_grillage(output, source, centers, log_callback)
        _remove_all_hatches(output)
        layer = output.layers.get(_GRILLAGE_LAYER)
        layer.on(); layer.thaw(); layer.dxf.color = 7; layer.dxf.lineweight = 35
        orientations = _orient_piles(output, source, log_callback)
        _shrink_pile_axes(output, log_callback)
        output.saveas(output_dxf)
        base = Path(output_dxf)
        base.with_name(base.stem + "_grillage_diagnostic.json").write_text(json.dumps({"schema_version": 5, "algorithm_id": "piles", "presentation_rules": {"hatches": "forbidden", "cross_length_mm": _COMPACT_CROSS_LENGTH, "min_dimension_value": _MIN_EXECUTION_DIMENSION, "dimensions": "source_anchors_only"}, "grillage": {"rendered": rendered, "candidates": candidates}, "pile_orientations": orientations}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        if log_callback:
            log_callback(f"[ПРЕДУПРЕЖДЕНИЕ] Structural post-process не выполнен: {exc}")
    return result

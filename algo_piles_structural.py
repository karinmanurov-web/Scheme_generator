"""Structural post-processing for the pile execution-sheet algorithm.

Keeps the existing pile extraction and randomized deviations intact while
adding two geometry-driven presentation fixes:
1) high-confidence grillage geometry is transferred to the generated layer;
2) generated pile symbols follow the local structural axis inferred from
   source geometry rather than trusting an arbitrary block rotation.
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


def _entity_center(entity):
    try:
        box = ezdxf_bbox.extents([entity])
        if box.has_data:
            return ((float(box.extmin.x) + float(box.extmax.x)) / 2.0,
                    (float(box.extmin.y) + float(box.extmax.y)) / 2.0)
    except Exception:
        return None
    return None


def _polyline_center(entity):
    try:
        points = list(entity.get_points())
        if len(points) >= 3:
            return (sum(float(p[0]) for p in points) / len(points),
                    sum(float(p[1]) for p in points) / len(points))
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


def _entity_angle(entity):
    try:
        if entity.dxftype() == "TEXT":
            return math.radians(float(getattr(entity.dxf, "rotation", 0.0)))
        if entity.dxftype() == "LINE":
            return math.atan2(float(entity.dxf.end.y) - float(entity.dxf.start.y),
                              float(entity.dxf.end.x) - float(entity.dxf.start.x))
        if entity.dxftype() == "LWPOLYLINE":
            points = list(entity.get_points())
            if len(points) >= 2:
                return math.atan2(float(points[1][1]) - float(points[0][1]),
                                  float(points[1][0]) - float(points[0][0]))
        if entity.dxftype() == "POLYLINE":
            points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            if len(points) >= 2:
                return math.atan2(float(points[1][1]) - float(points[0][1]),
                                  float(points[1][0]) - float(points[0][0]))
    except Exception:
        pass
    return None


def _nearest(point, points):
    if not points:
        return None, float("inf")
    q = min(points, key=lambda p: math.hypot(point[0] - p[0], point[1] - p[1]))
    return q, math.hypot(point[0] - q[0], point[1] - q[1])


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
    segments = collect_world_segments(source_doc)
    centers = _pile_centers(doc)
    if not segments or not centers:
        return []

    orientation = {}
    for center in centers:
        angle, confidence = infer_pile_axis(center, segments)
        orientation[center] = (angle, confidence)

    changed = 0
    for entity in list(doc.modelspace()):
        try:
            if entity.dxf.layer not in {"Сваи_Проект", "Оси_Проект", "Исполнительная_Номера", "Исполнительная_Отклонения"}:
                continue
            point = _entity_center(entity)
            if point is None:
                continue
            pile, distance = _nearest(point, centers)
            if pile is None or distance > 1200.0:
                continue
            target, confidence = orientation[pile]
            if confidence < 0.58:
                continue
            current = _entity_angle(entity)
            if current is None:
                continue
            # Pile symbol is square/cross-shaped: 90° is equivalent. Choose the
            # smallest correction modulo 90° so annotations move with the symbol.
            delta = ((target - current + math.pi / 4) % (math.pi / 2)) - math.pi / 4
            if _rotate_about(entity, pile, delta):
                if abs(delta) >= math.radians(0.05):
                    changed += 1
        except Exception:
            continue

    if log:
        log(f"[INFO] Оси свай выровнены по локальной конструктивной геометрии: {changed} объектов.")
    return [
        {"x": round(p[0], 3), "y": round(p[1], 3),
         "angle_deg": round(math.degrees(a), 3), "confidence": round(c, 3)}
        for p, (a, c) in orientation.items()
    ]


def _copy_grillage(doc_out, source_doc, pile_centers, log=None):
    layer = "Исполнительная_Ростверк"
    if layer not in doc_out.layers:
        doc_out.layers.new(layer, dxfattribs={"color": 7})

    candidates = detect_grillage(source_doc, pile_centers)
    rendered = []
    source_hatches = list(source_doc.modelspace().query("HATCH"))

    for candidate in candidates:
        if candidate.confidence < 0.85 or not candidate.bbox:
            continue

        # Hatch is strong evidence and is copied as-is onto the generated layer.
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

        x0, y0, x1, y1 = candidate.bbox
        for seg in candidate.segments:
            cx, cy = seg.center
            if x0 - 1000 <= cx <= x1 + 1000 and y0 - 1000 <= cy <= y1 + 1000:
                doc_out.modelspace().add_line(seg.start, seg.end,
                                              dxfattribs={"layer": layer, "color": 7})

        rendered.append({
            "bbox": [round(v, 3) for v in candidate.bbox],
            "angle_deg": round(math.degrees(candidate.angle), 3),
            "confidence": round(candidate.confidence, 3),
            "reason": candidate.reason,
        })

    if log:
        log(f"[INFO] Ростверк: кандидатов {len(candidates)}, отрисовано {len(rendered)}.")
    return rendered, [
        {
            "bbox": [round(v, 3) for v in c.bbox] if c.bbox else None,
            "angle_deg": round(math.degrees(c.angle), 3),
            "confidence": round(c.confidence, 3),
            "reason": c.reason,
        }
        for c in candidates
    ]


def run(input_dxf, output_dxf, output_csv=None, log_callback=None, stamp_data=None, table_data=None):
    # Base wrapper performs the existing generation, source-layer hiding and
    # presentation extents. We add the structural fixes afterwards.
    result = _base.run(input_dxf, output_dxf, output_csv,
                       log_callback=log_callback, stamp_data=stamp_data,
                       table_data=table_data)

    try:
        source_doc = ezdxf.readfile(input_dxf)
        doc_out = ezdxf.readfile(output_dxf)
        centers = _pile_centers(doc_out)

        rendered, candidates = _copy_grillage(doc_out, source_doc, centers, log_callback)
        orientations = _orient_piles(doc_out, source_doc, log_callback)
        doc_out.saveas(output_dxf)

        base = Path(output_dxf)
        base.with_name(base.stem + "_grillage_diagnostic.json").write_text(
            json.dumps({
                "schema_version": 1,
                "algorithm_id": "piles",
                "grillage": {"rendered": rendered, "candidates": candidates},
                "pile_orientations": orientations,
            }, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        if log_callback:
            log_callback(f"[ПРЕДУПРЕЖДЕНИЕ] Структурный post-process не выполнен: {exc}")

    return result

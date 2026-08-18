"""Минимальный универсальный алгоритм исполнительной схемы конусов.

Алгоритм намеренно не зависит от имён слоёв или блоков. В качестве признаков
используются окружности и замкнутые компактные полилинии, которые являются
естественными геометрическими кандидатами на конические элементы в плане.

Это первый рабочий MVP для папки «Конусы»: он не пытается восстановить всю
графику эталона, но создаёт полноценный DXF с исполнительными обозначениями,
нумерацией, рамкой и штампом и может быть выбран как обычный plugin.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf.math import Vec2

from algo_stamp import draw_gost_stamp, setup_gost_layers

ALGORITHM_NAME = "Конусы"
PREVIEW_IMAGE = "preview_cones.png"

A3_W = 420.0
A3_H = 297.0
FRAME_MARGIN = 10.0
STAMP_W = 185.0
STAMP_H = 55.0

LAYER_CONE = "ИСП_Конусы"
LAYER_TEXT = "ИСП_Текст"
LAYER_FRAME = "ГОСТ_Рамка"
LAYER_AXIS = "ИСП_Оси"


def _ensure_layers(doc: ezdxf.document.Drawing) -> None:
    setup_gost_layers(doc)
    for name, color, ltype, lw in (
        (LAYER_CONE, 7, "CONTINUOUS", 25),
        (LAYER_TEXT, 7, "CONTINUOUS", 15),
        (LAYER_FRAME, 7, "CONTINUOUS", 50),
        (LAYER_AXIS, 7, "DASHDOT", 15),
    ):
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": color, "linetype": ltype})
            doc.layers.get(name).dxf.lineweight = lw


def _bbox_of_points(points: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _polyline_vertices(ent) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    try:
        if ent.dxftype() == "LWPOLYLINE":
            pts = [(float(p[0]), float(p[1])) for p in ent.get_points("xy")]
        elif ent.dxftype() == "POLYLINE":
            pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in ent.vertices]
    except Exception:
        return []
    return pts


def detect_cones(msp) -> List[Dict[str, Any]]:
    """Распознаёт конусы по геометрической форме, без привязки к слоям/именам блоков."""
    candidates: List[Dict[str, Any]] = []

    for ent in msp:
        typ = ent.dxftype()
        try:
            if typ == "CIRCLE":
                c = ent.dxf.center
                r = float(ent.dxf.radius)
                if r > 1e-6:
                    candidates.append({"kind": "circle", "center": (float(c.x), float(c.y)), "radius": r, "entity": ent})
                continue

            if typ in ("LWPOLYLINE", "POLYLINE"):
                if not getattr(ent.dxf, "flags", 0) & 1:
                    continue
                pts = _polyline_vertices(ent)
                if len(pts) < 3:
                    continue
                xmin, ymin, xmax, ymax = _bbox_of_points(pts)
                w, h = xmax - xmin, ymax - ymin
                if w <= 0 or h <= 0:
                    continue
                # Компактность: конус в плане обычно близок к круглой/многоугольной форме.
                compactness = min(w, h) / max(w, h)
                if compactness < 0.55:
                    continue
                candidates.append({
                    "kind": "polyline",
                    "center": ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0),
                    "radius": 0.5 * max(w, h),
                    "points": pts,
                    "entity": ent,
                })
        except Exception:
            continue

    # Убираем дубликаты близко расположенных кандидатов.
    candidates.sort(key=lambda x: (x["center"][1], x["center"][0]))
    result: List[Dict[str, Any]] = []
    for item in candidates:
        cx, cy = item["center"]
        r = item["radius"]
        duplicate = False
        for prev in result:
            px, py = prev["center"]
            if math.hypot(cx - px, cy - py) < max(1.0, 0.15 * min(r, prev["radius"])):
                duplicate = True
                break
        if not duplicate:
            result.append(item)

    return result


def _source_bbox(msp) -> Optional[Tuple[float, float, float, float]]:
    points: List[Tuple[float, float]] = []
    for ent in msp:
        try:
            typ = ent.dxftype()
            if typ == "CIRCLE":
                c = ent.dxf.center
                r = float(ent.dxf.radius)
                points.extend([(c.x - r, c.y - r), (c.x + r, c.y + r)])
            elif typ in ("LWPOLYLINE", "POLYLINE"):
                points.extend(_polyline_vertices(ent))
        except Exception:
            continue
    if not points:
        return None
    return _bbox_of_points(points)


def _draw_frame(msp) -> None:
    msp.add_lwpolyline(
        [(FRAME_MARGIN, FRAME_MARGIN), (A3_W - FRAME_MARGIN, FRAME_MARGIN),
         (A3_W - FRAME_MARGIN, A3_H - FRAME_MARGIN), (FRAME_MARGIN, A3_H - FRAME_MARGIN)],
        close=True,
        dxfattribs={"layer": LAYER_FRAME, "color": 7, "lineweight": 50},
    )


def _add_text(msp, text: str, x: float, y: float, height: float = 3.0, align="MIDDLE_CENTER") -> None:
    from ezdxf.enums import TextEntityAlignment
    align_map = {
        "MIDDLE_CENTER": TextEntityAlignment.MIDDLE_CENTER,
        "MIDDLE_LEFT": TextEntityAlignment.MIDDLE_LEFT,
        "MIDDLE_RIGHT": TextEntityAlignment.MIDDLE_RIGHT,
    }
    msp.add_text(
        str(text),
        dxfattribs={"layer": LAYER_TEXT, "color": 7, "height": height, "style": "ГОСТ_2.304"},
    ).set_placement((x, y), align=align_map[align])


def _draw_cone_symbol(msp, item: Dict[str, Any], x: float, y: float, radius: float, number: int) -> None:
    # Радиус ограничиваем, чтобы густые группы не сливались.
    r = max(2.5, min(12.0, radius))
    msp.add_circle((x, y), r, dxfattribs={"layer": LAYER_CONE, "color": 7})
    cross = max(2.0, min(8.0, r * 0.65))
    msp.add_line((x - cross, y), (x + cross, y), dxfattribs={"layer": LAYER_AXIS, "color": 7})
    msp.add_line((x, y - cross), (x, y + cross), dxfattribs={"layer": LAYER_AXIS, "color": 7})
    _add_text(msp, str(number), x + r + 2.0, y + r + 1.0, height=2.5, align="MIDDLE_LEFT")


def _layout_candidates(candidates: List[Dict[str, Any]]) -> Tuple[float, float, float]:
    xs = [c["center"][0] for c in candidates]
    ys = [c["center"][1] for c in candidates]
    rs = [c["radius"] for c in candidates]
    xmin, xmax = min(xs) - max(rs), max(xs) + max(rs)
    ymin, ymax = min(ys) - max(rs), max(ys) + max(rs)
    src_w = max(1.0, xmax - xmin)
    src_h = max(1.0, ymax - ymin)

    # Нижняя часть листа занята штампом. Верхняя рабочая область — 390x225 мм.
    work_w = A3_W - 2 * FRAME_MARGIN - 8.0
    work_h = A3_H - FRAME_MARGIN - STAMP_H - 15.0
    factor = min(work_w / src_w, work_h / src_h)
    return factor, xmin, ymin


def process_dxf_to_asbuilt_scheme(
    input_path: str,
    output_path: str,
    csv_path: Optional[str] = None,
    log_callback=None,
    stamp_data: Optional[Dict[str, Any]] = None,
    table_data: Optional[List[Dict[str, Any]]] = None,
) -> None:
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    log(f"[ИНФО] Обработка конусов: {input_path}")
    src = ezdxf.readfile(input_path)
    candidates = detect_cones(src.modelspace())

    out = ezdxf.new("R2018")
    _ensure_layers(out)
    msp = out.modelspace()

    if candidates:
        factor, xmin, ymin = _layout_candidates(candidates)
        factor = max(0.0001, min(factor, 10.0))
        x0 = FRAME_MARGIN + 4.0
        y0 = FRAME_MARGIN + STAMP_H + 12.0

        for idx, item in enumerate(candidates, start=1):
            sx = x0 + (item["center"][0] - xmin) * factor
            sy = y0 + (item["center"][1] - ymin) * factor
            _draw_cone_symbol(msp, item, sx, sy, item["radius"] * factor, idx)
    else:
        # Даже для нетипичного DXF выдаём полезный результат вместо пустого листа.
        bbox = _source_bbox(src.modelspace())
        if bbox:
            xmin, ymin, xmax, ymax = bbox
            _add_text(msp, "Конусы: геометрические кандидаты не распознаны", A3_W / 2, A3_H / 2, 4.0)
            _add_text(msp, f"Исходный габарит: {xmax-xmin:.0f} × {ymax-ymin:.0f}", A3_W / 2, A3_H / 2 - 8, 3.0)
        else:
            _add_text(msp, "Конусы: исходная геометрия не найдена", A3_W / 2, A3_H / 2, 4.0)

    _add_text(msp, "ИСПОЛНИТЕЛЬНАЯ СХЕМА КОНУСОВ", A3_W / 2, A3_H - 16, 4.0)
    _add_text(msp, f"Распознано элементов: {len(candidates)}", FRAME_MARGIN + 4, A3_H - 16, 2.5, "MIDDLE_LEFT")

    _draw_frame(msp)
    draw_gost_stamp(
        msp,
        A3_W - FRAME_MARGIN - STAMP_W,
        FRAME_MARGIN,
        scale=1.0,
        stamp_data=stamp_data,
        scale_str="авто",
    )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    out.saveas(output_path)
    log(f"[УСПЕХ] Исполнительная схема конусов сохранена: {output_path}")

    if csv_path:
        rows = generate_table_data(input_path)
        import csv
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=["№", "X", "Y", "Радиус"])
            writer.writeheader()
            writer.writerows(rows)


def generate_table_data(input_path: str) -> List[Dict[str, Any]]:
    src = ezdxf.readfile(input_path)
    rows = []
    for idx, item in enumerate(detect_cones(src.modelspace()), start=1):
        rows.append({
            "№": idx,
            "X": round(item["center"][0], 3),
            "Y": round(item["center"][1], 3),
            "Радиус": round(item["radius"], 3),
        })
    return rows


def run(
    input_dxf: str,
    output_dxf: str,
    output_csv: Optional[str] = None,
    log_callback=None,
    stamp_data: Optional[Dict[str, Any]] = None,
    table_data: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Plugin entry point required by main.py."""
    process_dxf_to_asbuilt_scheme(
        input_dxf,
        output_dxf,
        output_csv,
        log_callback=log_callback,
        stamp_data=stamp_data,
        table_data=table_data,
    )

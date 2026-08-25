"""Канонический pipeline исполнительной схемы пролётного строения."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.enums import TextEntityAlignment

from algo_stamp import draw_gost_frame_and_stamp
from dxf_geometry import extract_geometry
from dxf_math import A3_HEIGHT_MM, A3_WIDTH_MM, STANDARD_SCALES, a3_work_area, fit_standard_scale

ALGORITHM_NAME = "Пролетное строение"
PREVIEW_IMAGE = "preview_bridge.png"
COLOR_MAIN = 7
COLOR_FACT = 1
FONT_GOST = "isocpeur.ttf"


def _log(msg: str, log_callback=None) -> None:
    (log_callback or print)(msg)


def _arc_points(item):
    _, center, radius, start, end = item
    span = (end - start) % 360.0
    count = max(8, int(math.ceil(span / 10.0)))
    return [
        (center[0] + radius * math.cos(math.radians(start + span * i / count)),
         center[1] + radius * math.sin(math.radians(start + span * i / count)))
        for i in range(count + 1)
    ]


def _bbox(elements):
    points = []
    for item in elements:
        if item[0] == "LINE":
            points.extend([item[1], item[2]])
        elif item[0] == "POLYLINE":
            points.extend([(p[0], p[1]) for p in item[1]])
        elif item[0] == "CIRCLE":
            c, r = item[1], item[2]
            points.extend([(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
        elif item[0] == "ARC":
            points.extend(_arc_points(item))
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _scale_element(item, factor: float, min_x: float, min_y: float, ox: float, oy: float):
    t = item[0]
    if t == "LINE":
        return ("LINE", ((item[1][0] - min_x) * factor + ox, (item[1][1] - min_y) * factor + oy),
                ((item[2][0] - min_x) * factor + ox, (item[2][1] - min_y) * factor + oy), item[3])
    if t == "POLYLINE":
        return ("POLYLINE", [((p[0] - min_x) * factor + ox, (p[1] - min_y) * factor + oy, p[2]) for p in item[1]], item[2], item[3])
    if t == "CIRCLE":
        return ("CIRCLE", ((item[1][0] - min_x) * factor + ox, (item[1][1] - min_y) * factor + oy), item[2] * factor, item[3])
    if t == "ARC":
        return ("ARC", ((item[1][0] - min_x) * factor + ox, (item[1][1] - min_y) * factor + oy), item[2] * factor, item[3], item[4], item[5])
    return item


def _draw_elements(msp, elements):
    for item in elements:
        t = item[0]
        if t == "LINE":
            msp.add_line(item[1], item[2], dxfattribs={"layer": item[3], "color": COLOR_MAIN})
        elif t == "POLYLINE":
            pts = [(p[0], p[1], 0.0, 0.0, p[2] if len(p) > 2 else 0.0) for p in item[1]]
            msp.add_lwpolyline(pts, format="xyseb", close=item[2], dxfattribs={"layer": item[3], "color": COLOR_MAIN})
        elif t == "CIRCLE":
            msp.add_circle(item[1], item[2], dxfattribs={"layer": item[3], "color": COLOR_MAIN})
        elif t == "ARC":
            msp.add_arc(item[1], item[2], start_angle=item[3], end_angle=item[4], dxfattribs={"layer": item[5], "color": COLOR_MAIN})


def _draw_dimension(msp, dim: Dict[str, Any]) -> None:
    p1, p2, pd = dim["p1"], dim["p2"], dim["p_dim"]
    angle = dim["angle_rad"]
    ux, uy = math.cos(angle), math.sin(angle)
    px, py = -uy, ux
    d1 = (pd[0] - p1[0]) * px + (pd[1] - p1[1]) * py
    d2 = (pd[0] - p2[0]) * px + (pd[1] - p2[1]) * py
    q1 = (p1[0] + d1 * px, p1[1] + d1 * py)
    q2 = (p2[0] + d2 * px, p2[1] + d2 * py)
    ext = 1.5
    msp.add_line(p1, (q1[0] + ext * px, q1[1] + ext * py), dxfattribs={"layer": "ИСП_Размеры_Проект", "color": COLOR_MAIN})
    msp.add_line(p2, (q2[0] + ext * px, q2[1] + ext * py), dxfattribs={"layer": "ИСП_Размеры_Проект", "color": COLOR_MAIN})
    msp.add_line((q1[0] - ext * ux, q1[1] - ext * uy), (q2[0] + ext * ux, q2[1] + ext * uy), dxfattribs={"layer": "ИСП_Размеры_Проект", "color": COLOR_MAIN})
    value = dim.get("prj_val", math.hypot(p2[0] - p1[0], p2[1] - p1[1]))
    text = f"{int(round(value))}" if value >= 10 else f"{value:.1f}"
    mx, my = (q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2
    msp.add_text(text, dxfattribs={"style": "ГОСТ_2.304", "height": 2.5, "layer": "ИСП_Размеры_Проект", "color": COLOR_MAIN, "rotation": math.degrees(angle) % 180}).set_placement((mx + 2 * px, my + 2 * py), align=TextEntityAlignment.MIDDLE_CENTER)


def _draw_level(msp, level: Dict[str, Any]) -> None:
    x, y = level["pt"]
    h = 1.5
    msp.add_lwpolyline([(x, y), (x - 1.5, y + h), (x + 1.5, y + h)], close=True, dxfattribs={"layer": "ИСП_Высотные_Отметки", "color": COLOR_MAIN})
    msp.add_line((x - 1.5, y + h), (x + 8.0, y + h), dxfattribs={"layer": "ИСП_Высотные_Отметки", "color": COLOR_MAIN})
    msp.add_text(f"{level['val']:+.3f}", dxfattribs={"style": "ГОСТ_2.304", "height": 2.5, "layer": "ИСП_Высотные_Отметки", "color": COLOR_MAIN}).set_placement((x + 0.5, y + h + 0.5), align=TextEntityAlignment.BOTTOM_LEFT)


def _layers(doc) -> None:
    for name, color in (
        ("ИСП_Конструкция_Серый", 7), ("ИСП_Размеры_Проект", 7),
        ("ИСП_Размеры_Факт", 1), ("ИСП_Высотные_Отметки", 7),
        ("ИСП_Текст", 7),
    ):
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": color})
    if "ГОСТ_2.304" not in doc.styles:
        doc.styles.new("ГОСТ_2.304", dxfattribs={"font": FONT_GOST, "width": 0.85, "oblique": 15.0})


def process_dxf_to_asbuilt_scheme(input_path: str, output_path: str, csv_path: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    _log(f"[ИНФО] Обработка пролётного строения: {input_path}", log_callback)
    try:
        src = ezdxf.readfile(input_path)
    except Exception as exc:
        _log(f"[ОШИБКА] Ошибка чтения DXF: {exc}", log_callback)
        return

    elements, dims, levels = extract_geometry(src.modelspace(), src)
    geom = _bbox(elements)
    if geom is None:
        _log("[ОШИБКА] Исполнительная геометрия не найдена.", log_callback)
        return
    min_x, min_y, max_x, max_y = geom
    work_w, work_h = a3_work_area()
    plan = fit_standard_scale(max_x - min_x, max_y - min_y, work_w, work_h, STANDARD_SCALES)

    out = ezdxf.new("R2018", setup=True)
    _layers(out)
    msp = out.modelspace()
    scaled = [_scale_element(item, plan.factor, min_x, min_y, 15.0, 15.0) for item in elements]
    _draw_elements(msp, scaled)

    for dim in dims:
        d = dict(dim)
        for key in ("p1", "p2", "p_dim"):
            x, y = d[key]
            d[key] = ((x - min_x) * plan.factor + 15.0, (y - min_y) * plan.factor + 15.0)
        _draw_dimension(msp, d)
    for level in levels:
        d = dict(level)
        d["pt"] = ((level["pt"][0] - min_x) * plan.factor + 15.0, (level["pt"][1] - min_y) * plan.factor + 15.0)
        _draw_level(msp, d)

    box = ezdxf_bbox.extents(msp)
    scale_str = f"1:{int(plan.denominator)}"
    in_x_min, in_y_min, in_x_max, in_y_max = draw_gost_frame_and_stamp(msp, box, scale=1.0, stamp_data=stamp_data, scale_str=scale_str)
    title = ((stamp_data or {}).get("doc_title") or "ИСПОЛНИТЕЛЬНАЯ СХЕМА. ПРОЛЁТНОЕ СТРОЕНИЕ").upper()
    msp.add_text(title, dxfattribs={"style": "ГОСТ_2.304", "height": 5.0, "layer": "ИСП_Текст", "color": COLOR_MAIN}).set_placement(((in_x_min + in_x_max) / 2, in_y_max - 8), align=TextEntityAlignment.MIDDLE_CENTER)
    out.saveas(output_path)
    _log(f"[УСПЕХ] Пролётное строение сохранено, масштаб {scale_str}: {output_path}", log_callback)


def run(input_dxf: str, output_dxf: str, output_csv: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    process_dxf_to_asbuilt_scheme(input_dxf, output_dxf, output_csv, log_callback, stamp_data, table_data)

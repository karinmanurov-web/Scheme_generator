"""Canonical clean presentation pipeline for slope-wall drawings."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.enums import TextEntityAlignment

from algo_stamp import STAMP_HEIGHT, draw_gost_frame_and_stamp
from algo_walls import (
    STANDARD_SCALES,
    analyze_wall_geometry,
    draw_fractional_dimension,
    draw_legend_and_notes,
    draw_level_mark,
    draw_quantities_table,
    extract_valid_geometry,
    setup_document,
)

ALGORITHM_NAME = "Откосные стенки"

SHEET_W = 420.0
SHEET_H = 297.0
INNER_LEFT = 20.0
INNER_BOTTOM = 5.0
INNER_RIGHT = 5.0
INNER_TOP = 5.0
STAMP_WIDTH = 185.0


def _geometry_bbox(elements):
    points = []
    for item in elements:
        if item[0] == "LINE":
            points.extend([item[1], item[2]])
        elif item[0] == "POLYLINE":
            points.extend(item[1])
        elif item[0] == "CIRCLE":
            c, r = item[1], item[2]
            points.extend([(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _unit_to_mm(doc) -> float:
    units = int(doc.header.get("$INSUNITS", 4) or 4)
    return {
        1: 25.4, 2: 304.8, 3: 1609344.0, 4: 1.0, 5: 10.0,
        6: 1000.0, 7: 1000000.0, 10: 914.4, 14: 100.0,
        15: 10000.0, 16: 100000.0, 17: 1000000.0,
    }.get(units, 1.0)


def _fit_scale(width_mm: float, height_mm: float) -> float:
    usable_w = SHEET_W - INNER_LEFT - INNER_RIGHT
    usable_h = SHEET_H - INNER_BOTTOM - INNER_TOP
    required_denominator = max(width_mm / usable_w, height_mm / usable_h, 1.0)
    return next((float(s) for s in STANDARD_SCALES if float(s) >= required_denominator), float(STANDARD_SCALES[-1]))


def _draw_elements(msp, elements):
    for item in elements:
        if item[0] == "LINE":
            _, p1, p2, layer = item
            msp.add_line(p1, p2, dxfattribs={"layer": layer, "color": 1 if layer == "ГОСТ_Оси" else 7})
        elif item[0] == "POLYLINE":
            _, points, closed, layer = item
            msp.add_lwpolyline(points, close=closed, dxfattribs={"layer": layer, "color": 7})
        elif item[0] == "CIRCLE":
            _, center, radius, layer = item
            msp.add_circle(center, radius, dxfattribs={"layer": layer, "color": 7})


def _scale_element(item, factor: float, dx: float, dy: float):
    if item[0] == "LINE":
        return ("LINE", ((item[1][0] + dx) * factor, (item[1][1] + dy) * factor),
                ((item[2][0] + dx) * factor, (item[2][1] + dy) * factor), item[3])
    if item[0] == "POLYLINE":
        return ("POLYLINE", [((x + dx) * factor, (y + dy) * factor) for x, y in item[1]], item[2], item[3])
    if item[0] == "CIRCLE":
        return ("CIRCLE", ((item[1][0] + dx) * factor, (item[1][1] + dy) * factor), item[2] * factor, item[3])
    return item


def _scale_dim(dim: Dict[str, Any], factor: float) -> Dict[str, Any]:
    result = dict(dim)
    for key in ("p1", "p2", "p_dim"):
        x, y = result[key]
        result[key] = (x * factor, y * factor)
    return result


def _draw_level_deterministic(msp, lvl_info: Dict[str, Any]) -> None:
    """Paper-space level marker; no invented/random survey deviation."""
    pt, value = lvl_info["pt"], lvl_info["val"]
    th, tri_w, tri_h, shelf_w = 2.5, 1.5, 1.5, 8.0
    base_y = pt[1] - 0.5
    msp.add_lwpolyline([(pt[0], base_y), (pt[0] - tri_w, base_y + tri_h),
                        (pt[0] + tri_w, base_y + tri_h)], close=True,
                       dxfattribs={"layer": "ГОСТ_Отметки", "color": 7})
    msp.add_line((pt[0] - tri_w, base_y + tri_h),
                 (pt[0] + shelf_w, base_y + tri_h),
                 dxfattribs={"layer": "ГОСТ_Отметки", "color": 7})
    text = f"{value:+.3f}"
    msp.add_text(text, dxfattribs={"style": "ГОСТ_Шрифт", "height": th,
                                   "layer": "ГОСТ_Отметки", "color": 7}).set_placement(
        (pt[0] + 0.5, base_y + tri_h + 0.5), align=TextEntityAlignment.BOTTOM_LEFT)


def _draw_dimension_deterministic(msp, dim_info: Dict[str, Any]) -> None:
    """Draw project dimension only; actual value is never fabricated."""
    import math
    p1, p2, p_dim = dim_info["p1"], dim_info["p2"], dim_info["p_dim"]
    angle = dim_info["angle_rad"]
    value = dim_info["prj_val"]
    dx, dy = math.cos(angle), math.sin(angle)
    px, py = -dy, dx
    distance1 = (p_dim[0] - p1[0]) * px + (p_dim[1] - p1[1]) * py
    distance2 = (p_dim[0] - p2[0]) * px + (p_dim[1] - p2[1]) * py
    i1 = (p1[0] + distance1 * px, p1[1] + distance1 * py)
    i2 = (p2[0] + distance2 * px, p2[1] + distance2 * py)
    ext = 1.5
    msp.add_line(p1, (i1[0] + math.copysign(ext * px, distance1), i1[1] + math.copysign(ext * py, distance1)),
                 dxfattribs={"layer": "ГОСТ_Размеры_Проект", "color": 7})
    msp.add_line(p2, (i2[0] + math.copysign(ext * px, distance2), i2[1] + math.copysign(ext * py, distance2)),
                 dxfattribs={"layer": "ГОСТ_Размеры_Проект", "color": 7})
    msp.add_line((i1[0] - ext * dx, i1[1] - ext * dy), (i2[0] + ext * dx, i2[1] + ext * dy),
                 dxfattribs={"layer": "ГОСТ_Размеры_Проект", "color": 7})
    mx, my = (i1[0] + i2[0]) / 2, (i1[1] + i2[1]) / 2
    text = f"{int(round(value))}" if value >= 10 else f"{value:.2f}"
    msp.add_text(text, dxfattribs={"style": "ГОСТ_Шрифт", "height": 2.5,
                                   "layer": "ГОСТ_Размеры_Проект", "color": 7,
                                   "rotation": math.degrees(angle) % 180}).set_placement(
        (mx + 2.0 * px, my + 2.0 * py), align=TextEntityAlignment.MIDDLE_CENTER)


def run(input_dxf: str, output_dxf: str, output_csv: Optional[str] = None,
        log_callback=None, stamp_data: Optional[Dict[str, Any]] = None,
        table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    src = ezdxf.readfile(input_dxf)
    unit_factor = _unit_to_mm(src)
    elements, dims, levels = extract_valid_geometry(src.modelspace(), src)

    elements_mm = []
    for item in elements:
        if item[0] == "LINE":
            elements_mm.append(("LINE", (item[1][0] * unit_factor, item[1][1] * unit_factor),
                                (item[2][0] * unit_factor, item[2][1] * unit_factor), item[3]))
        elif item[0] == "POLYLINE":
            elements_mm.append(("POLYLINE", [(x * unit_factor, y * unit_factor) for x, y in item[1]], item[2], item[3]))
        elif item[0] == "CIRCLE":
            elements_mm.append(("CIRCLE", (item[1][0] * unit_factor, item[1][1] * unit_factor),
                                        item[2] * unit_factor, item[3]))

    dims_mm = []
    for dim in dims:
        d = dict(dim)
        for key in ("p1", "p2", "p_dim"):
            d[key] = (d[key][0] * unit_factor, d[key][1] * unit_factor)
        d["prj_val"] *= unit_factor
        dims_mm.append(d)

    levels_mm = []
    for level in levels:
        d = dict(level)
        d["pt"] = (d["pt"][0] * unit_factor, d["pt"][1] * unit_factor)
        levels_mm.append(d)

    geom = _geometry_bbox(elements_mm)
    if geom is None:
        raise RuntimeError("Не удалось извлечь исполнительную геометрию")

    min_x, min_y, max_x, max_y = geom
    geom_w, geom_h = max_x - min_x, max_y - min_y
    scale_denominator = _fit_scale(geom_w, geom_h)
    drawing_factor = 1.0 / scale_denominator

    pad_mm = min(max(geom_w, geom_h) * 0.02, 20.0)
    dx, dy = -min_x + pad_mm, -min_y + pad_mm
    scaled_elements = [_scale_element(item, drawing_factor, dx, dy) for item in elements_mm]
    scaled_dims = [_scale_dim(d, drawing_factor) for d in dims_mm]
    scaled_levels = []
    for level in levels_mm:
        d = dict(level)
        d["pt"] = ((level["pt"][0] + dx) * drawing_factor,
                    (level["pt"][1] + dy) * drawing_factor)
        scaled_levels.append(d)

    out = ezdxf.new("R2018", setup=True)
    out = setup_document(out)
    msp = out.modelspace()
    _draw_elements(msp, scaled_elements)
    if not ezdxf_bbox.extents(msp).has_data:
        raise RuntimeError("Пустая исполнительная геометрия после очистки")

    for dim in scaled_dims:
        _draw_dimension_deterministic(msp, dim)
    for level in scaled_levels:
        _draw_level_deterministic(msp, level)

    drawing_box = ezdxf_bbox.extents(msp)
    scale_str = f"1:{int(scale_denominator)}"
    in_x_min, in_y_min, in_x_max, in_y_max = draw_gost_frame_and_stamp(
        msp, drawing_box, scale=1.0, stamp_data=stamp_data, scale_str=scale_str)

    stamp_top = in_y_min + STAMP_HEIGHT
    stamp_left = in_x_max - STAMP_WIDTH
    chrome_left = in_x_min + 2.0
    available_table_w = max(0.0, stamp_left - chrome_left - 3.0)
    table_scale = min(1.0, available_table_w / 230.0) if available_table_w else 0.8
    table_scale = max(table_scale, 0.75)
    table_top = stamp_top - 2.0
    notes_top = in_y_max - 12.0

    L, B, area = analyze_wall_geometry(elements_mm)
    draw_quantities_table(msp, (chrome_left, table_top), L=L, B=B, area=area,
                          scale=table_scale, table_data=table_data)
    draw_legend_and_notes(msp, (chrome_left, notes_top), scale=1.0,
                          custom_notes=((stamp_data or {}).get("_notes_data") or {}).get("notes"))

    title = ((stamp_data or {}).get("doc_title") or "ИСПОЛНИТЕЛЬНАЯ СХЕМА. ОТКОСНЫЕ СТЕНКИ").upper()
    msp.add_text(title, dxfattribs={"style": "ГОСТ_Шрифт", "height": 5.0,
                                    "layer": "ГОСТ_Текст", "color": 7}).set_placement(
        ((in_x_min + in_x_max) / 2, in_y_max - 8), align=TextEntityAlignment.MIDDLE_CENTER)

    out.saveas(output_dxf)

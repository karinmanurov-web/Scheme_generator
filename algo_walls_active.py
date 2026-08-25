"""Canonical clean presentation pipeline for slope-wall drawings.

This module keeps the existing geometry/dimension logic from ``algo_walls`` but
uses the clean-output strategy from the experimental implementation: the
source DXF is input data only and the final drawing is built in a fresh DXF.
"""
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


def _shift_dim(dim: Dict[str, Any], dx: float, dy: float) -> Dict[str, Any]:
    result = dict(dim)
    for key in ("p1", "p2", "p_dim"):
        x, y = result[key]
        result[key] = (x + dx, y + dy)
    return result


def _fit_scale(width: float, height: float) -> float:
    """Choose an engineering scale from actual model extents for A3."""
    usable_w = 385.0
    usable_h = 280.0
    required = max(width / usable_w, height / usable_h, 1.0)
    return next(
        (float(s) for s in STANDARD_SCALES if float(s) >= required),
        float(STANDARD_SCALES[-1]),
    )


def run(
    input_dxf: str,
    output_dxf: str,
    output_csv: Optional[str] = None,
    log_callback=None,
    stamp_data: Optional[Dict[str, Any]] = None,
    table_data: Optional[List[Dict[str, Any]]] = None,
) -> None:
    src = ezdxf.readfile(input_dxf)
    elements, dims, levels = extract_valid_geometry(src.modelspace(), src)

    # Critical change: never reuse the source document as the presentation
    # template.  This prevents source frames, stamps, hatches and helpers from
    # surviving in the generated drawing.
    out = ezdxf.new("R2018", setup=True)
    out = setup_document(out)
    msp = out.modelspace()

    geom = _geometry_bbox(elements)
    if geom is None:
        raise RuntimeError("Не удалось извлечь исполнительную геометрию")

    min_x, min_y, max_x, max_y = geom
    geom_w = max_x - min_x
    geom_h = max_y - min_y
    pad = max(geom_w, geom_h) * 0.04
    dx, dy = -min_x + pad, -min_y + pad

    shifted_elements = []
    for item in elements:
        if item[0] == "LINE":
            shifted_elements.append((
                "LINE",
                (item[1][0] + dx, item[1][1] + dy),
                (item[2][0] + dx, item[2][1] + dy),
                item[3],
            ))
        elif item[0] == "POLYLINE":
            shifted_elements.append((
                "POLYLINE",
                [(x + dx, y + dy) for x, y in item[1]],
                item[2],
                item[3],
            ))
        elif item[0] == "CIRCLE":
            shifted_elements.append((
                "CIRCLE",
                (item[1][0] + dx, item[1][1] + dy),
                item[2],
                item[3],
            ))
    _draw_elements(msp, shifted_elements)

    shifted_dims = [_shift_dim(d, dx, dy) for d in dims]
    shifted_levels = []
    for level in levels:
        copy = dict(level)
        copy["pt"] = (level["pt"][0] + dx, level["pt"][1] + dy)
        shifted_levels.append(copy)

    base_box = ezdxf_bbox.extents(msp)
    if not base_box.has_data:
        raise RuntimeError("Пустая исполнительная геометрия после очистки")

    text_scale = _fit_scale(geom_w, geom_h)

    for dim in shifted_dims:
        draw_fractional_dimension(msp, dim, scale=text_scale)
    for level in shifted_levels:
        draw_level_mark(msp, level, scale=text_scale)

    drawing_box = ezdxf_bbox.extents(msp)
    if not drawing_box.has_data:
        raise RuntimeError("Не удалось определить габарит исполнительной геометрии")

    # Draw the complete A3 frame first.  The returned inner bounds are then
    # used as the single coordinate system for the stamp, table and notes.
    scale_str = f"1:{int(text_scale)}"
    in_x_min, in_y_min, in_x_max, in_y_max = draw_gost_frame_and_stamp(
        msp,
        drawing_box,
        scale=text_scale,
        stamp_data=stamp_data,
        scale_str=scale_str,
    )

    stamp_top = in_y_min + STAMP_HEIGHT * text_scale
    chrome_left = in_x_min + 2.0 * text_scale
    notes_top = stamp_top + 26.0 * text_scale
    table_top = stamp_top - 2.0 * text_scale

    L, B, area = analyze_wall_geometry(elements)
    draw_quantities_table(
        msp,
        (chrome_left, table_top),
        L=L,
        B=B,
        area=area,
        scale=text_scale,
        table_data=table_data,
    )
    draw_legend_and_notes(
        msp,
        (chrome_left, notes_top),
        scale=text_scale,
        custom_notes=((stamp_data or {}).get("_notes_data") or {}).get("notes"),
    )

    title = ((stamp_data or {}).get("doc_title") or "ИСПОЛНИТЕЛЬНАЯ СХЕМА. ОТКОСНЫЕ СТЕНКИ").upper()
    msp.add_text(
        title,
        dxfattribs={
            "style": "ГОСТ_Шрифт",
            "height": 5.0 * text_scale,
            "layer": "ГОСТ_Текст",
            "color": 7,
        },
    ).set_placement(
        ((in_x_min + in_x_max) / 2, in_y_max - 8 * text_scale),
        align=TextEntityAlignment.MIDDLE_CENTER,
    )

    out.saveas(output_dxf)

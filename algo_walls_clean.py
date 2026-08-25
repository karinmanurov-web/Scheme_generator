"""Clean presentation pipeline for slope-wall drawings.

The source DXF is treated as input data, not as a presentation template.  Only
validated geometry, dimensions and levels are copied into a fresh document;
source frames, stamps, hatches, hidden helpers and stray source entities are
never carried into the result.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.enums import TextEntityAlignment

from algo_walls import (
    STANDARD_SCALES,
    analyze_wall_geometry,
    clean_format_text,
    draw_fractional_dimension,
    draw_gost_frame_and_stamp,
    draw_legend_and_notes,
    draw_level_mark,
    draw_quantities_table,
    extract_valid_geometry,
    setup_document,
)


def _source_is_disposable(entity) -> bool:
    """Reject presentation/fill geometry without depending on layer names."""
    typ = entity.dxftype()
    if typ in {"HATCH", "WIPEOUT", "IMAGE", "IMAGEDEF", "SOLID", "3DFACE"}:
        return True
    try:
        color = int(entity.dxf.color)
    except Exception:
        color = 256
    if color == 3:
        return True
    try:
        rgb = getattr(entity, "rgb", None)
        if rgb and rgb[1] > rgb[0] * 1.25 and rgb[1] > rgb[2] * 1.25:
            return True
    except Exception:
        pass
    return False


def _filtered_source_msp(doc):
    """Return the source modelspace unchanged; filtering is done during extraction."""
    return doc.modelspace()


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
    """Choose an A3 scale from actual content extents, not annotation size.

    The old implementation used ``geom_size / 120000`` which returned 1:1 for
    the real slope-wall fixture.  That produced a 420x297-unit frame around a
    ~50,000-unit drawing.  Here the scale is derived from the A3 usable area
    and snapped to the project's standard engineering scales.
    """
    usable_w = 385.0
    usable_h = 280.0
    required = max(width / usable_w, height / usable_h, 1.0)
    return next((float(s) for s in STANDARD_SCALES if float(s) >= required), float(STANDARD_SCALES[-1]))


def run(
    input_dxf: str,
    output_dxf: str,
    output_csv: Optional[str] = None,
    log_callback=None,
    stamp_data: Optional[Dict[str, Any]] = None,
    table_data: Optional[List[Dict[str, Any]]] = None,
) -> None:
    src = ezdxf.readfile(input_dxf)
    elements, dims, levels = extract_valid_geometry(_filtered_source_msp(src), src)

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
            shifted_elements.append((item[0], (item[1][0] + dx, item[1][1] + dy),
                                     (item[2][0] + dx, item[2][1] + dy), item[3]))
        elif item[0] == "POLYLINE":
            shifted_elements.append((item[0], [(x + dx, y + dy) for x, y in item[1]], item[2], item[3]))
        elif item[0] == "CIRCLE":
            shifted_elements.append((item[0], (item[1][0] + dx, item[1][1] + dy), item[2], item[3]))
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

    # First choose a real engineering scale from the construction itself.
    # The annotation band is deliberately small so it cannot force the model
    # out of the A3 frame.
    geom_size = max(geom_w, geom_h)
    band = max(geom_size * 0.06, 900.0)
    required_content_h = geom_h + band
    text_scale = _fit_scale(geom_w, required_content_h)

    for dim in shifted_dims:
        draw_fractional_dimension(msp, dim, scale=text_scale)
    for level in shifted_levels:
        draw_level_mark(msp, level, scale=text_scale)

    table_y = base_box.extmin.y - band * 0.35
    table_x = base_box.extmin.x
    L, B, area = analyze_wall_geometry(elements)
    draw_quantities_table(
        msp, (table_x, table_y), L=L, B=B, area=area,
        scale=text_scale, table_data=table_data,
    )
    draw_legend_and_notes(
        msp, (table_x, table_y - band * 0.45), scale=text_scale,
    )

    all_box = ezdxf_bbox.extents(msp)
    if not all_box.has_data:
        raise RuntimeError("Не удалось определить габарит исполнительного оформления")

    # The frame is created in the same model-space scale as the geometry and
    # annotations, so the generated content and its text have a consistent
    # paper size at the selected engineering scale.
    scale_str = f"1:{int(text_scale)}"
    draw_gost_frame_and_stamp(
        msp, all_box, scale=text_scale,
        stamp_data=stamp_data, scale_str=scale_str,
    )

    title = ((stamp_data or {}).get("doc_title") or "ИСПОЛНИТЕЛЬНАЯ СХЕМА. ОТКОСНЫЕ СТЕНКИ").upper()
    msp.add_text(
        title,
        dxfattribs={"style": "ГОСТ_Шрифт", "height": 5.0 * text_scale,
                    "layer": "ГОСТ_Текст", "color": 7},
    ).set_placement(
        ((all_box.extmin.x + all_box.extmax.x) / 2, all_box.extmax.y - 10 * text_scale),
        align=TextEntityAlignment.CENTER,
    )

    out.saveas(output_dxf)

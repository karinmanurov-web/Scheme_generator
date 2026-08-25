"""Compatibility and presentation wrapper for the pile structural pipeline.

The structural detector is intentionally geometry-driven. This wrapper fixes the
remaining presentation problem: the legacy pile algorithm starts from the source
DXF and therefore leaves unrelated source geometry in modelspace. That geometry
pollutes the extents, makes the real pile/grillage drawing tiny, and creates the
visual overlaps seen in regression previews.

The wrapper keeps only semantic output layers, then rebuilds the frame/stamp
around the clean execution geometry. Source DIMENSION anchors have already been
converted by the pile algorithm, so their positions remain source-derived.
"""
from __future__ import annotations

import json
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox

import algo_piles_structural as _struct
from algo_piles import draw_notes_and_legend, STANDARD_SCALES
from algo_stamp import draw_gost_frame_and_stamp, setup_gost_layers
from piles_sheet_layout import build_sheet_plan

ALGORITHM_NAME = _struct.ALGORITHM_NAME
PREVIEW_IMAGE = _struct.PREVIEW_IMAGE
generate_table_data = _struct.generate_table_data
process_dxf_to_asbuilt_scheme = _struct.process_dxf_to_asbuilt_scheme

_ORIGINAL_EXTRACT = _struct._base._piles.extract_source_dimensions

_KEEP_LAYERS = {
    "Сваи_Проект", "Оси_Проект", "Исполнительная_Номера",
    "Исполнительная_Размеры", "Исполнительная_Отклонения",
    "Исполнительная_Ростверк", "Исполнительная_Оси_Опор",
    "Исполнительная_Оформление", "ИСП_Текст", "ИСП_Таблица",
    "ИСП_Размеры_Проект", "ИСП_Размеры_Факт", "ИСП_Высотные_Отметки",
    "ГОСТ_Рамка", "ГОСТ_Штамп_Линии", "ГОСТ_Штамп_Текст", "ГОСТ_Таблица_Текст",
}
_PRESENTATION_LAYERS = {
    "ГОСТ_Рамка", "ГОСТ_Штамп_Линии", "ГОСТ_Штамп_Текст", "ГОСТ_Таблица_Текст",
    "Исполнительная_Оформление", "ИСП_Текст", "ИСП_Таблица",
}


def _dimension_filter(msp):
    dimensions = _ORIGINAL_EXTRACT(msp)
    return [item for item in dimensions if float(item.get("prj_val", 0)) >= _struct._MIN_EXECUTION_DIMENSION]


def _bbox_for_layers(msp, layers):
    entities = [e for e in msp if getattr(e.dxf, "layer", "") in layers]
    try:
        box = ezdxf_bbox.extents(entities)
        return box if box.has_data else None
    except Exception:
        return None


def _delete_layers(msp, layers):
    removed = 0
    for entity in list(msp):
        if getattr(entity.dxf, "layer", "") in layers:
            try:
                msp.delete_entity(entity)
                removed += 1
            except Exception:
                pass
    return removed


def _clean_source_geometry(doc):
    """Remove every source entity that is not an explicit output semantic."""
    msp = doc.modelspace()
    removed = 0
    for entity in list(msp):
        layer = getattr(entity.dxf, "layer", "")
        if layer not in _KEEP_LAYERS:
            try:
                msp.delete_entity(entity)
                removed += 1
            except Exception:
                pass
    return removed


def _choose_scale(box):
    if box is None or not box.has_data:
        return 100.0
    width = max(float(box.extmax.x - box.extmin.x), 100.0)
    height = max(float(box.extmax.y - box.extmin.y), 100.0)
    required = max(width / 360.0, height / 205.0, 1.0)
    return next((float(s) for s in STANDARD_SCALES if float(s) >= required), float(STANDARD_SCALES[-1]))


def _rebuild_presentation(doc, stamp_data, log_callback=None):
    msp = doc.modelspace()
    _delete_layers(msp, _PRESENTATION_LAYERS)

    geometry_layers = {
        "Сваи_Проект", "Оси_Проект", "Исполнительная_Номера",
        "Исполнительная_Размеры", "Исполнительная_Отклонения",
        "Исполнительная_Ростверк", "Исполнительная_Оси_Опор",
        "ИСП_Размеры_Проект", "ИСП_Размеры_Факт", "ИСП_Высотные_Отметки",
    }
    box = _bbox_for_layers(msp, geometry_layers)
    if box is None:
        raise RuntimeError("Не удалось определить габарит чистой исполнительной геометрии")

    scale = _choose_scale(box)
    setup_gost_layers(doc)
    draw_gost_frame_and_stamp(
        msp, box, scale=scale, stamp_data=stamp_data, scale_str=f"1:{int(scale)}"
    )

    frame_box = _bbox_for_layers(msp, {"ГОСТ_Рамка"})
    if frame_box and frame_box.has_data:
        # Keep notes outside the stamp, but do not alter the legacy frame
        # placement until the three-sheet layout is implemented properly.
        notes_x = frame_box.extmin.x + 10.0 * scale
        notes_y = frame_box.extmin.y + 60.0 * scale
        draw_notes_and_legend(msp, notes_x, notes_y, scale=scale)

    if log_callback:
        log_callback(
            f"[LAYOUT] Чистая геометрия: {box.extmax.x-box.extmin.x:.0f}x"
            f"{box.extmax.y-box.extmin.y:.0f} мм; масштаб 1:{int(scale)}."
        )


def run(input_dxf, output_dxf, output_csv=None, log_callback=None, stamp_data=None, table_data=None):
    original_filter = _struct._dimension_filter
    _struct._dimension_filter = _dimension_filter
    try:
        result = _struct.run(
            input_dxf, output_dxf, output_csv,
            log_callback=log_callback, stamp_data=stamp_data, table_data=table_data,
        )
    finally:
        _struct._dimension_filter = original_filter

    try:
        doc = ezdxf.readfile(output_dxf)
        removed = _clean_source_geometry(doc)
        _rebuild_presentation(doc, stamp_data, log_callback)
        doc.saveas(output_dxf)
        if log_callback:
            log_callback(f"[LAYOUT] Удалено исходных/лишних entities: {removed}.")

        base = Path(output_dxf)
        base.with_name(base.stem + "_sheet_plan.json").write_text(
            json.dumps(build_sheet_plan(doc), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        if log_callback:
            log_callback(f"[ПРЕДУПРЕЖДЕНИЕ] Clean presentation не выполнен: {exc}")

    return result

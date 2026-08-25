"""Geometry-only cleanup wrapper for the Подбетонка algorithm.

Keeps the stable geometry/bounds implementation from ``algo_base_fixed`` and
removes only source entities that are clearly outside the generated frame.
No source layer names are required: the decision is made from entity extents
and the generated frame extent.
"""
from __future__ import annotations

import ezdxf
from ezdxf import bbox as ezdxf_bbox

import algo_base_fixed as _base

ALGORITHM_NAME = _base.ALGORITHM_NAME
PREVIEW_IMAGE = _base.PREVIEW_IMAGE
generate_table_data = _base.generate_table_data
process_dxf_to_asbuilt_scheme = _base.process_dxf_to_asbuilt_scheme


def _box(entity):
    try:
        box = ezdxf_bbox.extents([entity])
        return box if box.has_data else None
    except Exception:
        return None


def _overlaps(a, b, margin=0.0):
    if not a or not b or not a.has_data or not b.has_data:
        return False
    return not (
        a.extmax.x < b.extmin.x - margin
        or a.extmin.x > b.extmax.x + margin
        or a.extmax.y < b.extmin.y - margin
        or a.extmin.y > b.extmax.y + margin
    )


def _cleanup_outliers(output_dxf: str, log_callback=None) -> int:
    doc = ezdxf.readfile(output_dxf)
    msp = doc.modelspace()

    frame_entities = [e for e in msp if getattr(e.dxf, "layer", "") == "ИС_Оформление_Штамп"]
    frame_box = ezdxf_bbox.extents(frame_entities)
    if not frame_box.has_data:
        return 0

    removed = 0
    for entity in list(msp):
        layer = getattr(entity.dxf, "layer", "")
        if layer == "ИС_Оформление_Штамп":
            continue
        box = _box(entity)
        if not box:
            continue
        # Remove only geometry that is completely outside the generated sheet.
        # A small margin keeps dimension/text entities sitting just outside the
        # construction bbox but still belonging to the sheet.
        if not _overlaps(box, frame_box, margin=500.0):
            try:
                msp.delete_entity(entity)
                removed += 1
            except Exception:
                pass

    if removed:
        doc.saveas(output_dxf)
    if log_callback:
        log_callback(f"[CLEANUP] Удалено геометрии вне рамки: {removed} entities.")
    return removed


def run(input_dxf, output_dxf, output_csv=None, log_callback=None, stamp_data=None, table_data=None):
    result = _base.run(
        input_dxf,
        output_dxf,
        output_csv,
        log_callback=log_callback,
        stamp_data=stamp_data,
        table_data=table_data,
    )
    _cleanup_outliers(output_dxf, log_callback)
    return result

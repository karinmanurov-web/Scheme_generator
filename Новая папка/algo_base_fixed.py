"""Compatibility wrapper for the Подбетонка algorithm.

The original algorithm calculates the sheet scale from construction primitives,
but its final frame bounds are calculated separately.  Keep those two
calculations on the same geometry-only basis so annotations/HATCH/INSERT
artifacts cannot make the sheet scale and frame disagree.
"""

import algo_base as _base
import ezdxf
from ezdxf import bbox as ezdxf_bbox

ALGORITHM_NAME = _base.ALGORITHM_NAME
PREVIEW_IMAGE = getattr(_base, "PREVIEW_IMAGE", "preview_base.png")

generate_table_data = _base.generate_table_data

# Keep the original implementation private while the wrapper is active.
_ORIGINAL_CALCULATE_BOUNDS = _base.calculate_bounds
_ORIGINAL_SAFE_EXTENTS = _base.safe_extents


def geometry_bounds(entities):
    """Return bounds from drawable construction primitives only."""
    return _ORIGINAL_CALCULATE_BOUNDS(entities)


def safe_extents(msp):
    """Return bounds of drawable construction primitives only."""
    primitives = _base.extract_primitives_wcs(msp)
    box = geometry_bounds(primitives)
    if box.has_data:
        return box
    return _ORIGINAL_SAFE_EXTENTS(msp)


def _box_area(box) -> float:
    if box is None or not box.has_data:
        return 0.0
    return abs(float(box.extmax.x - box.extmin.x)) * abs(float(box.extmax.y - box.extmin.y))


def _boxes_overlap(a, b, margin: float = 0.0) -> bool:
    if not a or not b or not a.has_data or not b.has_data:
        return False
    return not (
        a.extmax.x < b.extmin.x - margin
        or a.extmin.x > b.extmax.x + margin
        or a.extmax.y < b.extmin.y - margin
        or a.extmin.y > b.extmax.y + margin
    )


def _sanitize_extreme_hatches(output_dxf: str, source_box) -> int:
    """Remove only obviously unrelated giant HATCH entities.

    The rule is deliberately geometric: a hatch is removed only when its
    bounding-box area is at least 100x the meaningful construction area and it
    does not overlap that construction area. This avoids hard-coding source
    layer names while protecting legitimate hatches that belong to the drawing.
    """
    if not source_box or not source_box.has_data:
        return 0

    source_area = _box_area(source_box)
    if source_area <= 0:
        return 0

    doc = ezdxf.readfile(output_dxf)
    msp = doc.modelspace()
    removed = 0
    for entity in list(msp):
        if entity.dxftype() != 'HATCH':
            continue
        try:
            hatch_box = ezdxf_bbox.extents([entity])
            if not hatch_box.has_data:
                continue
            hatch_area = _box_area(hatch_box)
            if hatch_area >= source_area * 100.0 and not _boxes_overlap(hatch_box, source_box):
                msp.delete_entity(entity)
                removed += 1
        except Exception:
            continue

    if removed:
        doc.saveas(output_dxf)
    return removed


def run(input_dxf, output_dxf, output_csv=None, log_callback=None,
        stamp_data=None, table_data=None):
    """Run the original algorithm with one consistent geometry-based bbox."""
    src_doc = ezdxf.readfile(input_dxf)
    source_box = safe_extents(src_doc.modelspace())

    original_safe_extents = _base.safe_extents
    original_calculate_bounds = _base.calculate_bounds
    _base.safe_extents = safe_extents
    _base.calculate_bounds = geometry_bounds
    try:
        result = _base.run(
            input_dxf,
            output_dxf,
            output_csv,
            log_callback=log_callback,
            stamp_data=stamp_data,
            table_data=table_data,
        )
    finally:
        _base.safe_extents = original_safe_extents
        _base.calculate_bounds = original_calculate_bounds

    removed = _sanitize_extreme_hatches(output_dxf, source_box)
    if removed and log_callback:
        log_callback(f"Очищено служебных HATCH-выбросов: {removed}")
    return result


process_dxf_to_asbuilt_scheme = _base.process_dxf_to_asbuilt_scheme

"""Compatibility wrapper for the pile structural post-processor.

The structural module temporarily replaces the source-dimension extractor.
Its filter must delegate to the original extractor; this wrapper patches that
delegation before invoking the existing structural pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import algo_piles_structural as _struct
from piles_sheet_layout import build_sheet_plan

ALGORITHM_NAME = _struct.ALGORITHM_NAME
PREVIEW_IMAGE = _struct.PREVIEW_IMAGE
generate_table_data = _struct.generate_table_data
process_dxf_to_asbuilt_scheme = _struct.process_dxf_to_asbuilt_scheme

_ORIGINAL_EXTRACT = _struct._base._piles.extract_source_dimensions


def _dimension_filter(msp):
    dimensions = _ORIGINAL_EXTRACT(msp)
    return [
        item
        for item in dimensions
        if float(item.get("prj_val", 0)) >= _struct._MIN_EXECUTION_DIMENSION
    ]


def run(
    input_dxf,
    output_dxf,
    output_csv=None,
    log_callback=None,
    stamp_data=None,
    table_data=None,
):
    original_filter = _struct._dimension_filter
    _struct._dimension_filter = _dimension_filter
    try:
        result = _struct.run(
            input_dxf,
            output_dxf,
            output_csv,
            log_callback=log_callback,
            stamp_data=stamp_data,
            table_data=table_data,
        )
    finally:
        _struct._dimension_filter = original_filter

    # Phase 1 of the three-sheet redesign is observational only. It records
    # which semantic content is already available for each reference sheet;
    # no geometry is moved or rescaled yet.
    try:
        import ezdxf
        doc = ezdxf.readfile(output_dxf)
        base = Path(output_dxf)
        base.with_name(base.stem + "_sheet_plan.json").write_text(
            json.dumps(build_sheet_plan(doc), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        if log_callback:
            log_callback(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось записать sheet plan: {exc}")

    return result

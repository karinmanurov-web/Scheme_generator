"""Compatibility wrapper for the pile structural post-processor.

The structural module temporarily replaces the source-dimension extractor.
Its filter must delegate to the original extractor; this wrapper patches that
delegation before invoking the existing structural pipeline.
"""
from __future__ import annotations

import algo_piles_structural as _struct

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
        return _struct.run(
            input_dxf,
            output_dxf,
            output_csv,
            log_callback=log_callback,
            stamp_data=stamp_data,
            table_data=table_data,
        )
    finally:
        _struct._dimension_filter = original_filter

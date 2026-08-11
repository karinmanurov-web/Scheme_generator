"""Compatibility wrapper for the Подбетонка algorithm.

The original algorithm calculates the final GOST frame from all modelspace
entities. Large HATCH/annotation entities from a source drawing can therefore
expand the bounding box by orders of magnitude. This wrapper keeps the existing
algorithm intact while replacing only its final bounds helper with a geometry-
aware version that considers LINE/POLYLINE/CIRCLE/ARC primitives.

This is intentionally a wrapper first: once the regression result is confirmed,
the same change can be folded into algo_base.py without changing behaviour
elsewhere.
"""

import algo_base as _base

ALGORITHM_NAME = _base.ALGORITHM_NAME
PREVIEW_IMAGE = getattr(_base, "PREVIEW_IMAGE", "preview_base.png")

# Re-export GUI-facing helpers expected by the application.
generate_table_data = _base.generate_table_data


def safe_extents(msp):
    """Return bounds of drawable construction primitives only.

    In particular, do not let large HATCH entities, text, dimensions or other
    annotations determine the sheet bounds. The base module already has a
    geometry-aware primitive extractor and bounds calculator, so we reuse those
    instead of inventing layer/name based rules.
    """
    primitives = _base.extract_primitives_wcs(msp)
    box = _base.calculate_bounds(primitives)
    if box.has_data:
        return box
    return _base.safe_extents(msp)


def run(input_dxf, output_dxf, output_csv=None, log_callback=None,
        stamp_data=None, table_data=None):
    """Run the original algorithm with geometry-aware final frame bounds."""
    original_safe_extents = _base.safe_extents
    _base.safe_extents = safe_extents
    try:
        return _base.run(
            input_dxf,
            output_dxf,
            output_csv,
            log_callback=log_callback,
            stamp_data=stamp_data,
            table_data=table_data,
        )
    finally:
        _base.safe_extents = original_safe_extents


# Keep optional public symbols available to callers that use the plugin module.
process_dxf_to_asbuilt_scheme = _base.process_dxf_to_asbuilt_scheme

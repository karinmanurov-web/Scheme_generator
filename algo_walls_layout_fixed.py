"""Stable presentation adapter for the slope-wall generator.

The geometry extraction remains in ``algo_walls_clean``.  This adapter only
replaces the two presentation decisions that must be deterministic:
engineering-scale selection from the actual drawing extents and exact frame
centering.  No source layer/block names are used here.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import ezdxf
from ezdxf.math import BoundingBox

import algo_walls_clean as _base
from algo_stamp import (
    STAMP_WIDTH,
    STAMP_HEIGHT,
    draw_gost_stamp,
    setup_gost_layers,
)
from algo_walls import STANDARD_SCALES


def _fit_scale(width: float, height: float) -> float:
    """Return a standard scale with headroom for presentation annotations.

    The geometry estimate is made before dimensions, notes and the quantities
    table are drawn. Those presentation elements have non-zero extents and
    can otherwise make an apparently fitting A3 frame overflow. A modest
    headroom factor keeps the rule geometry-driven while making it robust to
    annotation growth.
    """
    usable_w = 385.0
    usable_h = 280.0
    headroom = 1.15
    required = max(
        float(width) / usable_w,
        float(height) / usable_h,
        1.0,
    ) * headroom
    for candidate in STANDARD_SCALES:
        candidate = float(candidate)
        if candidate >= required:
            return candidate
    return float(STANDARD_SCALES[-1])


def _draw_gost_frame_and_stamp(
    msp,
    bbox: BoundingBox,
    scale: float = 1.0,
    stamp_data: Optional[Dict[str, Any]] = None,
    scale_str: str = "1:100",
) -> Tuple[float, float, float, float]:
    """Draw an A3 frame exactly around the generated content."""
    setup_gost_layers(msp.doc)

    w_frame = 420.0 * scale
    h_frame = 297.0 * scale
    if bbox.has_data:
        cx = (bbox.extmin.x + bbox.extmax.x) / 2.0
        cy = (bbox.extmin.y + bbox.extmax.y) / 2.0
    else:
        cx = cy = 0.0

    x_min = cx - w_frame / 2.0
    y_min = cy - h_frame / 2.0
    x_max = x_min + w_frame
    y_max = y_min + h_frame

    msp.add_lwpolyline(
        [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)],
        close=True,
        dxfattribs={"layer": "ГОСТ_Рамка", "color": 7, "lineweight": 50},
    )

    in_x_min = x_min + 20.0 * scale
    in_y_min = y_min + 5.0 * scale
    in_x_max = x_max - 5.0 * scale
    in_y_max = y_max - 5.0 * scale
    msp.add_lwpolyline(
        [(in_x_min, in_y_min), (in_x_max, in_y_min), (in_x_max, in_y_max), (in_x_min, in_y_max)],
        close=True,
        dxfattribs={"layer": "ГОСТ_Рамка", "color": 7, "lineweight": 50},
    )

    stamp_x0 = in_x_max - STAMP_WIDTH * scale
    stamp_y0 = in_y_min
    draw_gost_stamp(
        msp,
        stamp_x0,
        stamp_y0,
        scale=scale,
        stamp_data=stamp_data,
        scale_str=scale_str,
    )
    return in_x_min, in_y_min, in_x_max, in_y_max


# Patch only the presentation hooks used by the clean generator. Geometry
# extraction and dimension preservation remain unchanged.
_base._fit_scale = _fit_scale
_base.draw_gost_frame_and_stamp = _draw_gost_frame_and_stamp


def run(
    input_dxf: str,
    output_dxf: str,
    output_csv: Optional[str] = None,
    log_callback=None,
    stamp_data: Optional[Dict[str, Any]] = None,
    table_data=None,
) -> None:
    _base.run(
        input_dxf,
        output_dxf,
        output_csv=output_csv,
        log_callback=log_callback,
        stamp_data=stamp_data,
        table_data=table_data,
    )

"""Stable presentation adapter for the slope-wall generator.

The geometry extraction remains in ``algo_walls_clean``. This adapter places
the A3 frame so the drawing occupies the upper usable area and the title block
stays in a reserved bottom-right band. Notes and the quantities table are then
drawn into the leftover bottom-left band.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ezdxf.math import BoundingBox

import algo_walls_clean as _base
from algo_stamp import (
    STAMP_WIDTH,
    STAMP_HEIGHT,
    draw_gost_stamp,
    setup_gost_layers,
)
from algo_walls import STANDARD_SCALES

# Paper-mm reservation for stamp + gap so the drawing cannot sit on the title block.
_TOP_MARGIN_MM = 12.0
_LEFT_MARGIN_MM = 20.0
_RIGHT_MARGIN_MM = 5.0
_BOTTOM_MARGIN_MM = 5.0
_STAMP_GAP_MM = 28.0


def _fit_scale(width: float, height: float) -> float:
    """Fit construction extents into the A3 area *above* the reserved stamp band."""
    usable_w = 420.0 - _LEFT_MARGIN_MM - _RIGHT_MARGIN_MM
    usable_h = 297.0 - _TOP_MARGIN_MM - _BOTTOM_MARGIN_MM - STAMP_HEIGHT - _STAMP_GAP_MM
    headroom = 1.08
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
    """Anchor an A3 frame with the drawing in the upper-left usable region."""
    setup_gost_layers(msp.doc)

    w_frame = 420.0 * scale
    h_frame = 297.0 * scale
    left = _LEFT_MARGIN_MM * scale
    right = _RIGHT_MARGIN_MM * scale
    top = _TOP_MARGIN_MM * scale
    bottom = _BOTTOM_MARGIN_MM * scale
    stamp_h = STAMP_HEIGHT * scale
    gap = _STAMP_GAP_MM * scale

    if bbox.has_data:
        x_min = float(bbox.extmin.x) - left
        y_min = float(bbox.extmin.y) - (stamp_h + gap + bottom)
        y_max = float(bbox.extmax.y) + top
        # Keep a true A3 sheet even if annotations grew a little.
        if y_max - y_min < h_frame:
            y_max = y_min + h_frame
        x_max = x_min + w_frame
    else:
        x_min, y_min = 0.0, 0.0
        x_max, y_max = w_frame, h_frame

    msp.add_lwpolyline(
        [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)],
        close=True,
        dxfattribs={"layer": "ГОСТ_Рамка", "color": 7, "lineweight": 50},
    )

    in_x_min = x_min + left
    in_y_min = y_min + bottom
    in_x_max = x_max - right
    in_y_max = y_max - top
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

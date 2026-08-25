"""Bridge-specific adapter for the generic layout engine.

The adapter keeps the existing bridge geometry generator as the source of
truth, but rebuilds the presentation on a clean sheet. Legacy presentation
text is removed before measuring the drawing, and the complete bridge view
plus its dimensions is packed as one coherent drawing group so relative
alignment is preserved.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.math import Matrix44

import algo_bridge
from layout_engine import LayoutItem, Sheet, Rect, layout_sheet

FRAME = {"ГОСТ_Рамка", "ИСП_Рамка_Основная"}
STAMP = {"ГОСТ_Штамп_Линии", "ГОСТ_Штамп_Текст", "ИСП_Штамп"}
TABLE = {"ГОСТ_Таблица_Текст", "ИСП_Таблица"}
LEGACY_PRESENTATION_TEXT = {"ИСП_Текст"}


def _layer(e) -> str:
    try:
        return str(e.dxf.layer)
    except Exception:
        return ""


def _bbox(items):
    try:
        b = ezdxf_bbox.extents(list(items))
        return b if b.has_data else None
    except Exception:
        return None


def _move(items, dx: float, dy: float) -> None:
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return
    m = Matrix44.translate(dx, dy, 0)
    for e in items:
        try:
            e.transform(m)
        except Exception:
            pass


def _delete_old_presentation(msp) -> None:
    """Remove the old fixed-position presentation before layout."""
    for e in list(msp):
        if _layer(e) in FRAME | STAMP | TABLE | LEGACY_PRESENTATION_TEXT:
            try:
                msp.delete_entity(e)
            except Exception:
                pass


def _group(msp, layers):
    return [e for e in msp if _layer(e) in layers]


def _scale_for(box):
    """Choose a practical A3 denominator from the drawing, not its tables.

    The bridge reference uses a large primary plan.  We therefore prefer the
    largest standard scale that still fits the *drawing group* into the main
    drawing zone.  A small safety margin is kept for dimensions and notes.
    """
    if box is None:
        return 100.0
    w = max(float(box.extmax.x - box.extmin.x), 1.0)
    h = max(float(box.extmax.y - box.extmin.y), 1.0)

    # Main drawing zone: roughly 380 x 205 mm of an A3 landscape sheet.
    required = max(w / 380.0, h / 205.0, 1.0)
    candidates = [float(s) for s in algo_bridge.STANDARD_SCALES if s >= required]
    if not candidates:
        return float(algo_bridge.STANDARD_SCALES[-1])
    return candidates[0]


def run(
    input_dxf: str,
    output_dxf: str,
    output_csv: Optional[str] = None,
    log_callback=None,
    stamp_data: Optional[Dict[str, Any]] = None,
    table_data: Optional[List[Dict[str, Any]]] = None,
) -> None:
    fd, tmp = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    try:
        # Reuse the proven geometry/data extraction from the existing bridge
        # algorithm. Presentation is replaced below.
        algo_bridge.run(
            input_dxf,
            tmp,
            output_csv,
            log_callback=log_callback,
            stamp_data=stamp_data,
            table_data=table_data,
        )

        doc = ezdxf.readfile(tmp)
        msp = doc.modelspace()

        construction = _group(msp, {"ИСП_Конструкция_Серый"})
        dims = _group(
            msp,
            {"ИСП_Размеры_Проект", "ИСП_Размеры_Факт", "ИСП_Высотные_Отметки"},
        )

        # Keep construction and dimensions together. They are one coherent
        # drawing in the source coordinate system; moving them independently
        # was the reason the previous preview became visually scattered.
        geometry = construction + dims
        box = _bbox(geometry)
        _delete_old_presentation(msp)

        scale = _scale_for(box)
        scale_str = f"1:{int(scale)}"

        # Model-space sheet dimensions correspond to the chosen paper scale.
        sheet = Sheet("bridge-01", 420 * scale, 297 * scale, margin=15 * scale)

        # Reserve the lower strip for the generated quantity/area tables and
        # the lower-right title block. The drawing itself must not enter it.
        table_band = Rect(
            sheet.margin,
            sheet.margin,
            sheet.width - sheet.margin,
            sheet.margin + 60 * scale,
        )
        sheet.reserve("table-band", table_band, role="table")

        stamp = Rect(
            sheet.width - 185 * scale,
            sheet.margin,
            sheet.width - sheet.margin,
            sheet.margin + 55 * scale,
        )
        sheet.reserve("stamp", stamp, role="stamp")

        if box:
            item = LayoutItem(
                "bridge-drawing",
                "main_view",
                float(box.extmax.x - box.extmin.x),
                float(box.extmax.y - box.extmin.y),
                priority=100,
                min_scale=1.0,
                max_scale=1.0,
                scale=1.0,
            )
            sheet.add(item)
            result = layout_sheet(sheet, gap=250 * scale, target_fill=0.55)

            if result.unplaced:
                if log_callback:
                    log_callback(f"[LAYOUT] Не размещено: {result.unplaced}")
            elif item.rect:
                _move(
                    geometry,
                    item.rect.left - box.extmin.x,
                    item.rect.bottom - box.extmin.y,
                )

        placed = _bbox(geometry) or box
        if placed is None:
            raise RuntimeError("Не удалось определить габарит исполнительной геометрии")

        # Frame/stamp are generated around the actual placed drawing.
        algo_bridge.draw_gost_frame_and_stamp(
            msp,
            placed,
            scale=scale,
            stamp_data=stamp_data,
            scale_str=scale_str,
        )

        # Tables are generated exactly once, below the drawing.
        table_y = placed.extmin.y - 3000 * scale / 100.0
        table_x = placed.extmin.x
        algo_bridge.draw_quantities_table(msp, table_x, table_y, scale)
        algo_bridge.draw_area_calc_table(msp, table_x + 16000 * scale / 100.0, table_y, scale)

        doc.saveas(output_dxf)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

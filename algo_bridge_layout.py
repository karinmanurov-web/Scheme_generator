"""Bridge-specific adapter for the generic layout engine."""
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

def _layer(e):
    try: return str(e.dxf.layer)
    except Exception: return ""

def _bbox(items):
    try:
        b = ezdxf_bbox.extents(list(items))
        return b if b.has_data else None
    except Exception: return None

def _move(items, dx, dy):
    if abs(dx) < 1e-9 and abs(dy) < 1e-9: return
    m = Matrix44.translate(dx, dy, 0)
    for e in items:
        try: e.transform(m)
        except Exception: pass

def _delete_presentation(msp):
    for e in list(msp):
        if _layer(e) in FRAME | STAMP | TABLE:
            try: msp.delete_entity(e)
            except Exception: pass

def _group(msp, layers):
    return [e for e in msp if _layer(e) in layers]

def _scale_for(box):
    if box is None: return 100.0
    w = max(float(box.extmax.x-box.extmin.x), 1.0)
    h = max(float(box.extmax.y-box.extmin.y), 1.0)
    required = max(w/390.0, h/215.0, 1.0)
    return next((float(s) for s in algo_bridge.STANDARD_SCALES if s >= required), float(algo_bridge.STANDARD_SCALES[-1]))

def run(input_dxf: str, output_dxf: str, output_csv: Optional[str]=None, log_callback=None, stamp_data: Optional[Dict[str, Any]]=None, table_data: Optional[List[Dict[str, Any]]]=None) -> None:
    fd, tmp = tempfile.mkstemp(suffix=".dxf"); os.close(fd)
    try:
        algo_bridge.run(input_dxf, tmp, output_csv, log_callback=log_callback, stamp_data=stamp_data, table_data=table_data)
        doc = ezdxf.readfile(tmp); msp = doc.modelspace()
        construction = _group(msp, {"ИСП_Конструкция_Серый"})
        dims = _group(msp, {"ИСП_Размеры_Проект", "ИСП_Размеры_Факт", "ИСП_Высотные_Отметки"})
        notes = _group(msp, {"ИСП_Текст"})
        content = construction + dims + notes
        box = _bbox(content)
        _delete_presentation(msp)
        scale = _scale_for(box)

        sheet = Sheet("bridge-01", 420*scale, 297*scale, margin=20*scale)
        stamp = Rect(sheet.width-185*scale, sheet.height-55*scale, sheet.width, sheet.height)
        sheet.reserve("stamp", stamp, role="stamp")
        band = Rect(sheet.margin, sheet.margin, stamp.left-10*scale, sheet.margin+62*scale)
        sheet.reserve("table-band", band, role="table")
        for ident, role, group, priority in [("main","main_view",construction,100),("dimensions","dimensions",dims,70),("notes","notes",notes,40)]:
            b = _bbox(group)
            if b:
                sheet.add(LayoutItem(ident, role, b.extmax.x-b.extmin.x, b.extmax.y-b.extmin.y, priority=priority, max_scale=1.0))
        result = layout_sheet(sheet, gap=350*scale, target_fill=0.60)
        if not result.unplaced:
            for ident, group in [("main",construction),("dimensions",dims),("notes",notes)]:
                item = next((x for x in sheet.items if x.id==ident), None)
                b = _bbox(group)
                if item and item.rect and b:
                    _move(group, item.rect.left-b.extmin.x, item.rect.bottom-b.extmin.y)

        placed = _bbox(content) or box
        algo_bridge.draw_gost_frame_and_stamp(msp, placed, scale=scale, stamp_data=stamp_data, scale_str=f"1:{int(scale)}")
        algo_bridge.draw_quantities_table(msp, sheet.margin+8*scale, sheet.margin+58*scale, scale)
        algo_bridge.draw_area_calc_table(msp, sheet.margin+190*scale, sheet.margin+58*scale, scale)
        doc.saveas(output_dxf)
    finally:
        try: os.remove(tmp)
        except OSError: pass

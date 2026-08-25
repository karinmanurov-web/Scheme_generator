"""
Модуль плагина: Исполнительная схема пролетного строения моста
Оформление исполнительного чертежа монолитной плиты пролетного строения моста по ГОСТ / СПДС.
"""

import csv
import math
import os
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.enums import TextEntityAlignment
from ezdxf.math import BoundingBox, Vec3

from algo_stamp import draw_gost_frame_and_stamp, draw_gost_stamp
from dxf_math import (
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    STANDARD_SCALES,
    bbox_mm,
    choose_standard_scale,
    normalize_to_mm,
    scale_geometry_value,
)

ALGORITHM_NAME = "Пролетное строение"
PREVIEW_IMAGE = "preview_bridge.png"
COLOR_MAIN = 7
COLOR_BASE = 7
COLOR_FACT = 1
FONT_GOST = "isocpeur.ttf"


def _log(msg: str, log_callback=None) -> None:
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def safe_extents(msp) -> ezdxf_bbox.BoundingBox:
    box = ezdxf_bbox.BoundingBox()
    for ent in msp:
        try:
            ent_box = ezdxf_bbox.extents([ent])
            if ent_box.has_data:
                box.extend([ent_box.extmin, ent_box.extmax])
        except Exception:
            pass
    return box


def setup_gost_environment(doc: ezdxf.document.Drawing) -> None:
    doc.header['$MEASUREMENT'] = 1
    doc.header['$INSUNITS'] = 4
    if 'DASHDOT' not in doc.linetypes:
        doc.linetypes.new('DASHDOT', dxfattribs={'description': 'Осевая ГОСТ', 'pattern': [20.0, 10.0, -2.0, 2.0, -2.0]})
    layers_config = [
        ('ИСП_Конструкция_Серый', COLOR_MAIN, 'CONTINUOUS', 25),
        ('ИСП_Рамка_Основная', COLOR_MAIN, 'CONTINUOUS', 50),
        ('ИСП_Размеры_Проект', COLOR_MAIN, 'CONTINUOUS', 25),
        ('ИСП_Размеры_Факт', COLOR_FACT, 'CONTINUOUS', 25),
        ('ИСП_Текст', COLOR_MAIN, 'CONTINUOUS', 25),
        ('ИСП_Оси', COLOR_FACT, 'DASHDOT', 25),
        ('ИСП_Высотные_Отметки', COLOR_MAIN, 'CONTINUOUS', 25),
        ('ИСП_Штамп', COLOR_MAIN, 'CONTINUOUS', 50),
        ('ИСП_Таблица', COLOR_MAIN, 'CONTINUOUS', 25),
    ]
    for name, color, ltype, lineweight in layers_config:
        if name not in doc.layers:
            layer = doc.layers.new(name, dxfattribs={'color': color, 'linetype': ltype})
            layer.dxf.lineweight = lineweight
    if 'ГОСТ_2.304' not in doc.styles:
        doc.styles.new('ГОСТ_2.304', dxfattribs={'font': FONT_GOST, 'width': 0.85, 'oblique': 15.0})


def parse_proj_value(user_text: str, geom_dist: float) -> float:
    if user_text and user_text != '<>':
        cleaned = re.sub(r'\\[A-Za-z0-9]+;', '', user_text)
        cleaned = re.sub(r'[{}\s]', '', cleaned)
        match = re.search(r'\d+(\.\d+)?', cleaned)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                pass
    return geom_dist


def draw_notes(msp, x_pos: float, y_pos: float, scale: float = 1.0, custom_notes=None) -> None:
    notes = custom_notes if custom_notes is not None else [
        "Линейные размеры указаны в миллиметрах, высотные отметки - в метрах.",
        "В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным цветом).",
        "Съемка выполнена электронным тахеометром.",
        "Система координат и система высот принимаются по проектной документации."
    ]
    th = 2.5
    step_y = 4.5
    msp.add_text("ПРИМЕЧАНИЯ:", dxfattribs={"style": "ГОСТ_2.304", "height": 3.5, "layer": "ИСП_Текст", "color": COLOR_MAIN}).set_placement((x_pos, y_pos), align=TextEntityAlignment.BOTTOM_LEFT)
    for i, note in enumerate(notes):
        msp.add_text(note, dxfattribs={"style": "ГОСТ_2.304", "height": th, "layer": "ИСП_Текст", "color": COLOR_MAIN}).set_placement((x_pos, y_pos - (i + 1) * step_y), align=TextEntityAlignment.BOTTOM_LEFT)


def process_dxf_to_asbuilt_scheme(input_path: str, output_path: str, csv_path: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    _log(f"[ИНФО] Обработка мостового пролета: {input_path}", log_callback)
    try:
        src_doc = ezdxf.readfile(input_path)
        src_msp = src_doc.modelspace()
    except Exception as e:
        _log(f"[ОШИБКА] Ошибка чтения DXF: {e}", log_callback)
        return

    setup_gost_environment(src_doc)
    normalize_to_mm(src_doc)
    out_msp = src_doc.modelspace()

    entities_to_delete = []
    for ent in list(out_msp):
        dxftype = ent.dxftype()
        if dxftype in ('DIMENSION', 'LEADER', 'MULTILEADER'):
            entities_to_delete.append(ent)
        elif dxftype in ('TEXT', 'MTEXT'):
            txt = ent.text if dxftype == 'MTEXT' else getattr(ent.dxf, 'text', '')
            cln = re.sub(r'[\\[A-Za-z0-9]+;|{}]', '', txt).strip()
            if re.search(r'^[+-]?\d{1,4}[.,]\d{3}$', cln):
                entities_to_delete.append(ent)
        else:
            try:
                ent.dxf.color = COLOR_MAIN
                ent.dxf.layer = 'ИСП_Конструкция_Серый'
            except Exception:
                pass
    for ent in entities_to_delete:
        try:
            out_msp.delete_entity(ent)
        except Exception:
            pass

    bbox = safe_extents(out_msp)
    if not bbox.has_data:
        bbox = BoundingBox([Vec3(0, 0, 0), Vec3(1000, 1000, 0)])
    (min_x, min_y), (max_x, max_y) = bbox_mm(bbox)
    geom_w = max(max_x - min_x, 100.0)
    geom_h = max(max_y - min_y, 100.0)
    scale = choose_standard_scale(geom_w, geom_h, A3_WIDTH_MM, A3_HEIGHT_MM)
    scale_str = f"1:{int(scale)}"

    # Приводим исходную геометрию к бумажному пространству: X/Y / N.
    dx = 20.0 - min_x / scale
    dy = 20.0 - min_y / scale
    for ent in list(out_msp):
        try:
            if ent.dxftype() in ('TEXT', 'MTEXT', 'DIMENSION', 'LEADER', 'MULTILEADER'):
                continue
            ent.transform(ezdxf.math.Matrix44.scale(1.0 / scale, 1.0 / scale, 1.0))
            ent.translate(dx, dy, 0.0)
        except Exception:
            pass

    paper_bbox = safe_extents(out_msp)
    if not paper_bbox.has_data:
        paper_bbox = BoundingBox([Vec3(20, 20, 0), Vec3(400, 277, 0)])
    draw_gost_frame_and_stamp(out_msp, paper_bbox, scale=1.0, stamp_data=stamp_data, scale_str=scale_str)

    stamp_x0 = paper_bbox.extmax.x - 185.0
    stamp_y0 = paper_bbox.extmin.y
    draw_notes(out_msp, stamp_x0, stamp_y0 + 65.0, 1.0, custom_notes=((stamp_data or {}).get("_notes_data") or {}).get("notes"))

    try:
        src_doc.saveas(output_path)
        _log(f"[УСПЕХ] Исполнительный чертеж моста успешно сформирован: {output_path}", log_callback)
    except Exception as e:
        _log(f"[ОШИБКА] Ошибка сохранения DXF: {e}", log_callback)


def run(input_dxf: str, output_dxf: str, output_csv: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    process_dxf_to_asbuilt_scheme(input_dxf, output_dxf, output_csv, log_callback=log_callback, stamp_data=stamp_data, table_data=table_data)

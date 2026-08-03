"""
Модуль оформления ГОСТ рамки и главного штампа (ГОСТ 2.104 Форма 3).
Отрисовывает ГОСТ рамку и штамп 185 х 55 мм с точной сеткой строк и колонок.
Поддерживает автоналожение данных из вкладки 'Штамп'.
"""

import math
from typing import Any, Dict, List, Optional, Tuple
import ezdxf
from ezdxf.enums import TextEntityAlignment
from ezdxf.math import Vec3, BoundingBox

STAMP_WIDTH = 185.0
STAMP_HEIGHT = 55.0

STANDARD_GOST_SCALES = [1, 2, 5, 10, 15, 20, 25, 40, 50, 75, 100, 150, 200, 250, 400, 500, 1000]


def setup_gost_layers(doc: ezdxf.document.Drawing) -> None:
    if 'ГОСТ_Рамка' not in doc.layers:
        doc.layers.new('ГОСТ_Рамка', dxfattribs={'color': 7, 'lineweight': 50})
    if 'ГОСТ_Штамп_Линии' not in doc.layers:
        doc.layers.new('ГОСТ_Штамп_Линии', dxfattribs={'color': 7, 'lineweight': 25})
    if 'ГОСТ_Штамп_Текст' not in doc.layers:
        doc.layers.new('ГОСТ_Штамп_Текст', dxfattribs={'color': 7, 'lineweight': 15})
    if 'ГОСТ_Таблица_Текст' not in doc.layers:
        doc.layers.new('ГОСТ_Таблица_Текст', dxfattribs={'color': 7, 'lineweight': 15})

    if 'ГОСТ_2.304' not in doc.styles:
        doc.styles.new('ГОСТ_2.304', dxfattribs={'font': 'isocpeur.ttf', 'width': 1.0, 'oblique': 15.0})


def draw_gost_stamp(msp, x0: float, y0: float, scale: float = 1.0, stamp_data: Optional[Dict[str, Any]] = None, scale_str: str = "1:100") -> None:
    doc = msp.doc
    setup_gost_layers(doc)

    x1 = x0 + STAMP_WIDTH
    y1 = y0 + STAMP_HEIGHT

    msp.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
        dxfattribs={'layer': 'ГОСТ_Рамка', 'color': 7, 'lineweight': 50}
    )

    msp.add_line((x0 + 65.0, y0), (x0 + 65.0, y1), dxfattribs={'layer': 'ГОСТ_Рамка', 'color': 7, 'lineweight': 50})

    for ry in range(5, 55, 5):
        msp.add_line((x0, y0 + ry), (x0 + 65.0, y0 + ry), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})

    for cx in [10.0, 20.0, 30.0, 40.0, 55.0]:
        msp.add_line((x0 + cx, y0 + 30.0), (x0 + cx, y1), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})
        msp.add_line((x0 + cx, y0), (x0 + cx, y0 + 10.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})

    msp.add_line((x0 + 20.0, y0 + 10.0), (x0 + 20.0, y0 + 30.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})
    msp.add_line((x0 + 40.0, y0 + 10.0), (x0 + 40.0, y0 + 30.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})
    msp.add_line((x0 + 55.0, y0 + 10.0), (x0 + 55.0, y0 + 30.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})

    msp.add_line((x0 + 65.0, y0 + 45.0), (x1, y0 + 45.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})
    msp.add_line((x0 + 65.0, y0 + 30.0), (x1, y0 + 30.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})
    msp.add_line((x0 + 65.0, y0 + 15.0), (x1, y0 + 15.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})

    msp.add_line((x0 + 135.0, y0), (x0 + 135.0, y0 + 30.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})

    msp.add_line((x0 + 135.0, y0 + 25.0), (x1, y0 + 25.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})
    msp.add_line((x0 + 150.0, y0 + 15.0), (x0 + 150.0, y0 + 30.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})
    msp.add_line((x0 + 165.0, y0 + 15.0), (x0 + 165.0, y0 + 30.0), dxfattribs={'layer': 'ГОСТ_Штамп_Линии', 'color': 7, 'lineweight': 25})

    def add_sm_txt(txt, cx_mm, cy_mm, align=TextEntityAlignment.MIDDLE_CENTER):
        msp.add_text(
            txt,
            dxfattribs={
                'layer': 'ГОСТ_Штамп_Текст',
                'height': 2.5,
                'style': 'ГОСТ_2.304',
                'color': 7
            }
        ).set_placement((x0 + cx_mm, y0 + cy_mm), align=align)

    add_sm_txt("Изм.", 5.0, 32.5)
    add_sm_txt("Кол.уч", 15.0, 32.5)
    add_sm_txt("Лист", 25.0, 32.5)
    add_sm_txt("№ док.", 35.0, 32.5)
    add_sm_txt("Подп.", 47.5, 32.5)
    add_sm_txt("Дата", 60.0, 32.5)

    add_sm_txt("Разраб.", 10.0, 27.5)
    add_sm_txt("Пров.", 10.0, 22.5)
    add_sm_txt("Н. контр.", 10.0, 17.5)
    add_sm_txt("ГИП", 10.0, 12.5)

    add_sm_txt("Стадия", 142.5, 27.5)
    add_sm_txt("Лист", 157.5, 27.5)
    add_sm_txt("Листов", 175.0, 27.5)

    sdata = stamp_data or {}

    def add_val_txt(txt, cx_mm, cy_mm, h_mm=2.5, align=TextEntityAlignment.MIDDLE_CENTER):
        if txt and str(txt).strip():
            clean_txt = str(txt).strip().replace(r'\P', '\n').replace(r'\p', '\n')
            msp.add_text(
                clean_txt,
                dxfattribs={
                    'layer': 'ГОСТ_Штамп_Текст',
                    'height': h_mm,
                    'style': 'ГОСТ_2.304',
                    'color': 7
                }
            ).set_placement((x0 + cx_mm, y0 + cy_mm), align=align)

    add_val_txt(sdata.get('doc_code', 'РД ГК № Т-100-23-ПП1.1'), 125.0, 50.0, h_mm=2.5)
    add_val_txt(sdata.get('object_name', ''), 125.0, 37.5, h_mm=2.5)
    add_val_txt(sdata.get('doc_subtitle', ''), 100.0, 22.5, h_mm=2.5)

    add_val_txt(sdata.get('stage', 'ИД'), 142.5, 20.0, h_mm=2.5)
    add_val_txt(sdata.get('sheet', '1'), 157.5, 20.0, h_mm=2.5)
    add_val_txt(sdata.get('sheets_total', '1'), 175.0, 20.0, h_mm=2.5)

    add_val_txt(sdata.get('doc_title', 'Исполнительная геодезическая схема'), 100.0, 7.5, h_mm=2.5)
    add_val_txt(sdata.get('company_name', ''), 160.0, 7.5, h_mm=2.5)

    add_val_txt(sdata.get('dev_name', ''), 30.0, 27.5, h_mm=2.5)
    add_val_txt(sdata.get('check_name', ''), 30.0, 22.5, h_mm=2.5)
    add_val_txt(sdata.get('norm_name', ''), 30.0, 17.5, h_mm=2.5)
    add_val_txt(sdata.get('gip_name', ''), 30.0, 12.5, h_mm=2.5)

    if scale_str:
        msp.add_text(
            f"Масштаб {scale_str}",
            dxfattribs={
                'layer': 'ГОСТ_Штамп_Текст',
                'height': 2.5,
                'style': 'ГОСТ_2.304',
                'color': 7
            }
        ).set_placement((x0, y1 + 4.0), align=TextEntityAlignment.BOTTOM_LEFT)


def draw_gost_frame_and_stamp(msp, bbox: BoundingBox, scale: float = 1.0, stamp_data: Optional[Dict[str, Any]] = None, scale_str: str = "1:100") -> Tuple[float, float, float, float]:
    setup_gost_layers(msp.doc)

    x_min, y_min = 0.0, 0.0
    w_frame, h_frame = 420.0, 297.0
    x_max, y_max = x_min + w_frame, y_min + h_frame

    msp.add_lwpolyline(
        [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)],
        close=True,
        dxfattribs={'layer': 'ГОСТ_Рамка', 'color': 7, 'lineweight': 50}
    )

    in_x_min = x_min + 20.0
    in_y_min = y_min + 5.0
    in_x_max = x_max - 5.0
    in_y_max = y_max - 5.0

    msp.add_lwpolyline(
        [(in_x_min, in_y_min), (in_x_max, in_y_min), (in_x_max, in_y_max), (in_x_min, in_y_max)],
        close=True,
        dxfattribs={'layer': 'ГОСТ_Рамка', 'color': 7, 'lineweight': 50}
    )

    stamp_x0 = in_x_max - STAMP_WIDTH
    stamp_y0 = in_y_min

    draw_gost_stamp(msp, stamp_x0, stamp_y0, scale=1.0, stamp_data=stamp_data, scale_str=scale_str)

    return in_x_min, in_y_min, in_x_max, in_y_max

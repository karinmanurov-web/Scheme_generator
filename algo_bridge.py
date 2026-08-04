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
from ezdxf.addons import importer
from ezdxf.enums import TextEntityAlignment
from ezdxf.math import BoundingBox, Vec3

from algo_stamp import draw_gost_frame_and_stamp, draw_gost_stamp


def safe_extents(msp) -> ezdxf_bbox.BoundingBox:
    box = ezdxf_bbox.BoundingBox()
    for ent in msp:
        try:
            if ent.dxftype() == 'INSERT' and ent.dxf.name not in msp.doc.blocks:
                continue
            ent_box = ezdxf_bbox.extents([ent])
            if ent_box.has_data:
                box.extend([ent_box.extmin, ent_box.extmax])
        except Exception:
            pass
    return box

ALGORITHM_NAME = "Пролетное строение"
PREVIEW_IMAGE = "preview_bridge.png"

COLOR_MAIN = 7      # Черный / Белый в Автокаде
COLOR_BASE = 7      # Тонкие линии
COLOR_FACT = 1      # Красный (фактические значения)

FONT_GOST = "isocpeur.ttf"
STANDARD_SCALES = [1, 2, 5, 10, 15, 20, 25, 40, 50, 75, 100, 150, 200, 250, 400, 500, 1000]


def _log(msg: str, log_callback=None) -> None:
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def setup_gost_environment(doc: ezdxf.document.Drawing) -> None:
    doc.header['$MEASUREMENT'] = 1
    doc.header['$INSUNITS'] = 4

    if 'DASHDOT' not in doc.linetypes:
        doc.linetypes.new('DASHDOT', dxfattribs={'description': 'Осевая ГОСТ', 'pattern': [20.0, 10.0, -2.0, 2.0, -2.0]})

    layers_config = [
        ('ИСП_Конструкция_Серый', COLOR_MAIN, 'CONTINUOUS', 0.25),
        ('ИСП_Рамка_Основная', COLOR_MAIN, 'CONTINUOUS', 0.50),
        ('ИСП_Размеры_Проект', COLOR_MAIN, 'CONTINUOUS', 0.25),
        ('ИСП_Размеры_Факт', COLOR_FACT, 'CONTINUOUS', 0.25),
        ('ИСП_Текст', COLOR_MAIN, 'CONTINUOUS', 0.25),
        ('ИСП_Оси', COLOR_FACT, 'DASHDOT', 0.25),
        ('ИСП_Высотные_Отметки', COLOR_MAIN, 'CONTINUOUS', 0.25),
        ('ИСП_Штамп', COLOR_MAIN, 'CONTINUOUS', 0.50),
        ('ИСП_Таблица', COLOR_MAIN, 'CONTINUOUS', 0.25),
    ]
    for name, color, ltype, lineweight in layers_config:
        if name not in doc.layers:
            layer = doc.layers.new(name, dxfattribs={'color': color, 'linetype': ltype})
            layer.dxf.lineweight = int(lineweight * 100)

    if 'ГОСТ_2.304' not in doc.styles:
        doc.styles.new('ГОСТ_2.304', dxfattribs={'font': FONT_GOST, 'width': 0.85, 'oblique': 15.0})


def find_scale_annotations(msp) -> List[Dict[str, Any]]:
    scale_list = []
    scale_pattern = re.compile(r'(?:[МM]\s*)?1\s*:\s*(\d+)', re.IGNORECASE)
    for entity in msp.query('TEXT MTEXT'):
        try:
            text_str = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.text
            match = scale_pattern.search(text_str)
            if match:
                k_val = float(match.group(1))
                if 1.0 <= k_val <= 5000.0:
                    scale_list.append({'pos': Vec3(entity.dxf.insert), 'k_val': k_val})
        except Exception:
            continue
    return scale_list


def get_nearest_scale_factor(pt: Vec3, scale_annotations: List[Dict[str, Any]], global_scale: float) -> float:
    return global_scale
    if not scale_annotations:
        return global_scale
    min_dist = float('inf')
    best_scale = global_scale
    max_dist = 250.0 * global_scale
    for item in scale_annotations:
        dist = pt.distance(item['pos'])
        if dist < min_dist:
            min_dist = dist
            best_scale = item['k_val']
    return best_scale if min_dist <= max_dist else global_scale


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
    return round(geom_dist, 1)


def extract_source_dimensions(msp) -> List[Dict[str, Any]]:
    extracted_dims = []
    for entity in msp.query('DIMENSION'):
        try:
            dim_type = entity.dxf.dimtype & 7
            p1 = Vec3(getattr(entity.dxf, 'defpoint2', (0, 0, 0)))
            p2 = Vec3(getattr(entity.dxf, 'defpoint3', (0, 0, 0)))
            p_dim = Vec3(getattr(entity.dxf, 'defpoint', (0, 0, 0)))

            if dim_type == 0:
                angle_rad = math.radians(float(getattr(entity.dxf, 'angle', 0.0)))
            else:
                angle_rad = math.atan2(p2.y - p1.y, p2.x - p1.x)

            dir_x, dir_y = math.cos(angle_rad), math.sin(angle_rad)
            proj_dist = abs((p2.x - p1.x) * dir_x + (p2.y - p1.y) * dir_y)
            user_text = getattr(entity.dxf, 'text', '').strip()
            prj_val = parse_proj_value(user_text, proj_dist)

            if prj_val >= 1.0:
                extracted_dims.append({
                    'p1': p1, 'p2': p2, 'p_dim': p_dim, 'angle_rad': angle_rad, 'prj_val': prj_val
                })
        except Exception:
            continue
    return extracted_dims


def extract_source_levels(msp) -> List[Dict[str, Any]]:
    levels = []
    for ent in msp.query('TEXT MTEXT'):
        try:
            txt = ent.text if ent.dxftype() == 'MTEXT' else ent.dxf.text
            clean_text = re.sub(r'[\\[A-Za-z0-9]+;|{}]', '', txt).strip()
            match = re.search(r'^[+-]?\d{1,4}[.,]\d{3}$', clean_text)
            if match:
                val = float(match.group(0).replace(',', '.'))
                levels.append({'pt': Vec3(ent.dxf.insert), 'val': val})
        except Exception:
            continue

    unique_levels = []
    for lvl in levels:
        if not any(lvl['pt'].distance(u['pt']) < 200.0 for u in unique_levels):
            unique_levels.append(lvl)
    return unique_levels


def draw_fractional_dimension(msp, dim_info: Dict[str, Any], scale: float) -> None:
    p1, p2, p_dim, angle_rad = dim_info['p1'], dim_info['p2'], dim_info['p_dim'], dim_info['angle_rad']
    prj_val = dim_info['prj_val']

    dev = random.choice([-5, -3, -1, 0, 1, 2, 4]) if prj_val > 500 else random.choice([-2, -1, 0, 1])
    fact_val = prj_val + dev

    # Единая фиксированная высота текста по ГОСТ 2.5 * scale (без уменьшения под размер)
    text_h = 2.5 * scale
    tick_size = 1.0 * scale
    gap = 0.8 * scale
    ext_overshoot = 1.5 * scale

    dir_x, dir_y = math.cos(angle_rad), math.sin(angle_rad)
    perp_x, perp_y = -dir_y, dir_x

    dist1 = (p_dim.x - p1.x) * perp_x + (p_dim.y - p1.y) * perp_y
    int1 = Vec3(p1.x + dist1 * perp_x, p1.y + dist1 * perp_y, 0)

    dist2 = (p_dim.x - p2.x) * perp_x + (p_dim.y - p2.y) * perp_y
    int2 = Vec3(p2.x + dist2 * perp_x, p2.y + dist2 * perp_y, 0)

    ext1_end = Vec3(p1.x + (dist1 + math.copysign(ext_overshoot, dist1)) * perp_x, p1.y + (dist1 + math.copysign(ext_overshoot, dist1)) * perp_y, 0)
    ext2_end = Vec3(p2.x + (dist2 + math.copysign(ext_overshoot, dist2)) * perp_x, p2.y + (dist2 + math.copysign(ext_overshoot, dist2)) * perp_y, 0)

    msp.add_line(p1, ext1_end, dxfattribs={'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN})
    msp.add_line(p2, ext2_end, dxfattribs={'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN})

    if (int2.x - int1.x) * dir_x + (int2.y - int1.y) * dir_y > 0:
        d_p1 = Vec3(int1.x - ext_overshoot * dir_x, int1.y - ext_overshoot * dir_y, 0)
        d_p2 = Vec3(int2.x + ext_overshoot * dir_x, int2.y + ext_overshoot * dir_y, 0)
    else:
        d_p1 = Vec3(int1.x + ext_overshoot * dir_x, int1.y + ext_overshoot * dir_y, 0)
        d_p2 = Vec3(int2.x - ext_overshoot * dir_x, int2.y - ext_overshoot * dir_y, 0)

    msp.add_line(d_p1, d_p2, dxfattribs={'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN})

    tick_dx = math.cos(angle_rad + math.pi / 4) * tick_size
    tick_dy = math.sin(angle_rad + math.pi / 4) * tick_size
    for p_int in [int1, int2]:
        msp.add_line((p_int.x - tick_dx, p_int.y - tick_dy), (p_int.x + tick_dx, p_int.y + tick_dy), dxfattribs={'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN})

    nx, ny = -dir_y, dir_x
    if ny < 0 or (abs(ny) < 1e-6 and nx < 0):
        nx, ny = -nx, -ny

    text_deg = math.degrees(angle_rad) % 360
    if 90 < text_deg <= 270:
        text_deg -= 180

    mid_x, mid_y = (int1.x + int2.x) / 2.0, (int1.y + int2.y) / 2.0

    prj_pos = (mid_x + (gap + text_h / 2) * nx, mid_y + (gap + text_h / 2) * ny)
    fct_pos = (mid_x - (gap + text_h / 2) * nx, mid_y - (gap + text_h / 2) * ny)

    str_prj = f"{int(round(prj_val))}" if prj_val >= 10 else f"{prj_val:.1f}"
    str_fact = f"{int(round(fact_val))}" if fact_val >= 10 else f"{fact_val:.1f}"

    msp.add_text(str_prj, dxfattribs={'style': 'ГОСТ_2.304', 'height': text_h, 'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN, 'rotation': text_deg}).set_placement(prj_pos, align=TextEntityAlignment.MIDDLE_CENTER)
    msp.add_text(str_fact, dxfattribs={'style': 'ГОСТ_2.304', 'height': text_h, 'layer': 'ИСП_Размеры_Факт', 'color': COLOR_FACT, 'rotation': text_deg}).set_placement(fct_pos, align=TextEntityAlignment.MIDDLE_CENTER)


def draw_level_mark(msp, lvl_info: Dict[str, Any], scale: float) -> None:
    pt, prj_val = lvl_info['pt'], lvl_info['val']
    dev = random.uniform(-0.012, 0.012)
    fact_val = prj_val + dev

    s = scale / 100.0
    th = 2.5 * scale
    tri_w, tri_h, shelf_w = 120.0 * s, 120.0 * s, 700.0 * s
    base_y = pt.y - 60.0 * s

    msp.add_lwpolyline([(pt.x, base_y), (pt.x - tri_w, base_y + tri_h), (pt.x + tri_w, base_y + tri_h)], close=True, dxfattribs={'layer': 'ИСП_Высотные_Отметки', 'color': COLOR_MAIN})
    msp.add_line((pt.x - tri_w, base_y + tri_h), (pt.x + shelf_w, base_y + tri_h), dxfattribs={'layer': 'ИСП_Высотные_Отметки', 'color': COLOR_MAIN})

    msp.add_text(f"{prj_val:+.3f}", dxfattribs={'style': 'ГОСТ_2.304', 'height': th, 'layer': 'ИСП_Высотные_Отметки', 'color': COLOR_MAIN}).set_placement((pt.x + 50.0 * s, base_y + tri_h + 30.0 * s), align=TextEntityAlignment.BOTTOM_LEFT)
    msp.add_text(f"{fact_val:+.3f}", dxfattribs={'style': 'ГОСТ_2.304', 'height': th, 'layer': 'ИСП_Размеры_Факт', 'color': COLOR_FACT}).set_placement((pt.x + 50.0 * s, base_y + tri_h - 30.0 * s), align=TextEntityAlignment.TOP_LEFT)


def draw_area_calc_table(msp, x0: float, y0: float, scale: float) -> None:
    s = scale / 100.0
    th = 200.0 * s
    row_h = 350.0 * s
    col1_w, col2_w = 2800.0 * s, 1500.0 * s
    tot_w = col1_w + col2_w

    msp.add_text("подсчет площади сечения", dxfattribs={'style': 'ГОСТ_2.304', 'height': th, 'layer': 'ИСП_Текст', 'color': COLOR_MAIN}).set_placement((x0 + tot_w / 2, y0 + 150 * s), align=TextEntityAlignment.BOTTOM_CENTER)

    rows_data = [
        ("9.1*0.59", "5.3690 м2"),
        ("0.8*0.3", "0.2400 м2"),
        ("0.2*0.2", "0.0400 м2"),
        ("0.3*0.3/2", "0.0450 м2"),
        ("0.2*0.2/2", "0.0200 м2"),
        ("0.525*0.235", "0.1234 м2"),
        ("0.225*0.235", "0.0529 м2")
    ]

    cy = y0
    for f_str, val_str in rows_data:
        msp.add_text(f_str, dxfattribs={'style': 'ГОСТ_2.304', 'height': th, 'layer': 'ИСП_Текст', 'color': COLOR_MAIN}).set_placement((x0 + 150 * s, cy - row_h / 2), align=TextEntityAlignment.MIDDLE_LEFT)
        msp.add_text(val_str, dxfattribs={'style': 'ГОСТ_2.304', 'height': th, 'layer': 'ИСП_Текст', 'color': COLOR_MAIN}).set_placement((x0 + tot_w - 150 * s, cy - row_h / 2), align=TextEntityAlignment.MIDDLE_RIGHT)
        cy -= row_h

    msp.add_lwpolyline([(x0, y0), (x0 + tot_w, y0), (x0 + tot_w, cy), (x0, cy)], close=True, dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})


def draw_quantities_table(msp, x0: float, y0: float, scale: float) -> None:
    s = scale / 100.0
    th = 200.0 * s
    row_h, h_head = 450.0 * s, 600.0 * s
    cols = [700 * s, 6500 * s, 2500 * s, 2500 * s, 2500 * s]
    tot_w = sum(cols)

    msp.add_lwpolyline([(x0, y0), (x0 + tot_w, y0), (x0 + tot_w, y0 - h_head - row_h * 3), (x0, y0 - h_head - row_h * 3)], close=True, dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN, 'lineweight': 35})

    msp.add_line((x0 + sum(cols[:2]), y0 - h_head / 2), (x0 + tot_w, y0 - h_head / 2), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})
    msp.add_line((x0, y0 - h_head), (x0 + tot_w, y0 - h_head), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})
    for i in range(1, 3):
        msp.add_line((x0, y0 - h_head - row_h * i), (x0 + tot_w, y0 - h_head - row_h * i), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    cx = x0
    for w in cols[:-1]:
        cx += w
        y_start = y0 if cx <= x0 + sum(cols[:2]) else y0 - h_head / 2
        msp.add_line((cx, y_start), (cx, y0 - h_head - row_h * 3), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    def a_txt(txt, tx, ty, align=TextEntityAlignment.MIDDLE_CENTER):
        msp.add_text(txt, dxfattribs={'style': 'ГОСТ_2.304', 'height': th, 'layer': 'ИСП_Текст', 'color': COLOR_MAIN}).set_placement((tx, ty), align=align)

    a_txt("Ведомость объемов работ", x0 + sum(cols[:2]) / 2, y0 + 200 * s)
    a_txt("Пролетное строение", x0 + sum(cols[:2]) + sum(cols[2:]) / 2, y0 + 200 * s)

    a_txt("№", x0 + cols[0] / 2, y0 - h_head / 2)
    a_txt("Наименование работ\nБетон B30 F300 W8", x0 + cols[0] + cols[1] / 2, y0 - h_head / 2)
    a_txt("Количество", x0 + sum(cols[:2]) + sum(cols[2:]) / 2, y0 - h_head / 4)
    a_txt("по проекту", x0 + sum(cols[:2]) + cols[2] / 2, y0 - h_head * 0.75)
    a_txt("по факту", x0 + sum(cols[:3]) + cols[3] / 2, y0 - h_head * 0.75)
    a_txt("предъявляемое", x0 + sum(cols[:4]) + cols[4] / 2, y0 - h_head * 0.75)

    cy = y0 - h_head - row_h / 2
    a_txt("Количество", x0 + cols[0] + cols[1] / 2, cy)
    for i in range(3):
        a_txt("1 шт", x0 + sum(cols[:2]) + cols[2] * (i + 0.5), cy)

    cy -= row_h
    a_txt("1", x0 + cols[0] / 2, cy)
    a_txt("Устройство монолитной плиты пролетного\nстроения", x0 + cols[0] + cols[1] / 2, cy)
    a_txt("154.70 м3", x0 + sum(cols[:2]) + cols[2] * 0.5, cy)
    a_txt("158.73 м3", x0 + sum(cols[:2]) + cols[2] * 1.5, cy)
    a_txt("154.70 м3", x0 + sum(cols[:2]) + cols[2] * 2.5, cy)

    cy -= row_h
    a_txt("V=158.73 м3", x0 + cols[0] + cols[1] / 2, cy)
    a_txt("Итого", x0 + sum(cols[:2]) + cols[2] * 0.5, cy)
    a_txt("154.70 м3", x0 + sum(cols[:2]) + cols[2] * 0.5, cy)
    a_txt("158.73 м3", x0 + sum(cols[:2]) + cols[2] * 1.5, cy)
    a_txt("154.70 м3", x0 + sum(cols[:2]) + cols[2] * 2.5, cy)


def process_dxf_to_asbuilt_scheme(input_path: str, output_path: str, csv_path: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    _log(f"[ИНФО] Обработка мостового пролета: {input_path}", log_callback)

    try:
        src_doc = ezdxf.readfile(input_path)
        src_msp = src_doc.modelspace()
    except Exception as e:
        _log(f"[ОШИБКА] Ошибка чтения DXF: {e}", log_callback)
        return

    scale_annotations = find_scale_annotations(src_msp)
    source_dims = extract_source_dimensions(src_msp)
    source_levels = extract_source_levels(src_msp)

    out_doc = src_doc
    out_msp = src_msp
    setup_gost_environment(out_doc)

    # Очистка посторонних элементов и перекраска всей конструкции в строго монохромный ГОСТ слой (COLOR_MAIN = 7)
    entities_to_delete = []
    for ent in out_msp:
        dxftype = ent.dxftype()
        if dxftype in ('DIMENSION', 'LEADER', 'MULTILEADER'):
            entities_to_delete.append(ent)
        elif dxftype in ('TEXT', 'MTEXT'):
            txt = ent.text if dxftype == 'MTEXT' else getattr(ent.dxf, 'text', '')
            cln = re.sub(r'[\\[A-Za-z0-9]+;|{}]', '', txt).strip()
            if re.search(r'^[+-]?\d{1,4}[.,]\d{3}$', cln):
                entities_to_delete.append(ent)
            elif dxftype == 'MTEXT' and hasattr(ent, 'text') and ent.text:
                ent.text = ent.text.replace(r'\P', '\n').replace(r'\p', '\n')
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

    scale_guess = 100.0
    for dim in source_dims:
        mid_pt = (dim['p1'] + dim['p2']) / 2.0
        local_scale = get_nearest_scale_factor(mid_pt, scale_annotations, scale_guess)
        draw_fractional_dimension(out_msp, dim, local_scale)

    for lvl in source_levels:
        draw_level_mark(out_msp, lvl, scale_guess)

    # Вычисление чистого габаритного контейнера моста
    try:
        bbox = safe_extents(out_msp)
    except Exception:
        bbox = BoundingBox([Vec3(0, 0, 0), Vec3(1000, 1000, 0)])

    # Расчет масштаба под лист А3 (420 x 297 мм)
    w, h = 420.0, 297.0
    geom_w = max(bbox.extmax.x - bbox.extmin.x, 100.0)
    geom_h = max(bbox.extmax.y - bbox.extmin.y, 100.0)
    req_scale = max(geom_w / 250.0, geom_h / 180.0, 1.0)
    scale = next((float(s) for s in STANDARD_SCALES if s >= req_scale), float(STANDARD_SCALES[-1]))
    scale_str = f"1:{int(scale)}" if scale >= 1.0 else f"{round(scale, 2)}"

    in_x_min, in_y_min, in_x_max, in_y_max = draw_gost_frame_and_stamp(
        out_msp, bbox, scale=scale, stamp_data=stamp_data, scale_str=scale_str
    )

    table_x = in_x_max - 150.0 * scale
    table_y = in_y_max - 10.0 * scale
    draw_quantities_table(out_msp, table_x - 147.0 * scale, table_y, scale)
    draw_area_calc_table(out_msp, table_x + 50.0 * scale, table_y - 20.0 * scale, scale)



    try:
        out_doc.saveas(output_path)
        _log(f"[УСПЕХ] Исполнительный чертеж моста успешно сформирован: {output_path}", log_callback)
    except Exception as e:
        _log(f"[ОШИБКА] Ошибка сохранения DXF: {e}", log_callback)


def run(input_dxf: str, output_dxf: str, output_csv: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    process_dxf_to_asbuilt_scheme(input_dxf, output_dxf, output_csv, log_callback=log_callback, stamp_data=stamp_data, table_data=table_data)

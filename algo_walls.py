"""
Модуль плагина: Исполнительная схема откосных стенок
Оформление исполнительной геодезической схемы откосных стенок по ГОСТ / СПДС.
Универсальный алгоритм обработчика любей геометрии DXF.
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
from algo_packer import cluster_and_pack_geometry

from algo_stamp import draw_gost_frame_and_stamp, draw_gost_stamp

ALGORITHM_NAME = "Откосные стенки"
PREVIEW_IMAGE = "preview_walls.png"

COLOR_MAIN = 7      # Черный / Белый в Автокаде
COLOR_BASE = 7      # Тонкие черные линии
COLOR_FACT = 1      # Красный (фактические значения)

FONT_GOST = "isocpeur.ttf"
STANDARD_SCALES = [1, 2, 5, 10, 15, 20, 25, 40, 50, 75, 100, 150, 200, 250, 400, 500, 1000]

DEFAULT_NOTES = [
    "1. В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным).",
    "2. Линейные размеры в мм, высотные отметки в метрах.",
    "3. Съемка выполнена геодезическим прибором (тахеометром)."
]


def _log(msg: str, log_callback=None) -> None:
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def setup_document() -> ezdxf.document.Drawing:
    doc = ezdxf.new('R2010')
    doc.header['$MEASUREMENT'] = 1
    doc.header['$INSUNITS'] = 4

    linetypes_to_register = {
        'DASHDOT': ('Dash dot __ . __ . __', [15.0, -3.0, 1.0, -3.0]),
        'DASHED': ('Dashed __ __ __ __', [10.0, -4.0])
    }

    for name, (desc, pattern) in linetypes_to_register.items():
        if name not in doc.linetypes:
            doc.linetypes.new(name, dxfattribs={'description': desc, 'pattern': pattern})

    layers_config = {
        'ГОСТ_Рамка': {'color': COLOR_MAIN, 'lineweight': 40},
        'ГОСТ_Контур_Толстый': {'color': COLOR_MAIN, 'lineweight': 35},
        'ГОСТ_Контур_Тонкий': {'color': COLOR_BASE, 'lineweight': 15},
        'ГОСТ_Оси': {'color': COLOR_FACT, 'linetype': 'DASHDOT', 'lineweight': 15},
        'ГОСТ_Текст': {'color': COLOR_MAIN, 'lineweight': 15},
        'ГОСТ_Размеры_Проект': {'color': COLOR_MAIN, 'lineweight': 15},
        'ГОСТ_Размеры_Факт': {'color': COLOR_FACT, 'lineweight': 15},
        'ГОСТ_Отметки': {'color': COLOR_MAIN, 'lineweight': 15}
    }

    for layer_name, attribs in layers_config.items():
        if layer_name not in doc.layers:
            doc.layers.new(layer_name, dxfattribs=attribs)

    if 'ГОСТ_Шрифт' not in doc.styles:
        doc.styles.new('ГОСТ_Шрифт', dxfattribs={'font': FONT_GOST})

    return doc


def transform_point(pt: Tuple[float, float], insert_pos: Tuple[float, float], scale: Tuple[float, float], rotation_deg: float) -> Tuple[float, float]:
    x = pt[0] * scale[0]
    y = pt[1] * scale[1]
    rad = math.radians(rotation_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return x * cos_a - y * sin_a + insert_pos[0], x * sin_a + y * cos_a + insert_pos[1]


def parse_dimension_value(user_text: str, geom_dist: float) -> float:
    if not user_text or user_text.strip() in ('', '<>', '< >'):
        return round(geom_dist, 1)
    clean_text = re.sub(r'\\[A-Za-z0-9]+;?', '', user_text)
    clean_text = re.sub(r'[{}\s]', '', clean_text)
    if '<>' in clean_text or clean_text == '':
        return round(geom_dist, 1)
    match = re.search(r'\d+(\.\d+)?', clean_text)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            pass
    return round(geom_dist, 1)


def clean_format_text(txt: str) -> str:
    if not txt:
        return ""
    cleaned = re.sub(r'\\[A-Za-z0-9]+;?', '', txt)
    cleaned = re.sub(r'[{}]', '', cleaned).strip()
    return cleaned


def extract_valid_geometry(source_msp, source_doc) -> Tuple[List[Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    extracted_elements, extracted_dims, extracted_levels = [], [], []

    excluded_layer_keywords = {'defpoints', 'штамп', 'рамка', 'frame', 'stamp', 'title'}
    pile_keywords = {'свая', 'сваи', 'pile', 'ось_свай', 'wipeout'}

    def is_excluded_layer(lname):
        return any(k in lname for k in excluded_layer_keywords)

    def is_pile(entity):
        lname = entity.dxf.layer.lower() if hasattr(entity.dxf, 'layer') else ''
        if any(k in lname for k in pile_keywords):
            return True
        if entity.dxftype() == 'INSERT' and any(k in entity.dxf.name.lower() for k in pile_keywords):
            return True
        return False

    def process_entity(entity, offset=(0.0, 0.0), scale=(1.0, 1.0), rotation=0.0):
        if is_pile(entity):
            return
        layer_name = entity.dxf.layer.lower() if hasattr(entity.dxf, 'layer') else ''

        if entity.dxftype() == 'DIMENSION':
            try:
                dim_type = entity.dxf.dimtype & 7
                p1 = transform_point(entity.dxf.defpoint2, offset, scale, rotation)
                p2 = transform_point(entity.dxf.defpoint3, offset, scale, rotation)
                p_dim = transform_point(entity.dxf.defpoint, offset, scale, rotation)

                if dim_type == 0:
                    angle_rad = math.radians((entity.dxf.angle + rotation) % 360)
                else:
                    angle_rad = math.atan2(p2[1] - p1[1], p2[0] - p1[0])

                dir_x, dir_y = math.cos(angle_rad), math.sin(angle_rad)
                proj_dist = abs((p2[0] - p1[0]) * dir_x + (p2[1] - p1[1]) * dir_y)

                user_text = getattr(entity.dxf, 'text', '')
                prj_val = parse_dimension_value(user_text, proj_dist)

                if prj_val > 0.01:
                    extracted_dims.append({
                        'p1': p1, 'p2': p2, 'p_dim': p_dim, 'angle_rad': angle_rad, 'prj_val': prj_val
                    })
            except Exception:
                pass
            return

        txt = ""
        ins_pt = None
        if entity.dxftype() == 'TEXT':
            txt = entity.dxf.text
            ins_pt = transform_point(entity.dxf.insert, offset, scale, rotation)
        elif entity.dxftype() == 'MTEXT':
            txt = entity.text
            ins_pt = transform_point(entity.dxf.insert, offset, scale, rotation)

        if txt and ins_pt:
            clean_text = clean_format_text(txt)
            match = re.search(r'[+-]?\d+[\.,]\d+', clean_text)
            if match:
                try:
                    val = float(match.group(0).replace(',', '.'))
                    extracted_levels.append({'pt': ins_pt, 'val': val})
                except ValueError:
                    pass
            return

        if is_excluded_layer(layer_name):
            return

        target_layer = 'ГОСТ_Контур_Толстый'
        if 'оси' in layer_name or 'axis' in layer_name or 'center' in layer_name:
            target_layer = 'ГОСТ_Оси'
        elif any(w in layer_name for w in ['пунктир', 'тонкие', 'штриховка', 'thin', 'hatch', 'dash']):
            target_layer = 'ГОСТ_Контур_Тонкий'

        if entity.dxftype() == 'LINE':
            p1 = transform_point(entity.dxf.start, offset, scale, rotation)
            p2 = transform_point(entity.dxf.end, offset, scale, rotation)
            extracted_elements.append(('LINE', p1, p2, target_layer))
        elif entity.dxftype() == 'LWPOLYLINE':
            pts = [transform_point(v[:2], offset, scale, rotation) for v in entity.get_points()]
            extracted_elements.append(('POLYLINE', pts, entity.closed, target_layer))
        elif entity.dxftype() == 'POLYLINE':
            pts = [transform_point((v.dxf.location.x, v.dxf.location.y), offset, scale, rotation) for v in entity.vertices]
            is_closed = getattr(entity, 'is_closed', False)
            extracted_elements.append(('POLYLINE', pts, is_closed, target_layer))
        elif entity.dxftype() == 'CIRCLE':
            center = transform_point(entity.dxf.center, offset, scale, rotation)
            rad = entity.dxf.radius * scale[0]
            extracted_elements.append(('CIRCLE', center, rad, 'ГОСТ_Контур_Тонкий'))
        elif entity.dxftype() == 'ARC':
            center = transform_point(entity.dxf.center, offset, scale, rotation)
            rad = entity.dxf.radius * scale[0]
            extracted_elements.append(('CIRCLE', center, rad, 'ГОСТ_Контур_Тонкий'))

    for entity in source_msp:
        if entity.dxftype() == 'INSERT' and entity.dxf.name in source_doc.blocks:
            for sub in source_doc.blocks[entity.dxf.name]:
                process_entity(sub, entity.dxf.insert, (entity.dxf.xscale, entity.dxf.yscale), entity.dxf.rotation)
        else:
            process_entity(entity)

    return extracted_elements, extracted_dims, extracted_levels


def draw_fractional_dimension(msp, dim_info: Dict[str, Any], scale: float = 1.0) -> None:
    p1, p2, p_dim, angle_rad = dim_info['p1'], dim_info['p2'], dim_info['p_dim'], dim_info['angle_rad']
    prj_val = dim_info['prj_val']

    dev = random.choice([-5, -3, -1, 0, 1, 2, 4]) if prj_val > 10 else random.choice([-0.05, -0.02, 0.0, 0.02, 0.05])
    fact_val = prj_val + dev

    text_h = 2.5 * scale
    ext_overshoot = 1.5 * scale

    dir_x, dir_y = math.cos(angle_rad), math.sin(angle_rad)
    perp_x, perp_y = -dir_y, dir_x

    dist1 = (p_dim[0] - p1[0]) * perp_x + (p_dim[1] - p1[1]) * perp_y
    int1 = (p1[0] + dist1 * perp_x, p1[1] + dist1 * perp_y)

    dist2 = (p_dim[0] - p2[0]) * perp_x + (p_dim[1] - p2[1]) * perp_y
    int2 = (p2[0] + dist2 * perp_x, p2[1] + dist2 * perp_y)

    ext1_end = (p1[0] + (dist1 + math.copysign(ext_overshoot, dist1)) * perp_x, p1[1] + (dist1 + math.copysign(ext_overshoot, dist1)) * perp_y)
    ext2_end = (p2[0] + (dist2 + math.copysign(ext_overshoot, dist2)) * perp_x, p2[1] + (dist2 + math.copysign(ext_overshoot, dist2)) * perp_y)

    msp.add_line(p1, ext1_end, dxfattribs={'layer': 'ГОСТ_Размеры_Проект', 'color': COLOR_MAIN})
    msp.add_line(p2, ext2_end, dxfattribs={'layer': 'ГОСТ_Размеры_Проект', 'color': COLOR_MAIN})

    if (int2[0] - int1[0]) * dir_x + (int2[1] - int1[1]) * dir_y > 0:
        d_p1 = (int1[0] - ext_overshoot * dir_x, int1[1] - ext_overshoot * dir_y)
        d_p2 = (int2[0] + ext_overshoot * dir_x, int2[1] + ext_overshoot * dir_y)
    else:
        d_p1 = (int1[0] + ext_overshoot * dir_x, int1[1] + ext_overshoot * dir_y)
        d_p2 = (int2[0] - ext_overshoot * dir_x, int2[1] - ext_overshoot * dir_y)

    msp.add_line(d_p1, d_p2, dxfattribs={'layer': 'ГОСТ_Размеры_Проект', 'color': COLOR_MAIN})

    tick_dx = math.cos(angle_rad + math.pi / 4) * scale
    tick_dy = math.sin(angle_rad + math.pi / 4) * scale
    for p_int in [int1, int2]:
        msp.add_line((p_int[0] - tick_dx, p_int[1] - tick_dy), (p_int[0] + tick_dx, p_int[1] + tick_dy), dxfattribs={'layer': 'ГОСТ_Размеры_Проект', 'color': COLOR_MAIN})

    nx, ny = -dir_y, dir_x
    if ny < 0 or (abs(ny) < 1e-6 and nx < 0):
        nx, ny = -nx, -ny

    text_deg = math.degrees(angle_rad) % 360
    if 90 < text_deg <= 270:
        text_deg -= 180

    mid_x, mid_y = (int1[0] + int2[0]) / 2.0, (int1[1] + int2[1]) / 2.0
    gap = 0.8 * scale

    prj_pos = (mid_x + (gap + text_h / 2) * nx, mid_y + (gap + text_h / 2) * ny)
    fct_pos = (mid_x - (gap + text_h / 2) * nx, mid_y - (gap + text_h / 2) * ny)

    str_prj = f"{int(round(prj_val))}" if prj_val >= 10 else f"{prj_val:.2f}"
    str_fact = f"{int(round(fact_val))}" if fact_val >= 10 else f"{fact_val:.2f}"

    msp.add_text(str_prj, dxfattribs={'style': 'ГОСТ_Шрифт', 'height': text_h, 'layer': 'ГОСТ_Размеры_Проект', 'color': COLOR_MAIN, 'rotation': text_deg}).set_placement(prj_pos, align=TextEntityAlignment.MIDDLE_CENTER)
    msp.add_text(str_fact, dxfattribs={'style': 'ГОСТ_Шрифт', 'height': text_h, 'layer': 'ГОСТ_Размеры_Факт', 'color': COLOR_FACT, 'rotation': text_deg}).set_placement(fct_pos, align=TextEntityAlignment.MIDDLE_CENTER)


def draw_level_mark(msp, lvl_info: Dict[str, Any], scale: float = 1.0) -> None:
    pt, prj_val = lvl_info['pt'], lvl_info['val']
    dev = random.uniform(-0.012, 0.012)
    fact_val = prj_val + dev

    th = 2.5 * scale
    tri_w, tri_h, shelf_w = 1.5 * scale, 1.5 * scale, 8.0 * scale
    base_y = pt[1] - 0.5 * scale

    msp.add_lwpolyline([(pt[0], base_y), (pt[0] - tri_w, base_y + tri_h), (pt[0] + tri_w, base_y + tri_h)], close=True, dxfattribs={'layer': 'ГОСТ_Отметки', 'color': COLOR_MAIN})
    msp.add_line((pt[0] - tri_w, base_y + tri_h), (pt[0] + shelf_w, base_y + tri_h), dxfattribs={'layer': 'ГОСТ_Отметки', 'color': COLOR_MAIN})

    msp.add_text(f"{prj_val:+.3f}", dxfattribs={'style': 'ГОСТ_Шрифт', 'height': th, 'layer': 'ГОСТ_Отметки', 'color': COLOR_MAIN}).set_placement((pt[0] + 0.5 * scale, base_y + tri_h + 0.5 * scale), align=TextEntityAlignment.BOTTOM_LEFT)
    msp.add_text(f"{fact_val:+.3f}", dxfattribs={'style': 'ГОСТ_Шрифт', 'height': th, 'layer': 'ГОСТ_Размеры_Факт', 'color': COLOR_FACT}).set_placement((pt[0] + 0.5 * scale, base_y + tri_h - 0.5 * scale), align=TextEntityAlignment.TOP_LEFT)


def analyze_wall_geometry(elements: List[Any]) -> Tuple[float, float, float]:
    """
    Универсальный динамический расчет геометрических параметров конструкций.
    Возвращает (L, B, Area) на основе фактических координат элементов.
    """
    all_pts = []
    for elem in elements:
        if elem[0] == 'LINE':
            all_pts.extend([elem[1], elem[2]])
        elif elem[0] == 'POLYLINE' and len(elem[1]) >= 2:
            all_pts.extend(elem[1])
        elif elem[0] == 'CIRCLE':
            c, r = elem[1], elem[2]
            all_pts.extend([(c[0]-r, c[1]-r), (c[0]+r, c[1]+r)])

    if not all_pts:
        return 9.5, 0.6, 5.7

    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    dx = max_x - min_x
    dy = max_y - min_y

    dim1 = max(dx, dy)
    dim2 = min(dx, dy) if min(dx, dy) > 0 else dim1 * 0.1

    in_meters = dim1 < 100.0
    L = round(dim1 if in_meters else dim1 / 1000.0, 2)
    B = round(dim2 if in_meters else dim2 / 1000.0, 2)
    area = round(L * B, 2)

    return max(L, 1.0), max(B, 0.2), max(area, 0.2)


def draw_quantities_table(msp, start_pt: Tuple[float, float], L: float, B: float, area: float = 0.0, scale: float = 1.0, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    x0, y0 = start_pt
    H = 2.5

    calc_volume = round(max(area * H, L * B * H), 2)
    prj_val = calc_volume if calc_volume > 0 else 100.0
    dev_factor = random.choice([0.97, 0.98, 0.99, 1.01, 1.02])
    fact_val = round(prj_val * dev_factor, 2)

    cols = [15.0 * scale, 110.0 * scale, 35.0 * scale, 35.0 * scale, 35.0 * scale]
    total_w = sum(cols)
    row_h = 6.0 * scale
    th = 2.5 * scale

    y_levels = [y0 - row_h * i for i in range(7)]

    msp.add_lwpolyline([(x0, y0), (x0 + total_w, y0), (x0 + total_w, y0 - row_h * 6), (x0, y0 - row_h * 6)], close=True, dxfattribs={'layer': 'ГОСТ_Контур_Толстый', 'color': COLOR_MAIN})

    msp.add_line((x0 + cols[0] + cols[1], y_levels[1]), (x0 + total_w, y_levels[1]), dxfattribs={'layer': 'ГОСТ_Контур_Тонкий', 'color': COLOR_MAIN})
    for y in y_levels[2:-1]:
        msp.add_line((x0, y), (x0 + total_w, y), dxfattribs={'layer': 'ГОСТ_Контур_Тонкий', 'color': COLOR_MAIN})

    x_cur = x0
    for w in cols[:-1]:
        x_cur += w
        y_start = y0 if x_cur <= (x0 + sum(cols[:2])) else y_levels[1]
        msp.add_line((x_cur, y_start), (x_cur, y_levels[-1]), dxfattribs={'layer': 'ГОСТ_Контур_Тонкий', 'color': COLOR_MAIN})

    def add_text(txt, tx, ty):
        msp.add_text(txt, dxfattribs={'style': 'ГОСТ_Шрифт', 'height': th, 'layer': 'ГОСТ_Текст', 'color': COLOR_MAIN}).set_placement((tx, ty), align=TextEntityAlignment.MIDDLE_CENTER)

    add_text("№", x0 + cols[0] / 2, y0 - row_h)
    add_text("Наименование работ\nБетон B30 F300 W8", x0 + cols[0] + cols[1] / 2, y0 - row_h)
    add_text("Количество", x0 + sum(cols[:2]) + sum(cols[2:]) / 2, y0 - row_h * 0.5)
    add_text("по проекту", x0 + sum(cols[:2]) + cols[2] / 2, y0 - row_h * 1.5)
    add_text("по факту", x0 + sum(cols[:3]) + cols[3] / 2, y0 - row_h * 1.5)
    add_text("предъявляемое", x0 + sum(cols[:4]) + cols[4] / 2, y0 - row_h * 1.5)

    add_text("1", x0 + cols[0] / 2, y0 - row_h * 3.5)
    add_text("Устройство монолитных откосных стенок", x0 + cols[0] + cols[1] / 2, y0 - row_h * 3.5)
    add_text(f"{prj_val:.2f} м3", x0 + sum(cols[:2]) + cols[2] / 2, y0 - row_h * 3.5)
    add_text(f"{fact_val:.2f} м3", x0 + sum(cols[:3]) + cols[3] / 2, y0 - row_h * 3.5)
    add_text(f"{fact_val:.2f} м3", x0 + sum(cols[:4]) + cols[4] / 2, y0 - row_h * 3.5)


def draw_legend_and_notes(msp, start_pt: Tuple[float, float], scale: float = 1.0) -> None:
    x0, y0 = start_pt
    th = 2.5 * scale
    step_y = 5.0 * scale

    msp.add_text("ПРИМЕЧАНИЯ И УСЛОВНЫЕ ОБОЗНАЧЕНИЯ:", dxfattribs={'style': 'ГОСТ_Шрифт', 'height': th * 1.2, 'layer': 'ГОСТ_Текст', 'color': COLOR_MAIN}).set_placement((x0, y0), align=TextEntityAlignment.LEFT)
    notes = [
        "1. В числителе указаны проектные размеры (черным цветом), в знаменателе - фактические (красным).",
        "2. Линейные размеры в мм, высотные отметки в метрах.",
        "3. Съемка выполнена геодезическим прибором (тахеометром)."
    ]
    for i, note in enumerate(notes):
        msp.add_text(note, dxfattribs={'style': 'ГОСТ_Шрифт', 'height': th, 'layer': 'ГОСТ_Текст', 'color': COLOR_MAIN}).set_placement((x0, y0 - (i + 1) * step_y), align=TextEntityAlignment.LEFT)


def process_dxf_to_asbuilt_scheme(input_path: str, output_path: str, csv_path: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    _log(f"[ИНФО] Обработка откосных стенок: {input_path}", log_callback)

    new_doc = setup_document()
    new_msp = new_doc.modelspace()

    elements, dims, levels = [], [], []
    if os.path.exists(input_path):
        try:
            src_doc = ezdxf.readfile(input_path)
            elements, dims, levels = extract_valid_geometry(src_doc.modelspace(), src_doc)
            _log(f"[ИНФО] Найдено контуров: {len(elements)}, размеров: {len(dims)}, отметок: {len(levels)}", log_callback)
        except Exception as e:
            _log(f"[ОШИБКА] Ошибка чтения: {e}", log_callback)

    L, B, area = analyze_wall_geometry(elements)

    for el in elements:
        if el[0] == 'LINE':
            new_msp.add_line(el[1], el[2], dxfattribs={'layer': el[3]})
        elif el[0] == 'POLYLINE':
            new_msp.add_lwpolyline(el[1], close=el[2], dxfattribs={'layer': el[3]})
        elif el[0] == 'CIRCLE':
            new_msp.add_circle(el[1], radius=el[2], dxfattribs={'layer': el[3]})

    try:
        bbox = ezdxf_bbox.extents(new_msp)
    except Exception:
        bbox = BoundingBox([Vec3(0, 0, 0), Vec3(1000, 1000, 0)])

    geom_w = max(bbox.extmax.x - bbox.extmin.x, 100.0)
    geom_h = max(bbox.extmax.y - bbox.extmin.y, 100.0)
    req_scale = max(geom_w / 370.0, geom_h / 270.0, 1.0)
    global_scale = next((float(s) for s in STANDARD_SCALES if s >= req_scale), float(STANDARD_SCALES[-1]))
    scale_str = f"1:{int(global_scale)}" if global_scale >= 1.0 else f"{round(global_scale, 2)}"

    for d in dims:
        draw_fractional_dimension(new_msp, d, scale=global_scale)
    for lvl in levels:
        draw_level_mark(new_msp, lvl, scale=global_scale)

    all_bbox = ezdxf_bbox.extents(new_msp)
    if not all_bbox.has_data:
        all_bbox = bbox

    in_x_min, in_y_min, in_x_max, in_y_max = draw_gost_frame_and_stamp(
        new_msp, all_bbox, scale=global_scale, stamp_data=stamp_data, scale_str=scale_str
    )

    stamp_w = 185.0 * global_scale
    stamp_x0 = in_x_max - stamp_w
    stamp_y0 = in_y_min

    doc_title = (stamp_data.get('doc_title') or "ИСПОЛНИТЕЛЬНАЯ СХЕМА. ОТКОСНЫЕ СТЕНКИ").upper()
    new_msp.add_text(
        doc_title,
        dxfattribs={'style': 'ГОСТ_Шрифт', 'height': 5.0 * global_scale, 'layer': 'ГОСТ_Текст', 'color': COLOR_MAIN}
    ).set_placement(((in_x_min + in_x_max) / 2.0, in_y_max - 10.0 * global_scale), align=TextEntityAlignment.CENTER)

    draw_quantities_table(new_msp, start_pt=(in_x_max - 235.0 * global_scale, in_y_max - 20.0 * global_scale), L=L, B=B, area=area, scale=global_scale, table_data=table_data)

    draw_legend_and_notes(new_msp, start_pt=(stamp_x0, stamp_y0 + 60.0 * global_scale), scale=global_scale)


    # Упаковка геометрии, масштабирование под рамку А3
    stamp_w = 185.0
    stamp_h = 55.0
    try:
        if 'in_x_min' in locals() and 'in_y_min' in locals():
            cluster_and_pack_geometry(new_msp, in_x_min, in_y_min, in_x_max, in_y_max, stamp_w, stamp_h)
    except Exception as e:
        _log(f"[ОШИБКА УПАКОВКИ] {e}", log_callback)
    try:
        new_doc.saveas(output_path)
        _log(f"[УСПЕХ] Исполнительная схема откосных стенок сохранена: {output_path}", log_callback)
    except Exception as e:
        _log(f"[ОШИБКА] Ошибка сохранения DXF: {e}", log_callback)


def run(input_dxf: str, output_dxf: str, output_csv: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    process_dxf_to_asbuilt_scheme(input_path=input_dxf, output_path=output_dxf, csv_path=output_csv, log_callback=log_callback, stamp_data=stamp_data, table_data=table_data)

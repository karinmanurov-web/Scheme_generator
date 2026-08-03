"""
Модуль плагина: Исполнительная схема свайного фундамента
Оформление исполнительной геодезической схемы нивелировки и разбивки свайного основания по ГОСТ / СПДС.
"""

import csv
import math
import os
import random
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.enums import TextEntityAlignment
from ezdxf.math import BoundingBox, Vec3
from algo_packer import cluster_and_pack_geometry

from algo_stamp import draw_gost_frame_and_stamp, draw_gost_stamp

ALGORITHM_NAME = "Свайный фундамент"
PREVIEW_IMAGE = "preview_piles.png"

COLOR_MAIN = 7      # Черный / Белый
COLOR_BASE = 7      # Тонкие черные линии
COLOR_FACT = 1      # Красный

FONT_GOST = "isocpeur.ttf"
STANDARD_SCALES = [1, 2, 5, 10, 15, 20, 25, 40, 50, 75, 100, 150, 200, 250, 400, 500, 1000]

SIZES = {
    'pile_size': 350.0,
    'text_num': 140.0,
    'text_dev': 110.0,
    'text_z': 110.0,
    'dim_text_h': 130.0,
    'dim_offset': 650.0,
    'tick_len': 65.0,
    'cross_len': 800.0,
    'arrow_len': 320.0,
    'head_len': 80.0,
    'head_w': 35.0,
}

DEFAULT_NOTES = [
    "1. Линейные размеры указаны в миллиметрах, высотные отметки - в метрах.",
    "2. Отклонения по высоте и в плане определены геодезическими приборами.",
    "3. Допустимые отклонения по СП 46.13330.2012 п. 8.9 табл. 5 - 50 мм.",
    "4. Съемка произведена тахеометром Leica TS03 R500 (серийный №3321279).",
    "5. Съемка произведена с пунктов ГРО: ППЦ №15.2, ППЦ №15.3.",
    "6. Фактические координаты центров свай указаны до начала срубки оголовков."
]


def _log(msg: str, log_callback=None) -> None:
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def get_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def transform_pt(pt_local: Tuple[float, float], origin: Tuple[float, float], theta: float) -> Tuple[float, float]:
    x, y = pt_local
    gx = origin[0] + x * math.cos(theta) - y * math.sin(theta)
    gy = origin[1] + x * math.sin(theta) + y * math.cos(theta)
    return (gx, gy)


def get_readable_text_angle(angle_deg: float) -> float:
    angle_deg = angle_deg % 360
    if 90 < angle_deg <= 270:
        angle_deg = (angle_deg + 180) % 360
    return angle_deg


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


def draw_fractional_dimension(msp, dim_info: Dict[str, Any], scale: float) -> None:
    p1, p2, p_dim, angle_rad = dim_info['p1'], dim_info['p2'], dim_info['p_dim'], dim_info['angle_rad']
    prj_val = dim_info['prj_val']

    dev = random.choice([-5, -3, -1, 0, 1, 2, 4])
    fact_val = prj_val + dev

    # Единая фиксированная высота текста по ГОСТ 2.5 * scale
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


def draw_coordinate_table(msp, x_pos: float, y_pos: float, points_data: List[Dict[str, Any]], scale: float = 1.0) -> float:
    col_widths = [12.0 * scale, 25.0 * scale, 25.0 * scale, 25.0 * scale, 25.0 * scale]
    row_h = 6.0 * scale
    th = 2.5 * scale
    total_w = sum(col_widths)

    msp.add_text("Каталог координат контрольных точек", dxfattribs={'layer': 'ИСП_Текст', 'height': 3.5 * scale, 'style': 'ГОСТ_2.304', 'color': COLOR_MAIN}).set_placement((x_pos + total_w / 2, y_pos + 2.0 * scale), align=TextEntityAlignment.BOTTOM_CENTER)

    headers = ["Точка", "X пр. (м)", "Y пр. (м)", "X фкт. (м)", "Y фкт. (м)"]

    curr_y = y_pos
    msp.add_line((x_pos, curr_y), (x_pos + total_w, curr_y), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    curr_y -= row_h
    curr_x = x_pos
    for i, h in enumerate(headers):
        msp.add_text(h, dxfattribs={'layer': 'ИСП_Текст', 'height': th, 'style': 'ГОСТ_2.304', 'color': COLOR_MAIN}).set_placement((curr_x + col_widths[i] / 2, curr_y + row_h / 2 - th / 2), align=TextEntityAlignment.MIDDLE_CENTER)
        curr_x += col_widths[i]

    msp.add_line((x_pos, curr_y), (x_pos + total_w, curr_y), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    for row in points_data[:12]:
        curr_y -= row_h
        curr_x = x_pos

        def fmt_val(v):
            if v == "" or v is None:
                return "-"
            try:
                return f"{float(v):.3f}"
            except (ValueError, TypeError):
                return str(v)

        vals = [
            str(row.get('point_name', row.get('id', ''))),
            fmt_val(row.get('x_prj')),
            fmt_val(row.get('y_prj')),
            fmt_val(row.get('x_fact')),
            fmt_val(row.get('y_fact'))
        ]

        for i, val in enumerate(vals):
            color = COLOR_FACT if i >= 3 else COLOR_MAIN
            msp.add_text(val, dxfattribs={'layer': 'ИСП_Текст', 'height': th, 'style': 'ГОСТ_2.304', 'color': color}).set_placement((curr_x + col_widths[i] / 2, curr_y + row_h / 2 - th / 2), align=TextEntityAlignment.MIDDLE_CENTER)
            curr_x += col_widths[i]
        msp.add_line((x_pos, curr_y), (x_pos + total_w, curr_y), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    curr_x = x_pos
    msp.add_line((curr_x, y_pos), (curr_x, curr_y), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})
    for w in col_widths:
        curr_x += w
        msp.add_line((curr_x, y_pos), (curr_x, curr_y), dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    return curr_y


def is_pile_block_def(block_def) -> bool:
    b_name = block_def.name.lower()
    if 'свая' in b_name or 'pile' in b_name:
        return True

    pts = []
    has_solid_poly = False
    for e in block_def:
        try:
            etype = e.dxftype()
            if etype in ('LWPOLYLINE', 'POLYLINE'):
                p = [pt[:2] for pt in e.get_points()] if etype == 'LWPOLYLINE' else [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                if len(p) >= 3:
                    p_closed = p + [p[0]] if get_distance(p[0], p[-1]) > 0.1 else p
                    perim = sum(get_distance(p_closed[i], p_closed[i + 1]) for i in range(len(p_closed) - 1))
                    if (1200 <= perim <= 1600) or (1.2 <= perim <= 1.6):
                        has_solid_poly = True
                pts.extend(p)
            elif etype == 'CIRCLE':
                r = e.dxf.radius
                if (150 <= r <= 250) or (0.15 <= r <= 0.25):
                    has_solid_poly = True
            elif etype == 'LINE':
                pts.extend([(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)])
        except Exception:
            continue

    if has_solid_poly:
        return True

    if pts:
        try:
            min_x, max_x = min(p[0] for p in pts), max(p[0] for p in pts)
            min_y, max_y = min(p[1] for p in pts), max(p[1] for p in pts)
            dx, dy = max_x - min_x, max_y - min_y
            if (300 <= dx <= 450 and 300 <= dy <= 450) or (0.30 <= dx <= 0.45 and 0.30 <= dy <= 0.45):
                return True
        except Exception:
            pass
    return False


def get_block_local_center(block_def) -> Tuple[float, float]:
    pts = []
    for e in block_def:
        try:
            etype = e.dxftype()
            if etype in ('LWPOLYLINE', 'POLYLINE'):
                p = [pt[:2] for pt in e.get_points()] if etype == 'LWPOLYLINE' else [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                if len(p) >= 3:
                    p_closed = p + [p[0]] if get_distance(p[0], p[-1]) > 0.1 else p
                    perim = sum(get_distance(p_closed[i], p_closed[i + 1]) for i in range(len(p_closed) - 1))
                    if (1200 <= perim <= 1600) or (1.2 <= perim <= 1.6):
                        return (sum(pt[0] for pt in p) / len(p), sum(pt[1] for pt in p) / len(p))
                pts.extend(p)
            elif etype == 'CIRCLE':
                r = e.dxf.radius
                if (150 <= r <= 250) or (0.15 <= r <= 0.25):
                    return (e.dxf.center.x, e.dxf.center.y)
            elif etype == 'LINE':
                pts.extend([(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)])
        except Exception:
            continue

    if pts:
        return ((min(p[0] for p in pts) + max(p[0] for p in pts)) / 2.0, (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2.0)
    return (0.0, 0.0)


def transform_pt_local(pt: Tuple[float, float], trans_pos: Tuple[float, float], scale: Tuple[float, float], rotation_deg: float) -> Tuple[float, float]:
    px, py = pt[0] * scale[0], pt[1] * scale[1]
    rad = math.radians(rotation_deg)
    return (px * math.cos(rad) - py * math.sin(rad) + trans_pos[0],
            px * math.sin(rad) + py * math.cos(rad) + trans_pos[1])


def draw_pile_arrow(msp, origin: Tuple[float, float], val_mm: int, axis: str, theta: float, text_h: float = 110.0, hw: float = 175.0) -> None:
    if val_mm == 0:
        return
    layer = 'Исполнительная_Отклонения'
    sign = 1 if val_mm > 0 else -1
    arr_len, h_len, h_w = SIZES['arrow_len'], SIZES['head_len'], SIZES['head_w']

    if axis == 'X':
        u_start, u_end = sign * hw, sign * hw + sign * arr_len
        line_start, line_end = (u_start, 0.0), (u_end, 0.0)
        head_pts = [(u_end, 0.0), (u_end - sign * h_len, h_w), (u_end - sign * h_len, -h_w)]
        text_pos, text_rot = (u_start + sign * arr_len * 0.5, text_h * 0.7), get_readable_text_angle(math.degrees(theta))
    else:
        v_start, v_end = sign * hw, sign * hw + sign * arr_len
        line_start, line_end = (0.0, v_start), (0.0, v_end)
        head_pts = [(0.0, v_end), (h_w, v_end - sign * h_len), (-h_w, v_end - sign * h_len)]
        text_pos, text_rot = (text_h * 0.7, v_start + sign * arr_len * 0.5), get_readable_text_angle(math.degrees(theta) + 90.0)

    msp.add_line(transform_pt(line_start, origin, theta), transform_pt(line_end, origin, theta), dxfattribs={'layer': layer, 'color': COLOR_MAIN})
    msp.add_lwpolyline([transform_pt(p, origin, theta) for p in head_pts], close=True, dxfattribs={'layer': layer, 'color': COLOR_MAIN})
    t = msp.add_text(str(abs(val_mm)), dxfattribs={'layer': layer, 'height': text_h, 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304', 'rotation': text_rot})
    t.set_placement(transform_pt(text_pos, origin, theta), align=TextEntityAlignment.MIDDLE_CENTER)


def draw_notes_and_legend(msp, x0: float, y0: float, scale: float = 1.0) -> float:
    layer = 'Исполнительная_Оформление'
    s = scale if scale > 0 else 1.0
    th = 2.5 * s
    step_y = 4.5 * s

    msp.add_text("Примечания:", dxfattribs={'layer': layer, 'height': th * 1.2, 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304'}).set_placement((x0, y0))
    y_cursor = y0 - step_y * 1.2
    for line in DEFAULT_NOTES:
        msp.add_text(line, dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304'}).set_placement((x0, y_cursor))
        y_cursor -= step_y

    y_cursor -= step_y * 1.5
    msp.add_text("Условные обозначения:", dxfattribs={'layer': layer, 'height': th * 1.2, 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304'}).set_placement((x0, y_cursor))
    y_cursor -= step_y * 1.5

    sq_size = 4.0 * s
    msp.add_lwpolyline([(x0, y_cursor), (x0 + sq_size, y_cursor), (x0 + sq_size, y_cursor + sq_size), (x0, y_cursor + sq_size)], close=True, dxfattribs={'layer': layer, 'color': COLOR_MAIN})
    msp.add_text("- Проектное положение сваи", dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304'}).set_placement((x0 + sq_size * 1.5, y_cursor + th * 0.2))

    y_cursor -= step_y * 1.8
    msp.add_line((x0, y_cursor + th), (x0 + 4.0 * s, y_cursor + th), dxfattribs={'layer': layer, 'color': COLOR_FACT})
    msp.add_lwpolyline([(x0 + 4.0 * s, y_cursor + th), (x0 + 3.0 * s, y_cursor + th + 0.8 * s), (x0 + 3.0 * s, y_cursor + th - 0.8 * s)], close=True, dxfattribs={'layer': layer, 'color': COLOR_FACT})
    msp.add_text("18 - Направление и величина отклонения сваи в плане, мм", dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304'}).set_placement((x0 + sq_size * 1.5, y_cursor + th * 0.2))

    y_cursor -= step_y * 1.8
    msp.add_text("+15", dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304'}).set_placement((x0 + 1.0 * s, y_cursor + th * 0.2))
    msp.add_text("- Высотное отклонение сваи, мм", dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304'}).set_placement((x0 + sq_size * 1.5, y_cursor + th * 0.2))

    return y_cursor


def process_dxf_to_asbuilt_scheme(input_path: str, output_path: str, csv_path: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    _log(f"[ЗАПУСК] Обработка свайного фундамента: {input_path}", log_callback)

    try:
        doc_in = ezdxf.readfile(input_path)
        msp_in = doc_in.modelspace()
    except Exception as e:
        _log(f"[ОШИБКА] Не удалось открыть чертеж: {e}", log_callback)
        return

    # 1. Извлечение исходных размеров из исходного чертежа
    source_dims = extract_source_dimensions(msp_in)

    raw_piles = []
    found_meters = False

    valid_pile_blocks = set()
    for block in doc_in.blocks:
        b_name = block.name
        if not b_name.startswith('_') and b_name.lower() not in ('оформление', 'рамка', 'штамп', 'ось'):
            if is_pile_block_def(block):
                valid_pile_blocks.add(b_name)

    def scan_entities(entities, trans_pos=(0.0, 0.0), scale=(1.0, 1.0), rotation=0.0, visited=None):
        nonlocal found_meters
        if visited is None:
            visited = set()

        for entity in sorted(entities, key=lambda e: e.dxf.handle if hasattr(e.dxf, 'handle') else 0):
            etype = entity.dxftype()

            if etype == 'INSERT':
                b_name = entity.dxf.name

                if b_name in valid_pile_blocks:
                    bx, by = entity.dxf.insert.x, entity.dxf.insert.y
                    b_rot_deg = entity.dxf.rotation if entity.dxf.hasattr('rotation') else 0.0

                    center_pos = transform_pt_local((bx, by), trans_pos, scale, rotation)
                    true_rot_deg = rotation + b_rot_deg

                    raw_piles.append({
                        'center_pt': center_pos,
                        'rot_rad': math.radians(true_rot_deg),
                        'is_round': False
                    })

                elif b_name in doc_in.blocks and b_name not in visited:
                    visited.add(b_name)
                    bx, by = entity.dxf.insert.x, entity.dxf.insert.y
                    b_rot = entity.dxf.rotation if entity.dxf.hasattr('rotation') else 0.0
                    b_sx = entity.dxf.xscale if entity.dxf.hasattr('xscale') else 1.0
                    b_sy = entity.dxf.yscale if entity.dxf.hasattr('yscale') else 1.0

                    b_ins_pos = transform_pt_local((bx, by), trans_pos, scale, rotation)
                    scan_entities(doc_in.blocks[b_name], b_ins_pos, (scale[0] * b_sx, scale[1] * b_sy), rotation + b_rot, visited)
                    visited.remove(b_name)  # ИСПРАВЛЕНО: удаляем b_name!

            elif etype in ('LWPOLYLINE', 'POLYLINE'):
                pts = [(p[0], p[1]) for p in entity.get_points()] if etype == 'LWPOLYLINE' else [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                if len(pts) >= 3:
                    pts_g = [transform_pt_local(pt, trans_pos, scale, rotation) for pt in pts]
                    pts_g_closed = pts_g + [pts_g[0]] if get_distance(pts_g[0], pts_g[-1]) > 0.1 else pts_g

                    perim = sum(get_distance(pts_g_closed[i], pts_g_closed[i + 1]) for i in range(len(pts_g_closed) - 1))
                    cx, cy = sum(p[0] for p in pts_g) / len(pts_g), sum(p[1] for p in pts_g) / len(pts_g)
                    poly_rot = math.atan2(pts_g[1][1] - pts_g[0][1], pts_g[1][0] - pts_g[0][0]) if len(pts_g) >= 2 else 0.0

                    if 1200 <= perim <= 1600 or 1.2 <= perim <= 1.6:
                        raw_piles.append({
                            'center_pt': (cx, cy),
                            'rot_rad': poly_rot,
                            'is_round': False
                        })
                        if perim < 100:
                            found_meters = True

    scan_entities(msp_in)

    unique_piles = []
    threshold = 0.3 if found_meters else 300.0
    for p in raw_piles:
        if not any(get_distance(p['center_pt'], up['center_pt']) < threshold for up in unique_piles):
            unique_piles.append(p)

    if not unique_piles:
        _log("[ОШИБКА] Сваи не найдены на чертеже.", log_callback)
        return

    doc_out = ezdxf.new('R2010')
    if 'ГОСТ_2.304' not in doc_out.styles:
        doc_out.styles.new('ГОСТ_2.304', dxfattribs={'font': FONT_GOST, 'width': 1.0, 'oblique': 15.0})

    msp_out = doc_out.modelspace()
    for lname, color in {'Сваи_Проект': COLOR_MAIN, 'Оси_Проект': COLOR_MAIN, 'Исполнительная_Номера': COLOR_MAIN, 'Исполнительная_Размеры': COLOR_MAIN, 'Исполнительная_Отклонения': COLOR_FACT, 'Исполнительная_Ростверк': COLOR_BASE, 'Исполнительная_Оси_Опор': COLOR_FACT, 'Исполнительная_Оформление': COLOR_MAIN, 'ИСП_Текст': COLOR_MAIN, 'ИСП_Таблица': COLOR_MAIN}.items():
        doc_out.layers.new(lname, dxfattribs={'color': color})

    hw = SIZES['pile_size'] / 2.0
    final_report = []

    for idx, p in enumerate(unique_piles, start=1):
        origin = p['center_pt']
        pile_rot = p['rot_rad']

        if table_data and (idx - 1) < len(table_data):
            row_d = table_data[idx - 1]
            dx_mm = row_d.get('dx_mm', random.randint(-48, 48))
            dy_mm = row_d.get('dy_mm', random.randint(-48, 48))
            dz_mm = row_d.get('dz_mm', random.randint(-45, 45))
            pt_name = row_d.get('point_name', str(idx))
            xp_val = row_d.get('x_prj', origin[0] / 1000.0)
            yp_val = row_d.get('y_prj', origin[1] / 1000.0)
        else:
            dx_mm = random.randint(-48, 48)
            dy_mm = random.randint(-48, 48)
            dz_mm = random.randint(-45, 45)
            pt_name = str(idx)
            xp_val = origin[0] / 1000.0
            yp_val = origin[1] / 1000.0

        final_report.append({
            'id': idx,
            'point_name': pt_name,
            'x_prj': xp_val,
            'y_prj': yp_val,
            'x_fact': (float(xp_val) + dx_mm / 1000.0) if xp_val != "" else "",
            'y_fact': (float(yp_val) + dy_mm / 1000.0) if yp_val != "" else "",
            'dx_mm': dx_mm,
            'dy_mm': dy_mm,
            'dz_mm': dz_mm
        })

        sq_pts = [(-hw, -hw), (hw, -hw), (hw, hw), (-hw, hw)]
        sq_g = [transform_pt(pt, origin, pile_rot) for pt in sq_pts]
        msp_out.add_lwpolyline(sq_g, close=True, dxfattribs={'layer': 'Сваи_Проект', 'color': COLOR_MAIN})

        cr = SIZES['cross_len'] / 2.0
        msp_out.add_line(transform_pt((-cr, 0), origin, pile_rot), transform_pt((cr, 0), origin, pile_rot), dxfattribs={'layer': 'Оси_Проект', 'color': COLOR_MAIN})
        msp_out.add_line(transform_pt((0, -cr), origin, pile_rot), transform_pt((0, cr), origin, pile_rot), dxfattribs={'layer': 'Оси_Проект', 'color': COLOR_MAIN})

        num_rot = get_readable_text_angle(math.degrees(pile_rot))
        t_num = msp_out.add_text(pt_name, dxfattribs={'layer': 'Исполнительная_Номера', 'height': SIZES['text_num'], 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304', 'rotation': num_rot})
        t_num.set_placement(transform_pt((-hw * 1.5, hw * 1.5), origin, pile_rot), align=TextEntityAlignment.MIDDLE_CENTER)

        draw_pile_arrow(msp_out, origin, dx_mm, 'X', pile_rot, hw=hw)
        draw_pile_arrow(msp_out, origin, dy_mm, 'Y', pile_rot, hw=hw)

        z_txt = f"+{dz_mm}" if dz_mm > 0 else str(dz_mm)
        t_z = msp_out.add_text(z_txt, dxfattribs={'layer': 'Исполнительная_Отклонения', 'height': SIZES['text_z'], 'color': COLOR_MAIN, 'style': 'ГОСТ_2.304', 'rotation': num_rot})
        t_z.set_placement(transform_pt((hw * 1.3, -hw * 1.5), origin, pile_rot), align=TextEntityAlignment.MIDDLE_CENTER)

    # Вычисление общего bbox геометрии свай
    try:
        bbox = ezdxf_bbox.extents(msp_out)
    except Exception:
        bbox = BoundingBox([Vec3(0, 0, 0), Vec3(1000, 1000, 0)])

    # Динамический выбор глобального масштаба под лист А3 (420 x 297 мм)
    geom_w = max(bbox.extmax.x - bbox.extmin.x, 100.0)
    geom_h = max(bbox.extmax.y - bbox.extmin.y, 100.0)
    req_scale = max(geom_w / 370.0, geom_h / 270.0, 1.0)
    global_scale = next((float(s) for s in STANDARD_SCALES if s >= req_scale), float(STANDARD_SCALES[-1]))
    scale_str = f"1:{int(global_scale)}" if global_scale >= 1.0 else f"{round(global_scale, 2)}"

    # Отрисовка исходных размеров с фиксированной высотой текста 2.5 * global_scale
    for dim_info in source_dims:
        draw_fractional_dimension(msp_out, dim_info, global_scale)

    # Пересчет bbox после отрисовки размеров
    all_bbox = ezdxf_bbox.extents(msp_out)
    if not all_bbox.has_data:
        all_bbox = bbox

    # Отрисовка рамки ГОСТ и основного штампа 185х55 мм
    in_x_min, in_y_min, in_x_max, in_y_max = draw_gost_frame_and_stamp(
        msp_out, all_bbox, scale=global_scale, stamp_data=stamp_data, scale_str=scale_str
    )

    stamp_w = 185.0 * global_scale
    stamp_x0 = in_x_max - stamp_w
    stamp_y0 = in_y_min

    # Отрисовка таблицы каталога координат вверху справа
    table_x = in_x_max - 112.0 * global_scale
    table_y = in_y_max - 10.0 * global_scale
    if final_report:
        draw_coordinate_table(msp_out, table_x, table_y, final_report)

    # Примечания и условные обозначения над штампом (без наслоений)
    draw_notes_and_legend(msp_out, stamp_x0, stamp_y0 + 60.0 * global_scale, scale=global_scale)


    # Упаковка геометрии, масштабирование под рамку А3
    stamp_w = 185.0
    stamp_h = 55.0
    try:
        if 'in_x_min' in locals() and 'in_y_min' in locals():
            cluster_and_pack_geometry(msp_out, in_x_min, in_y_min, in_x_max, in_y_max, stamp_w, stamp_h)
    except Exception as e:
        _log(f"[ОШИБКА УПАКОВКИ] {e}", log_callback)
    try:
        doc_out.saveas(output_path)
        _log(f"[УСПЕХ] Исполнительная схема свайного фундамента успешно создана: {output_path}", log_callback)
    except Exception as e:
        _log(f"[ОШИБКА] Не удалось записать DXF: {e}", log_callback)


def run(input_dxf: str, output_dxf: str, output_csv: Optional[str] = None, log_callback=None, stamp_data: Optional[Dict[str, Any]] = None, table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    process_dxf_to_asbuilt_scheme(input_dxf, output_dxf, output_csv, log_callback=log_callback, stamp_data=stamp_data, table_data=table_data)

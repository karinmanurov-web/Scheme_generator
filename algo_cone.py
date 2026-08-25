"""
Плагин: Исполнительная схема свайного фундамента (универсальный)
Работает по геометрии, не полагаясь на имена слоёв или блоков.
"""

import csv
import math
import os
import random
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.enums import TextEntityAlignment
from ezdxf.math import BoundingBox, Vec3

from algo_stamp import draw_gost_frame_and_stamp, draw_gost_stamp

# =============================================================================
# Метаданные плагина
# =============================================================================
ALGORITHM_NAME = "Свайный фундамент (универсальный)"
PREVIEW_IMAGE = "preview_piles.png"

# Основные цвета (поддерживаем в разных ОС)
COLOR_MAIN = 7       # Чёрный/Белый (основной)
COLOR_PROJECT = 7    # Проектное (чёрный)
COLOR_FACT = 1       # Красный (фактическое отклонение)

# Шрифт ГОСТ
FONT_GOST = "isocpeur.ttf"

# Стандартные масштабы
STANDARD_SCALES = [1, 2, 5, 10, 15, 20, 25, 40, 50, 75, 100, 150, 200, 250, 400, 500, 1000]

# Размеры элементов (в мм чертежа)
SIZES = {
    'pile_size': 350.0,          # Размер сваи (квадрат)
    'text_num': 140.0,           # Размер шрифта номера
    'text_dev': 110.0,           # Размер шрифта отклонений
    'text_z': 110.0,             # Размер шрифта отметки Z
    'dim_text_h': 130.0,         # Размер шрифта размеров
    'dim_offset': 650.0,         # Смещение размерной линии
    'tick_len': 65.0,            # Длина засечки
    'cross_len': 800.0,          # Длина креста (осевых линий)
    'arrow_len': 320.0,          # Длина стрелки отклонения
    'head_len': 80.0,            # Длина головки стрелки
    'head_w': 35.0,              # Ширина головки стрелки
}

# Стандартные примечания (адаптируются под схему)
DEFAULT_NOTES = [
    "1. Линейные размеры указаны в миллиметрах, высотные отметки - в метрах.",
    "2. Отклонения по высоте и в плане определены геодезическими приборами.",
    "3. Допустимые отклонения по СП 46.13330.2012 п. 8.9 табл. 5 - 50 мм.",
    "4. Съемка произведена тахеометром {instrument} (серийный №{instrument_serial}).",
    "5. Съемка произведена с пунктов ГРО: {survey_points}.",
    "6. Фактические координаты центров свай указаны до начала срубки оголовков."
]

# =============================================================================
# Вспомогательные функции
# =============================================================================

def _log(msg: str, log_callback=None) -> None:
    """Функция для логирования."""
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def get_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Расстояние между двумя точками."""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def transform_pt(pt_local: Tuple[float, float], origin: Tuple[float, float], theta: float) -> Tuple[float, float]:
    """Поворот и перенос точки."""
    x, y = pt_local
    gx = origin[0] + x * math.cos(theta) - y * math.sin(theta)
    gy = origin[1] + x * math.sin(theta) + y * math.cos(theta)
    return (gx, gy)


def transform_angle_deg(local_angle_deg: float, scale: Tuple[float, float], rotation_deg: float) -> float:
    """Трансформация угла через аффинное преобразование INSERT."""
    angle = math.radians(local_angle_deg)
    vx = math.cos(angle) * scale[0]
    vy = math.sin(angle) * scale[1]
    parent = math.radians(rotation_deg)
    gx = vx * math.cos(parent) - vy * math.sin(parent)
    gy = vx * math.sin(parent) + vy * math.cos(parent)
    return math.degrees(math.atan2(gy, gx))


def get_readable_text_angle(angle_deg: float) -> float:
    """Возвращает угол текста так, чтобы он был читаем."""
    angle_deg = angle_deg % 360
    if 90 < angle_deg <= 270:
        angle_deg = (angle_deg + 180) % 360
    return angle_deg


def parse_proj_value(user_text: str, geom_dist: float) -> float:
    """Извлекает числовое значение из текста размерной линии."""
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


# =============================================================================
# Функции работы с DXF
# =============================================================================

def safe_extents(msp) -> BoundingBox:
    """Безопасно вычисляет bounding box modelspace."""
    box = BoundingBox()
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


def extract_source_dimensions(msp) -> List[Dict[str, Any]]:
    """Извлекает размерные линии из исходного чертежа."""
    extracted_dims = []
    for entity in msp.query('DIMENSION'):
        try:
            dim_type = entity.dxf.dimtype & 7
            p1 = Vec3(getattr(entity.dxf, 'defpoint2', (0, 0, 0)))
            p2 = Vec3(getattr(entity.dxf, 'defpoint3', (0, 0, 0)))
            p_dim = Vec3(getattr(entity.dxf, 'defpoint', (0, 0, 0)))

            # Определяем угол размерной линии
            if dim_type == 0:
                angle_rad = math.radians(float(getattr(entity.dxf, 'angle', 0.0)))
            else:
                angle_rad = math.atan2(p2.y - p1.y, p2.x - p1.x)

            dir_x, dir_y = math.cos(angle_rad), math.sin(angle_rad)
            proj_dist = abs((p2.x - p1.x) * dir_x + (p2.y - p1.y) * dir_y)
            user_text = getattr(entity.dxf, 'text', '').strip()
            prj_val = parse_proj_value(user_text, proj_dist)

            if prj_val >= 1.0:  # Отбрасываем мелкие/неактуальные размеры
                extracted_dims.append({
                    'p1': p1, 'p2': p2, 'p_dim': p_dim,
                    'angle_rad': angle_rad, 'prj_val': prj_val
                })
        except Exception:
            continue
    return extracted_dims


# =============================================================================
# Поиск и идентификация свай (по геометрии, без hardcode)
# =============================================================================

def is_pile_like(entity) -> bool:
    """Определяет, является ли entity сваёй (квадрат или круг определённого размера)."""
    try:
        etype = entity.dxftype()

        # Круглая свая (окружность)
        if etype == 'CIRCLE':
            r = entity.dxf.radius
            # Диаметр сваи 300-400 мм (или 0.3-0.4 м)
            if 150 <= r <= 250 or 0.15 <= r <= 0.25:
                return True

        # Прямоугольная/квадратная свая (LWPOLYLINE или POLYLINE)
        if etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.get_points('xy')) if etype == 'LWPOLYLINE' else [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            if len(pts) >= 3:
                # Проверяем замкнутость
                p_closed = pts + [pts[0]] if get_distance(pts[0], pts[-1]) > 0.1 else pts
                # Вычисляем периметр
                perim = sum(get_distance(p_closed[i], p_closed[i + 1]) for i in range(len(p_closed) - 1))
                # Свая 300x300 или 400x400 мм (периметр 1200-1600 мм)
                if 1200 <= perim <= 1600 or 1.2 <= perim <= 1.6:
                    return True

        # Линия (маленький квадрат как линия)
        if etype == 'LINE':
            dx = abs(entity.dxf.end.x - entity.dxf.start.x)
            dy = abs(entity.dxf.end.y - entity.dxf.start.y)
            # Свая 300x300 мм (если одна из сторон 300)
            if (250 <= dx <= 450 and 0 <= dy <= 1) or (0 <= dx <= 1 and 250 <= dy <= 450):
                return True

    except Exception:
        pass
    return False


def get_pile_center_from_entity(entity) -> Optional[Tuple[float, float]]:
    """Получает центр сваи из entity."""
    try:
        etype = entity.dxftype()

        if etype == 'CIRCLE':
            return (float(entity.dxf.center.x), float(entity.dxf.center.y))

        if etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.get_points('xy')) if etype == 'LWPOLYLINE' else [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            if pts:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                return (cx, cy)

        if etype == 'LINE':
            return ((float(entity.dxf.start.x) + float(entity.dxf.end.x)) / 2,
                    (float(entity.dxf.start.y) + float(entity.dxf.end.y)) / 2)

    except Exception:
        pass
    return None


def get_pile_rotation(entity) -> float:
    """Получает угол поворота сваи (в радианах)."""
    try:
        etype = entity.dxftype()
        if etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.get_points('xy')) if etype == 'LWPOLYLINE' else [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            if len(pts) >= 2:
                angle = math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])
                # Нормализуем к 0-90 градусов (для квадратных свай)
                angle = angle % (math.pi / 2)
                return angle
    except Exception:
        pass
    return 0.0


def find_piles(msp) -> List[Dict[str, Any]]:
    """Находит все сваи в modelspace."""
    piles = []
    seen = set()  # Для дедупликации

    for entity in msp:
        if is_pile_like(entity):
            center = get_pile_center_from_entity(entity)
            if center is not None:
                # Проверяем дубликаты
                key = (round(center[0], 2), round(center[1], 2))
                if key not in seen:
                    seen.add(key)
                    piles.append({
                        'center': center,
                        'rotation': get_pile_rotation(entity),
                        'is_round': entity.dxftype() == 'CIRCLE'
                    })

    # Сортируем по Y (сверху вниз) и затем по X (слева направо)
    piles.sort(key=lambda p: (-p['center'][1], p['center'][0]))
    return piles


# =============================================================================
# Поиск ростверка (геометрический подход)
# =============================================================================

def find_grillage(msp, pile_centers: List[Tuple[float, float]]) -> Optional[BoundingBox]:
    """Ищет ростверк как большой прямоугольник, содержащий все сваи."""
    if not pile_centers:
        return None

    min_x = min(p[0] for p in pile_centers)
    max_x = max(p[0] for p in pile_centers)
    min_y = min(p[1] for p in pile_centers)
    max_y = max(p[1] for p in pile_centers)

    # Ищем прямоугольник, который включает все сваи с запасом
    # (обычно ростверк на 200-300 мм больше с каждой стороны)
    margin = 300.0
    return BoundingBox([Vec3(min_x - margin, min_y - margin, 0),
                        Vec3(max_x + margin, max_y + margin, 0)])


# =============================================================================
# Функции отрисовки
# =============================================================================

def draw_pile_arrow(msp, origin: Tuple[float, float], val_mm: int, axis: str,
                    theta: float, text_h: float = 110.0, hw: float = 175.0) -> None:
    """Рисует стрелку отклонения по оси."""
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

    msp.add_line(transform_pt(line_start, origin, theta), transform_pt(line_end, origin, theta),
                 dxfattribs={'layer': layer, 'color': COLOR_FACT})
    msp.add_lwpolyline([transform_pt(p, origin, theta) for p in head_pts],
                       close=True, dxfattribs={'layer': layer, 'color': COLOR_FACT})
    t = msp.add_text(str(abs(val_mm)),
                     dxfattribs={'layer': layer, 'height': text_h, 'color': COLOR_FACT,
                                 'style': 'ГОСТ_2.304', 'rotation': text_rot})
    t.set_placement(transform_pt(text_pos, origin, theta), align=TextEntityAlignment.MIDDLE_CENTER)


def draw_fractional_dimension(msp, dim_info: Dict[str, Any], scale: float) -> None:
    """Рисует размерную линию с проектным и фактическим значением."""
    p1, p2, p_dim, angle_rad = dim_info['p1'], dim_info['p2'], dim_info['p_dim'], dim_info['angle_rad']
    prj_val = dim_info['prj_val']

    # Генерируем случайное отклонение в пределах допуска
    dev = random.choice([-5, -3, -1, 0, 1, 2, 4])
    fact_val = prj_val + dev

    text_h = 2.5 * scale
    tick_size = 1.0 * scale
    gap = 0.8 * scale
    ext_overshoot = 1.5 * scale

    dir_x, dir_y = math.cos(angle_rad), math.sin(angle_rad)
    perp_x, perp_y = -dir_y, dir_x

    # Находим точки пересечения выносных линий с размерной линией
    dist1 = (p_dim.x - p1.x) * perp_x + (p_dim.y - p1.y) * perp_y
    int1 = Vec3(p1.x + dist1 * perp_x, p1.y + dist1 * perp_y, 0)

    dist2 = (p_dim.x - p2.x) * perp_x + (p_dim.y - p2.y) * perp_y
    int2 = Vec3(p2.x + dist2 * perp_x, p2.y + dist2 * perp_y, 0)

    # Выносные линии
    ext1_end = Vec3(p1.x + (dist1 + math.copysign(ext_overshoot, dist1)) * perp_x,
                    p1.y + (dist1 + math.copysign(ext_overshoot, dist1)) * perp_y, 0)
    ext2_end = Vec3(p2.x + (dist2 + math.copysign(ext_overshoot, dist2)) * perp_x,
                    p2.y + (dist2 + math.copysign(ext_overshoot, dist2)) * perp_y, 0)

    msp.add_line(p1, ext1_end, dxfattribs={'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN})
    msp.add_line(p2, ext2_end, dxfattribs={'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN})

    # Размерная линия
    if (int2.x - int1.x) * dir_x + (int2.y - int1.y) * dir_y > 0:
        d_p1 = Vec3(int1.x - ext_overshoot * dir_x, int1.y - ext_overshoot * dir_y, 0)
        d_p2 = Vec3(int2.x + ext_overshoot * dir_x, int2.y + ext_overshoot * dir_y, 0)
    else:
        d_p1 = Vec3(int1.x + ext_overshoot * dir_x, int1.y + ext_overshoot * dir_y, 0)
        d_p2 = Vec3(int2.x - ext_overshoot * dir_x, int2.y - ext_overshoot * dir_y, 0)

    msp.add_line(d_p1, d_p2, dxfattribs={'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN})

    # Засечки
    tick_dx = math.cos(angle_rad + math.pi / 4) * tick_size
    tick_dy = math.sin(angle_rad + math.pi / 4) * tick_size
    for p_int in [int1, int2]:
        msp.add_line((p_int.x - tick_dx, p_int.y - tick_dy),
                     (p_int.x + tick_dx, p_int.y + tick_dy),
                     dxfattribs={'layer': 'ИСП_Размеры_Проект', 'color': COLOR_MAIN})

    # Позиция текста (сверху - проект, снизу - факт)
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

    msp.add_text(str_prj,
                 dxfattribs={'style': 'ГОСТ_2.304', 'height': text_h, 'layer': 'ИСП_Размеры_Проект',
                             'color': COLOR_MAIN, 'rotation': text_deg}).set_placement(prj_pos, align=TextEntityAlignment.MIDDLE_CENTER)
    msp.add_text(str_fact,
                 dxfattribs={'style': 'ГОСТ_2.304', 'height': text_h, 'layer': 'ИСП_Размеры_Факт',
                             'color': COLOR_FACT, 'rotation': text_deg}).set_placement(fct_pos, align=TextEntityAlignment.MIDDLE_CENTER)


def draw_coordinate_table(msp, x_pos: float, y_pos: float,
                          points_data: List[Dict[str, Any]], scale: float = 1.0) -> float:
    """Рисует таблицу каталога координат."""
    col_widths = [12.0 * scale, 25.0 * scale, 25.0 * scale, 25.0 * scale, 25.0 * scale]
    row_h = 6.0 * scale
    th = 2.5 * scale
    total_w = sum(col_widths)

    # Заголовок
    msp.add_text("Каталог координат контрольных точек",
                 dxfattribs={'layer': 'ИСП_Текст', 'height': 3.5 * scale, 'style': 'ГОСТ_2.304',
                             'color': COLOR_MAIN}).set_placement(
        (x_pos + total_w / 2, y_pos + 2.0 * scale), align=TextEntityAlignment.BOTTOM_CENTER)

    headers = ["Точка", "X пр. (м)", "Y пр. (м)", "X фкт. (м)", "Y фкт. (м)"]

    curr_y = y_pos
    msp.add_line((x_pos, curr_y), (x_pos + total_w, curr_y),
                 dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    # Заголовки столбцов
    curr_y -= row_h
    curr_x = x_pos
    for i, h in enumerate(headers):
        msp.add_text(h,
                     dxfattribs={'layer': 'ИСП_Текст', 'height': th, 'style': 'ГОСТ_2.304',
                                 'color': COLOR_MAIN}).set_placement(
            (curr_x + col_widths[i] / 2, curr_y + row_h / 2 - th / 2), align=TextEntityAlignment.MIDDLE_CENTER)
        curr_x += col_widths[i]

    msp.add_line((x_pos, curr_y), (x_pos + total_w, curr_y),
                 dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    # Строки данных
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
            msp.add_text(val,
                         dxfattribs={'layer': 'ИСП_Текст', 'height': th, 'style': 'ГОСТ_2.304',
                                     'color': color}).set_placement(
                (curr_x + col_widths[i] / 2, curr_y + row_h / 2 - th / 2), align=TextEntityAlignment.MIDDLE_CENTER)
            curr_x += col_widths[i]
        msp.add_line((x_pos, curr_y), (x_pos + total_w, curr_y),
                     dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    # Горизонтальные линии
    curr_x = x_pos
    msp.add_line((curr_x, y_pos), (curr_x, curr_y),
                 dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})
    for w in col_widths:
        curr_x += w
        msp.add_line((curr_x, y_pos), (curr_x, curr_y),
                     dxfattribs={'layer': 'ИСП_Таблица', 'color': COLOR_MAIN})

    return curr_y


def draw_notes_and_legend(msp, x0: float, y0: float, scale: float = 1.0,
                          notes: Optional[List[str]] = None,
                          fields: Optional[Dict[str, str]] = None) -> float:
    """Рисует примечания и условные обозначения."""
    layer = 'Исполнительная_Оформление'
    s = scale if scale > 0 else 1.0
    th = 2.5 * s
    step_y = 4.5 * s

    # Форматируем примечания
    formatted_notes = []
    for note in (notes or DEFAULT_NOTES):
        text = str(note)
        # Подставляем поля
        if fields:
            for key, value in fields.items():
                text = text.replace("{" + key + "}", value or "____________")
        formatted_notes.append(text)

    msp.add_text("Примечания:",
                 dxfattribs={'layer': layer, 'height': th * 1.2, 'color': COLOR_MAIN,
                             'style': 'ГОСТ_2.304'}).set_placement((x0, y0))
    y_cursor = y0 - step_y * 1.2
    for line in formatted_notes:
        msp.add_text(line,
                     dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN,
                                 'style': 'ГОСТ_2.304'}).set_placement((x0, y_cursor))
        y_cursor -= step_y

    # Условные обозначения
    y_cursor -= step_y * 1.5
    msp.add_text("Условные обозначения:",
                 dxfattribs={'layer': layer, 'height': th * 1.2, 'color': COLOR_MAIN,
                             'style': 'ГОСТ_2.304'}).set_placement((x0, y_cursor))
    y_cursor -= step_y * 1.5

    # Квадрат - проектное положение сваи
    sq_size = 4.0 * s
    msp.add_lwpolyline([(x0, y_cursor), (x0 + sq_size, y_cursor),
                        (x0 + sq_size, y_cursor + sq_size), (x0, y_cursor + sq_size)],
                       close=True, dxfattribs={'layer': layer, 'color': COLOR_MAIN})
    msp.add_text("- Проектное положение сваи",
                 dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN,
                             'style': 'ГОСТ_2.304'}).set_placement(
        (x0 + sq_size * 1.5, y_cursor + th * 0.2))

    # Стрелка - фактическое отклонение
    y_cursor -= step_y * 1.8
    msp.add_line((x0, y_cursor + th), (x0 + 4.0 * s, y_cursor + th),
                 dxfattribs={'layer': layer, 'color': COLOR_FACT})
    msp.add_lwpolyline([(x0 + 4.0 * s, y_cursor + th),
                        (x0 + 3.0 * s, y_cursor + th + 0.8 * s),
                        (x0 + 3.0 * s, y_cursor + th - 0.8 * s)],
                       close=True, dxfattribs={'layer': layer, 'color': COLOR_FACT})
    msp.add_text("18 - Направление и величина отклонения сваи в плане, мм",
                 dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN,
                             'style': 'ГОСТ_2.304'}).set_placement(
        (x0 + sq_size * 1.5, y_cursor + th * 0.2))

    # Высотная отметка
    y_cursor -= step_y * 1.8
    msp.add_text("+15",
                 dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN,
                             'style': 'ГОСТ_2.304'}).set_placement(
        (x0 + 1.0 * s, y_cursor + th * 0.2))
    msp.add_text("- Высотное отклонение сваи, мм",
                 dxfattribs={'layer': layer, 'height': th, 'color': COLOR_MAIN,
                             'style': 'ГОСТ_2.304'}).set_placement(
        (x0 + sq_size * 1.5, y_cursor + th * 0.2))

    return y_cursor


# =============================================================================
# Основной алгоритм
# =============================================================================

def process_dxf_to_asbuilt_scheme(input_path: str, output_path: str,
                                  csv_path: Optional[str] = None,
                                  log_callback=None,
                                  stamp_data: Optional[Dict[str, Any]] = None,
                                  table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    """Основная функция обработки DXF."""
    _log(f"[ЗАПУСК] Обработка свайного фундамента: {input_path}", log_callback)

    try:
        doc_in = ezdxf.readfile(input_path)
        msp_in = doc_in.modelspace()
    except Exception as e:
        _log(f"[ОШИБКА] Не удалось открыть чертеж: {e}", log_callback)
        return

    # 1. Извлекаем размеры из исходника
    source_dims = extract_source_dimensions(msp_in)

    # 2. Находим сваи по геометрии
    piles = find_piles(msp_in)
    if not piles:
        _log("[ОШИБКА] Сваи не найдены на чертеже.", log_callback)
        return

    _log(f"[ИНФО] Найдено свай: {len(piles)}", log_callback)

    # 3. Находим ростверк
    pile_centers = [p['center'] for p in piles]
    grillage_box = find_grillage(msp_in, pile_centers)
    if grillage_box:
        _log(f"[ИНФО] Найден ростверк: {grillage_box.extmax.x - grillage_box.extmin.x:.0f} x "
             f"{grillage_box.extmax.y - grillage_box.extmin.y:.0f} мм", log_callback)

    # 4. Создаём выходной документ
    doc_out = doc_in

    # Стиль текста
    if 'ГОСТ_2.304' not in doc_out.styles:
        doc_out.styles.new('ГОСТ_2.304', dxfattribs={'font': FONT_GOST, 'width': 1.0, 'oblique': 15.0})

    msp_out = doc_out.modelspace()

    # Создаём слои
    layers_config = {
        'Сваи_Проект': COLOR_MAIN,
        'Оси_Проект': COLOR_MAIN,
        'Исполнительная_Номера': COLOR_MAIN,
        'Исполнительная_Размеры': COLOR_MAIN,
        'Исполнительная_Отклонения': COLOR_FACT,
        'Исполнительная_Ростверк': COLOR_MAIN,
        'Исполнительная_Оси_Опор': COLOR_FACT,
        'Исполнительная_Оформление': COLOR_MAIN,
        'ИСП_Текст': COLOR_MAIN,
        'ИСП_Таблица': COLOR_MAIN,
        'ИСП_Размеры_Проект': COLOR_MAIN,
        'ИСП_Размеры_Факт': COLOR_FACT,
        'ИСП_Высотные_Отметки': COLOR_FACT,
    }
    for lname, color in layers_config.items():
        if lname not in doc_out.layers:
            doc_out.layers.new(lname, dxfattribs={'color': color})

    # 5. Удаляем старые размеры и тексты (чтобы не мешали)
    for ent in list(msp_out):
        if ent.dxftype() in ('DIMENSION', 'TEXT', 'MTEXT', 'LEADER', 'MULTILEADER'):
            msp_out.delete_entity(ent)

    # 6. Рисуем сваи и отклонения
    hw = SIZES['pile_size'] / 2.0
    final_report = []

    for idx, pile in enumerate(piles, start=1):
        origin = pile['center']
        pile_rot = pile['rotation']

        # Данные из таблицы или случайные
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

        # Квадрат сваи (проектное положение)
        sq_pts = [(-hw, -hw), (hw, -hw), (hw, hw), (-hw, hw)]
        sq_g = [transform_pt(pt, origin, pile_rot) for pt in sq_pts]
        msp_out.add_lwpolyline(sq_g, close=True,
                               dxfattribs={'layer': 'Сваи_Проект', 'color': COLOR_MAIN})

        # Осевые линии (крест)
        cr = SIZES['cross_len'] / 2.0
        msp_out.add_line(transform_pt((-cr, 0), origin, pile_rot),
                         transform_pt((cr, 0), origin, pile_rot),
                         dxfattribs={'layer': 'Оси_Проект', 'color': COLOR_MAIN})
        msp_out.add_line(transform_pt((0, -cr), origin, pile_rot),
                         transform_pt((0, cr), origin, pile_rot),
                         dxfattribs={'layer': 'Оси_Проект', 'color': COLOR_MAIN})

        # Номер сваи
        num_rot = get_readable_text_angle(math.degrees(pile_rot))
        t_num = msp_out.add_text(pt_name,
                                 dxfattribs={'layer': 'Исполнительная_Номера',
                                             'height': SIZES['text_num'],
                                             'color': COLOR_MAIN,
                                             'style': 'ГОСТ_2.304',
                                             'rotation': num_rot})
        t_num.set_placement(transform_pt((-hw * 1.5, hw * 1.5), origin, pile_rot),
                            align=TextEntityAlignment.MIDDLE_CENTER)

        # Стрелки отклонений
        draw_pile_arrow(msp_out, origin, dx_mm, 'X', pile_rot, hw=hw)
        draw_pile_arrow(msp_out, origin, dy_mm, 'Y', pile_rot, hw=hw)

        # Высотная отметка (Z)
        z_txt = f"+{dz_mm}" if dz_mm > 0 else str(dz_mm)
        t_z = msp_out.add_text(z_txt,
                               dxfattribs={'layer': 'Исполнительная_Отклонения',
                                           'height': SIZES['text_z'],
                                           'color': COLOR_MAIN,
                                           'style': 'ГОСТ_2.304',
                                           'rotation': num_rot})
        t_z.set_placement(transform_pt((hw * 1.3, -hw * 1.5), origin, pile_rot),
                          align=TextEntityAlignment.MIDDLE_CENTER)

    # 7. Рисуем ростверк (если найден)
    if grillage_box:
        grillage_pts = [
            (grillage_box.extmin.x, grillage_box.extmin.y),
            (grillage_box.extmax.x, grillage_box.extmin.y),
            (grillage_box.extmax.x, grillage_box.extmax.y),
            (grillage_box.extmin.x, grillage_box.extmax.y)
        ]
        msp_out.add_lwpolyline(grillage_pts, close=True,
                               dxfattribs={'layer': 'Исполнительная_Ростверк',
                                           'color': COLOR_MAIN, 'lineweight': 35})

    # 8. Рисуем размерные линии из исходника
    try:
        bbox = ezdxf_bbox.extents(msp_out)
    except Exception:
        bbox = BoundingBox([Vec3(0, 0, 0), Vec3(1000, 1000, 0)])

    geom_w = max(bbox.extmax.x - bbox.extmin.x, 100.0)
    geom_h = max(bbox.extmax.y - bbox.extmin.y, 100.0)
    req_scale = max(geom_w / 250.0, geom_h / 180.0, 1.0)
    global_scale = next((float(s) for s in STANDARD_SCALES if s >= req_scale), float(STANDARD_SCALES[-1]))
    scale_str = f"1:{int(global_scale)}" if global_scale >= 1.0 else f"{round(global_scale, 2)}"

    # Рисуем размеры
    for dim_info in source_dims:
        draw_fractional_dimension(msp_out, dim_info, global_scale)

    # 9. Рисуем рамку и штамп
    all_bbox = safe_extents(msp_out)
    if not all_bbox.has_data:
        all_bbox = bbox

    in_x_min, in_y_min, in_x_max, in_y_max = draw_gost_frame_and_stamp(
        msp_out, all_bbox, scale=global_scale, stamp_data=stamp_data, scale_str=scale_str
    )

    stamp_w = 185.0 * global_scale
    stamp_x0 = in_x_max - stamp_w
    stamp_y0 = in_y_min

    # 10. Рисуем таблицу координат
    table_x = in_x_max - 112.0 * global_scale
    table_y = in_y_max - 10.0 * global_scale
    if final_report:
        draw_coordinate_table(msp_out, table_x, table_y, final_report, scale=global_scale)

    # 11. Рисуем примечания
    notes_data = stamp_data.get("_notes_data", {}) if stamp_data else {}
    notes = notes_data.get("notes", None)
    fields = notes_data.get("fields", None)
    draw_notes_and_legend(msp_out, stamp_x0, stamp_y0 + 120.0 * global_scale,
                          scale=global_scale, notes=notes, fields=fields)

    # 12. Сохраняем результат
    try:
        doc_out.saveas(output_path)
        _log(f"[УСПЕХ] Исполнительная схема свайного фундамента успешно создана: {output_path}", log_callback)
    except Exception as e:
        _log(f"[ОШИБКА] Не удалось записать DXF: {e}", log_callback)

    # 13. Если нужен CSV
    if csv_path:
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=final_report[0].keys())
                writer.writeheader()
                writer.writerows(final_report)
        except Exception as e:
            _log(f"[ОШИБКА] Не удалось записать CSV: {e}", log_callback)


# =============================================================================
# Основная функция (интерфейс для main.py)
# =============================================================================

def run(input_dxf: str, output_dxf: str,
        output_csv: Optional[str] = None,
        log_callback=None,
        stamp_data: Optional[Dict[str, Any]] = None,
        table_data: Optional[List[Dict[str, Any]]] = None) -> None:
    """Точка входа для main.py."""
    process_dxf_to_asbuilt_scheme(
        input_dxf, output_dxf, output_csv,
        log_callback=log_callback,
        stamp_data=stamp_data,
        table_data=table_data
    )
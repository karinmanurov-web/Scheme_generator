"""Подбетонка: единый DXF -> mm -> paper-space pipeline."""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional

import ezdxf
from ezdxf.enums import TextEntityAlignment
from ezdxf.math import Vec3

from algo_stamp import draw_gost_frame_and_stamp
from dxf_math import A3_H_MM, A3_W_MM, fit_standard_scale, translate_and_scale_xy, unit_to_mm_from_doc

ALGORITHM_NAME = "Подбетонка"
PREVIEW_IMAGE = "preview_base.png"
COLOR_MAIN = 7
COLOR_FACT = 1
FONT_GOST = "isocpeur.ttf"


def _log(msg: str, log_callback=None) -> None:
    (log_callback or print)(msg)


def setup_gost_environment(doc) -> None:
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = 4
    if "DASHDOT" not in doc.linetypes:
        doc.linetypes.new("DASHDOT", dxfattribs={"description": "Осевая ГОСТ", "pattern": [20, 10, -2, 2, -2]})
    layers = [
        ("ИС_Конструкция_Черный", 7, "CONTINUOUS", 0.50),
        ("ИС_Размеры_Проект_Факт", 7, "CONTINUOUS", 0.25),
        ("ИС_Оси", 1, "DASHDOT", 0.25),
        ("ИС_Высотные_Отметки", 7, "CONTINUOUS", 0.25),
        ("ИС_Оформление_Штамп", 7, "CONTINUOUS", 0.50),
        ("ИС_Текст", 7, "CONTINUOUS", 0.25),
    ]
    for name, color, ltype, weight in layers:
        if name not in doc.layers:
            layer = doc.layers.new(name, dxfattribs={"color": color, "linetype": ltype})
            layer.dxf.lineweight = int(weight * 100)
    if "ГОСТ_2.304" not in doc.styles:
        doc.styles.new("ГОСТ_2.304", dxfattribs={"font": FONT_GOST, "width": 1.0, "oblique": 15.0})


def _primitive_points(entity):
    t = entity.dxftype()
    if t == "LINE":
        return [Vec3(entity.dxf.start), Vec3(entity.dxf.end)]
    if t == "LWPOLYLINE":
        return [Vec3(x, y, 0) for x, y, *_ in entity.get_points("xyb")]
    if t == "POLYLINE":
        return [Vec3(v.dxf.location) for v in entity.vertices]
    if t == "CIRCLE":
        c, r = entity.dxf.center, entity.dxf.radius
        return [Vec3(c.x-r, c.y-r, 0), Vec3(c.x+r, c.y+r, 0)]
    if t == "ARC":
        c, r = entity.dxf.center, entity.dxf.radius
        a1, a2 = math.radians(entity.dxf.start_angle), math.radians(entity.dxf.end_angle)
        pts = [Vec3(c.x + r*math.cos(a), c.y + r*math.sin(a), 0) for a in (a1, a2)]
        for a in (0, math.pi/2, math.pi, 3*math.pi/2):
            aa = a
            if a2 < a1: a2 += 2*math.pi
            if a1 <= aa <= a2:
                pts.append(Vec3(c.x+r*math.cos(a), c.y+r*math.sin(a), 0))
        return pts
    return []


def extract_primitives(entities, depth=0, max_depth=8):
    if depth > max_depth:
        return []
    out = []
    for ent in entities:
        if ent.dxftype() == "INSERT":
            try:
                out.extend(extract_primitives(ent.virtual_entities(), depth+1, max_depth))
            except Exception:
                pass
        elif ent.dxftype() in {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC"}:
            out.append(ent)
    return out


def _bbox(primitives, unit_factor):
    points = []
    for ent in primitives:
        for p in _primitive_points(ent):
            points.append((p.x * unit_factor, p.y * unit_factor))
    if not points:
        return (0.0, 0.0, 1000.0, 1000.0)
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _copy_geometry(out_msp, primitives, bbox, factor, unit_factor, pad):
    min_x, min_y = bbox[:2]
    for ent in primitives:
        t = ent.dxftype()
        try:
            if t == "LINE":
                a = translate_and_scale_xy((ent.dxf.start.x*unit_factor, ent.dxf.start.y*unit_factor), min_x, min_y, factor, pad)
                b = translate_and_scale_xy((ent.dxf.end.x*unit_factor, ent.dxf.end.y*unit_factor), min_x, min_y, factor, pad)
                out_msp.add_line((a[0], a[1]), (b[0], b[1]), dxfattribs={"layer":"ИС_Конструкция_Черный", "color":COLOR_MAIN})
            elif t in {"LWPOLYLINE", "POLYLINE"}:
                pts = _primitive_points(ent)
                paper = [translate_and_scale_xy((p.x*unit_factor,p.y*unit_factor),min_x,min_y,factor,pad) for p in pts]
                if len(paper) >= 2:
                    out_msp.add_lwpolyline(paper, close=bool(getattr(ent,"closed",False) or getattr(ent,"is_closed",False)), dxfattribs={"layer":"ИС_Конструкция_Черный","color":COLOR_MAIN})
            elif t == "CIRCLE":
                c = ent.dxf.center
                cx, cy = translate_and_scale_xy((c.x*unit_factor,c.y*unit_factor),min_x,min_y,factor,pad)
                out_msp.add_circle((cx,cy), ent.dxf.radius*unit_factor*factor, dxfattribs={"layer":"ИС_Конструкция_Черный","color":COLOR_MAIN})
            elif t == "ARC":
                c = ent.dxf.center
                cx, cy = translate_and_scale_xy((c.x*unit_factor,c.y*unit_factor),min_x,min_y,factor,pad)
                out_msp.add_arc((cx,cy),ent.dxf.radius*unit_factor*factor,ent.dxf.start_angle,ent.dxf.end_angle,dxfattribs={"layer":"ИС_Конструкция_Черный","color":COLOR_MAIN})
        except Exception:
            continue


def _draw_level(msp, x, y, scale_factor, prj, fact):
    s = scale_factor
    w, h = 1.5*s, 1.5*s
    msp.add_lwpolyline([(x,y),(x-w,y+h),(x+w,y+h)],close=True,dxfattribs={"layer":"ИС_Высотные_Отметки","color":COLOR_MAIN})
    msp.add_line((x-w,y+h),(x+8*s,y+h),dxfattribs={"layer":"ИС_Высотные_Отметки","color":COLOR_MAIN})
    msp.add_text(f"{prj:+.3f}",dxfattribs={"layer":"ИС_Высотные_Отметки","height":2.5*s,"color":COLOR_MAIN,"style":"ГОСТ_2.304"}).set_placement((x+0.5*s,y+h+0.5*s),align=TextEntityAlignment.BOTTOM_LEFT)
    msp.add_text(f"{fact:+.3f}",dxfattribs={"layer":"ИС_Высотные_Отметки","height":2.5*s,"color":COLOR_FACT,"style":"ГОСТ_2.304"}).set_placement((x+0.5*s,y+h-0.5*s),align=TextEntityAlignment.TOP_LEFT)


def generate_table_data(input_dxf: str) -> List[Dict[str, Any]]:
    doc = ezdxf.readfile(input_dxf)
    primitives = extract_primitives(doc.modelspace())
    unit = unit_to_mm_from_doc(doc)
    min_x,min_y,max_x,max_y = _bbox(primitives,unit)
    return [{"id":i,"point_name":f"Т{i}","x_prj":"","y_prj":"","x_fact":"","y_fact":"","tolerance_mm":20} for i in range(1,5)]


def process_dxf_to_asbuilt_scheme(input_path: str, output_path: str, csv_path: Optional[str]=None, log_callback=None, stamp_data: Optional[Dict[str,Any]]=None, table_data: Optional[List[Dict[str,Any]]]=None) -> None:
    _log(f"[ИНФО] Обработка подбетонки: {input_path}",log_callback)
    try:
        src = ezdxf.readfile(input_path)
    except Exception as exc:
        _log(f"[ОШИБКА] {exc}",log_callback); return

    primitives = extract_primitives(src.modelspace())
    unit = unit_to_mm_from_doc(src)
    bbox = _bbox(primitives,unit)
    sw, sh = bbox[2]-bbox[0], bbox[3]-bbox[1]
    plan = fit_standard_scale(sw,sh,360.0,237.0)
    out = ezdxf.new("R2018",setup=True)
    setup_gost_environment(out)
    omsp = out.modelspace()
    _copy_geometry(omsp,primitives,bbox,plan.factor,unit,20.0)

    # Все исполнительные обозначения физически масштабируются тем же factor.
    center_x = 20.0 + sw*plan.factor/2.0
    center_y = 20.0 + sh*plan.factor/2.0
    _draw_level(omsp,center_x,center_y,1.0,96.969,96.956)

    all_bbox = type("B",(),{"extmin":Vec3(0,0,0),"extmax":Vec3(A3_W_MM,A3_H_MM,0),"has_data":True})()
    scale_str = f"1:{int(plan.denominator)}"
    in_x_min,in_y_min,in_x_max,in_y_max = draw_gost_frame_and_stamp(omsp,all_bbox,scale=1.0,stamp_data=stamp_data,scale_str=scale_str)
    out.saveas(output_path)
    _log(f"[УСПЕХ] Подбетонка сохранена: {output_path}",log_callback)


def run(input_dxf: str, output_dxf: str, output_csv: Optional[str]=None, log_callback=None, stamp_data: Optional[Dict[str,Any]]=None, table_data: Optional[List[Dict[str,Any]]]=None) -> None:
    process_dxf_to_asbuilt_scheme(input_dxf,output_dxf,output_csv,log_callback,stamp_data,table_data)

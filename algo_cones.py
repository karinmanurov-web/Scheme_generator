"""Минимальный универсальный алгоритм исполнительной схемы конусов."""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

import ezdxf

from algo_stamp import draw_gost_stamp, setup_gost_layers
from dxf_math import A3_H_MM, A3_W_MM, bbox_from_points, fit_standard_scale, paper_point_from_source, unit_to_mm_from_doc

ALGORITHM_NAME = "Конусы"
PREVIEW_IMAGE = "preview_cones.png"
A3_W = A3_W_MM
A3_H = A3_H_MM
FRAME_MARGIN = 10.0
STAMP_W = 185.0
STAMP_H = 55.0
LAYER_CONE = "ИСП_Конусы"
LAYER_TEXT = "ИСП_Текст"
LAYER_FRAME = "ГОСТ_Рамка"
LAYER_AXIS = "ИСП_Оси"


def _ensure_layers(doc: ezdxf.document.Drawing) -> None:
    setup_gost_layers(doc)
    for name, color, ltype, lw in ((LAYER_CONE,7,"CONTINUOUS",25),(LAYER_TEXT,7,"CONTINUOUS",15),(LAYER_FRAME,7,"CONTINUOUS",50),(LAYER_AXIS,7,"DASHDOT",15)):
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": color, "linetype": ltype})
            doc.layers.get(name).dxf.lineweight = lw


def _bbox_of_points(points: List[Tuple[float,float]]) -> Tuple[float,float,float,float]:
    return bbox_from_points(points)


def _polyline_vertices(ent) -> List[Tuple[float,float]]:
    try:
        if ent.dxftype() == "LWPOLYLINE":
            return [(float(p[0]),float(p[1])) for p in ent.get_points("xy")]
        if ent.dxftype() == "POLYLINE":
            return [(float(v.dxf.location.x),float(v.dxf.location.y)) for v in ent.vertices]
    except Exception:
        pass
    return []


def detect_cones(msp) -> List[Dict[str,Any]]:
    candidates=[]
    for ent in msp:
        try:
            typ=ent.dxftype()
            if typ=="CIRCLE":
                c=ent.dxf.center; r=float(ent.dxf.radius)
                if r>1e-6: candidates.append({"kind":"circle","center":(float(c.x),float(c.y)),"radius":r,"entity":ent})
            elif typ in ("LWPOLYLINE","POLYLINE") and getattr(ent.dxf,"flags",0)&1:
                pts=_polyline_vertices(ent)
                if len(pts)<3: continue
                xmin,ymin,xmax,ymax=_bbox_of_points(pts); w=xmax-xmin; h=ymax-ymin
                if w<=0 or h<=0 or min(w,h)/max(w,h)<0.55: continue
                candidates.append({"kind":"polyline","center":((xmin+xmax)/2,(ymin+ymax)/2),"radius":0.5*max(w,h),"points":pts,"entity":ent})
        except Exception: continue
    candidates.sort(key=lambda x:(x["center"][1],x["center"][0]))
    result=[]
    for item in candidates:
        cx,cy=item["center"]; r=item["radius"]
        if not any(math.hypot(cx-p["center"][0],cy-p["center"][1]) < max(1.0,0.15*min(r,p["radius"])) for p in result): result.append(item)
    return result


def _source_bbox(msp) -> Optional[Tuple[float,float,float,float]]:
    points=[]
    for ent in msp:
        try:
            if ent.dxftype()=="CIRCLE":
                c=ent.dxf.center; r=float(ent.dxf.radius); points += [(c.x-r,c.y-r),(c.x+r,c.y+r)]
            elif ent.dxftype() in ("LWPOLYLINE","POLYLINE"): points += _polyline_vertices(ent)
        except Exception: continue
    return bbox_from_points(points) if points else None


def _draw_frame(msp) -> None:
    msp.add_lwpolyline([(FRAME_MARGIN,FRAME_MARGIN),(A3_W-FRAME_MARGIN,FRAME_MARGIN),(A3_W-FRAME_MARGIN,A3_H-FRAME_MARGIN),(FRAME_MARGIN,A3_H-FRAME_MARGIN)],close=True,dxfattribs={"layer":LAYER_FRAME,"color":7,"lineweight":50})


def _add_text(msp,text,x,y,height=3.0,align="MIDDLE_CENTER") -> None:
    from ezdxf.enums import TextEntityAlignment
    amap={"MIDDLE_CENTER":TextEntityAlignment.MIDDLE_CENTER,"MIDDLE_LEFT":TextEntityAlignment.MIDDLE_LEFT,"MIDDLE_RIGHT":TextEntityAlignment.MIDDLE_RIGHT}
    msp.add_text(str(text),dxfattribs={"layer":LAYER_TEXT,"color":7,"height":height,"style":"ГОСТ_2.304"}).set_placement((x,y),align=amap[align])


def _draw_cone_symbol(msp,item,x,y,radius,number) -> None:
    r=max(2.5,min(12.0,radius))
    msp.add_circle((x,y),r,dxfattribs={"layer":LAYER_CONE,"color":7})
    cross=max(2.0,min(8.0,r*0.65))
    msp.add_line((x-cross,y),(x+cross,y),dxfattribs={"layer":LAYER_AXIS,"color":7})
    msp.add_line((x,y-cross),(x,y+cross),dxfattribs={"layer":LAYER_AXIS,"color":7})
    _add_text(msp,str(number),x+r+2.0,y+r+1.0,height=2.5,align="MIDDLE_LEFT")


def process_dxf_to_asbuilt_scheme(input_path:str,output_path:str,csv_path:Optional[str]=None,log_callback=None,stamp_data:Optional[Dict[str,Any]]=None,table_data:Optional[List[Dict[str,Any]]]=None) -> None:
    def log(msg):
        (log_callback(msg) if log_callback else print(msg))
    log(f"[ИНФО] Обработка конусов: {input_path}")
    src=ezdxf.readfile(input_path)
    unit_factor=unit_to_mm_from_doc(src)
    candidates=detect_cones(src.modelspace())
    out=ezdxf.new("R2018"); _ensure_layers(out); msp=out.modelspace()
    scale_str="авто"
    if candidates:
        # Source coordinates are normalized to mm before scale selection.
        centers=[(c["center"][0]*unit_factor,c["center"][1]*unit_factor) for c in candidates]
        radii=[c["radius"]*unit_factor for c in candidates]
        xmin=min(p[0]-r for p,r in zip(centers,radii)); ymin=min(p[1]-r for p,r in zip(centers,radii))
        xmax=max(p[0]+r for p,r in zip(centers,radii)); ymax=max(p[1]+r for p,r in zip(centers,radii))
        work_w=A3_W-2*FRAME_MARGIN-8.0
        work_h=A3_H-FRAME_MARGIN-STAMP_H-15.0
        plan=fit_standard_scale(xmax-xmin,ymax-ymin,work_w,work_h)
        scale_str=f"1:{plan.denominator:g}"
        x0=FRAME_MARGIN+4.0; y0=FRAME_MARGIN+STAMP_H+12.0
        for idx,item in enumerate(candidates,1):
            p=(item["center"][0]*unit_factor,item["center"][1]*unit_factor)
            sx,sy=paper_point_from_source(p,(xmin,ymin),plan,(x0,y0))
            _draw_cone_symbol(msp,item,sx,sy,item["radius"]*unit_factor*plan.factor,idx)
    else:
        bbox=_source_bbox(src.modelspace())
        if bbox:
            f=unit_factor; _add_text(msp,"Конусы: геометрические кандидаты не распознаны",A3_W/2,A3_H/2,4.0); _add_text(msp,f"Исходный габарит: {(bbox[2]-bbox[0])*f:.0f} × {(bbox[3]-bbox[1])*f:.0f} мм",A3_W/2,A3_H/2-8,3.0)
        else: _add_text(msp,"Конусы: исходная геометрия не найдена",A3_W/2,A3_H/2,4.0)
    _add_text(msp,"ИСПОЛНИТЕЛЬНАЯ СХЕМА КОНУСОВ",A3_W/2,A3_H-16,4.0)
    _add_text(msp,f"Распознано элементов: {len(candidates)}",FRAME_MARGIN+4,A3_H-16,2.5,"MIDDLE_LEFT")
    _draw_frame(msp)
    draw_gost_stamp(msp,A3_W-FRAME_MARGIN-STAMP_W,FRAME_MARGIN,scale=1.0,stamp_data=stamp_data,scale_str=scale_str)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".",exist_ok=True); out.saveas(output_path)
    log(f"[УСПЕХ] Исполнительная схема конусов сохранена: {output_path}")
    if csv_path:
        import csv
        with open(csv_path,"w",newline="",encoding="utf-8-sig") as fh:
            writer=csv.DictWriter(fh,fieldnames=["№","X","Y","Радиус"]); writer.writeheader(); writer.writerows(generate_table_data(input_path))


def generate_table_data(input_path:str)->List[Dict[str,Any]]:
    src=ezdxf.readfile(input_path); f=unit_to_mm_from_doc(src); rows=[]
    for idx,item in enumerate(detect_cones(src.modelspace()),1): rows.append({"№":idx,"X":round(item["center"][0]*f,3),"Y":round(item["center"][1]*f,3),"Радиус":round(item["radius"]*f,3)})
    return rows


def run(input_dxf:str,output_dxf:str,output_csv:Optional[str]=None,log_callback=None,stamp_data:Optional[Dict[str,Any]]=None,table_data:Optional[List[Dict[str,Any]]]=None)->None:
    process_dxf_to_asbuilt_scheme(input_dxf,output_dxf,output_csv,log_callback=log_callback,stamp_data=stamp_data,table_data=table_data)

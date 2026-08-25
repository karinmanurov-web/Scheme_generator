"""Canonical clean presentation pipeline for slope-wall drawings."""
from __future__ import annotations
import math
from typing import Any, Dict, List, Optional
import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.enums import TextEntityAlignment
from algo_stamp import STAMP_HEIGHT, draw_gost_frame_and_stamp
from algo_walls import analyze_wall_geometry, draw_legend_and_notes, draw_quantities_table, setup_document
from dxf_geometry import extract_geometry
from dxf_math import A3_H_MM, A3_W_MM, STANDARD_SCALES, fit_standard_scale

ALGORITHM_NAME="Откосные стенки"
SHEET_W,SHEET_H=A3_W_MM,A3_H_MM
INNER_LEFT,INNER_BOTTOM,INNER_RIGHT,INNER_TOP=20.0,5.0,5.0,5.0
STAMP_WIDTH=185.0


def _arc_points(item):
    _,c,r,a0,a1,_=item; span=(a1-a0)%360.0; n=max(8,int(math.ceil(span/10.0)))
    return [(c[0]+r*math.cos(math.radians(a0+span*i/n)),c[1]+r*math.sin(math.radians(a0+span*i/n))) for i in range(n+1)]


def _geometry_bbox(elements):
    p=[]
    for x in elements:
        if x[0]=="LINE": p += [x[1],x[2]]
        elif x[0]=="POLYLINE": p += [(v[0],v[1]) for v in x[1]]
        elif x[0]=="CIRCLE": c,r=x[1],x[2]; p += [(c[0]-r,c[1]-r),(c[0]+r,c[1]+r)]
        elif x[0]=="ARC": p += _arc_points(x)
    if not p:return None
    xs,ys=zip(*p); return min(xs),min(ys),max(xs),max(ys)


def _fit_scale(w,h):
    return fit_standard_scale(
        w, h,
        SHEET_W-INNER_LEFT-INNER_RIGHT,
        SHEET_H-INNER_BOTTOM-INNER_TOP,
        scales=STANDARD_SCALES,
        allow_rotation=False,
    )


def _draw_elements(msp,elements):
    for x in elements:
        if x[0]=="LINE": msp.add_line(x[1],x[2],dxfattribs={"layer":x[3],"color":1 if x[3]=="ГОСТ_Оси" else 7})
        elif x[0]=="POLYLINE":
            pts=[(p[0],p[1],0.0,0.0,p[2]) if len(p)>2 else (p[0],p[1],0.0,0.0,0.0) for p in x[1]]
            msp.add_lwpolyline(pts,format="xyseb",close=x[2],dxfattribs={"layer":x[3],"color":7})
        elif x[0]=="CIRCLE": msp.add_circle(x[1],x[2],dxfattribs={"layer":x[3],"color":7})
        elif x[0]=="ARC": msp.add_arc(x[1],x[2],start_angle=x[3],end_angle=x[4],dxfattribs={"layer":x[5],"color":7})


def _scale_element(x,f,dx,dy):
    if x[0]=="LINE": return ("LINE",((x[1][0]+dx)*f,(x[1][1]+dy)*f),((x[2][0]+dx)*f,(x[2][1]+dy)*f),x[3])
    if x[0]=="POLYLINE": return ("POLYLINE",[((p[0]+dx)*f,(p[1]+dy)*f,p[2] if len(p)>2 else 0.0) for p in x[1]],x[2],x[3])
    if x[0]=="CIRCLE": return ("CIRCLE",((x[1][0]+dx)*f,(x[1][1]+dy)*f),x[2]*f,x[3])
    if x[0]=="ARC": return ("ARC",((x[1][0]+dx)*f,(x[1][1]+dy)*f),x[2]*f,x[3],x[4],x[5])
    return x


def _scale_dim(d,f,dx,dy):
    d=dict(d)
    for k in ("p1","p2","p_dim"):
        x,y=d[k]; d[k]=((x+dx)*f,(y+dy)*f)
    d["angle_rad"]=float(d["angle_rad"])
    d["prj_val"]=float(d["prj_val"])*f
    return d


def _draw_level(msp,d):
    p,v=d["pt"],d["val"]; by=p[1]-.5; tw,hh,sw=1.5,1.5,8.0
    msp.add_lwpolyline([(p[0],by),(p[0]-tw,by+hh),(p[0]+tw,by+hh)],close=True,dxfattribs={"layer":"ГОСТ_Отметки","color":7})
    msp.add_line((p[0]-tw,by+hh),(p[0]+sw,by+hh),dxfattribs={"layer":"ГОСТ_Отметки","color":7})
    msp.add_text(f"{v:+.3f}",dxfattribs={"style":"ГОСТ_Шрифт","height":2.5,"layer":"ГОСТ_Отметки","color":7}).set_placement((p[0]+.5,by+hh+.5),align=TextEntityAlignment.BOTTOM_LEFT)


def _draw_dimension(msp,d):
    p1,p2,pd=d["p1"],d["p2"],d["p_dim"]; a=d["angle_rad"]; dx,dy=math.cos(a),math.sin(a); px,py=-dy,dx
    q1=(p1[0]+((pd[0]-p1[0])*px+(pd[1]-p1[1])*py)*px,p1[1]+((pd[0]-p1[0])*px+(pd[1]-p1[1])*py)*py)
    q2=(p2[0]+((pd[0]-p2[0])*px+(pd[1]-p2[1])*py)*px,p2[1]+((pd[0]-p2[0])*px+(pd[1]-p2[1])*py)*py)
    ext=1.5
    msp.add_line(p1,(q1[0]+ext*px,q1[1]+ext*py),dxfattribs={"layer":"ГОСТ_Размеры_Проект","color":7})
    msp.add_line(p2,(q2[0]+ext*px,q2[1]+ext*py),dxfattribs={"layer":"ГОСТ_Размеры_Проект","color":7})
    msp.add_line((q1[0]-ext*dx,q1[1]-ext*dy),(q2[0]+ext*dx,q2[1]+ext*dy),dxfattribs={"layer":"ГОСТ_Размеры_Проект","color":7})
    mx,my=(q1[0]+q2[0])/2,(q1[1]+q2[1])/2; v=d["prj_val"]; text=f"{int(round(v))}" if v>=10 else f"{v:.2f}"
    msp.add_text(text,dxfattribs={"style":"ГОСТ_Шрифт","height":2.5,"layer":"ГОСТ_Размеры_Проект","color":7,"rotation":math.degrees(a)%180}).set_placement((mx+2*px,my+2*py),align=TextEntityAlignment.MIDDLE_CENTER)


def run(input_dxf:str,output_dxf:str,output_csv:Optional[str]=None,log_callback=None,stamp_data:Optional[Dict[str,Any]]=None,table_data:Optional[List[Dict[str,Any]]]=None)->None:
    src=ezdxf.readfile(input_dxf)
    elements,dims,levels=extract_geometry(src.modelspace(),src)
    geom=_geometry_bbox(elements)
    if geom is None: raise RuntimeError("Не удалось извлечь исполнительную геометрию")
    min_x,min_y,max_x,max_y=geom
    w,h=max_x-min_x,max_y-min_y
    plan=_fit_scale(w,h)
    f=plan.factor
    pad=5.0  # physical paper-space padding in millimetres
    dx,dy=-min_x,-min_y
    scaled=[_scale_element(x,f,dx,dy) for x in elements]
    out=setup_document(ezdxf.new("R2018",setup=True)); msp=out.modelspace(); _draw_elements(msp,scaled)
    dims=[_scale_dim(x,f,dx,dy) for x in dims]
    for d in dims: _draw_dimension(msp,d)
    for x in levels:
        d=dict(x); d["pt"]=((x["pt"][0]+dx)*f+pad,(x["pt"][1]+dy)*f+pad); d["val"]=float(x["val"]); _draw_level(msp,d)
    # Shift all geometry into the same paper-space padding after scaling.
    for ent in msp:
        if ent.dxftype() in {"LINE","LWPOLYLINE","CIRCLE","ARC","TEXT","MTEXT"}:
            try: ent.translate(pad,pad,0)
            except Exception: pass
    box=ezdxf_bbox.extents(msp); scale_str=f"1:{int(plan.denominator)}"; ix0,iy0,ix1,iy1=draw_gost_frame_and_stamp(msp,box,scale=1.0,stamp_data=stamp_data,scale_str=scale_str)
    stamp_top=iy0+STAMP_HEIGHT; stamp_left=ix1-STAMP_WIDTH; chrome_left=ix0+2.0; available=max(0.0,stamp_left-chrome_left-3.0); table_scale=max(.75,min(1.0,available/230.0))
    L,B,area=analyze_wall_geometry(elements); draw_quantities_table(msp,(chrome_left,stamp_top-2),L=L,B=B,area=area,scale=table_scale,table_data=table_data); draw_legend_and_notes(msp,(chrome_left,iy1-12),scale=1.0,custom_notes=((stamp_data or {}).get("_notes_data") or {}).get("notes"))
    title=((stamp_data or {}).get("doc_title") or "ИСПОЛНИТЕЛЬНАЯ СХЕМА. ОТКОСНЫЕ СТЕНКИ").upper(); msp.add_text(title,dxfattribs={"style":"ГОСТ_Шрифт","height":5.0,"layer":"ГОСТ_Текст","color":7}).set_placement(((ix0+ix1)/2,iy1-8),align=TextEntityAlignment.MIDDLE_CENTER); out.saveas(output_dxf)

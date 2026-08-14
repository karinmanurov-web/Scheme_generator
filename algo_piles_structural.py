"""Structural post-processing for the pile execution-sheet algorithm."""
from __future__ import annotations

import json
import math
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.math import Matrix44

import algo_piles_fixed as _base
from grillage_detector import collect_world_segments, detect_grillage, infer_pile_axis

ALGORITHM_NAME = _base.ALGORITHM_NAME
PREVIEW_IMAGE = _base.PREVIEW_IMAGE
generate_table_data = _base.generate_table_data
process_dxf_to_asbuilt_scheme = _base.process_dxf_to_asbuilt_scheme

_PILE_OUTPUT_LAYERS = {"Сваи_Проект", "Оси_Проект", "Исполнительная_Номера", "Исполнительная_Отклонения"}
_COMPACT_CROSS_LENGTH = 500.0
_MIN_EXECUTION_DIMENSION = 100.0
_GRILLAGE_LAYER = "Исполнительная_Ростверк"


def _entity_center(entity):
    try:
        box = ezdxf_bbox.extents([entity])
        if box.has_data:
            return ((box.extmin.x + box.extmax.x) / 2.0, (box.extmin.y + box.extmax.y) / 2.0)
    except Exception:
        pass
    return None


def _polyline_center(entity):
    try:
        pts = list(entity.get_points())
        if len(pts) >= 3:
            return (sum(float(p[0]) for p in pts) / len(pts), sum(float(p[1]) for p in pts) / len(pts))
    except Exception:
        pass
    return None


def _pile_centers(doc):
    out = []
    for e in doc.modelspace():
        try:
            if e.dxf.layer == "Сваи_Проект" and e.dxftype() in ("LWPOLYLINE", "POLYLINE"):
                p = _polyline_center(e)
                if p and not any(math.hypot(p[0]-q[0], p[1]-q[1]) < .1 for q in out):
                    out.append(p)
        except Exception:
            pass
    return out


def _matrix_apply(m, p):
    a,b,c,d,tx,ty = m
    x,y = p
    return a*x+b*y+tx, c*x+d*y+ty


def _matrix_compose(parent, local):
    pa,pb,pc,pd,ptx,pty = parent
    la,lb,lc,ld,ltx,lty = local
    return (pa*la+pb*lc, pa*lb+pb*ld, pc*la+pd*lc, pc*lb+pd*ld,
            pa*ltx+pb*lty+ptx, pc*ltx+pd*lty+pty)


def _insert_matrix(ins):
    r = math.radians(float(getattr(ins.dxf, "rotation", 0.0)))
    sx = float(getattr(ins.dxf, "xscale", 1.0)); sy = float(getattr(ins.dxf, "yscale", 1.0))
    c,s = math.cos(r), math.sin(r)
    return (c*sx, -s*sy, s*sx, c*sy, float(ins.dxf.insert.x), float(ins.dxf.insert.y))


def _block_bbox(block):
    pts=[]
    for e in block:
        try:
            if e.dxftype()=="LINE": pts += [(e.dxf.start.x,e.dxf.start.y),(e.dxf.end.x,e.dxf.end.y)]
            elif e.dxftype()=="LWPOLYLINE": pts += [(p[0],p[1]) for p in e.get_points()]
            elif e.dxftype()=="POLYLINE": pts += [(v.dxf.location.x,v.dxf.location.y) for v in e.vertices]
            elif e.dxftype()=="CIRCLE":
                x,y,r=e.dxf.center.x,e.dxf.center.y,e.dxf.radius; pts += [(x-r,y-r),(x+r,y+r)]
        except Exception: pass
    if not pts: return None
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    return min(xs),min(ys),max(xs),max(ys)


def _is_pile_bbox(bb, m):
    if not bb: return False
    x0,y0,x1,y1=bb
    corners=[_matrix_apply(m,p) for p in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
    w=max(p[0] for p in corners)-min(p[0] for p in corners)
    h=max(p[1] for p in corners)-min(p[1] for p in corners)
    return min(w,h)>1e-6 and max(w,h)/min(w,h)<=1.35 and 200<=max(w,h)<=700


def _source_pile_axes(doc):
    found=[]; cache={}
    def walk(entities, parent=(1,0,0,1,0,0), stack=()):
        for e in entities:
            if e.dxftype()!="INSERT": continue
            name=str(e.dxf.name)
            if name not in doc.blocks or name in stack: continue
            m=_matrix_compose(parent,_insert_matrix(e)); block=doc.blocks[name]
            if name not in cache: cache[name]=_block_bbox(block)
            if _is_pile_bbox(cache[name],m):
                found.append((_matrix_apply(m,(0,0)), math.atan2(m[2],m[0])))
            walk(block,m,stack+(name,))
    walk(doc.modelspace())
    return found


def _nearest(p, points):
    if not points: return None,float("inf")
    q=min(points,key=lambda x:math.hypot(p[0]-x[0],p[1]-x[1]))
    return q,math.hypot(p[0]-q[0],p[1]-q[1])


def _entity_angle(e):
    try:
        if e.dxftype()=="LINE": return math.atan2(e.dxf.end.y-e.dxf.start.y,e.dxf.end.x-e.dxf.start.x)
        if e.dxftype()=="LWPOLYLINE":
            p=list(e.get_points()); return math.atan2(p[1][1]-p[0][1],p[1][0]-p[0][0]) if len(p)>1 else None
        if e.dxftype()=="POLYLINE":
            p=[(v.dxf.location.x,v.dxf.location.y) for v in e.vertices]; return math.atan2(p[1][1]-p[0][1],p[1][0]-p[0][0]) if len(p)>1 else None
        if e.dxftype()=="TEXT": return math.radians(float(getattr(e.dxf,"rotation",0)))
    except Exception: pass
    return None


def _rotate_about(e, center, delta):
    if abs(delta)<math.radians(.05): return False
    cx,cy=center
    try:
        e.transform(Matrix44.chain(Matrix44.translate(-cx,-cy,0),Matrix44.z_rotate(delta),Matrix44.translate(cx,cy,0)))
        return True
    except Exception: return False


def _orient_piles(doc, source, log=None):
    centers=_pile_centers(doc); src=_source_pile_axes(source); src_pts=[p for p,_ in src]
    matched=[]
    for c in centers:
        q,d=_nearest(c,src_pts)
        if q is not None and d<=300:
            a=min(src,key=lambda x:math.hypot(x[0][0]-c[0],x[0][1]-c[1]))[1]
            matched.append((c,a,1.0,"source_insert_affine"))
    if len(matched)<len(centers):
        segs=collect_world_segments(source); used={x[0] for x in matched}
        for c in centers:
            if c in used: continue
            a,conf=infer_pile_axis(c,segs)
            if conf>=.58: matched.append((c,a,conf,"nearby_structural_geometry"))
    mp=[x[0] for x in matched]; changed=0
    for e in list(doc.modelspace()):
        try:
            if e.dxf.layer not in _PILE_OUTPUT_LAYERS: continue
            p=_entity_center(e); q,d=_nearest(p,mp)
            if q is None or d>750: continue
            target,conf,_=next(x[1:] for x in matched if x[0]==q)
            if conf<.58: continue
            cur=_entity_angle(e)
            if cur is None: continue
            delta=((target-cur+math.pi/4)%(math.pi/2))-math.pi/4
            if _rotate_about(e,q,delta): changed+=1
        except Exception: pass
    if log: log(f"[INFO] Оси свай выровнены по affine-трансформации: {changed} объектов.")
    return [{"x":round(c[0],3),"y":round(c[1],3),"angle_deg":round(math.degrees(a)%360,3),"confidence":round(conf,3),"source":src}
            for c,a,conf,src in matched]


def _copy_grillage(doc, source, pile_centers, log=None):
    if _GRILLAGE_LAYER not in doc.layers:
        doc.layers.new(_GRILLAGE_LAYER,dxfattribs={"color":7,"lineweight":35})
    layer=doc.layers.get(_GRILLAGE_LAYER)
    try:
        layer.on(); layer.thaw(); layer.dxf.color=7; layer.dxf.lineweight=35
    except Exception: pass
    candidates=detect_grillage(source,pile_centers); rendered=[]
    for c in candidates:
        if c.confidence<.80 or not c.bbox: continue
        for seg in c.segments:
            doc.modelspace().add_line(seg.start,seg.end,dxfattribs={"layer":_GRILLAGE_LAYER,"color":7,"lineweight":35})
        rendered.append({"bbox":[round(v,3) for v in c.bbox],"angle_deg":round(math.degrees(c.angle)%360,3),"confidence":round(c.confidence,3),"reason":c.reason,"segments":len(c.segments)})
    if log: log(f"[INFO] Ростверк: кандидатов {len(candidates)}, отрисовано {len(rendered)}; hatch не переносится.")
    return rendered,[{"bbox":[round(v,3) for v in c.bbox] if c.bbox else None,"angle_deg":round(math.degrees(c.angle)%360,3),"confidence":round(c.confidence,3),"reason":c.reason} for c in candidates]


def _remove_hatches(doc):
    n=0
    for e in list(doc.modelspace()):
        if e.dxftype()=="HATCH":
            try: doc.modelspace().delete_entity(e); n+=1
            except Exception: pass
    return n


def _shrink_axes(doc,log=None):
    centers=_pile_centers(doc); half=_COMPACT_CROSS_LENGTH/2; changed=0
    for e in list(doc.modelspace()):
        try:
            if e.dxf.layer!="Оси_Проект" or e.dxftype()!="LINE": continue
            s=(e.dxf.start.x,e.dxf.start.y); t=(e.dxf.end.x,e.dxf.end.y); L=math.hypot(t[0]-s[0],t[1]-s[1])
            if L<=_COMPACT_CROSS_LENGTH: continue
            mid=((s[0]+t[0])/2,(s[1]+t[1])/2); q,d=_nearest(mid,centers)
            if q is None or d>100: continue
            ux=(t[0]-s[0])/L; uy=(t[1]-s[1])/L
            e.dxf.start=(q[0]-ux*half,q[1]-uy*half,0); e.dxf.end=(q[0]+ux*half,q[1]+uy*half,0); changed+=1
        except Exception: pass
    if log and changed: log(f"[INFO] Сокращены оси свай: {changed} линий до {_COMPACT_CROSS_LENGTH:.0f} мм.")
    return changed


def run(input_dxf, output_dxf, output_csv=None, log_callback=None, stamp_data=None, table_data=None):
    # Only source DIMENSION entities may create execution dimensions. Their
    # original p1/p2/p_dim anchors are preserved by the base renderer.
    original_extract=_base._piles.extract_source_dimensions
    def source_only_dimensions(msp):
        dims=original_extract(msp)
        return [d for d in dims if float(d.get("prj_val",0))>=_MIN_EXECUTION_DIMENSION]
    _base._piles.extract_source_dimensions=source_only_dimensions
    try:
        result=_base.run(input_dxf,output_dxf,output_csv,log_callback=log_callback,stamp_data=stamp_data,table_data=table_data)
    finally:
        _base._piles.extract_source_dimensions=original_extract
    try:
        source=ezdxf.readfile(input_dxf); out=ezdxf.readfile(output_dxf); centers=_pile_centers(out)
        _remove_hatches(out)
        rendered,candidates=_copy_grillage(out,source,centers,log_callback)
        _remove_hatches(out)
        layer=out.layers.get(_GRILLAGE_LAYER); layer.on(); layer.thaw(); layer.dxf.color=7; layer.dxf.lineweight=35
        orientations=_orient_piles(out,source,log_callback); _shrink_axes(out,log_callback)
        out.saveas(output_dxf)
        base=Path(output_dxf)
        base.with_name(base.stem+"_grillage_diagnostic.json").write_text(json.dumps({
            "schema_version":4,"algorithm_id":"piles",
            "presentation_rules":{"hatches":"forbidden","cross_length_mm":_COMPACT_CROSS_LENGTH,"min_dimension_value":_MIN_EXECUTION_DIMENSION,"dimensions":"source_anchors_only"},
            "grillage":{"rendered":rendered,"candidates":candidates},"pile_orientations":orientations
        },ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception as exc:
        if log_callback: log_callback(f"[ПРЕДУПРЕЖДЕНИЕ] Структурный post-process не выполнен: {exc}")
    return result

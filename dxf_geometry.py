from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Tuple


def unit_to_mm(doc) -> float:
    units = int(doc.header.get("$INSUNITS", 4) or 4)
    return {1:25.4, 2:304.8, 3:1609344.0, 4:1.0, 5:10.0, 6:1000.0,
            7:1000000.0, 10:914.4, 14:100.0, 15:10000.0,
            16:100000.0, 17:1000000.0}.get(units, 1.0)


def _green(entity) -> bool:
    try:
        c = int(entity.dxf.color)
        if c == 3:
            return True
    except Exception:
        pass
    return False


def _skip(entity) -> bool:
    if entity.dxftype() in {"HATCH", "WIPEOUT", "IMAGE", "IMAGEDEF", "SOLID", "3DFACE"}:
        return True
    if _green(entity):
        return True
    layer = str(getattr(entity.dxf, "layer", "")).lower()
    return any(k in layer for k in ("defpoints", "штамп", "рамка", "frame", "stamp", "title"))


def _text_value(text: str):
    text = re.sub(r"\\[A-Za-z0-9]+;?", "", text or "")
    m = re.search(r"[+-]?\d+[\.,]\d+", text)
    return float(m.group(0).replace(",", ".")) if m else None


def _transform_entity(entity, unit_factor: float):
    t = entity.dxftype()
    layer = str(getattr(entity.dxf, "layer", ""))
    target = "ГОСТ_Контур_Толстый"
    low = layer.lower()
    if any(k in low for k in ("оси", "axis", "center")):
        target = "ГОСТ_Оси"
    elif any(k in low for k in ("пунктир", "тонкие", "thin", "dash")):
        target = "ГОСТ_Контур_Тонкий"

    if t == "LINE":
        return [("LINE", (entity.dxf.start.x*unit_factor, entity.dxf.start.y*unit_factor),
                 (entity.dxf.end.x*unit_factor, entity.dxf.end.y*unit_factor), target)]
    if t == "CIRCLE":
        return [("CIRCLE", (entity.dxf.center.x*unit_factor, entity.dxf.center.y*unit_factor),
                 entity.dxf.radius*unit_factor, target)]
    if t == "ARC":
        return [("ARC", (entity.dxf.center.x*unit_factor, entity.dxf.center.y*unit_factor),
                 entity.dxf.radius*unit_factor, float(entity.dxf.start_angle),
                 float(entity.dxf.end_angle), target)]
    if t in {"LWPOLYLINE", "POLYLINE"}:
        pts = []
        for v in entity.get_points("xy") if t == "LWPOLYLINE" else entity.vertices:
            p = (v[0]*unit_factor, v[1]*unit_factor) if t == "LWPOLYLINE" else (v.dxf.location.x*unit_factor, v.dxf.location.y*unit_factor)
            pts.append(p)
        return [("POLYLINE", pts, bool(getattr(entity, "closed", False) or getattr(entity, "is_closed", False)), target)] if len(pts) >= 2 else []
    return []


def extract_geometry(source_msp, source_doc):
    elements: List[Any] = []
    dims: List[Dict[str, Any]] = []
    levels: List[Dict[str, Any]] = []
    factor = unit_to_mm(source_doc)

    def visit(entity):
        if _skip(entity):
            return
        t = entity.dxftype()
        if t == "INSERT":
            try:
                for sub in entity.virtual_entities():
                    visit(sub)
            except Exception:
                return
            return
        if t in {"TEXT", "MTEXT"}:
            text = entity.dxf.text if t == "TEXT" else entity.text
            val = _text_value(text)
            if val is not None:
                p = entity.dxf.insert
                levels.append({"pt": (p.x*factor, p.y*factor), "val": val})
            return
        if t == "DIMENSION":
            try:
                p1, p2, pd = entity.dxf.defpoint2, entity.dxf.defpoint3, entity.dxf.defpoint
                dx, dy = p2.x-p1.x, p2.y-p1.y
                angle = math.atan2(dy, dx)
                dist = math.hypot(dx, dy)*factor
                text = getattr(entity.dxf, "text", "")
                val = _text_value(text)
                if val is None:
                    val = dist
                else:
                    val *= factor
                dims.append({"p1":(p1.x*factor,p1.y*factor), "p2":(p2.x*factor,p2.y*factor),
                             "p_dim":(pd.x*factor,pd.y*factor), "angle_rad":angle, "prj_val":val})
            except Exception:
                pass
            return
        try:
            elements.extend(_transform_entity(entity, factor))
        except Exception:
            pass

    for entity in source_msp:
        visit(entity)
    return elements, dims, levels

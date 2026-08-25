from __future__ import annotations

import math
import re
from typing import Any, Dict, List

UNIT_TO_MM = {
    0: 1.0, 1: 25.4, 2: 304.8, 3: 1609344.0, 4: 1.0, 5: 10.0,
    6: 1000.0, 7: 1000000.0, 8: 0.0000254, 9: 0.0254, 10: 914.4,
    14: 100.0, 15: 10000.0, 16: 100000.0, 17: 1000000.0,
}

_PRESENTATION_TYPES = {"HATCH", "WIPEOUT", "IMAGE", "IMAGEDEF", "SOLID", "3DFACE"}


def unit_to_mm(doc) -> float:
    try:
        units = int(doc.header.get("$INSUNITS", 0) or 0)
    except Exception:
        units = 0
    return UNIT_TO_MM.get(units, 1.0)


def _green(entity) -> bool:
    try:
        return int(entity.dxf.color) == 3
    except Exception:
        return False


def _skip(entity) -> bool:
    # Filter presentation-only entities and explicit green construction geometry.
    # Do not filter by source layer/block names: those are project-specific.
    return entity.dxftype() in _PRESENTATION_TYPES or _green(entity)


def _text_value(text: str):
    text = re.sub(r"\\[A-Za-z0-9]+;?", "", text or "")
    m = re.search(r"[+-]?\d+(?:[\.,]\d+)?", text)
    return float(m.group(0).replace(",", ".")) if m else None


def _polyline_points(entity, factor: float):
    if entity.dxftype() == "LWPOLYLINE":
        # Preserve bulge for downstream consumers instead of flattening arcs away.
        return [
            (float(p[0]) * factor, float(p[1]) * factor, float(p[4]) if len(p) > 4 else 0.0)
            for p in entity.get_points("xyseb")
        ]
    return [
        (float(v.dxf.location.x) * factor, float(v.dxf.location.y) * factor, 0.0)
        for v in entity.vertices
    ]


def _transform_entity(entity, unit_factor: float):
    t = entity.dxftype()
    if t == "LINE":
        return [("LINE", (entity.dxf.start.x*unit_factor, entity.dxf.start.y*unit_factor),
                 (entity.dxf.end.x*unit_factor, entity.dxf.end.y*unit_factor))]
    if t == "CIRCLE":
        return [("CIRCLE", (entity.dxf.center.x*unit_factor, entity.dxf.center.y*unit_factor),
                 entity.dxf.radius*unit_factor)]
    if t == "ARC":
        return [("ARC", (entity.dxf.center.x*unit_factor, entity.dxf.center.y*unit_factor),
                 entity.dxf.radius*unit_factor, float(entity.dxf.start_angle),
                 float(entity.dxf.end_angle))]
    if t in {"LWPOLYLINE", "POLYLINE"}:
        pts = _polyline_points(entity, unit_factor)
        closed = bool(getattr(entity.dxf, "flags", 0) & 1) if t == "POLYLINE" else bool(getattr(entity, "closed", False))
        return [("POLYLINE", pts, closed)] if len(pts) >= 2 else []
    return []


def extract_geometry(source_msp, source_doc):
    """Extract geometry, dimensions and levels in millimetres.

    INSERTs are recursively expanded. Geometry is normalized to mm before any
    sheet scaling. Source layer/block names are intentionally ignored.
    """
    elements: List[Any] = []
    dims: List[Dict[str, Any]] = []
    levels: List[Dict[str, Any]] = []
    factor = unit_to_mm(source_doc)

    def visit(entity, depth=0):
        if depth > 8 or _skip(entity):
            return
        t = entity.dxftype()
        if t == "INSERT":
            try:
                for sub in entity.virtual_entities():
                    visit(sub, depth + 1)
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
                dist = math.hypot(dx, dy) * factor
                text = getattr(entity.dxf, "text", "")
                val = _text_value(text)
                if val is None:
                    val = dist
                elif factor != 1.0:
                    # Explicit dimension text is normally already expressed in drawing units;
                    # normalize it only when source units are not mm.
                    val *= factor
                dims.append({
                    "p1": (p1.x*factor, p1.y*factor),
                    "p2": (p2.x*factor, p2.y*factor),
                    "p_dim": (pd.x*factor, pd.y*factor),
                    "angle_rad": angle,
                    "prj_val": val,
                })
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

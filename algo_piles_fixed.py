"""Geometry-safe wrapper for the pile foundation algorithm.

The wrapper keeps the existing pile extraction and intentional randomized
SP-compliant deviations untouched. It changes only presentation geometry:
frame bounds are based on generated geometry and source drawing layers are
hidden after generation so the output is an actual execution-sheet view.

It also emits a machine-readable pile layout diagnostic next to the generated
DXF. The diagnostic is deliberately observational: it does not renumber piles
or change the existing algorithm.
"""

import csv
import json
import math
from pathlib import Path

import algo_piles as _piles
from ezdxf import bbox as ezdxf_bbox

ALGORITHM_NAME = _piles.ALGORITHM_NAME
PREVIEW_IMAGE = getattr(_piles, "PREVIEW_IMAGE", "preview_piles.png")

# Preserve the existing public API and, importantly, the existing random
# deviation generation in algo_piles.
process_dxf_to_asbuilt_scheme = _piles.process_dxf_to_asbuilt_scheme

_GENERATED_LAYERS = {
    "Сваи_Проект",
    "Оси_Проект",
    "Исполнительная_Номера",
    "Исполнительная_Размеры",
    "Исполнительная_Отклонения",
    "Исполнительная_Ростверк",
    "Исполнительная_Оси_Опор",
    "Исполнительная_Оформление",
    "ИСП_Текст",
    "ИСП_Таблица",
    "ИСП_Размеры_Проект",
    "ИСП_Размеры_Факт",
    "ГОСТ_Рамка",
}

_ORIGINAL_EXTENTS = ezdxf_bbox.extents


def _generated_extents(layout):
    """Return bounds only for entities produced by the pile generator."""
    box = ezdxf_bbox.BoundingBox()
    for entity in layout:
        try:
            layer = entity.dxf.layer
            if layer not in _GENERATED_LAYERS:
                continue
            entity_box = _ORIGINAL_EXTENTS([entity])
            if entity_box.has_data:
                box.extend([entity_box.extmin, entity_box.extmax])
        except Exception:
            continue
    return box


def _patched_extents(entities, *args, **kwargs):
    """Intercept only modelspace-wide bbox requests; delegate entity calls."""
    if hasattr(entities, "name") and getattr(entities, "name", None) == "Model":
        return _generated_extents(entities)
    return _ORIGINAL_EXTENTS(entities, *args, **kwargs)


def _snapshot_source_layers(doc):
    """Capture layers present before generation, without relying on their names."""
    return {layer.dxf.name for layer in doc.layers}


def _hide_source_layers(doc, source_layers):
    """Hide pre-existing layers; leave all generator-created layers visible."""
    for layer_name in source_layers:
        if layer_name in _GENERATED_LAYERS or layer_name not in doc.layers:
            continue
        try:
            layer = doc.layers.get(layer_name)
            layer.off = True
        except Exception:
            continue


def _polyline_center(entity):
    points = list(entity.get_points())
    if len(points) < 3:
        return None
    xy = [(float(p[0]), float(p[1])) for p in points]
    return (
        sum(p[0] for p in xy) / len(xy),
        sum(p[1] for p in xy) / len(xy),
    )


def _build_pile_layout_diagnostic(doc):
    """Extract generated pile positions without changing their existing IDs.

    The current generator draws one closed square per pile on Сваи_Проект and
    one label on Исполнительная_Номера. We use that generated geometry as an
    observation point, not as a new source of truth for the algorithm.
    """
    msp = doc.modelspace()
    generated = []

    for entity in msp:
        try:
            if entity.dxf.layer != "Сваи_Проект":
                continue
            if entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
                continue
            center = _polyline_center(entity)
            if center is None:
                continue
            generated.append(center)
        except Exception:
            continue

    # De-duplicate centers defensively; a future renderer must not silently
    # create duplicate diagnostic rows if it adds another outline.
    unique = []
    for center in generated:
        if not any(math.hypot(center[0] - other[0], center[1] - other[1]) < 0.1 for other in unique):
            unique.append(center)

    # Existing IDs remain the canonical order. Geometric order is diagnostic
    # only: Y descending, then X ascending, with no mutation of the DXF.
    geometric = sorted(unique, key=lambda p: (-p[1], p[0]))
    geometric_rank = {point: idx for idx, point in enumerate(geometric, start=1)}

    rows = []
    for idx, (x, y) in enumerate(unique, start=1):
        nearest = None
        for j, (ox, oy) in enumerate(unique, start=1):
            if j == idx:
                continue
            d = math.hypot(x - ox, y - oy)
            if nearest is None or d < nearest:
                nearest = d
        rows.append({
            "current_id": idx,
            "x": round(x, 3),
            "y": round(y, 3),
            "nearest_neighbor_distance": round(nearest, 3) if nearest is not None else None,
            "geometric_rank": geometric_rank[(x, y)],
        })

    if unique:
        xs = [p[0] for p in unique]
        ys = [p[1] for p in unique]
        bounds = {
            "min_x": min(xs),
            "min_y": min(ys),
            "max_x": max(xs),
            "max_y": max(ys),
            "width": max(xs) - min(xs),
            "height": max(ys) - min(ys),
        }
    else:
        bounds = None

    return {
        "schema_version": 1,
        "purpose": "diagnostic_only",
        "algorithm_id": "piles",
        "canonical_numbering": "existing generator order; diagnostic does not renumber",
        "geometric_order": "Y descending, then X ascending",
        "pile_count": len(rows),
        "bounds": bounds,
        "piles": rows,
    }


def _write_pile_layout_artifacts(output_dxf):
    """Write JSON/CSV diagnostics next to the generated DXF."""
    doc = __import__("ezdxf").readfile(output_dxf)
    diagnostic = _build_pile_layout_diagnostic(doc)
    base = Path(output_dxf)
    json_path = base.with_name(base.stem + "_pile_layout.json")
    csv_path = base.with_name(base.stem + "_pile_layout.csv")

    json_path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = ["current_id", "x", "y", "nearest_neighbor_distance", "geometric_rank"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(diagnostic["piles"])


def run(input_dxf, output_dxf, output_csv=None, log_callback=None,
        stamp_data=None, table_data=None):
    """Run the original algorithm with generated-geometry frame bounds.

    Source layers are hidden only after generation. This preserves the original
    algorithm and avoids any dependency on project-specific source layer names.
    """
    import ezdxf

    # Snapshot the input layer set before the original algorithm adds its own
    # presentation layers. The original algorithm reopens the input itself, so
    # we keep the snapshot by path and apply it to the saved result afterward.
    source_doc = ezdxf.readfile(input_dxf)
    source_layers = _snapshot_source_layers(source_doc)

    original_extents = ezdxf_bbox.extents
    original_safe_extents = _piles.safe_extents
    ezdxf_bbox.extents = _patched_extents
    _piles.safe_extents = _generated_extents
    try:
        result = _piles.run(
            input_dxf,
            output_dxf,
            output_csv,
            log_callback=log_callback,
            stamp_data=stamp_data,
            table_data=table_data,
        )
    finally:
        _piles.safe_extents = original_safe_extents
        ezdxf_bbox.extents = original_extents

    # Turn the generated DXF into a clean presentation without deleting source
    # entities. A contractor can still inspect them by turning layers back on.
    try:
        doc_out = ezdxf.readfile(output_dxf)
        _hide_source_layers(doc_out, source_layers)
        doc_out.saveas(output_dxf)
        _write_pile_layout_artifacts(output_dxf)
    except Exception as exc:
        _piles._log(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось подготовить диагностические артефакты: {exc}", log_callback)

    return result


def generate_table_data(*args, **kwargs):
    return _piles.generate_table_data(*args, **kwargs)

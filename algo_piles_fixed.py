"""Geometry-safe wrapper for the pile foundation algorithm.

The wrapper keeps the existing pile extraction and intentional randomized
SP-compliant deviations untouched. It changes only presentation geometry:
frame bounds are based on generated geometry and source drawing layers are
hidden after generation so the output is an actual execution-sheet view.

No source layer/block names are required for the bounds rule. We snapshot the
source layers before running the original algorithm and hide only those layers
that existed before generation; our generated layers remain visible.
"""

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
    except Exception as exc:
        _piles._log(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось скрыть исходные слои: {exc}", log_callback)

    return result


def generate_table_data(*args, **kwargs):
    return _piles.generate_table_data(*args, **kwargs)

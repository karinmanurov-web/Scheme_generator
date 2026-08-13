"""Semantic and structural regression checks for generated DXF files.

The evaluator deliberately checks the output contract rather than the names of
layers/blocks in the source drawing. Source-side conventions are therefore free
to vary between projects.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import bbox as ezdxf_bbox


@dataclass
class CheckResult:
    check_id: str
    title: str
    severity: str
    status: str
    details: str = ""


@dataclass
class Evaluation:
    case_id: str
    checks: list[CheckResult] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def failed_critical(self) -> bool:
        return any(c.status == "FAIL" and c.severity == "critical" for c in self.checks)

    @property
    def failed(self) -> bool:
        return any(c.status == "FAIL" for c in self.checks)

    @property
    def passed(self) -> bool:
        return not self.failed

    def add(self, check_id: str, title: str, severity: str, status: str, details: str = "") -> None:
        self.checks.append(CheckResult(check_id, title, severity, status, details))


def _entity_counts(msp) -> Counter[str]:
    return Counter(entity.dxftype() for entity in msp)


def _text_values(msp) -> list[str]:
    values: list[str] = []
    for entity in msp:
        try:
            if entity.dxftype() == "TEXT":
                values.append(str(entity.dxf.text))
            elif entity.dxftype() == "MTEXT":
                values.append(str(entity.text))
            elif entity.dxftype() == "ATTRIB":
                values.append(str(entity.dxf.text))
        except Exception:
            continue
    return values


def _bbox_for_entities(entities):
    try:
        box = ezdxf_bbox.extents(entities)
        return box if box.has_data else None
    except Exception:
        return None


def _bbox_dict(box) -> dict[str, float] | None:
    if box is None or not box.has_data:
        return None
    return {
        "min_x": round(float(box.extmin.x), 3),
        "min_y": round(float(box.extmin.y), 3),
        "max_x": round(float(box.extmax.x), 3),
        "max_y": round(float(box.extmax.y), 3),
        "width": round(float(box.extmax.x - box.extmin.x), 3),
        "height": round(float(box.extmax.y - box.extmin.y), 3),
    }


def _geometry_diagnostics(doc, msp) -> dict[str, Any]:
    all_box = _bbox_for_entities(list(msp))
    frame_layers = {"ГОСТ_Рамка", "Исполнительная_Оформление"}
    frame_entities = [e for e in msp if str(getattr(e.dxf, "layer", "")) in frame_layers]
    frame_box = _bbox_for_entities(frame_entities)

    by_layer: Counter[str] = Counter()
    for entity in msp:
        try:
            by_layer[str(entity.dxf.layer)] += 1
        except Exception:
            continue

    diagnostics: dict[str, Any] = {
        "modelspace_bbox": _bbox_dict(all_box),
        "frame_bbox": _bbox_dict(frame_box),
        "frame_entity_count": len(frame_entities),
        "entities_by_layer": dict(sorted(by_layer.items())),
    }

    if frame_box and frame_box.has_data:
        fw = abs(float(frame_box.extmax.x - frame_box.extmin.x))
        fh = abs(float(frame_box.extmax.y - frame_box.extmin.y))
        diagnostics["frame_aspect_ratio"] = round(fw / fh, 4) if fh else None
        diagnostics["frame_aspect_deviation_from_a3"] = round(abs((fw / fh if fh else 0.0) - 420 / 297), 4) if fh else None

    if all_box and frame_box and all_box.has_data and frame_box.has_data:
        model_w = abs(float(all_box.extmax.x - all_box.extmin.x))
        model_h = abs(float(all_box.extmax.y - all_box.extmin.y))
        frame_w = abs(float(frame_box.extmax.x - frame_box.extmin.x))
        frame_h = abs(float(frame_box.extmax.y - frame_box.extmin.y))
        diagnostics["model_to_frame_width_ratio"] = round(model_w / frame_w, 4) if frame_w else None
        diagnostics["model_to_frame_height_ratio"] = round(model_h / frame_h, 4) if frame_h else None
        diagnostics["model_to_frame_area_ratio"] = round((model_w * model_h) / (frame_w * frame_h), 4) if frame_w and frame_h else None

    return diagnostics


def _presentation_check(evaluation: Evaluation, doc, msp, manifest: dict[str, Any]) -> None:
    """Check presentation without assuming source layer names.

    A generated execution sheet may legitimately retain source geometry that is
    part of the title block. Therefore the check ignores empty layers and source
    layers whose *entire* visible geometry is confined to the lower-right title-
    block zone of the generated frame. It still fails when a source layer leaks
    into the main drawing area. This is intentionally geometric rather than
    dependent on Russian layer names.
    """
    presentation = manifest.get("presentation", {}) or {}
    if not presentation.get("hide_source_layers"):
        return

    generated_layers = {str(v) for v in presentation.get("generated_layers", [])}
    source_layer_count = 0
    visible_source_layers: list[str] = []

    frame_box = _bbox_for_entities([
        e for e in msp
        if str(getattr(e.dxf, "layer", "")) in {"ГОСТ_Рамка", "Исполнительная_Оформление"}
    ])

    title_block_box = None
    if frame_box and frame_box.has_data:
        min_x, min_y = float(frame_box.extmin.x), float(frame_box.extmin.y)
        max_x, max_y = float(frame_box.extmax.x), float(frame_box.extmax.y)
        fw, fh = max_x - min_x, max_y - min_y
        # Lower-right presentation zone: deliberately generous so standard
        # title blocks and their text remain visible without preserving the
        # source drawing in the main sheet area.
        title_block_box = (
            min_x + fw * 0.50,
            min_y,
            max_x,
            min_y + fh * 0.32,
        )

    def is_title_block_geometry(layer_box) -> bool:
        if not layer_box or not layer_box.has_data or not title_block_box:
            return False
        x0, y0, x1, y1 = title_block_box
        return (
            float(layer_box.extmin.x) >= x0
            and float(layer_box.extmax.x) <= x1
            and float(layer_box.extmin.y) >= y0
            and float(layer_box.extmax.y) <= y1
        )

    for layer in doc.layers:
        name = str(layer.dxf.name)
        if name in generated_layers or name.upper() == "DEFPOINTS":
            continue

        entities = [e for e in msp if str(getattr(e.dxf, "layer", "")) == name]
        if not entities:
            continue

        source_layer_count += 1
        try:
            if bool(layer.is_off()):
                continue
        except Exception:
            continue

        layer_box = _bbox_for_entities(entities)
        if is_title_block_geometry(layer_box):
            continue

        visible_source_layers.append(name)

    evaluation.diagnostics["source_layer_count"] = source_layer_count
    evaluation.diagnostics["visible_source_layers"] = sorted(visible_source_layers)
    evaluation.add(
        "PRESENTATION-SOURCE-LAYERS",
        "Исходная геометрия не просачивается в рабочую область исполнительного листа",
        "critical",
        "PASS" if not visible_source_layers else "FAIL",
        ", ".join(sorted(visible_source_layers)) if visible_source_layers else "source drawing hidden; title-block geometry preserved",
    )


def evaluate_dxf(output_path: Path, manifest: dict[str, Any]) -> Evaluation:
    case_id = str(manifest["id"])
    evaluation = Evaluation(case_id)

    if not output_path.exists():
        evaluation.add("EXEC-OUT", "Выходной DXF создан", "critical", "FAIL", str(output_path))
        return evaluation

    try:
        doc = ezdxf.readfile(output_path)
        msp = doc.modelspace()
    except Exception as exc:
        evaluation.add("EXEC-READ", "Выходной DXF читается ezdxf", "critical", "FAIL", repr(exc))
        return evaluation

    counts = _entity_counts(msp)
    texts = _text_values(msp)
    layers = {str(entity.dxf.layer) for entity in msp if hasattr(entity.dxf, "layer")}
    total = sum(counts.values())
    evaluation.diagnostics = _geometry_diagnostics(doc, msp)

    evaluation.add("EXEC-READ", "Выходной DXF читается ezdxf", "critical", "PASS", f"entities={total}")

    checks = manifest.get("checks", {}) or {}
    min_entities = int(checks.get("min_entity_count", 1))
    evaluation.add("DXF-COUNT", f"В результате не менее {min_entities} объектов", "critical", "PASS" if total >= min_entities else "FAIL", f"actual={total}")

    required_types = checks.get("required_entity_types", []) or []
    for entity_type in required_types:
        actual = counts.get(str(entity_type).upper(), 0)
        evaluation.add(f"DXF-TYPE-{entity_type}", f"В результате присутствуют {entity_type}", "critical", "PASS" if actual > 0 else "FAIL", f"count={actual}")

    for layer_name in checks.get("required_output_layers", []) or []:
        present = str(layer_name) in layers
        evaluation.add(f"DXF-LAYER-{layer_name}", f"Присутствует выходной слой {layer_name}", "critical", "PASS" if present else "FAIL", "present" if present else "missing")

    for index, group in enumerate(checks.get("required_output_layer_any", []) or [], start=1):
        options = [str(value) for value in group]
        matching = [name for name in options if name in layers]
        evaluation.add(f"DXF-LAYER-ANY-{index}", "Присутствует хотя бы один слой из группы: " + " / ".join(options), "critical", "PASS" if matching else "FAIL", ", ".join(matching) if matching else "none")

    for prefix in checks.get("required_output_layer_prefixes", []) or []:
        matching = sorted(layer for layer in layers if layer.startswith(str(prefix)))
        evaluation.add(f"DXF-LAYER-PREFIX-{prefix}", f"Присутствуют выходные слои с префиксом {prefix}", "critical", "PASS" if matching else "FAIL", ", ".join(matching) if matching else "none")

    text_min = checks.get("min_text_count")
    if text_min is not None:
        text_min = int(text_min)
        evaluation.add("DXF-TEXT-COUNT", f"В результате не менее {text_min} текстовых объектов", "critical", "PASS" if len(texts) >= text_min else "FAIL", f"actual={len(texts)}")

    for rule in checks.get("text_contains", []) or []:
        needle = str(rule["text"] if isinstance(rule, dict) else rule)
        severity = str(rule.get("severity", "warning")) if isinstance(rule, dict) else "warning"
        found = any(needle.casefold() in value.casefold() for value in texts)
        evaluation.add(f"TEXT-{needle}", f"Текст содержит «{needle}»", severity, "PASS" if found else "FAIL", "found" if found else "missing")

    expected_contract = checks.get("output_contract", {}) or {}
    for layer_name in expected_contract.get("required_layers", []) or []:
        present = str(layer_name) in layers
        evaluation.add(f"CONTRACT-LAYER-{layer_name}", f"Контракт: слой {layer_name}", "critical", "PASS" if present else "FAIL", "present" if present else "missing")

    for key, title, default_options in [
        ("project_dimensions", "Контракт: проектные размеры", ["ГОСТ_Размеры_Проект", "ИС_Размеры_Проект_Факт"]),
        ("actual_dimensions", "Контракт: фактические размеры", ["ГОСТ_Размеры_Факт", "ИС_Размеры_Проект_Факт"]),
        ("frame", "Контракт: рамка/штамп", ["ГОСТ_Рамка", "ИС_Оформление_Штамп"]),
    ]:
        configured = expected_contract.get(key)
        if not configured:
            continue
        options = [configured] if isinstance(configured, str) else list(configured)
        if not options:
            options = default_options
        matching = [str(name) for name in options if str(name) in layers]
        evaluation.add(f"CONTRACT-{key}", title, "critical", "PASS" if matching else "FAIL", ", ".join(matching) if matching else "none")

    _presentation_check(evaluation, doc, msp, manifest)
    return evaluation


def evaluate_manifest(manifest: dict[str, Any], output_path: Path) -> Evaluation:
    return evaluate_dxf(output_path, manifest)


def evaluation_to_dict(evaluation: Evaluation) -> dict[str, Any]:
    return {
        "case_id": evaluation.case_id,
        "passed": evaluation.passed,
        "failed_critical": evaluation.failed_critical,
        "diagnostics": evaluation.diagnostics,
        "checks": [
            {"id": c.check_id, "title": c.title, "severity": c.severity, "status": c.status, "details": c.details}
            for c in evaluation.checks
        ],
    }

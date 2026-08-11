"""Semantic and structural regression checks for generated DXF files.

The evaluator deliberately checks the *output contract* rather than the names of
layers/blocks in the source drawing. Source-side conventions are therefore free
to vary between projects.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ezdxf


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

    evaluation.add("EXEC-READ", "Выходной DXF читается ezdxf", "critical", "PASS", f"entities={total}")

    checks = manifest.get("checks", {}) or {}
    min_entities = int(checks.get("min_entity_count", 1))
    evaluation.add(
        "DXF-COUNT",
        f"В результате не менее {min_entities} объектов",
        "critical",
        "PASS" if total >= min_entities else "FAIL",
        f"actual={total}",
    )

    required_types = checks.get("required_entity_types", []) or []
    for entity_type in required_types:
        actual = counts.get(str(entity_type).upper(), 0)
        evaluation.add(
            f"DXF-TYPE-{entity_type}",
            f"В результате присутствуют {entity_type}",
            "critical",
            "PASS" if actual > 0 else "FAIL",
            f"count={actual}",
        )

    for layer_name in checks.get("required_output_layers", []) or []:
        present = str(layer_name) in layers
        evaluation.add(
            f"DXF-LAYER-{layer_name}",
            f"Присутствует выходной слой {layer_name}",
            "critical",
            "PASS" if present else "FAIL",
            "present" if present else "missing",
        )

    # Each group is an OR: different implemented algorithms use different
    # output-layer naming conventions, while the semantic role is identical.
    for index, group in enumerate(checks.get("required_output_layer_any", []) or [], start=1):
        options = [str(value) for value in group]
        matching = [name for name in options if name in layers]
        evaluation.add(
            f"DXF-LAYER-ANY-{index}",
            "Присутствует хотя бы один слой из группы: " + " / ".join(options),
            "critical",
            "PASS" if matching else "FAIL",
            ", ".join(matching) if matching else "none",
        )

    for prefix in checks.get("required_output_layer_prefixes", []) or []:
        matching = sorted(layer for layer in layers if layer.startswith(str(prefix)))
        evaluation.add(
            f"DXF-LAYER-PREFIX-{prefix}",
            f"Присутствуют выходные слои с префиксом {prefix}",
            "critical",
            "PASS" if matching else "FAIL",
            ", ".join(matching) if matching else "none",
        )

    text_min = checks.get("min_text_count")
    if text_min is not None:
        text_min = int(text_min)
        evaluation.add(
            "DXF-TEXT-COUNT",
            f"В результате не менее {text_min} текстовых объектов",
            "critical",
            "PASS" if len(texts) >= text_min else "FAIL",
            f"actual={len(texts)}",
        )

    for rule in checks.get("text_contains", []) or []:
        needle = str(rule["text"] if isinstance(rule, dict) else rule)
        severity = str(rule.get("severity", "warning")) if isinstance(rule, dict) else "warning"
        found = any(needle.casefold() in value.casefold() for value in texts)
        evaluation.add(
            f"TEXT-{needle}",
            f"Текст содержит «{needle}»",
            severity,
            "PASS" if found else "FAIL",
            "found" if found else "missing",
        )

    expected_contract = checks.get("output_contract", {}) or {}
    for layer_name in expected_contract.get("required_layers", []) or []:
        present = str(layer_name) in layers
        evaluation.add(
            f"CONTRACT-LAYER-{layer_name}",
            f"Контракт: слой {layer_name}",
            "critical",
            "PASS" if present else "FAIL",
            "present" if present else "missing",
        )

    # Semantic roles can point either to one exact output layer or to a list of
    # acceptable layer names. This keeps the contract independent of the source
    # drawing while allowing the four current algorithms to evolve separately.
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
        evaluation.add(
            f"CONTRACT-{key}",
            title,
            "critical",
            "PASS" if matching else "FAIL",
            ", ".join(matching) if matching else "none",
        )

    return evaluation


def evaluate_manifest(manifest: dict[str, Any], output_path: Path) -> Evaluation:
    return evaluate_dxf(output_path, manifest)


def evaluation_to_dict(evaluation: Evaluation) -> dict[str, Any]:
    return {
        "case_id": evaluation.case_id,
        "passed": evaluation.passed,
        "failed_critical": evaluation.failed_critical,
        "checks": [
            {
                "id": c.check_id,
                "title": c.title,
                "severity": c.severity,
                "status": c.status,
                "details": c.details,
            }
            for c in evaluation.checks
        ],
    }

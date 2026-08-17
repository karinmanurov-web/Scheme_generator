"""Semantic sheet contract for the pile execution scheme.

The contract is intentionally presentation-oriented: it describes what each
reference sheet is supposed to contain without depending on source DXF layer or
block names. Generated semantic layers are used only as evidence when building
the current diagnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SheetRequirement:
    id: str
    title: str
    required_roles: tuple[str, ...]


SHEET_REQUIREMENTS = (
    SheetRequirement(
        "sheet_01",
        "Схема свай и исполнительных отклонений",
        ("pile_plan", "pile_ids", "pile_deviations", "project_dimensions", "actual_dimensions"),
    ),
    SheetRequirement(
        "sheet_02",
        "Исполнительные данные и координаты свай",
        ("coordinate_register",),
    ),
    SheetRequirement(
        "sheet_03",
        "Ростверк, опорные оси и сечения",
        ("grillage", "support_axes", "sections", "project_dimensions", "actual_dimensions"),
    ),
)


ROLE_LAYERS = {
    "pile_plan": ("Сваи_Проект", "Оси_Проект"),
    "pile_ids": ("Исполнительная_Номера",),
    "pile_deviations": ("Исполнительная_Отклонения",),
    "project_dimensions": ("ИСП_Размеры_Проект",),
    "actual_dimensions": ("ИСП_Размеры_Факт",),
    "coordinate_register": ("ИСП_Таблица", "ИСП_Текст"),
    "grillage": ("Исполнительная_Ростверк",),
    "support_axes": ("Исполнительная_Оси_Опор",),
    # Sections are deliberately a semantic role, not a layer-name rule. The
    # current generator does not emit them yet; this makes the gap explicit.
    "sections": (),
}


def _present_layers(doc) -> set[str]:
    return {
        str(getattr(entity.dxf, "layer", ""))
        for entity in doc.modelspace()
        if getattr(entity.dxf, "layer", None)
    }


def build_sheet_plan(doc) -> dict:
    """Return an observational sheet plan for the current generated DXF."""
    layers = _present_layers(doc)
    sheets = []
    for spec in SHEET_REQUIREMENTS:
        roles = []
        missing = []
        for role in spec.required_roles:
            evidence = [layer for layer in ROLE_LAYERS[role] if layer in layers]
            item = {"role": role, "evidence_layers": evidence, "available": bool(evidence)}
            roles.append(item)
            if not evidence:
                missing.append(role)
        sheets.append({
            "id": spec.id,
            "title": spec.title,
            "roles": roles,
            "ready": not missing,
            "missing_roles": missing,
        })
    return {
        "schema_version": 1,
        "mode": "diagnostic_only",
        "sheet_count": len(SHEET_REQUIREMENTS),
        "sheets": sheets,
    }


def required_sheet_ids() -> Iterable[str]:
    return tuple(spec.id for spec in SHEET_REQUIREMENTS)

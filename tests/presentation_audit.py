"""Universal geometry checks for generated presentation sheets.

The audit is intentionally independent of source DXF layer names. A generated
sheet has a frame, while visible drawing content must fit inside it.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import bbox as ezdxf_bbox

FRAME_LAYER = "ГОСТ_Рамка"
EXCLUDED_PREFIXES = ("ГОСТ_Рамка", "ГОСТ_Штамп", "ГОСТ_Таблица_")
EXCLUDED_EXACT = {"Исполнительная_Оформление"}


def _bbox(entities):
    try:
        box = ezdxf_bbox.extents(entities)
        return box if box.has_data else None
    except Exception:
        return None


def _as_dict(box) -> dict[str, float] | None:
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


def audit_presentation(output_path: Path) -> dict[str, Any]:
    """Audit whether visible generated content is contained by the frame."""
    doc = ezdxf.readfile(output_path)
    msp = doc.modelspace()

    frame = _bbox([e for e in msp if str(getattr(e.dxf, "layer", "")) == FRAME_LAYER])
    content_entities = []
    for entity in msp:
        layer = str(getattr(entity.dxf, "layer", ""))
        if layer in EXCLUDED_EXACT or any(layer.startswith(p) for p in EXCLUDED_PREFIXES):
            continue
        content_entities.append(entity)
    content = _bbox(content_entities)

    result: dict[str, Any] = {
        "passed": False,
        "frame_bbox": _as_dict(frame),
        "content_bbox": _as_dict(content),
    }
    if not frame or not content:
        result["reason"] = "frame or visible content is missing"
        return result

    fx0, fy0 = float(frame.extmin.x), float(frame.extmin.y)
    fx1, fy1 = float(frame.extmax.x), float(frame.extmax.y)
    cx0, cy0 = float(content.extmin.x), float(content.extmin.y)
    cx1, cy1 = float(content.extmax.x), float(content.extmax.y)
    tolerance = max(fx1 - fx0, fy1 - fy0) * 0.01

    violations = []
    if cx0 < fx0 - tolerance:
        violations.append("left")
    if cy0 < fy0 - tolerance:
        violations.append("bottom")
    if cx1 > fx1 + tolerance:
        violations.append("right")
    if cy1 > fy1 + tolerance:
        violations.append("top")

    result["passed"] = not violations
    result["violations"] = violations
    result["tolerance"] = round(tolerance, 3)
    result["content_to_frame_width_ratio"] = round((cx1 - cx0) / (fx1 - fx0), 4) if fx1 != fx0 else None
    result["content_to_frame_height_ratio"] = round((cy1 - cy0) / (fy1 - fy0), 4) if fy1 != fy0 else None
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit generated DXF content against its GOST frame")
    parser.add_argument("paths", nargs="*", type=Path, help="Generated DXF files to audit")
    args = parser.parse_args()

    paths = args.paths or sorted(Path("reports").glob("*/result.dxf"))
    if not paths:
        print("No generated DXF files found")
        return 1

    failed = False
    for path in paths:
        try:
            result = audit_presentation(path)
        except Exception as exc:
            print(f"FAIL {path}: {exc!r}")
            failed = True
            continue
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} {path}: violations={result.get('violations', [])} content={result.get('content_bbox')} frame={result.get('frame_bbox')}")
        failed = failed or not result["passed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

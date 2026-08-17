"""Headless presentation safety checks for generated sheets.

The audit is deliberately geometry-based: it does not know source layer names.
It verifies that visible generated content stays inside the generated outer
frame. A drawing outside the frame is a hard failure even when structural
regression checks pass.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
FRAME_LAYERS = {"ГОСТ_Рамка", "ГОСТ_Штамп_Линии", "ГОСТ_Штамп_Текст", "ГОСТ_Таблица_Текст"}


def _bbox(entities):
    try:
        box = ezdxf_bbox.extents(entities)
        return box if box.has_data else None
    except Exception:
        return None


def _inside(content, frame, tolerance_ratio: float = 0.01) -> bool:
    fw = frame.extmax.x - frame.extmin.x
    fh = frame.extmax.y - frame.extmin.y
    tx = max(10.0, abs(fw) * tolerance_ratio)
    ty = max(10.0, abs(fh) * tolerance_ratio)
    return (
        content.extmin.x >= frame.extmin.x - tx
        and content.extmax.x <= frame.extmax.x + tx
        and content.extmin.y >= frame.extmin.y - ty
        and content.extmax.y <= frame.extmax.y + ty
    )


def audit_case(path: Path) -> bool:
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    frame = _bbox([e for e in msp if getattr(e.dxf, "layer", "") == "ГОСТ_Рамка"])
    if frame is None:
        print(f"FAIL {path.parent.name}: ГОСТ_Рамка missing")
        return False

    visible = []
    for entity in msp:
        layer = getattr(entity.dxf, "layer", "")
        if layer in FRAME_LAYERS:
            continue
        try:
            if doc.layers.get(layer).is_off():
                continue
        except Exception:
            pass
        visible.append(entity)

    content = _bbox(visible)
    if content is None:
        print(f"FAIL {path.parent.name}: no visible content")
        return False

    ok = _inside(content, frame)
    status = "PASS" if ok else "FAIL"
    print(
        f"{status} {path.parent.name}: "
        f"content={content.extmax.x-content.extmin.x:.1f}x{content.extmax.y-content.extmin.y:.1f}; "
        f"frame={frame.extmax.x-frame.extmin.x:.1f}x{frame.extmax.y-frame.extmin.y:.1f}"
    )
    if not ok:
        print(
            f"     content bbox=({content.extmin.x:.1f},{content.extmin.y:.1f}).."
            f"({content.extmax.x:.1f},{content.extmax.y:.1f})"
        )
        print(
            f"     frame   bbox=({frame.extmin.x:.1f},{frame.extmin.y:.1f}).."
            f"({frame.extmax.x:.1f},{frame.extmax.y:.1f})"
        )
    return ok


def main() -> int:
    paths = sorted(REPORTS.glob("*/result.dxf"))
    if not paths:
        print("FAIL: no regression result DXFs found")
        return 1
    return 0 if all(audit_case(path) for path in paths) else 1


if __name__ == "__main__":
    raise SystemExit(main())

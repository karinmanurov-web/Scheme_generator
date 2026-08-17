from pathlib import Path

import ezdxf

from presentation_audit import audit_presentation


def _make_sheet(path: Path, outside: bool) -> None:
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (420, 0), (420, 297), (0, 297)], close=True, dxfattribs={"layer": "ГОСТ_Рамка"})
    if outside:
        msp.add_line((-10, 50), (100, 50), dxfattribs={"layer": "Исполнительная_Геометрия"})
    else:
        msp.add_line((20, 50), (100, 50), dxfattribs={"layer": "Исполнительная_Геометрия"})
    doc.saveas(path)


def test_presentation_audit_accepts_content_inside_frame(tmp_path):
    path = tmp_path / "inside.dxf"
    _make_sheet(path, outside=False)
    result = audit_presentation(path)
    assert result["passed"]
    assert result["violations"] == []


def test_presentation_audit_rejects_content_outside_frame(tmp_path):
    path = tmp_path / "outside.dxf"
    _make_sheet(path, outside=True)
    result = audit_presentation(path)
    assert not result["passed"]
    assert "left" in result["violations"]

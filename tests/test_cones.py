from pathlib import Path

import ezdxf

from algo_cones import detect_cones, generate_table_data, process_dxf_to_asbuilt_scheme, run


def _make_fixture(path: Path) -> None:
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_circle((1000, 1000), 250)
    msp.add_circle((2500, 1200), 300)
    msp.add_lwpolyline(
        [(4000, 1000), (4300, 1000), (4300, 1300), (4000, 1300)],
        close=True,
    )
    doc.saveas(path)


def test_cones_exposes_standard_plugin_entry_point():
    assert callable(run)


def test_detect_cones_is_geometry_based(tmp_path: Path):
    src = tmp_path / "input.dxf"
    _make_fixture(src)

    doc = ezdxf.readfile(src)
    cones = detect_cones(doc.modelspace())

    assert len(cones) == 3
    assert cones[0]["center"] == (1000.0, 1000.0)
    assert cones[1]["center"] == (2500.0, 1200.0)


def test_cone_algorithm_generates_nonempty_dxf_and_table(tmp_path: Path):
    src = tmp_path / "input.dxf"
    out = tmp_path / "result.dxf"
    csv = tmp_path / "result.csv"
    _make_fixture(src)

    process_dxf_to_asbuilt_scheme(str(src), str(out), str(csv))

    assert out.exists()
    assert csv.exists()

    result = ezdxf.readfile(out)
    msp = result.modelspace()
    assert len(msp) > 0
    assert "ИСП_Конусы" in result.layers
    assert "ГОСТ_Рамка" in result.layers

    rows = generate_table_data(str(src))
    assert len(rows) == 3
    assert rows[0]["№"] == 1

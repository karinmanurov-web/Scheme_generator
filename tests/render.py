"""Headless render helpers for regression reports.

DXF is rendered with ezdxf's Matplotlib backend. PDF pages are rendered with
PyMuPDF. AutoCAD is never required by the regression loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def render_dxf_to_png(dxf_path: Path, png_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    png_path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(16, 10), dpi=140)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_axis_off()

    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend).draw_layout(msp, finalize=True)
    fig.savefig(png_path, dpi=140, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def render_pdf_to_pngs(pdf_path: Path, output_dir: Path, dpi: int = 120) -> list[Path]:
    import fitz

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    doc = fitz.open(pdf_path)
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    for index, page in enumerate(doc, start=1):
        target = output_dir / f"page_{index:02d}.png"
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(target)
        rendered.append(target)
    doc.close()
    return rendered


def render_reference_if_available(pdf_path: Path, output_dir: Path) -> list[Path]:
    if not pdf_path.exists():
        return []
    try:
        return render_pdf_to_pngs(pdf_path, output_dir)
    except ImportError:
        return []

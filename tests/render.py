"""Headless render helpers for regression reports.

The preview is intentionally rendered for *inspection*, not as a DXF plotter:
- white background;
- ACI 7 (AutoCAD black/white) is shown as black;
- explicit red/other colors stay colored;
- the original DXF is never modified or saved by the renderer.

AutoCAD is never required by the regression loop.
"""

from __future__ import annotations

from pathlib import Path


def _prepare_preview_colors(doc) -> None:
    """Make AutoCAD ACI-7 geometry visible on a white preview background.

    In AutoCAD ACI 7 is the context-dependent black/white color. On a dark
    AutoCAD canvas it appears white, while ezdxf's Matplotlib renderer resolves
    it to white as well. That made the old regression PNG hide the most
    important geometry when the background was changed to white.

    For rendering only, layers using ACI 7 get an explicit black true-color.
    Red ACI 1 and all other colors are left untouched. The loaded document is
    never written back to disk.
    """
    for layer in doc.layers:
        try:
            if int(layer.dxf.color) == 7 and not layer.dxf.hasattr("true_color"):
                layer.dxf.true_color = 0x000000
        except Exception:
            continue


def render_dxf_to_png(dxf_path: Path, png_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.properties import LayoutProperties

    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    _prepare_preview_colors(doc)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    # Do not use bbox_inches="tight": for engineering drawings it can produce
    # misleading crops when modelspace contains distant construction entities.
    # A fixed canvas gives us a stable preview and makes such extent problems
    # visible instead of hiding them.
    fig = plt.figure(figsize=(16, 10), dpi=140, facecolor="white")
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96], facecolor="white")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_axis_off()

    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    config = Configuration(
        color_policy=ColorPolicy.COLOR,
        background_policy=BackgroundPolicy.WHITE,
        lineweight_scaling=0.8,
    )
    layout_properties = LayoutProperties(
        msp.name,
        background_color="#ffffff",
        foreground_color="#000000",
        dark_background=False,
    )

    Frontend(ctx, backend, config).draw_layout(
        msp,
        finalize=True,
        layout_properties=layout_properties,
    )

    fig.savefig(png_path, dpi=140, facecolor="white")
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

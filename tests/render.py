"""Headless render helpers for regression reports.

The preview is for inspection, not as a DXF plotter:
- white background;
- AutoCAD ACI 7 is rendered as black on white;
- explicit red/other colors stay colored;
- the original DXF is never modified or saved by the renderer.

AutoCAD is never required by the regression loop.
"""

from __future__ import annotations

from pathlib import Path


def _prepare_preview_colors(doc) -> None:
    """Make AutoCAD ACI-7 geometry visible on a white preview background."""
    for layer in doc.layers:
        try:
            if int(layer.dxf.color) == 7 and not layer.dxf.hasattr("true_color"):
                layer.dxf.true_color = 0x000000
        except Exception:
            continue


def _layer_bbox(doc, layer_names: set[str]):
    from ezdxf import bbox as ezdxf_bbox

    entities = [e for e in doc.modelspace() if str(getattr(e.dxf, "layer", "")) in layer_names]
    if not entities:
        return None
    try:
        box = ezdxf_bbox.extents(entities)
        return box if box.has_data else None
    except Exception:
        return None


def _bbox_tuple(box):
    if box is None or not box.has_data:
        return None
    return (float(box.extmin.x), float(box.extmin.y), float(box.extmax.x), float(box.extmax.y))


def render_dxf_to_png(dxf_path: Path, png_path: Path, focus: bool = False) -> None:
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

    # A full preview deliberately shows the complete modelspace. A focused
    # preview is additionally produced for AI/visual inspection and uses the
    # generated sheet frame when one exists. This keeps distant source geometry
    # from making a perfectly valid sheet microscopic while still preserving the
    # full preview for diagnosing bad extents.
    if focus:
        frame_box = _layer_bbox(doc, {"ГОСТ_Рамка", "Исполнительная_Оформление"})
        if frame_box is not None:
            x0, y0, x1, y1 = _bbox_tuple(frame_box)
            w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
            margin = max(w, h) * 0.04
            ax.set_xlim(x0 - margin, x1 + margin)
            ax.set_ylim(y0 - margin, y1 + margin)

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

"""Run the four implemented scheme algorithms without AutoCAD.

Usage:
    python tests/run_regression.py
    python tests/run_regression.py --case piles
    python tests/run_regression.py --no-render

The runner creates only generated artifacts under reports/ (gitignored).
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import time
from html import escape
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - user-facing dependency error
    raise SystemExit("PyYAML is required: pip install -r tests/requirements.txt") from exc

from evaluator import evaluate_manifest, evaluation_to_dict
from render import render_dxf_to_png, render_reference_if_available

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
REPORTS = ROOT / "reports"


def decode_github_unicode_path(value: str) -> str:
    """Decode #U0410-style paths created by older manifest tooling."""
    pattern = re.compile(r"#U([0-9A-Fa-f]{4})")
    return pattern.sub(lambda m: chr(int(m.group(1), 16)), value)


def resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    decoded = decode_github_unicode_path(value)
    return ROOT / Path(decoded)


def fallback_fixture_file(manifest_path: Path, suffix: str, search_dir: Path | None = None) -> Path | None:
    """Find a unique fixture file when a manifest path is stale or names changed."""
    candidates: list[Path] = []
    if search_dir and search_dir.exists():
        candidates.extend(sorted(search_dir.glob(f"*{suffix}")))
    candidates.extend(sorted(manifest_path.parent.glob(f"*{suffix}")))
    unique = list(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else None


def load_manifests(case_filter: str | None) -> list[tuple[Path, dict[str, Any]]]:
    manifests = sorted(FIXTURES.glob("*/manifest.yaml"))
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in manifests:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if case_filter and str(data.get("id")) != case_filter:
            continue
        result.append((path, data))
    return result


def import_algorithm(module_name: str):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module(module_name)


def run_algorithm(manifest: dict[str, Any], source: Path, output: Path) -> tuple[bool, float, str]:
    algorithm = manifest.get("algorithm", {}) or {}
    module_name = str(algorithm["module"])
    function_name = str(algorithm.get("function", "run"))
    try:
        module = import_algorithm(module_name)
        function = getattr(module, function_name)
    except Exception as exc:
        return False, 0.0, repr(exc)

    started = time.perf_counter()
    try:
        function(str(source), str(output))
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return False, elapsed, repr(exc)
    elapsed = time.perf_counter() - started
    return output.exists(), elapsed, ""


def reference_page_count(pdf_path: Path) -> int | None:
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(pdf_path)
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return None


def evaluate_case(manifest_path: Path, manifest: dict[str, Any], render: bool) -> dict[str, Any]:
    case_id = str(manifest["id"])
    case_report = REPORTS / case_id
    case_report.mkdir(parents=True, exist_ok=True)

    source = resolve_path(str(manifest.get("source", "")))
    if not source or not source.exists():
        source = fallback_fixture_file(manifest_path, ".dxf")

    reference_path = resolve_path(str((manifest.get("reference") or {}).get("file", "")))
    source_dir = source.parent if source and source.exists() else None
    if not reference_path or not reference_path.exists():
        reference_path = fallback_fixture_file(manifest_path, ".pdf", search_dir=source_dir)

    output = case_report / "result.dxf"

    result: dict[str, Any] = {
        "case_id": case_id,
        "name": manifest.get("name", case_id),
        "manifest": str(manifest_path.relative_to(ROOT)),
        "source": str(source.relative_to(ROOT)) if source and source.exists() else str(source),
        "reference_file": str(reference_path.relative_to(ROOT)) if reference_path and reference_path.exists() else str(reference_path),
        "output": str(output.relative_to(ROOT)),
        "execution": {},
        "evaluation": None,
        "reference": {},
        "manual_checks": manifest.get("manual_checks", []) or [],
        "render": {},
    }

    if not source or not source.exists():
        result["execution"] = {"passed": False, "error": f"Source DXF not found: {source}"}
        return result

    if reference_path and reference_path.exists():
        expected_pages = int((manifest.get("reference") or {}).get("pages", 0) or 0)
        actual_pages = reference_page_count(reference_path)
        result["reference"] = {"expected_pages": expected_pages, "actual_pages": actual_pages}
        if expected_pages and actual_pages is not None and expected_pages != actual_pages:
            result["reference"]["warning"] = "PDF page count differs from manifest"
    else:
        result["reference"] = {"warning": f"Reference PDF not found: {reference_path}"}

    ok, elapsed, error = run_algorithm(manifest, source, output)
    result["execution"] = {"passed": ok, "seconds": round(elapsed, 3), "error": error}

    evaluation = evaluate_manifest(manifest, output)
    result["evaluation"] = evaluation_to_dict(evaluation)

    if render and output.exists():
        result_png = case_report / "result_full.png"
        focus_png = case_report / "result_focus.png"
        try:
            render_dxf_to_png(output, result_png, focus=False)
            result["render"]["result_full_png"] = str(result_png.relative_to(ROOT))
            render_dxf_to_png(output, focus_png, focus=True)
            result["render"]["result_focus_png"] = str(focus_png.relative_to(ROOT))
        except Exception as exc:
            result["render"]["result_error"] = repr(exc)

        if reference_path and reference_path.exists():
            ref_dir = case_report / "reference"
            try:
                paths = render_reference_if_available(reference_path, ref_dir)
                result["render"]["reference_pngs"] = [str(p.relative_to(ROOT)) for p in paths]
            except Exception as exc:
                result["render"]["reference_error"] = repr(exc)

    return result


def write_json(results: list[dict[str, Any]]) -> Path:
    target = REPORTS / "report.json"
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def html_report(results: list[dict[str, Any]]) -> Path:
    rows: list[str] = []
    for item in results:
        evaluation = item.get("evaluation") or {}
        status = "PASS" if item.get("execution", {}).get("passed") and evaluation.get("passed") else "FAIL"
        css = "pass" if status == "PASS" else "fail"
        checks = evaluation.get("checks", [])
        check_html = "".join(
            f"<tr><td>{escape(str(c['id']))}</td><td>{escape(str(c['title']))}</td>"
            f"<td>{escape(str(c['severity']))}</td><td>{escape(str(c['status']))}</td>"
            f"<td>{escape(str(c.get('details', '')))}</td></tr>"
            for c in checks
        )
        manual_html = "".join(
            f"<li><b>{escape(str(c.get('severity', 'warning')))}</b>: {escape(str(c.get('title', '')))}</li>"
            for c in item.get("manual_checks", [])
        )
        diagnostics = evaluation.get("diagnostics", {})
        diagnostic_html = "".join(
            f"<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>"
            for k, v in diagnostics.items()
        )
        render_data = item.get("render", {})
        full_img = render_data.get("result_full_png")
        focus_img = render_data.get("result_focus_png")
        ref_imgs = render_data.get("reference_pngs", [])
        visuals = ""
        if full_img:
            visuals += f'<div class="image"><h4>Generated — full modelspace</h4><img src="{escape(full_img)}"></div>'
        if focus_img:
            visuals += f'<div class="image"><h4>Generated — focused sheet</h4><img src="{escape(focus_img)}"></div>'
        for ref in ref_imgs:
            visuals += f'<div class="image"><h4>{escape(Path(ref).name)}</h4><img src="{escape(ref)}"></div>'

        rows.append(
            f"<section><h2>{escape(str(item['name']))} <span class='{css}'>{status}</span></h2>"
            f"<p>Execution: {escape(str(item.get('execution', {}).get('seconds', '—')))} s</p>"
            f"<p>Source: <code>{escape(str(item.get('source', '')))}</code><br>Reference: <code>{escape(str(item.get('reference_file', '')))}</code></p>"
            f"<h3>Geometry diagnostics</h3><table><tr><th>Metric</th><th>Value</th></tr>{diagnostic_html}</table>"
            f"<h3>Automated checks</h3><table><tr><th>ID</th><th>Check</th><th>Severity</th><th>Status</th><th>Details</th></tr>{check_html}</table>"
            f"<h3>Manual checks still to automate</h3><ul>{manual_html}</ul>"
            f"<div class='gallery'>{visuals}</div></section>"
        )

    html = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Scheme Generator regression report</title>
<style>
body{font-family:Arial,sans-serif;max-width:1800px;margin:30px auto;padding:0 20px;background:#f5f5f5;color:#222}
section{background:white;padding:20px;margin:20px 0;border-radius:10px;box-shadow:0 1px 5px #ccc}
h2{margin-top:0}.pass,.fail{padding:4px 8px;border-radius:5px;font-size:12px}.pass{background:#d7f5dc;color:#176b2c}.fail{background:#ffd9d9;color:#9a1d1d}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #ddd;padding:6px;text-align:left;vertical-align:top}th{background:#eee}
.gallery{display:flex;flex-wrap:wrap;gap:12px;margin-top:18px}.image{max-width:48%}.image img{max-width:100%;max-height:700px;border:1px solid #ccc}
code{font-size:12px}
</style></head><body>
<h1>Scheme Generator — regression report</h1>
<p>Generated headlessly. AutoCAD is not used. Full and focused previews are shown separately so distant source geometry can be diagnosed without hiding the sheet.</p>
""" + "\n".join(rows) + "\n</body></html>"
    target = REPORTS / "report.html"
    target.write_text(html, encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", help="Run only one case id")
    parser.add_argument("--no-render", action="store_true", help="Skip PNG rendering")
    args = parser.parse_args()

    manifests = load_manifests(args.case)
    if not manifests:
        raise SystemExit("No matching manifests found")

    REPORTS.mkdir(parents=True, exist_ok=True)
    results = [evaluate_case(path, manifest, render=not args.no_render) for path, manifest in manifests]
    json_path = write_json(results)
    html_path = html_report(results)

    print(f"Report: {html_path}")
    print(f"JSON:   {json_path}")
    failed = False
    for item in results:
        evaluation = item.get("evaluation") or {}
        ok = bool(item.get("execution", {}).get("passed")) and bool(evaluation.get("passed"))
        status = "PASS" if ok else "FAIL"
        print(f"{status:4} {item['case_id']:<12} {item.get('execution', {}).get('seconds', '—')} s")
        diagnostics = evaluation.get("diagnostics", {})
        if diagnostics:
            print(f"     bbox={diagnostics.get('modelspace_bbox')} frame={diagnostics.get('frame_bbox')} ratio={diagnostics.get('model_to_frame_area_ratio')}")
        failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

# Scheme Generator — agent instructions

## Goal
Generate universal as-built construction schemes from arbitrary project DXF inputs. Do not hard-code source layer names, block names, or the presence of a particular source entity. Infer geometry and presentation from content and measured extents.

## Non-negotiable visual requirements
- Never carry source title blocks, frames, hatches, hidden helpers, or unrelated source geometry into a generated sheet unless explicitly required by the algorithm.
- No drawing/table/note/stamp overlaps.
- Do not accept large unexplained empty sheet areas when content can be enlarged or repositioned safely.
- Preserve randomized actual deviations; they are intentional and must not be replaced by fixed values.
- Generated output must be inspected as PNG in the headless regression workflow, not only judged by a green unit-test result.

## Workflow
1. Read the relevant fixture manifest and reference PDF metadata.
2. Run the focused regression case before changing code.
3. Make changes on a dedicated branch.
4. Run the focused case and render both full and focused PNG previews.
5. Compare generated PNGs against the reference pages and record concrete visual deltas.
6. Run the full four-case regression before opening a PR.

## Architecture
- Algorithm modules decide WHAT to draw.
- Shared layout/composer code decides WHERE semantic items go and how they are scaled.
- Presentation code must be geometry/semantics driven, not source-layer-name driven.

## Review rule
A passing CI check is necessary but not sufficient. A visual regression is not fixed until the generated preview demonstrates the intended change.

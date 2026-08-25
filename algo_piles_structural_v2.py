"""Second structural pass for pile sheets.

Uses the existing structural post-processor but refines axis inference at wing
junctions and removes generated pile-number labels, which are not part of the
reference execution-sheet presentation.
"""

from __future__ import annotations

import algo_piles_structural as _base
from pile_axis_refinement import infer_pile_axis as _refined_infer_pile_axis

# _orient_piles in the base module resolves infer_pile_axis from its own module
# globals, so replace that dependency without duplicating the whole pipeline.
_base.infer_pile_axis = _refined_infer_pile_axis

ALGORITHM_NAME = _base.ALGORITHM_NAME
PREVIEW_IMAGE = _base.PREVIEW_IMAGE
generate_table_data = _base.generate_table_data
process_dxf_to_asbuilt_scheme = _base.process_dxf_to_asbuilt_scheme


def run(input_dxf, output_dxf, output_csv=None, log_callback=None, stamp_data=None, table_data=None):
    result = _base.run(input_dxf, output_dxf, output_csv, log_callback=log_callback,
                       stamp_data=stamp_data, table_data=table_data)

    # Generated pile numbers are not present in the reference presentation and
    # add noise/overlaps. Remove only this generator-owned layer; random
    # deviations and all geometric pile data remain untouched.
    try:
        import ezdxf
        doc = ezdxf.readfile(output_dxf)
        removed = 0
        for entity in list(doc.modelspace()):
            try:
                if entity.dxf.layer == "Исполнительная_Номера":
                    doc.modelspace().delete_entity(entity)
                    removed += 1
            except Exception:
                continue
        doc.saveas(output_dxf)
        if log_callback:
            log_callback(f"[INFO] Удалены только сгенерированные номера свай: {removed} объектов.")
    except Exception as exc:
        if log_callback:
            log_callback(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось удалить номера свай: {exc}")

    return result

"""Temporary branch-only guarded patch applicator for F.22.

This file is removed by the workflow after the patch passes focused tests.
It refuses to modify the extractor unless every expected source fragment is
present exactly once, preventing an accidental broad rewrite of the large file.
"""
from pathlib import Path


path = Path("pb_planreader_pdf_extractor.py")
text = path.read_text(encoding="utf-8")

old = '''                footprint_res = builder.build()
                total_floor_screed = footprint_res.gross_floor_area_m2
                perimeter_m = round(2 * (length_m + width_m), 2)
'''
new = '''                footprint_res = builder.build()
                structural_bed_area_m2 = footprint_res.gross_floor_area_m2
                total_floor_screed = structural_bed_area_m2

                # F.22: an enclosed main room's floor finish is measured to
                # the clear wall faces when wall thickness is independently
                # corroborated. Evidenced open verandahs remain at their full
                # component area. Unsupported/partial compound geometry fails
                # closed in the helper and leaves the existing footprint basis
                # unchanged. Structural slab/DPM/mesh area is preserved
                # separately below.
                floor_finish_geometry = None
                if global_resolved_wall_thickness_m is not None:
                    from pb_component_floor_finish_geometry import (
                        derive_component_aware_floor_finish_area,
                    )

                    floor_finish_geometry = derive_component_aware_floor_finish_area(
                        footprint_res,
                        global_resolved_wall_thickness_m,
                    )
                    if floor_finish_geometry is not None:
                        total_floor_screed = floor_finish_geometry.floor_finish_area_m2

                perimeter_m = round(2 * (length_m + width_m), 2)
'''
if text.count(old) != 1:
    raise SystemExit(f"F22 patch point 1 count={text.count(old)}; refusing unsafe edit")
text = text.replace(old, new, 1)

old = '''                    else:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope)"

                    # External wall area: derived deterministically from perimeter * height.
'''
new = '''                    else:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope)"

                    if floor_finish_geometry is not None:
                        desc_flr = (
                            "Floor screed / finish ("
                            f"{floor_finish_geometry.main_clear_area_m2} m2 clear enclosed main space"
                            f" + {floor_finish_geometry.open_verandah_area_m2} m2 evidenced verandah)"
                        )

                    # External wall area: derived deterministically from perimeter * height.
'''
if text.count(old) != 1:
    raise SystemExit(f"F22 patch point 2 count={text.count(old)}; refusing unsafe edit")
text = text.replace(old, new, 1)

old = '''                            "footprint_status": footprint_res.status,
                            "missing_components": footprint_res.missing_components,
'''
new = '''                            "footprint_status": footprint_res.status,
                            "missing_components": footprint_res.missing_components,
                            "structural_bed_area_m2": structural_bed_area_m2,
                            **(
                                {
                                    "floor_finish_area_derivation": "component_clear_main_plus_evidenced_verandah",
                                    "wall_thickness_m": floor_finish_geometry.wall_thickness_m,
                                    "main_clear_floor_area_m2": floor_finish_geometry.main_clear_area_m2,
                                    "open_verandah_floor_area_m2": floor_finish_geometry.open_verandah_area_m2,
                                    "component_finish_areas_m2": floor_finish_geometry.component_finish_areas_m2,
                                    "main_clear_dimensions_m": [
                                        floor_finish_geometry.main_clear_length_m,
                                        floor_finish_geometry.main_clear_width_m,
                                    ],
                                }
                                if floor_finish_geometry is not None
                                else {}
                            ),
'''
if text.count(old) != 1:
    raise SystemExit(f"F22 patch point 3 count={text.count(old)}; refusing unsafe edit")
text = text.replace(old, new, 1)

old = '''                tot_flr = pred_dict["floor_screed"].quantity
                flr_meta = pred_dict["floor_screed"].metadata or {}
'''
new = '''                tot_flr = pred_dict["floor_screed"].quantity
                flr_meta = pred_dict["floor_screed"].metadata or {}
                bed_area_for_substructure_m2 = float(
                    flr_meta.get(
                        "structural_bed_area_m2",
                        flr_meta.get("gross_floor_area_m2", tot_flr),
                    )
                )
'''
if text.count(old) != 1:
    raise SystemExit(f"F22 patch point 4 count={text.count(old)}; refusing unsafe edit")
text = text.replace(old, new, 1)

if text.count("and tot_flr > 0") != 3:
    raise SystemExit(
        f"Expected 3 substructure quantity guards, found {text.count('and tot_flr > 0')}"
    )
text = text.replace("and tot_flr > 0", "and bed_area_for_substructure_m2 > 0")

if text.count("quantity=tot_flr") != 3:
    raise SystemExit(
        f"Expected 3 substructure quantity assignments, found {text.count('quantity=tot_flr')}"
    )
text = text.replace("quantity=tot_flr", "quantity=bed_area_for_substructure_m2")

if text.count("({tot_flr} m2)") != 3:
    raise SystemExit(
        f"Expected 3 substructure descriptions, found {text.count('({tot_flr} m2)')}"
    )
text = text.replace("({tot_flr} m2)", "({bed_area_for_substructure_m2} m2)")

path.write_text(text, encoding="utf-8")
print("F22 extractor patch applied with all guarded source checks satisfied")

"""Temporary F26 branch patcher.

Applies only the generic explicit drawing FLOOR AREA wiring to the extractor.
Every replacement is assertion-guarded so source drift fails closed rather
than producing a partial patch. This file is deleted by the validation job
before the production commit is pushed.
"""
from pathlib import Path


path = Path("pb_planreader_pdf_extractor.py")
text = path.read_text(encoding="utf-8")

old = "        global_dimension_chains: List[Any] = []  # List[DimensionChain], imported lazily below\n"
new = old + "        global_explicit_floor_area_evidence: List[Any] = []  # source-only figured FLOOR AREA evidence\n"
assert old in text and "global_explicit_floor_area_evidence" not in text
text = text.replace(old, new, 1)

old = '            norm_pg = re.sub(r"\\s+", " ", pg_txt.lower())\n\n            # Track verandah mention across drawings\n'
new = '''            norm_pg = re.sub(r"\\s+", " ", pg_txt.lower())

            # F.26: explicit figured overall FLOOR AREA on an actual plan sheet
            # outranks a later coarse rectangle reconstruction. This reads
            # drawing text only and fails closed on ambiguity.
            from pb_explicit_floor_area_evidence import extract_explicit_floor_area_evidence
            explicit_floor_area = extract_explicit_floor_area_evidence(
                pg_txt, source_page=p_idx + 1
            )
            if explicit_floor_area is not None:
                global_explicit_floor_area_evidence.append(explicit_floor_area)

            # Track verandah mention across drawings
'''
assert old in text
text = text.replace(old, new, 1)

old = "        global_resolved_wall_thickness_m: Optional[float] = resolve_corroborated_wall_thickness_m(global_dimension_chains)\n\n        pred_dict: Dict[str, ExtractedPrediction] = {}\n"
new = '''        global_resolved_wall_thickness_m: Optional[float] = resolve_corroborated_wall_thickness_m(global_dimension_chains)

        # Resolve document-level explicit area only when every qualifying plan
        # annotation agrees. Multi-plan packages with different floor areas
        # therefore remain unresolved rather than silently choosing one.
        from pb_explicit_floor_area_evidence import resolve_explicit_floor_area_evidence
        global_resolved_explicit_floor_area = resolve_explicit_floor_area_evidence(
            global_explicit_floor_area_evidence
        )

        pred_dict: Dict[str, ExtractedPrediction] = {}
'''
assert old in text
text = text.replace(old, new, 1)

old = '''                footprint_res = builder.build()
                structural_bed_area_m2 = footprint_res.gross_floor_area_m2
                total_floor_screed = structural_bed_area_m2
'''
new = '''                footprint_res = builder.build()
                derived_footprint_area_m2 = footprint_res.gross_floor_area_m2
                explicit_floor_area_for_page = (
                    global_resolved_explicit_floor_area
                    if global_resolved_explicit_floor_area is not None
                    and page_num in global_resolved_explicit_floor_area.source_pages
                    else None
                )
                structural_bed_area_m2 = (
                    explicit_floor_area_for_page.area_m2
                    if explicit_floor_area_for_page is not None
                    else derived_footprint_area_m2
                )
                total_floor_screed = structural_bed_area_m2
'''
assert old in text
text = text.replace(old, new, 1)

old = "                floor_finish_geometry = None\n                if global_resolved_wall_thickness_m is not None:\n"
new = '''                floor_finish_geometry = None
                if (
                    global_resolved_wall_thickness_m is not None
                    and explicit_floor_area_for_page is None
                ):
'''
assert old in text
text = text.replace(old, new, 1)

old = '''                existing_area = pred_dict.get("floor_screed")
                current_best_area = existing_area.quantity if existing_area else 0.0

                if total_floor_screed > current_best_area or current_best_area == 0:
'''
new = '''                existing_area = pred_dict.get("floor_screed")
                current_best_area = existing_area.quantity if existing_area else 0.0
                existing_area_meta = (existing_area.metadata or {}) if existing_area else {}
                existing_is_explicit = (
                    existing_area_meta.get("area_authority") == "explicit_drawing_floor_area"
                )
                current_is_explicit = explicit_floor_area_for_page is not None
                should_replace_area = (
                    (current_is_explicit and not existing_is_explicit)
                    or (
                        current_is_explicit == existing_is_explicit
                        and (total_floor_screed > current_best_area or current_best_area == 0)
                    )
                )

                if should_replace_area:
'''
assert old in text
text = text.replace(old, new, 1)

old = '''                    if global_verandah_width is not None and global_verandah_width > 0:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope + {length_m}m x {global_verandah_width}m verandah)"
                    else:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope)"

                    if floor_finish_geometry is not None:
'''
new = '''                    if explicit_floor_area_for_page is not None:
                        desc_flr = (
                            "Floor screed / finish ("
                            f"{explicit_floor_area_for_page.area_m2} m2 explicit drawing FLOOR AREA)"
                        )
                    elif global_verandah_width is not None and global_verandah_width > 0:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope + {length_m}m x {global_verandah_width}m verandah)"
                    else:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope)"

                    if floor_finish_geometry is not None:
'''
assert old in text
text = text.replace(old, new, 1)

old = '''                            "structural_bed_area_m2": structural_bed_area_m2,
                            **(
'''
new = '''                            "structural_bed_area_m2": structural_bed_area_m2,
                            "derived_footprint_area_m2": derived_footprint_area_m2,
                            **(
                                {
                                    "area_authority": explicit_floor_area_for_page.authority,
                                    "explicit_floor_area_source_pages": list(
                                        explicit_floor_area_for_page.source_pages
                                    ),
                                    "explicit_floor_area_raw_evidence": list(
                                        explicit_floor_area_for_page.raw_evidence
                                    ),
                                }
                                if explicit_floor_area_for_page is not None
                                else {}
                            ),
                            **(
'''
assert old in text
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("F26 explicit floor-area wiring applied")

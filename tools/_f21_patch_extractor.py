from pathlib import Path

path = Path("pb_planreader_pdf_extractor.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
'''                footprint_res = builder.build()
                total_floor_screed = footprint_res.gross_floor_area_m2
                perimeter_m = round(2 * (length_m + width_m), 2)
''',
'''                footprint_res = builder.build()
                structural_bed_area_m2 = footprint_res.gross_floor_area_m2
                total_floor_screed = structural_bed_area_m2

                # F.21: convert a genuinely evidenced rectangular OUTER
                # envelope to internal clear floor-finish area only when the
                # footprint is a single confirmed solid rectangle and wall
                # thickness independently resolves from corroborated dimension
                # chains. Compound/verandah/void/partial footprints remain
                # unchanged rather than forcing a rectangle assumption.
                floor_finish_geometry = None
                if (
                    global_resolved_wall_thickness_m is not None
                    and footprint_res.status == "confirmed"
                    and footprint_res.metadata.get("num_solid_spaces") == 1
                    and footprint_res.metadata.get("num_voids") == 0
                    and not footprint_res.missing_components
                ):
                    from pb_floor_finish_geometry import derive_internal_clear_rectangular_area

                    floor_finish_geometry = derive_internal_clear_rectangular_area(
                        length_m,
                        width_m,
                        global_resolved_wall_thickness_m,
                    )
                    if floor_finish_geometry is not None:
                        total_floor_screed = floor_finish_geometry.internal_clear_area_m2

                perimeter_m = round(2 * (length_m + width_m), 2)
''',
"footprint clear-area wiring",
)

replace_once(
'''                    else:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope)"

                    # External wall area: derived deterministically from perimeter * height.
''',
'''                    else:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope)"

                    if floor_finish_geometry is not None:
                        desc_flr = (
                            f"Internal floor finish ({floor_finish_geometry.clear_length_m}m x "
                            f"{floor_finish_geometry.clear_width_m}m clear within "
                            f"{length_m}m x {width_m}m evidenced outer envelope)"
                        )

                    # External wall area: derived deterministically from perimeter * height.
''',
"floor description wiring",
)

replace_once(
'''                            "missing_components": footprint_res.missing_components,
                        },
                    )
''',
'''                            "missing_components": footprint_res.missing_components,
                            **(
                                {
                                    "structural_bed_area_m2": structural_bed_area_m2,
                                    "outer_envelope_area_m2": floor_finish_geometry.outer_area_m2,
                                    "floor_finish_area_derivation": (
                                        "internal_clear_rectangle_from_corroborated_wall_thickness"
                                    ),
                                    "wall_thickness_m": floor_finish_geometry.wall_thickness_m,
                                    "internal_clear_floor_area_m2": floor_finish_geometry.internal_clear_area_m2,
                                    "internal_clear_dimensions_m": [
                                        floor_finish_geometry.clear_length_m,
                                        floor_finish_geometry.clear_width_m,
                                    ],
                                }
                                if floor_finish_geometry is not None
                                else {}
                            ),
                        },
                    )
''',
"floor metadata wiring",
)

replace_once(
'''                # Substructure DPM & mesh: exactly equal to floor slab area
                # NO 1.06 magic multiplier
                tot_flr = pred_dict["floor_screed"].quantity
                flr_meta = pred_dict["floor_screed"].metadata or {}
                if global_has_dpm and "substructure_bed_dpm" not in pred_dict and tot_flr > 0:
                    pred_dict["substructure_bed_dpm"] = ExtractedPrediction(
                        tag="substructure_bed_dpm",
                        trade_type="finishes",
                        description=f"Polythene damp-proof membrane under bed ({tot_flr} m2)",
                        quantity=tot_flr,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=flr_meta,
                    )
                if global_has_mesh and "substructure_a142_mesh" not in pred_dict and tot_flr > 0:
                    pred_dict["substructure_a142_mesh"] = ExtractedPrediction(
                        tag="substructure_a142_mesh",
                        trade_type="structure",
                        description=f"Fabric mesh reinforcement A142 in floor bed ({tot_flr} m2)",
                        quantity=tot_flr,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=flr_meta,
                    )
''',
'''                # Substructure DPM & mesh retain the structural-bed footprint
                # basis even when F.21 has a smaller, independently evidenced
                # internal clear floor-finish area. No lap/turn-up multiplier is
                # invented here; this only preserves the pre-existing slab basis.
                tot_flr = pred_dict["floor_screed"].quantity
                flr_meta = pred_dict["floor_screed"].metadata or {}
                bed_area_for_substructure_m2 = float(
                    flr_meta.get(
                        "structural_bed_area_m2",
                        flr_meta.get("gross_floor_area_m2", tot_flr),
                    )
                )
                if (
                    global_has_dpm
                    and "substructure_bed_dpm" not in pred_dict
                    and bed_area_for_substructure_m2 > 0
                ):
                    pred_dict["substructure_bed_dpm"] = ExtractedPrediction(
                        tag="substructure_bed_dpm",
                        trade_type="finishes",
                        description=(
                            f"Polythene damp-proof membrane under bed "
                            f"({bed_area_for_substructure_m2} m2)"
                        ),
                        quantity=bed_area_for_substructure_m2,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=flr_meta,
                    )
                if (
                    global_has_mesh
                    and "substructure_a142_mesh" not in pred_dict
                    and bed_area_for_substructure_m2 > 0
                ):
                    pred_dict["substructure_a142_mesh"] = ExtractedPrediction(
                        tag="substructure_a142_mesh",
                        trade_type="structure",
                        description=(
                            f"Fabric mesh reinforcement A142 in floor bed "
                            f"({bed_area_for_substructure_m2} m2)"
                        ),
                        quantity=bed_area_for_substructure_m2,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=flr_meta,
                    )
''',
"substructure basis preservation",
)

path.write_text(text, encoding="utf-8")

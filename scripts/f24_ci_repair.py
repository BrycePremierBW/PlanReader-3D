from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement anchor, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Production: deterministic row-aligned schedule fallback.
# ---------------------------------------------------------------------------
replace_once(
    "pb_raster_schedule_extractor.py",
    '''        # 2. Column-aligned schedule detection (CAD multi-column schedules)\n        col_rows = self._extract_column_aligned_schedules(page, page_num)\n        page_rows.extend(col_rows)\n\n        # 3. Explicit callouts (windows, doors, vents, pillars, trusses)\n''',
    '''        # 2. Row-aligned schedule detection. This path is independent of\n        # PyMuPDF's structured-table detector and is therefore stable for\n        # vector/CAD schedules whose cells are visually aligned but not\n        # recognized by ``find_tables()``.\n        row_rows = self._extract_row_aligned_opening_schedules(page, page_num)\n        page_rows.extend(row_rows)\n\n        # 3. Column-aligned schedule detection (CAD multi-column schedules)\n        col_rows = self._extract_column_aligned_schedules(page, page_num)\n        page_rows.extend(col_rows)\n\n        # 4. Explicit callouts (windows, doors, vents, pillars, trusses)\n''',
)

row_method = r'''    def _extract_row_aligned_opening_schedules(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:
        """Recover explicit opening schedule rows from native word geometry.

        This is a deterministic fallback for vector/CAD schedule sheets where
        ``Page.find_tables()`` does not recognize the grid. A firm row requires
        all three pieces of source evidence on one visual row: an explicit W/D
        identity, figured dimensions, and an explicit count marker. Dimensions
        or counts alone never manufacture an opening identity.
        """
        rows: List[ScheduleRow] = []
        try:
            page_text = page.get_text("text") or ""
            normalized_page = re.sub(r"\s+", " ", page_text.lower())
            has_schedule_context = (
                bool(re.search(r"\bschedules?\b", normalized_page))
                and bool(re.search(r"\b(?:windows?|doors?)\b", normalized_page))
            )
            if not has_schedule_context:
                return rows

            words = page.get_text("words") or []
            if not words:
                return rows

            # Cluster by visual baseline rather than PDF block identity. CAD
            # exports commonly place each schedule cell in a separate block.
            visual_rows: List[Dict[str, Any]] = []
            for word in sorted(words, key=lambda w: (((w[1] + w[3]) / 2.0), w[0])):
                cy = (float(word[1]) + float(word[3])) / 2.0
                target = None
                for candidate in visual_rows:
                    if abs(cy - candidate["cy"]) <= 4.5:
                        target = candidate
                        break
                if target is None:
                    target = {"cy": cy, "words": []}
                    visual_rows.append(target)
                target["words"].append(word)
                n = len(target["words"])
                target["cy"] = ((target["cy"] * (n - 1)) + cy) / n

            for visual in visual_rows:
                row_words = sorted(visual["words"], key=lambda w: w[0])
                row_text = " ".join(str(w[4]) for w in row_words).strip()
                normalized_opening = normalize_opening_tag(row_text)
                if normalized_opening is None:
                    continue

                dims = self._parse_dimensions_string(row_text)
                qty_match = re.search(r"\b(\d{1,3})\s*(?:no\.?s?|nos?)\b", row_text, re.I)
                if dims is None or qty_match is None:
                    continue

                qty = float(qty_match.group(1))
                if qty <= 0:
                    continue

                x0 = min(float(w[0]) for w in row_words)
                y0 = min(float(w[1]) for w in row_words)
                x1 = max(float(w[2]) for w in row_words)
                y1 = max(float(w[3]) for w in row_words)
                rows.append(
                    ScheduleRow(
                        tag=normalized_opening.tag,
                        trade_type=normalized_opening.trade_type,
                        description=(
                            f"Row-aligned schedule item {normalized_opening.tag} "
                            f"({int(qty)} No)"
                        ),
                        quantity=qty,
                        unit="NO",
                        dimensions=dims,
                        source_page=page_num,
                        bbox=(x0, y0, x1, y1),
                        confidence=0.87,
                        evidence_text=f"Row-aligned native schedule evidence: {row_text}",
                    )
                )
        except Exception:
            return []

        return rows

'''
replace_once(
    "pb_raster_schedule_extractor.py",
    '''    def _extract_column_aligned_schedules(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:\n''',
    row_method + '''    def _extract_column_aligned_schedules(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:\n''',
)

# ---------------------------------------------------------------------------
# New regression: structured-table detection may be absent and the same
# explicit arbitrary schedule must still be production-wired.
# ---------------------------------------------------------------------------
replace_once(
    "tests/benchmarks/test_mutation_generic_opening_binding_wiring.py",
    '''from pathlib import Path\n\nimport fitz\n''',
    '''from pathlib import Path\nfrom unittest.mock import patch\n\nimport fitz\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_generic_opening_binding_wiring.py",
    '''\ndef test_mutating_source_count_changes_only_that_opening(tmp_path: Path) -> None:\n''',
    '''\ndef test_row_aligned_fallback_does_not_depend_on_structured_table_detection(tmp_path: Path) -> None:\n    pdf = _schedule_pdf(\n        tmp_path,\n        "row_fallback.pdf",\n        [\n            ["Mark", "Dimensions", "Quantity", "Description"],\n            ["WINDOW 42", "1610 x 1180 mm", "7 No.", "Casement window"],\n            ["DR-19", "920 x 2110 mm", "2 No.", "Flush door"],\n        ],\n    )\n    with patch.object(GenericScheduleTableExtractor, "_extract_tables_from_page", return_value=[]):\n        preds = {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)}\n\n    assert preds["W42"].quantity == 7.0\n    assert preds["W42"].dimensions == [1610.0, 1180.0]\n    assert preds["D19"].quantity == 2.0\n    assert preds["D19"].dimensions == [920.0, 2110.0]\n\n\ndef test_mutating_source_count_changes_only_that_opening(tmp_path: Path) -> None:\n''',
)

# ---------------------------------------------------------------------------
# Legacy leakage tests: preserve their mutation purpose, but require explicit
# generic identities and counts rather than dimension-only W1/D1 synthesis.
# ---------------------------------------------------------------------------
replace_once(
    "tests/benchmarks/test_mutation_leakage_cleanup.py",
    '''        "TRUSS T1 (6 No.)\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "D.P.C.\\n"\n''',
    '''        "TRUSS T1 (6 No.)\\n"\n        "WINDOW SCHEDULE\\n"\n        "W17 3,000 x 1,200 mm 2 No. steel casement window\\n"\n        "D.P.C.\\n"\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_leakage_cleanup.py",
    '''    assert preds_a["W1"].quantity == 2.0\n''',
    '''    assert preds_a["W17"].quantity == 2.0\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_leakage_cleanup.py",
    '''        "TRUSS T1 (11 No.)\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "D.P.C.\\n"\n''',
    '''        "TRUSS T1 (11 No.)\\n"\n        "WINDOW SCHEDULE\\n"\n        "W17 3,000 x 1,200 mm 4 No. steel casement window\\n"\n        "D.P.C.\\n"\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_leakage_cleanup.py",
    '''    assert preds_b["W1"].quantity == 4.0\n''',
    '''    assert preds_b["W17"].quantity == 4.0\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_leakage_cleanup.py",
    '''    assert preds_a["W1"].quantity != preds_b["W1"].quantity\n''',
    '''    assert preds_a["W17"].quantity != preds_b["W17"].quantity\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_leakage_cleanup.py",
    '''        "20 degree roof pitch\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "3,000mm x 1,200mm steel casement\\n"\n        "1,000mm x 2,100mm timber door\\n"\n        "1,000mm x 2,100mm timber door\\n"\n        "2,400mm x 1,200mm black board\\n"\n''',
    '''        "20 degree roof pitch\\n"\n        "WINDOW & DOOR SCHEDULE\\n"\n        "W17 3,000 x 1,200 mm 3 No. steel casement window\\n"\n        "D12 1,000 x 2,100 mm 2 No. timber door\\n"\n        "2,400mm x 1,200mm black board\\n"\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_leakage_cleanup.py",
    '''    assert preds["W1"].quantity == 3.0\n    assert preds["W1"].dimensions == [3000.0, 1200.0]\n    # Doors: exactly 2.0 NO with parsed dimensions [1000, 2100]\n    assert preds["D1"].quantity == 2.0\n    assert preds["D1"].dimensions == [1000.0, 2100.0]\n''',
    '''    assert preds["W17"].quantity == 3.0\n    assert preds["W17"].dimensions == [3000.0, 1200.0]\n    # Doors: exactly 2.0 NO with parsed dimensions [1000, 2100]\n    assert preds["D12"].quantity == 2.0\n    assert preds["D12"].dimensions == [1000.0, 2100.0]\n''',
)

# ---------------------------------------------------------------------------
# OCR contract: only explicit complete native opening evidence suppresses OCR.
# ---------------------------------------------------------------------------
replace_once(
    "tests/benchmarks/test_mutation_ocr_evidence_layer_wiring.py",
    '''            "2,900mm x 900mm steel casement windows with 4mm thick glass",\n''',
    '''            "WINDOW SCHEDULE",\n            "W27: 2,900 x 900 mm 4 No. steel casement window",\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_ocr_evidence_layer_wiring.py",
    '''            return_value=_ocr_lines("W2: 999 x 999 mm 99 No."),\n''',
    '''            return_value=_ocr_lines("W27: 999 x 999 mm 99 No."),\n''',
)
replace_once(
    "tests/benchmarks/test_mutation_ocr_evidence_layer_wiring.py",
    '''        # Native W2 occurrence was found (non-zero quantity) -- the bogus\n        # injected OCR count must never have overwritten or added to it.\n        if "W2" in pred_map:\n            assert pred_map["W2"].quantity != 99.0\n        assert not mocked.called\n''',
    '''        # Explicit native W27 schedule evidence is complete, so the bogus\n        # injected OCR count must never run or overwrite it.\n        assert pred_map["W27"].quantity == 4.0\n        assert not mocked.called\n''',
)

print("F24 CI repair patch applied")

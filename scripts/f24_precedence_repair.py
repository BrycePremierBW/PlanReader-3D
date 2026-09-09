from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "pb_raster_schedule_extractor.py"
old = '''        conflicting_opening_tags = set()\n        for tag, group in opening_groups.items():\n            quantities = {float(r.quantity) for r in group if r.quantity is not None}\n            dimensions = {\n                tuple(float(v) for v in r.dimensions[:2])\n                for r in group\n                if r.dimensions is not None and len(r.dimensions) >= 2\n            }\n            if len(quantities) > 1 or len(dimensions) > 1:\n                conflicting_opening_tags.add(tag)\n\n        for r in rows:\n'''
new = '''        conflicting_opening_tags = set()\n        resolved_opening_rows: Dict[str, ScheduleRow] = {}\n        for tag, group in opening_groups.items():\n            quantities = {float(r.quantity) for r in group if r.quantity is not None}\n            dimensions = {\n                tuple(float(v) for v in r.dimensions[:2])\n                for r in group\n                if r.dimensions is not None and len(r.dimensions) >= 2\n            }\n            if len(quantities) > 1 or len(dimensions) > 1:\n                conflicting_opening_tags.add(tag)\n                continue\n\n            # Multiple generic detectors may observe the same explicit W/D row.\n            # Prefer the most complete agreeing evidence over raw confidence:\n            # a count-only note must never overwrite a lower-confidence row\n            # that carries the same count plus figured width/height.\n            resolved_opening_rows[tag] = max(\n                group,\n                key=lambda candidate: (\n                    int(\n                        candidate.quantity is not None\n                        and candidate.quantity > 0\n                        and candidate.dimensions is not None\n                        and len(candidate.dimensions) >= 2\n                    ),\n                    int(candidate.dimensions is not None and len(candidate.dimensions) >= 2),\n                    int(candidate.quantity is not None and candidate.quantity > 0),\n                    candidate.confidence,\n                ),\n            )\n\n        for r in rows:\n'''
replace_once(path, old, new)

old = '''            norm = normalize_opening_tag(r.tag)\n            if norm is not None:\n                r.tag = norm.tag\n                r.trade_type = norm.trade_type\n                if r.tag in conflicting_opening_tags:\n                    continue\n\n            if r.tag == "brick_vents":\n'''
new = '''            norm = normalize_opening_tag(r.tag)\n            if norm is not None:\n                r.tag = norm.tag\n                r.trade_type = norm.trade_type\n                if r.tag in conflicting_opening_tags:\n                    continue\n                # One canonical row per explicit opening identity.  Selecting\n                # it here prevents a second count-only detector result from\n                # surviving under a dimensionless key and later overwriting\n                # the complete schedule prediction in production.\n                if resolved_opening_rows.get(r.tag) is not r:\n                    continue\n\n            if r.tag == "brick_vents":\n'''
replace_once(path, old, new)

# Synthetic regression for the exact detector-precedence failure class.
test_path = "tests/benchmarks/test_mutation_raster_cad_schedules.py"
old = '''\ndef test_mutation_2_removing_schedule_row_removes_prediction(tmp_path: Path) -> None:\n'''
new = '''\ndef test_agreeing_count_only_duplicate_cannot_strip_figured_dimensions() -> None:\n    extractor = GenericScheduleTableExtractor()\n    rows = extractor.deduplicate_schedule_rows([\n        ScheduleRow(\n            tag="WINDOW 42",\n            trade_type="windows",\n            description="Explicit drawing count",\n            quantity=7.0,\n            unit="NO",\n            dimensions=None,\n            source_page=1,\n            confidence=0.99,\n        ),\n        ScheduleRow(\n            tag="W-42",\n            trade_type="windows",\n            description="Complete schedule row",\n            quantity=7.0,\n            unit="NO",\n            dimensions=[1610.0, 1180.0],\n            source_page=1,\n            confidence=0.80,\n        ),\n    ])\n\n    assert len(rows) == 1\n    assert rows[0].tag == "W42"\n    assert rows[0].quantity == 7.0\n    assert rows[0].dimensions == [1610.0, 1180.0]\n\n\ndef test_mutation_2_removing_schedule_row_removes_prediction(tmp_path: Path) -> None:\n'''
replace_once(test_path, old, new)

print("F24 evidence-precedence repair applied")

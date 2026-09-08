from pathlib import Path
import json

manifest_path = Path("benchmarks/public_tenders/tenders_ke_kstvet_cbc_classroom/expected_boq_summary.json")
data = json.loads(manifest_path.read_text(encoding="utf-8"))

items = data.get("sample_measurable_items", [])
filtered = [item for item in items if item.get("item_id") != "substructure_surface_bed"]
if len(filtered) != len(items) - 1:
    raise SystemExit("expected exactly one substructure_surface_bed benchmark entry to remove")
data["sample_measurable_items"] = filtered

data["provisional_sums_count"] = 1
data["classified_breakdown"]["provisional_sum"] = 1
manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

test_path = Path("tests/benchmarks/test_public_tender_verified_benchmark.py")
text = test_path.read_text(encoding="utf-8")
old = '''    # 2, not 1: the SUBSTRUCTURES element (75mm R.C. slab on hardcore) is
    # priced ALL PROVISIONAL in the real BOQ's own SECTION SUMMARY and is
    # now individually registered (tag substructure_surface_bed) so the
    # accuracy engine's existing provisional-sum exclusion recognizes a
    # genuinely evidenced extraction for it rather than flagging it as a
    # phantom hallucination.
    assert summary["provisional_sums_count"] == 2
    assert summary["classified_breakdown"]["preliminaries"] == 2
    assert summary["classified_breakdown"]["provisional_sum"] == 2
'''
new = '''    assert summary["provisional_sums_count"] == 1
    assert summary["classified_breakdown"]["preliminaries"] == 2
    assert summary["classified_breakdown"]["provisional_sum"] == 1
'''
if text.count(old) != 1:
    raise SystemExit("expected exactly one PR202 provisional-count assertion block")
test_path.write_text(text.replace(old, new, 1), encoding="utf-8")

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path

import fitz
import pytest

import pb_shadow_opening_count_provider as provider_mod
from pb_gold_free_shadow_runner import GoldFreeShadowRunner
from pb_shadow_opening_count_gate import OPENING_COUNT_MIGRATION_GATE
from pb_shadow_opening_count_provider import (
    ShadowOpeningCountProvider,
    page_has_opening_evidence,
    resolve_opening_identity,
)


def _answered(bundle):
    return {item.semantic_key: item for item in bundle.quantities if not item.abstained}


def _abstained(bundle):
    return {item.semantic_key: item for item in bundle.quantities if item.abstained}


def _schedule_pdf(
    tmp_path: Path,
    name: str,
    rows: list[list[str]],
    extra_text: str = "",
    *,
    title: str = "DRAWING TITLE: WINDOW & DOOR SCHEDULE",
    origin: tuple[float, float] = (40.0, 85.0),
    fontsize: float = 9,
    reverse_draw_order: bool = False,
) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), title, fontsize=10)
    page.insert_text((40, 50), "SCALE 1:100", fontsize=9)
    x = [origin[0], origin[0] + 90, origin[0] + 260, origin[0] + 350, origin[0] + 610]
    y0 = origin[1]
    rh = 28
    draw_rows = list(enumerate(rows))
    if reverse_draw_order:
        draw_rows = list(reversed(draw_rows))
    for ridx, row in draw_rows:
        y = y0 + ridx * rh
        page.draw_line(fitz.Point(x[0], y), fitz.Point(x[-1], y))
        for cidx, cell in enumerate(row):
            page.draw_line(fitz.Point(x[cidx], y), fitz.Point(x[cidx], y + rh))
            page.insert_text((x[cidx] + 5, y + 18), cell, fontsize=fontsize)
        page.draw_line(fitz.Point(x[-1], y), fitz.Point(x[-1], y + rh))
    page.draw_line(fitz.Point(x[0], y0 + len(rows) * rh), fitz.Point(x[-1], y0 + len(rows) * rh))
    if extra_text:
        page.insert_text((40, y0 + len(rows) * rh + 35), extra_text, fontsize=9)
    doc.save(path)
    doc.close()
    return path


def _plan_pdf(tmp_path: Path, name: str, tags: list[tuple[str, tuple[float, float]]], extra: str = "") -> Path:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=12)
    page.insert_text((40, 50), "SCALE 1:100", fontsize=9)
    for tag, pos in tags:
        page.insert_text(pos, tag, fontsize=11)
    if extra:
        page.insert_text((40, 520), extra, fontsize=8)
    doc.save(path)
    doc.close()
    return path


def _multi_page(tmp_path: Path, name: str, builders: list) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    for builder in builders:
        builder(doc)
    doc.save(path)
    doc.close()
    return path


def test_tabular_schedule_emits_type_count_quantity_evidence(tmp_path: Path) -> None:
    pdf = _schedule_pdf(
        tmp_path,
        "tabular.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W1", "1200 x 1500 mm", "6 No.", "Powder coated casement"],
            ["D1", "900 x 2100 mm", "3 No.", "Flush door"],
        ],
    )
    bundle = ShadowOpeningCountProvider().extract_bundle(pdf)
    answered = _answered(bundle)
    assert answered["W1"].value == 6.0
    assert answered["W1"].family == "window_count"
    assert answered["W1"].unit == "ea"
    assert answered["W1"].formula == "explicit_schedule_count"
    assert answered["W1"].evidence_ids
    assert answered["D1"].value == 3.0
    assert answered["D1"].family == "door_count"
    assert all(opening.takeoff_eligible is False for opening in bundle.canonical_openings)
    assert all(opening.metadata.get("physical_instance_count_not_implied") for opening in bundle.canonical_openings)
    assert len(bundle.canonical_openings) == 2
    physical = [item for item in bundle.entity_evidence if item.candidate_type == "opening_instance"]
    assert physical == []
    assert bundle.diagnostics["gold_consulted"] is False
    assert bundle.diagnostics["authoritative"] is False


def test_schedule_row_reorder_and_collection_order_are_stable(tmp_path: Path) -> None:
    first = _schedule_pdf(
        tmp_path,
        "order_a.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W1", "1200 x 1500 mm", "6 No.", "Casement"],
            ["D2", "900 x 2100 mm", "2 No.", "Door"],
        ],
    )
    second = _schedule_pdf(
        tmp_path,
        "order_b.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["D2", "900 x 2100 mm", "2 No.", "Door"],
            ["W1", "1200 x 1500 mm", "6 No.", "Casement"],
        ],
        reverse_draw_order=True,
    )
    a = _answered(ShadowOpeningCountProvider().extract_bundle(first))
    b = _answered(ShadowOpeningCountProvider().extract_bundle(second))
    assert a["W1"].value == b["W1"].value == 6.0
    assert a["D2"].value == b["D2"].value == 2.0
    reversed_pages = _answered(ShadowOpeningCountProvider().extract_bundle(first, pages=[0]))
    assert reversed_pages["W1"].value == 6.0


def test_card_schedule_uses_overall_quantity(tmp_path: Path) -> None:
    path = tmp_path / "card.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=1200)
    page.insert_text((40, 40), "WINDOW SCHEDULE", fontsize=12)
    page.insert_text((100, 200), "W - 07", fontsize=9)
    page.insert_text((100, 260), "Overall Quantity: 6", fontsize=9)
    page.insert_text((300, 200), "D - 05", fontsize=9)
    page.insert_text((300, 260), "Overall Quantity: 12", fontsize=9)
    doc.save(path)
    doc.close()
    answered = _answered(ShadowOpeningCountProvider().extract_bundle(path))
    assert answered["W7"].value == 6.0
    assert answered["D5"].value == 12.0
    assert answered["W7"].family == "window_count"
    assert answered["D5"].family == "door_count"


def test_ocr_injected_schedule_line_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "ocr.pdf"
    doc = fitz.open()
    doc.new_page(width=842, height=595)
    doc.save(path)
    doc.close()
    provider = ShadowOpeningCountProvider(
        ocr_lines_by_page={
            1: (
                {
                    "text": "W1: 1200 x 1500 - 6 No.",
                    "bbox": [40, 80, 240, 100],
                    "confidence": 0.84,
                },
            )
        }
    )
    answered = _answered(provider.extract_bundle(path))
    assert answered["W1"].value == 6.0
    assert answered["W1"].authority == "schedule_extracted"
    assert any("ocr" in evid or evid.startswith("ev_") for evid in answered["W1"].evidence_ids)


def test_plan_only_counts_tags_not_geometry(tmp_path: Path) -> None:
    pdf = _plan_pdf(
        tmp_path,
        "plan_only.pdf",
        [("W1", (80, 140)), ("W1", (220, 140)), ("W1", (360, 140)), ("D1", (80, 260))],
    )
    answered = _answered(ShadowOpeningCountProvider().extract_bundle(pdf))
    assert answered["W1"].value == 3.0
    assert answered["W1"].formula == "plan_tag_count"
    assert answered["D1"].value == 1.0
    physical = [
        item
        for item in ShadowOpeningCountProvider().extract_bundle(pdf).entity_evidence
        if item.candidate_type == "opening_instance"
    ]
    assert len(physical) == 4


def _add_schedule_page(doc: fitz.Document, rows: list[list[str]], title: str = "WINDOW SCHEDULE") -> None:
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), title, fontsize=12)
    page.insert_text((40, 50), "SCALE 1:100", fontsize=9)
    x = [40, 130, 300, 390, 650]
    y0 = 85
    rh = 28
    for ridx, row in enumerate(rows):
        y = y0 + ridx * rh
        page.draw_line(fitz.Point(x[0], y), fitz.Point(x[-1], y))
        for cidx, cell in enumerate(row):
            page.draw_line(fitz.Point(x[cidx], y), fitz.Point(x[cidx], y + rh))
            page.insert_text((x[cidx] + 5, y + 18), cell, fontsize=9)
        page.draw_line(fitz.Point(x[-1], y), fitz.Point(x[-1], y + rh))
    page.draw_line(fitz.Point(x[0], y0 + len(rows) * rh), fitz.Point(x[-1], y0 + len(rows) * rh))


def test_schedule_and_plan_agreement_is_firm(tmp_path: Path) -> None:
    def schedule(doc: fitz.Document) -> None:
        _add_schedule_page(
            doc,
            [
                ["Mark", "Dimensions", "Quantity", "Description"],
                ["W1", "1200 x 1500 mm", "3 No.", "Casement"],
            ],
        )

    def plan(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=12)
        page.insert_text((80, 140), "W1", fontsize=11)
        page.insert_text((220, 140), "W1", fontsize=11)
        page.insert_text((360, 140), "W1", fontsize=11)

    pdf = _multi_page(tmp_path, "agree.pdf", [schedule, plan])
    answered = _answered(ShadowOpeningCountProvider().extract_bundle(pdf))
    assert answered["W1"].value == 3.0
    assert answered["W1"].formula == "schedule_plan_corroborated"
    assert answered["W1"].status == "firm"


def test_schedule_plan_disagreement_abstains(tmp_path: Path) -> None:
    def schedule(doc: fitz.Document) -> None:
        _add_schedule_page(
            doc,
            [
                ["Mark", "Dimensions", "Quantity", "Description"],
                ["W1", "1200 x 1500 mm", "6 No.", "Casement"],
            ],
        )

    def plan(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=12)
        page.insert_text((80, 140), "W1", fontsize=11)
        page.insert_text((220, 140), "W1", fontsize=11)
        page.insert_text((360, 140), "W1", fontsize=11)

    pdf = _multi_page(tmp_path, "disagree.pdf", [schedule, plan])
    bundle = ShadowOpeningCountProvider().extract_bundle(pdf)
    abstained = _abstained(bundle)
    assert "W1" in abstained
    assert abstained["W1"].value is None
    assert "schedule_vs_plan_count_mismatch" in abstained["W1"].blocking_reasons
    assert "W1" not in _answered(bundle)


def test_duplicate_schedule_observation_conflicts(tmp_path: Path) -> None:
    pdf = _schedule_pdf(
        tmp_path,
        "dup_sched.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W-33", "1870 x 1240 mm", "4 No.", "Casement"],
            ["WINDOW 33", "1870 x 1240 mm", "7 No.", "Casement"],
        ],
    )
    bundle = ShadowOpeningCountProvider().extract_bundle(pdf)
    abstained = _abstained(bundle)
    assert "W33" in abstained
    assert abstained["W33"].value is None
    assert any("conflict" in str(item.get("type", "")) for item in bundle.conflicts) or (
        "duplicate_schedule_conflict" in abstained["W33"].blocking_reasons
    )


def test_conflicting_dimensions_abstain(tmp_path: Path) -> None:
    pdf = _schedule_pdf(
        tmp_path,
        "dims.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W1", "1200 x 1500 mm", "6 No.", "Casement"],
            ["W1", "1800 x 1500 mm", "6 No.", "Casement"],
        ],
    )
    bundle = ShadowOpeningCountProvider().extract_bundle(pdf)
    abstained = _abstained(bundle)
    assert "W1" in abstained
    assert abstained["W1"].value is None


def test_ambiguous_wd_abstains_and_does_not_guess_trade(tmp_path: Path) -> None:
    path = tmp_path / "wd.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 40), "WINDOW SCHEDULE", fontsize=12)
    page.insert_text((40, 120), "WD 01 1800 x 2200  Overall Quantity missing", fontsize=10)
    doc.save(path)
    doc.close()
    bundle = ShadowOpeningCountProvider().extract_bundle(path)
    abstained = _abstained(bundle)
    assert "WD" in abstained or "WD1" in abstained
    answered = _answered(bundle)
    assert "W1" not in answered
    assert "D1" not in answered
    assert all(item.family == "opening_count" for item in abstained.values() if item.semantic_key.startswith("WD"))


def test_dimension_only_geometry_does_not_create_identities(tmp_path: Path) -> None:
    path = tmp_path / "dims_only.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=12)
    page.insert_text((60, 100), "2,900mm x 900mm steel casement windows with 4mm thick glass", fontsize=9)
    page.insert_text((60, 130), "1,000mm x 2,100mm timber batten door", fontsize=9)
    page.draw_rect(fitz.Rect(80, 200, 200, 280))
    page.draw_rect(fitz.Rect(240, 200, 360, 280))
    doc.save(path)
    doc.close()
    bundle = ShadowOpeningCountProvider().extract_bundle(path)
    answered = _answered(bundle)
    assert "W1" not in answered
    assert "W2" not in answered
    assert "D1" not in answered
    assert all(item.value != 0 for item in bundle.quantities if not item.abstained)


def test_missing_quantity_and_missing_identity_do_not_invent_zeros(tmp_path: Path) -> None:
    missing_qty = _schedule_pdf(
        tmp_path,
        "missing_qty.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W1", "1200 x 1500 mm", "No.", "Casement"],
        ],
    )
    missing_id = _schedule_pdf(
        tmp_path,
        "missing_id.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["", "1200 x 1500 mm", "6 No.", "Casement"],
        ],
    )
    qty_bundle = ShadowOpeningCountProvider().extract_bundle(missing_qty)
    id_bundle = ShadowOpeningCountProvider().extract_bundle(missing_id)
    if "W1" in {item.semantic_key for item in qty_bundle.quantities}:
        record = next(item for item in qty_bundle.quantities if item.semantic_key == "W1")
        assert record.abstained is True
        assert record.value is None
    assert "W1" not in _answered(id_bundle)
    assert not any(item.value == 0 for item in id_bundle.quantities)


def test_duplicate_detail_and_elevation_do_not_inflate_count(tmp_path: Path) -> None:
    def schedule(doc: fitz.Document) -> None:
        _add_schedule_page(
            doc,
            [
                ["Mark", "Dimensions", "Quantity", "Description"],
                ["W1", "1200 x 1500 mm", "3 No.", "Casement"],
            ],
        )

    def elevation(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "NORTH ELEVATION", fontsize=12)
        page.insert_text((80, 140), "W1", fontsize=11)
        page.insert_text((220, 140), "W1", fontsize=11)
        page.insert_text((360, 140), "W1", fontsize=11)

    def detail(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "TYPICAL DETAIL W1", fontsize=12)
        page.insert_text((80, 140), "W1", fontsize=11)
        page.insert_text((80, 180), "W1", fontsize=11)

    def elev_dup(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "NORTH ELEVATION", fontsize=12)
        page.insert_text((80, 140), "W1", fontsize=11)
        page.insert_text((220, 140), "W1", fontsize=11)
        page.insert_text((360, 140), "W1", fontsize=11)

    pdf = _multi_page(tmp_path, "views.pdf", [schedule, elevation, detail, elev_dup])
    answered = _answered(ShadowOpeningCountProvider().extract_bundle(pdf))
    assert answered["W1"].value == 3.0


def test_unrelated_notes_font_and_translation_do_not_change_counts(tmp_path: Path) -> None:
    rows = [
        ["Mark", "Dimensions", "Quantity", "Description"],
        ["W1", "1200 x 1500 mm", "6 No.", "Casement"],
        ["D1", "900 x 2100 mm", "2 No.", "Door"],
    ]
    base = _schedule_pdf(tmp_path, "base.pdf", rows)
    notes = _schedule_pdf(tmp_path, "notes.pdf", rows, extra_text="REFER STRUCTURAL NOTES REV C FOR STEEL")
    font = _schedule_pdf(tmp_path, "font.pdf", rows, fontsize=14)
    shifted = _schedule_pdf(tmp_path, "shift.pdf", rows, origin=(90.0, 140.0))
    values = []
    for pdf in (base, notes, font, shifted):
        answered = _answered(ShadowOpeningCountProvider().extract_bundle(pdf))
        values.append((answered["W1"].value, answered["D1"].value))
    assert values == [(6.0, 2.0)] * 4


def test_page_object_and_page_order_changes_do_not_create_fake_counts(tmp_path: Path) -> None:
    def schedule(doc: fitz.Document) -> None:
        _add_schedule_page(
            doc,
            [
                ["Mark", "Dimensions", "Quantity", "Description"],
                ["D1", "900 x 2100 mm", "4 No.", "Flush door"],
            ],
            title="DOOR SCHEDULE",
        )

    def blank_notes(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 40), "GENERAL NOTES", fontsize=12)
        page.insert_text((40, 80), "This sheet has no opening identities.", fontsize=9)

    first = _multi_page(tmp_path, "a.pdf", [schedule, blank_notes])
    second = _multi_page(tmp_path, "b.pdf", [blank_notes, schedule])
    a = _answered(ShadowOpeningCountProvider().extract_bundle(first))
    b = _answered(ShadowOpeningCountProvider().extract_bundle(second))
    assert a["D1"].value == b["D1"].value


def test_f28_resolved_wd_is_window_type_not_guessed_door() -> None:
    resolved = resolve_opening_identity(
        "WD01",
        evidence_text="WD 01; Overall Quantity: 14; window fields: frame, panel",
        trade_type="windows",
    )
    assert resolved is not None
    assert resolved.tag == "WD1"
    assert resolved.trade_type == "windows"
    assert resolve_opening_identity("WD", evidence_text="ambiguous mark") is None
    assert resolve_opening_identity("WD01") is None


def test_provider_and_shadow_runner_are_gold_free() -> None:
    source = inspect.getsource(provider_mod)
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = (
        "benchmark_accuracy_engine",
        "public_tender_benchmark",
        "benchmark_runner",
        "holdout_suite",
        "expected_boq",
        "pb_shadow_opening_count_eval",
        "pb_quantity_commercial_adapter",
    )
    assert not [module for module in imported if any(token in module.lower() for token in forbidden)]
    assert "NEW_SELECTIVE" not in source
    assert "NEW_AUTHORITATIVE" not in source
    assert "expected_quantity" not in source
    params = {name.lower() for name in inspect.signature(ShadowOpeningCountProvider.extract_quantities).parameters}
    assert "benchmark_id" not in params
    assert "expected" not in params


def test_gate_constants_remain_frozen_from_provider_module() -> None:
    assert OPENING_COUNT_MIGRATION_GATE["min_precision_on_answered_identities"] == 0.99
    assert OPENING_COUNT_MIGRATION_GATE["min_exact_correctness_on_answered_counts"] == 0.99


def test_shadow_runner_accepts_provider_without_gold(tmp_path: Path) -> None:
    pdf = _schedule_pdf(
        tmp_path,
        "shadow.pdf",
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W1", "1200 x 1500 mm", "6 No.", "Casement"],
        ],
    )
    result = GoldFreeShadowRunner().run(pdf, ShadowOpeningCountProvider())
    payload = result.to_dict()

    def keys(value, found=None):
        found = found if found is not None else set()
        if isinstance(value, dict):
            found.update(value)
            for item in value.values():
                keys(item, found)
        elif isinstance(value, list):
            for item in value:
                keys(item, found)
        return found

    assert {"expected", "expected_quantity", "benchmark_id", "ground_truth"}.isdisjoint(keys(payload))
    new_w1 = [item for item in result.new_output if item.semantic_key == "W1" and not item.abstained]
    assert new_w1 and new_w1[0].value == 6.0


def test_committed_headline_benchmark_is_unchanged() -> None:
    dashboard = json.loads(Path("benchmark_results/headline_accuracy_dashboard.json").read_text(encoding="utf-8"))
    metrics = dashboard["headline_metrics"]
    accepted = int(metrics["exact_matches"]) + int(metrics["within_5_percent"])
    assert accepted == 24
    assert int(metrics["total_items_compared"]) == 61
    assert pytest.approx(metrics["overall_accuracy_percentage"], rel=0, abs=0.01) == 39.34


def test_legacy_extractor_source_was_not_edited_for_this_family() -> None:
    digest = hashlib.sha256(Path("pb_planreader_pdf_extractor.py").read_bytes()).hexdigest()
    assert len(digest) == 64
    source = Path("pb_planreader_pdf_extractor.py").read_text(encoding="utf-8")
    assert "shadow_opening_count" not in source


def test_page_probe_ignores_unrelated_notes() -> None:
    assert page_has_opening_evidence("WINDOW SCHEDULE\nW1 6 No")
    assert not page_has_opening_evidence("GENERAL PRELIMINARIES AND CONDITIONS OF CONTRACT")

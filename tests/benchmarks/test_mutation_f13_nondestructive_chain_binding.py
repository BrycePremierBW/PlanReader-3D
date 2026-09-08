"""F.13/F.15 regression tests for non-destructive dimension anchoring.

Synthetic only: no benchmark values, identities, paths, or coordinates.
"""
from __future__ import annotations

import fitz

from pb_dimension_chain_evidence_extractor import extract_dimension_chains_from_page
from pb_figured_dimension_evidence import BindingStatus, extract_dimension_evidence_bundle


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def test_ambiguous_parallel_vector_lines_do_not_delete_valid_text_chain() -> None:
    """Anchor ambiguity must not erase an independently readable dimension row."""
    doc = fitz.open()
    page = doc.new_page(width=360, height=240)

    # Dense CAD export: two visually plausible parallel dimension-line
    # candidates. The rich F.13 binder must flag the anchor as ambiguous.
    page.draw_line((45, 116), (300, 116))
    page.draw_line((45, 118), (300, 118))

    # The printed dimension values remain clear documented evidence.
    page.insert_text((70, 113), "150", fontsize=9)
    page.insert_text((145, 113), "6700", fontsize=9)
    page.insert_text((255, 113), "150", fontsize=9)
    doc = _reopen(doc)

    bundle = extract_dimension_evidence_bundle(doc[0], page_num=1, view_id="SYNTH")
    assert bundle.observations
    assert any(binding.status == BindingStatus.AMBIGUOUS.value for binding in bundle.bindings)

    chains = extract_dimension_chains_from_page(doc[0], page_num=1, view_id="SYNTH")
    matching = [
        chain
        for chain in chains
        if [round(obs.value_m, 3) for obs in chain.observations] == [0.15, 6.7, 0.15]
    ]
    assert len(matching) == 1
    assert all(obs.endpoints is None for obs in matching[0].observations)
    doc.close()


def test_fully_witness_bound_vertical_dimension_stays_out_of_horizontal_f15_consumer() -> None:
    """A confidently vertical dimension cannot leak into wall-thickness rows."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    x = 150
    page.draw_line((x, 50), (x, 250))
    page.draw_line((x - 25, 50), (x + 25, 50))
    page.draw_line((x - 25, 250), (x + 25, 250))
    page.insert_text((x + 4, 165), "4200", fontsize=9, rotate=90)
    doc = _reopen(doc)

    bundle = extract_dimension_evidence_bundle(doc[0], page_num=1, view_id="SYNTH")
    assert bundle.bindings
    assert bundle.bindings[0].status == BindingStatus.WITNESS_BOUND.value
    assert bundle.observations[0].orientation == "vertical"

    chains = extract_dimension_chains_from_page(doc[0], page_num=1, view_id="SYNTH")
    assert all(
        all(round(obs.value_m, 3) != 4.2 for obs in chain.observations)
        for chain in chains
    )
    doc.close()

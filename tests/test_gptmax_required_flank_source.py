"""A local orphan on the opposite flank is not the first missing source parent."""
from copy import deepcopy

import pytest

from tools.diag_gptmax_required_flank_source import required_flank_source_census


def source_report():
    sha = '1' * 64
    geometries = [(-5., -1., 0., -1.), (-5., 1., 0., 1.),
                  (10., -1., 15., -1.), (10., 1., 15., 1.),
                  (0., -1., 0., 1.), (10., -1., 10., 1.)]
    support = [{'requested_source_observation_id': f'support-{i}', 'source_observation_id': f'support-{i}',
                'source_receipt_authenticated': True, 'document_id': 'doc', 'revision_id': 'rev',
                'source_sha256': sha, 'snapshot_id': 'snap', 'page_id': '3', 'viewport_id': None,
                'observation_kind': 'raster_wall_band_face' if i < 4 else 'raster_wall_band_end',
                'original_source_support_geometry_pt': list(geometry)} for i, geometry in enumerate(geometries)]
    return {'source_sha256': sha, 'revision_id': 'rev', 'snapshot_id': 'snap', 'page_id': '3',
        'host_publication_allowed': False, 'opening_count_publication_allowed': False,
        'metric_quantity_publication_allowed': False, 'benchmark_accuracy': None,
        'opening_rows': [{'opening_identity_id': 'opening',
        'original_binding_reason_codes': ['raster_source_band_left_source_primitive_unmapped'],
        'original_g17_support_receipts': support,
        'original_g17_support_observation_ids': [r['source_observation_id'] for r in support],
        'original_aperture_coordinate_basis': {'origin': [0., 0.], 'axis': [1., 0.], 'normal': [0., 1.], 'length': 10., 'thickness': 2.},
        'source_w4_ancestry_audit': {'diagnostic_local_raster_lines': [
            {'source_primitive_id': 'right-orphan', 'original_source_line_pt': [10., 0., 15., 0.], 'exact_positive_ancestry_w4_candidate_ids': []}]}}]}


def audit(report):
    return required_flank_source_census(report, expected_source_sha='1' * 64)


def test_opposite_flank_orphan_never_becomes_required_missing_left_parent():
    report = source_report()
    before = deepcopy(report)
    result = audit(report)
    assert report == before
    left, right = result['opening_rows'][0]['flanks']
    assert left['role'] == 'left'
    assert left['reported_source_primitive_candidates'] == []
    assert left['no_qualifying_primitive_observed_in_reported_local_inventory']
    assert right['role'] == 'right'
    assert [r['source_primitive_id'] for r in right['reported_source_primitive_candidates']] == ['right-orphan']
    assert not result['source_universe_completeness_proven']
    assert not result['original_pdf_reauthenticated']
    assert not result['host_publication_allowed']
    assert not result['metric_quantity_publication_allowed']


def test_all_source_parent_owners_remain_alternatives_without_contact_or_equivalence():
    report = source_report()
    lines = report['opening_rows'][0]['source_w4_ancestry_audit']['diagnostic_local_raster_lines']
    lines.extend([{'source_primitive_id': 'left-parent', 'original_source_line_pt': [-5., 0., 0., 0.],
                   'exact_positive_ancestry_w4_candidate_ids': ['wall-b', 'wall-a']},
                  {'source_primitive_id': 'remote', 'original_source_line_pt': [-30., 0., -15., 0.],
                   'exact_positive_ancestry_w4_candidate_ids': ['remote-wall']},
                  {'source_primitive_id': 'cross-outside', 'original_source_line_pt': [-5., 100., 0., 100.],
                   'exact_positive_ancestry_w4_candidate_ids': ['cross-wall']}])
    result = audit(report)
    candidates = result['opening_rows'][0]['flanks'][0]['reported_source_primitive_candidates']
    assert [r['source_primitive_id'] for r in candidates] == ['left-parent']
    assert candidates[0]['reported_w4_candidate_alternatives'] == ['wall-a', 'wall-b']
    assert not candidates[0]['local_contact_proven']
    assert not candidates[0]['host_publication_allowed']
    assert not result['physical_equivalence_proven']
    lines.reverse()
    report['opening_rows'][0]['original_g17_support_receipts'].reverse()
    assert audit(report) == result


@pytest.mark.parametrize('field,value', [('source_sha256', 'foreign'), ('revision_id', 'foreign'),
    ('snapshot_id', 'foreign'), ('page_id', '4'), ('viewport_id', 'foreign'),
    ('source_receipt_authenticated', False)])
def test_foreign_or_unresolved_band_receipts_cannot_supply_flank_geometry(field, value):
    report = source_report()
    report['opening_rows'][0]['original_g17_support_receipts'][0][field] = value
    with pytest.raises(ValueError, match='source scope mismatch'):
        audit(report)


def test_missing_or_contradictory_sealed_end_remains_unknown_without_inferred_cap():
    report = source_report()
    report['opening_rows'][0]['original_g17_support_receipts'][-1]['original_source_support_geometry_pt'][0] = 11.
    result = audit(report)
    assert not result['opening_rows'][0]['reported_flank_geometry_available']
    assert result['opening_rows'][0]['flanks'] == []
    assert not result['host_publication_allowed']


def test_duplicate_raw_parent_address_cannot_silently_select_an_owner():
    report = source_report()
    lines = report['opening_rows'][0]['source_w4_ancestry_audit']['diagnostic_local_raster_lines']
    lines.append(deepcopy(lines[0]))
    with pytest.raises(ValueError, match='reported local source IDs'):
        audit(report)


def test_required_flank_candidates_survive_rotation_translation_and_reversed_source_direction():
    report = source_report()
    ordinary = audit(report)
    row = report['opening_rows'][0]
    def rotated(line):
        return [100.-line[1], 200.+line[0], 100.-line[3], 200.+line[2]]
    for receipt in row['original_g17_support_receipts']:
        receipt['original_source_support_geometry_pt'] = rotated(receipt['original_source_support_geometry_pt'])
    for line in row['source_w4_ancestry_audit']['diagnostic_local_raster_lines']:
        coords = rotated(line['original_source_line_pt'])
        line['original_source_line_pt'] = coords[2:] + coords[:2]
    row['original_aperture_coordinate_basis'].update(origin=[100., 200.], axis=[0., 1.], normal=[-1., 0.])
    transformed = audit(report)
    for left, right in zip(ordinary['opening_rows'][0]['flanks'], transformed['opening_rows'][0]['flanks']):
        assert left['axis_span_pt'] == right['axis_span_pt']
        assert left['normal_span_pt'] == right['normal_span_pt']
        assert [r['source_primitive_id'] for r in left['reported_source_primitive_candidates']] == [r['source_primitive_id'] for r in right['reported_source_primitive_candidates']]


def test_foreign_source_report_is_rejected_without_mutation():
    report = source_report()
    before = deepcopy(report)
    with pytest.raises(ValueError, match='original source SHA mismatch'):
        required_flank_source_census(report, expected_source_sha='2' * 64)
    assert report == before


@pytest.mark.parametrize('field,value', [('host_publication_allowed', True),
    ('opening_count_publication_allowed', True), ('metric_quantity_publication_allowed', True),
    ('benchmark_accuracy', 99.0)])
def test_publishing_report_cannot_enter_nonpublishing_flank_reader(field, value):
    report = source_report()
    report[field] = value
    with pytest.raises(ValueError, match='publication boundary'):
        audit(report)


@pytest.mark.parametrize('field', ['revision_id', 'snapshot_id', 'page_id'])
def test_missing_reported_source_scope_cannot_be_reconstructed(field):
    report = source_report()
    report[field] = None
    with pytest.raises(ValueError, match='lineage scope unavailable'):
        audit(report)

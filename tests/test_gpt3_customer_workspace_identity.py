"""Customer family bridges cannot coerce source workspace identities."""
import importlib
import inspect

import pytest


BRIDGES = (
    ("pb_live_opening_customer_projection", "project_live_opening_customer_rows", "LivePhysicalNetWallClaim"),
    ("pb_live_floor_area_customer_projection", "project_live_floor_area_customer_rows", "LivePhysicalNetWallClaim"),
    ("pb_live_ceiling_area_customer_projection", "project_live_ceiling_area_customer_rows", "LiveCeilingLiningResult"),
    ("pb_live_ceiling_customer_projection", "project_live_ceiling_customer_rows", "LivePhysicalNetWallClaim"),
    ("pb_live_floor_finish_customer_projection", "project_live_floor_finish_customer_rows", "LivePhysicalNetWallClaim"),
    ("pb_live_room_area_customer_projection", "project_live_room_area_customer_rows", "LivePhysicalNetWallClaim"),
)


@pytest.mark.parametrize("module_name,function_name,claim_type_name",BRIDGES)
@pytest.mark.parametrize("bad_workspace",[True,False,0,-1,1.0,1.5,"1"," 1",None,[],{}])
def test_noncanonical_workspace_blocked_before_any_customer_source_binding(
    module_name,function_name,claim_type_name,bad_workspace,monkeypatch,
):
    module=importlib.import_module(module_name)
    class EmptyClaim:
        opening_quantity_evidence=()
        opening_count_quantity_evidence=()
        ceiling_lining_quantity_evidence=()
        floor_finish_quantity_evidence=()
        room_area_quantity_evidence=()
    monkeypatch.setattr(module,claim_type_name,EmptyClaim)
    func=getattr(module,function_name)
    with pytest.raises(ValueError,match="workspace_id must be an authenticated positive integer"):
        func(EmptyClaim(),workspace_id=bad_workspace,project_id="project-1")


@pytest.mark.parametrize("module_name,function_name,claim_type_name",BRIDGES)
def test_positive_original_workspace_identity_reaches_only_supported_empty_path(
    module_name,function_name,claim_type_name,monkeypatch,
):
    module=importlib.import_module(module_name)
    class EmptyClaim:
        opening_quantity_evidence=()
        opening_count_quantity_evidence=()
        ceiling_lining_quantity_evidence=()
        floor_finish_quantity_evidence=()
        room_area_quantity_evidence=()
    monkeypatch.setattr(module,claim_type_name,EmptyClaim)
    if hasattr(module,"publish_live_floor_area_quantities"):
        monkeypatch.setattr(module,"publish_live_floor_area_quantities",lambda *_:())
    if hasattr(module,"publish_live_ceiling_area_quantities"):
        monkeypatch.setattr(module,"publish_live_ceiling_area_quantities",lambda *_:())
    if hasattr(module,"_firm_room_area_quantities"):
        monkeypatch.setattr(module,"_firm_room_area_quantities",lambda *_:())
    func=getattr(module,function_name)
    assert func(EmptyClaim(),workspace_id=7,project_id="project-1")==()


@pytest.mark.parametrize("module_name,function_name,claim_type_name",BRIDGES)
def test_gpt3_customer_bridges_never_truncate_workspace_before_source_trace(
    module_name,function_name,claim_type_name,
):
    module=importlib.import_module(module_name)
    source=inspect.getsource(getattr(module,function_name))
    assert "workspace_id=int(workspace_id)" not in source
    assert "type(workspace_id) is not int" in source

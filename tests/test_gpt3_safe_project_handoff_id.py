"""GPT3 project handoff filenames stay within their declared output root."""
import pytest
from tools.finalize_source_closed_project_handoff import finalize_split_project_handoff


@pytest.mark.parametrize("malformed",[
    "../escape", "../../parent", "/tmp/absolute", "subdir/project",
    "subdir\\project", ".", "..", "", " ", " project-a", "project-a ",
    "project\nnew", "project:a", None, 7, True,
])
def test_malformed_project_id_never_attempts_input_or_output_access(tmp_path,malformed):
    output=tmp_path/"output"
    with pytest.raises(ValueError,match="single canonical filename-safe token"):
        finalize_split_project_handoff(
            project_id=malformed,input_dir=tmp_path,output_dir=output,
        )
    assert not output.exists()


def test_normal_project_id_reaches_original_missing_source_gate(tmp_path):
    with pytest.raises(FileNotFoundError,match="no split sealed runs"):
        finalize_split_project_handoff(
            project_id="au_qld_maryborough_service_station",
            input_dir=tmp_path,output_dir=tmp_path/"output",
        )

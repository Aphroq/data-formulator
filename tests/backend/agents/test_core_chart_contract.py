from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

from data_formulator.analyst.skills import build_registry
from data_formulator.analyst.skills.base import SkillContext
from data_formulator.analyst.skills.core.skill import CoreSkill


pytestmark = [pytest.mark.backend]


def test_visualize_schema_requires_title_and_exposes_subtitle():
    registry = build_registry()
    visualize = next(
        spec for spec in registry.action_tools_for(["core"])
        if spec["function"]["name"] == "visualize"
    )
    parameters = visualize["function"]["parameters"]

    assert "title" in parameters["required"]
    assert "input_tables" in parameters["required"]
    assert "subtitle" in parameters["properties"]
    subtitle_description = parameters["properties"]["subtitle"]["description"]
    assert "at most 16 words" in subtitle_description
    assert "Do not restate the measure or analytical lens" in subtitle_description


def test_visualize_handler_forwards_title_and_subtitle():
    runtime = MagicMock()
    runtime.run_visualize_code.return_value = {
        "status": "error",
        "error_message": "stop after argument capture",
    }
    workspace = MagicMock()
    workspace.get_table_metadata.return_value = MagicMock()
    ctx = SkillContext(client=None, workspace=workspace, runtime=runtime)

    list(CoreSkill()._handle_visualize({
        "title": "Growth Accelerated After 2020",
        "subtitle": "US monthly index, January 2006 = 100",
        "code": "result_df = source",
        "input_tables": ["source"],
        "output_variable": "result_df",
        "chart": {"chart_type": "Line Chart", "encodings": {}},
    }, ctx))

    runtime.run_visualize_code.assert_called_once()
    kwargs = runtime.run_visualize_code.call_args.kwargs
    assert kwargs["title"] == "Growth Accelerated After 2020"
    assert kwargs["subtitle"] == "US monthly index, January 2006 = 100"
    assert kwargs["input_tables"] == ["source"]


def test_visualize_records_signed_artifact_ids_before_emitting_result(monkeypatch):
    monkeypatch.delenv("DF_CODE_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    runtime = MagicMock()
    runtime.run_visualize_code.return_value = {
        "status": "ok",
        "transform_result": {
            "status": "ok",
            "chart_id": "chart-abc",
            "code": "result_df = source.copy()",
            "content": {
                "rows": [{"value": 1}],
                "virtual": {"table_name": "derived", "row_count": 1},
            },
        },
    }
    runtime.record_visualize_artifacts.return_value = {
        "status": "ok",
        "transform_artifact_id": "art_" + "1" * 64,
        "chart_artifact_id": "art_" + "2" * 64,
    }
    workspace = MagicMock()
    workspace.get_table_metadata.return_value = MagicMock()
    ctx = SkillContext(client=None, workspace=workspace, runtime=runtime)
    action = {
        "title": "Values",
        "subtitle": "Current selection",
        "display_instruction": "Inspect values",
        "input_tables": ["source"],
        "code": "result_df = source.copy()",
        "output_variable": "result_df",
        "chart": {"chart_type": "Table", "encodings": {}},
        "field_metadata": {},
        "field_display_names": {},
    }

    app = Flask(__name__)
    app.secret_key = "process-local-interactive-secret"
    app.config["AUTOMATION_ENABLED"] = False
    with app.app_context():
        events = list(CoreSkill()._handle_visualize(action, ctx))

    record_kwargs = runtime.record_visualize_artifacts.call_args.kwargs
    assert record_kwargs["transform_result"]["code_signature"]
    result = events[-1]["content"]["result"]
    assert result["transform_artifact_id"] == "art_" + "1" * 64
    assert result["chart_artifact_id"] == "art_" + "2" * 64
    assert result["lineage"]["status"] == "ok"


def test_visualize_rejects_undeclared_or_unknown_inputs_before_sandbox():
    runtime = MagicMock()
    workspace = MagicMock()
    workspace.get_table_metadata.return_value = None
    ctx = SkillContext(client=None, workspace=workspace, runtime=runtime)

    events = list(CoreSkill()._handle_visualize({
        "title": "Values",
        "input_tables": ["missing"],
        "code": "result_df = missing.copy()",
        "output_variable": "result_df",
        "chart": {"chart_type": "Table", "encodings": {}},
    }, ctx))

    assert events[-1]["type"] == "error"
    assert "missing" in events[-1]["message"]
    runtime.run_visualize_code.assert_not_called()

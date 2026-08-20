from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from data_formulator.automation.report_analysis import (
    AutomationReportAnalysisError,
    analyze_automation_report,
)


pytestmark = [pytest.mark.backend]


class _Client:
    model = "test-model"

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.messages: list[dict] | None = None
        self.reasoning_effort: str | None = None
        self.timeout: int | float | None = None

    def get_completion(self, messages, *, reasoning_effort, timeout):
        self.messages = messages
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(self.payload, ensure_ascii=False),
        ))])


def _report() -> dict:
    return {
        "title": "Movies by genre",
        "description": "Summarize one selected movie genre.",
        "parameters": [{
            "id": "major_genre",
            "name": "Movie genre",
            "description": "Genre included in this run.",
            "type": "string",
        }],
        "steps": [
            {"step_id": "load", "kind": "load", "title": "Movies"},
            {"step_id": "transform", "kind": "transform", "title": "genre_summary"},
            {"step_id": "chart", "kind": "chart", "title": "Movies by genre"},
        ],
    }


def _outputs() -> tuple[dict, ...]:
    return ({
        "step_id": "chart",
        "kind": "chart",
        "title": "Movies by genre",
        "subtitle": "Selected segment",
        "display_instruction": "Compare count and worldwide gross.",
        "chart": {
            "spec": {
                "chart_type": "Bar Chart",
                "encodings": {"x": "Major Genre", "y": "movie_count"},
            },
        },
        "table": {
            "name": "genre_summary",
            "row_count": 1,
            "column_count": 3,
            "columns": [
                {"name": "Major Genre", "type": "string"},
                {"name": "movie_count", "type": "integer"},
                {"name": "Worldwide Gross", "type": "integer"},
            ],
            "rows": [{
                "Major Genre": "Comedy",
                "movie_count": 675,
                "Worldwide Gross": 50_384_049_282,
            }],
            "rows_truncated": False,
            "columns_truncated": False,
        },
    },)


def test_report_analysis_is_concise_grounded_and_uses_run_context() -> None:
    client = _Client({
        "summary": "Comedy has 675 movies in this saved run.",
        "insights": [
            {
                "finding": "The selected segment is substantial.",
                "evidence": "The result contains 675 Comedy movies.",
            },
            {
                "finding": "Worldwide gross is high in aggregate.",
                "evidence": "The saved total is 50,384,049,282.",
            },
        ],
        "caveat": "This single run does not compare Comedy with other genres.",
    })

    analysis = analyze_automation_report(
        client,
        report=_report(),
        outputs=_outputs(),
        parameter_values={"major_genre": "Comedy"},
        language_code="en",
        timeout_seconds=45,
    )

    assert analysis.to_dict() == client.payload
    assert client.reasoning_effort in {"minimal", "low", "none"}
    assert client.timeout == 45
    prompt = client.messages[1]["content"]
    assert "Comedy" in prompt
    assert "50384049282" in prompt
    assert "load" in prompt and "transform" in prompt and "chart" in prompt


def test_report_analysis_bounds_data_sent_to_the_model() -> None:
    client = _Client({
        "summary": "The saved result is available.",
        "insights": [{"finding": "Rows exist.", "evidence": "The table is non-empty."}],
        "caveat": "",
    })
    columns = [{"name": f"column_{index}", "type": "string"} for index in range(50)]
    rows = [
        {column["name"]: "x" * 2_000 for column in columns}
        for _ in range(100)
    ]
    output = {
        **_outputs()[0],
        "table": {
            **_outputs()[0]["table"],
            "row_count": 100,
            "column_count": 50,
            "columns": columns,
            "rows": rows,
        },
    }

    analyze_automation_report(
        client,
        report=_report(),
        outputs=(output,),
        parameter_values={"major_genre": "Comedy"},
    )

    assert len(client.messages[1]["content"].encode("utf-8")) <= 70_000


@pytest.mark.parametrize(
    "payload",
    [
        {"summary": "Missing evidence", "insights": [], "caveat": ""},
        {
            "summary": "Too many findings",
            "insights": [
                {"finding": str(index), "evidence": "value"}
                for index in range(4)
            ],
            "caveat": "",
        },
        {
            "summary": "Unexpected shape",
            "insights": [{"finding": "A", "evidence": "B", "extra": True}],
            "caveat": "",
        },
    ],
)
def test_report_analysis_fails_closed_on_invalid_model_output(payload: object) -> None:
    with pytest.raises(AutomationReportAnalysisError):
        analyze_automation_report(
            _Client(payload),
            report=_report(),
            outputs=_outputs(),
            parameter_values={"major_genre": "Comedy"},
        )

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Explicit, post-Run AI interpretation of verified Automation results.

This module is deliberately outside the Scheduler/Worker execution path.  It
does not change a Run, persist another artifact, or create a second Agent
runtime.  A user must request it from an already successful, verified result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from data_formulator.agent_config import reasoning_effort_for
from data_formulator.agents.agent_utils import extract_json_objects
from data_formulator.agents.client_utils import Client


_MAX_CONTEXT_BYTES = 60_000
_MAX_OUTPUTS = 10
_MAX_STEPS = 50
_MAX_PARAMETERS = 20
_MAX_COLUMNS = 20
_MAX_ROWS_PER_OUTPUT = 20
_MAX_VALUE_CHARS = 500

_SYSTEM_PROMPT = """\
You analyze one completed deterministic Automation Run at the user's explicit
request. Use ONLY the supplied immutable Recipe context, frozen parameter
values, and saved output samples. Never claim a comparison, trend, cause, or
business conclusion that the supplied evidence does not support.

Keep the result useful and short:
- summary: one sentence stating the most important supported result.
- insights: one to three findings. Each finding must include concrete evidence
  from the supplied saved rows, counts, or values.
- caveat: one material limitation when needed, otherwise an empty string.

Write in the requested UI language. Do not describe internal execution steps
unless they materially limit interpretation. Return JSON only with this exact
shape:
{"summary":"...","insights":[{"finding":"...","evidence":"..."}],"caveat":""}
"""


class AutomationReportAnalysisError(ValueError):
    """The model response is not a safe, concise report interpretation."""


def _text(value: Any, *, field: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise AutomationReportAnalysisError(f"Invalid {field}")
    normalized = value.strip()
    if required and not normalized:
        raise AutomationReportAnalysisError(f"Missing {field}")
    if len(normalized) > limit:
        raise AutomationReportAnalysisError(f"{field} is too long")
    return normalized


@dataclass(frozen=True, slots=True)
class AutomationReportInsight:
    finding: str
    evidence: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "finding",
            _text(self.finding, field="analysis finding", limit=240),
        )
        object.__setattr__(
            self,
            "evidence",
            _text(self.evidence, field="analysis evidence", limit=600),
        )

    def to_dict(self) -> dict[str, str]:
        return {"finding": self.finding, "evidence": self.evidence}


@dataclass(frozen=True, slots=True)
class AutomationReportAnalysis:
    summary: str
    insights: tuple[AutomationReportInsight, ...]
    caveat: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "summary",
            _text(self.summary, field="analysis summary", limit=600),
        )
        if not 1 <= len(self.insights) <= 3:
            raise AutomationReportAnalysisError(
                "Analysis must contain one to three insights"
            )
        object.__setattr__(
            self,
            "caveat",
            _text(
                self.caveat,
                field="analysis caveat",
                limit=600,
                required=False,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "insights": [item.to_dict() for item in self.insights],
            "caveat": self.caveat,
        }


def _parse_analysis(content: str) -> AutomationReportAnalysis:
    objects = extract_json_objects(content + "\n")
    payload = next(
        (
            item
            for item in objects
            if isinstance(item, Mapping) and "insights" in item
        ),
        None,
    )
    if payload is None or set(payload) != {"summary", "insights", "caveat"}:
        raise AutomationReportAnalysisError("Missing report analysis")
    raw_insights = payload["insights"]
    if not isinstance(raw_insights, list) or not 1 <= len(raw_insights) <= 3:
        raise AutomationReportAnalysisError("Invalid report insights")

    insights: list[AutomationReportInsight] = []
    for raw in raw_insights:
        if not isinstance(raw, Mapping) or set(raw) != {"finding", "evidence"}:
            raise AutomationReportAnalysisError("Invalid report insight")
        insights.append(AutomationReportInsight(
            finding=raw["finding"],
            evidence=raw["evidence"],
        ))
    return AutomationReportAnalysis(
        summary=payload["summary"],
        insights=tuple(insights),
        caveat=payload["caveat"],
    )


def _bounded_text(value: Any, limit: int = _MAX_VALUE_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    return normalized if len(normalized) <= limit else normalized[:limit] + "…"


def _bounded_value(value: Any) -> Any:
    if value is None or type(value) in {bool, int, float}:
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    return _bounded_text(str(value))


def _report_context(
    *,
    report: Mapping[str, Any],
    outputs: Sequence[Mapping[str, Any]],
    parameter_values: Mapping[str, Any],
) -> str:
    raw_steps = report.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    raw_parameters = report.get("parameters")
    parameter_definitions = (
        raw_parameters if isinstance(raw_parameters, list) else []
    )
    truncated = (
        len(steps) > _MAX_STEPS
        or len(parameter_definitions) > _MAX_PARAMETERS
        or len(outputs) > _MAX_OUTPUTS
        or len(parameter_values) > _MAX_PARAMETERS
    )
    payload: dict[str, Any] = {
        "report": {
            "title": _bounded_text(report.get("title"), 240),
            "description": _bounded_text(report.get("description"), 1_000),
            "parameters": [
                {
                    "id": _bounded_text(item.get("id"), 200),
                    "name": _bounded_text(item.get("name"), 240),
                    "type": _bounded_text(item.get("type"), 40),
                }
                for item in parameter_definitions[:_MAX_PARAMETERS]
                if isinstance(item, Mapping)
            ],
            "steps": [
                {
                    "kind": _bounded_text(item.get("kind"), 40),
                    "title": _bounded_text(item.get("title"), 240),
                }
                for item in steps[:_MAX_STEPS]
                if isinstance(item, Mapping)
            ],
        },
        "parameter_values": {
            _bounded_text(key, 200): _bounded_value(value)
            for key, value in list(parameter_values.items())[:_MAX_PARAMETERS]
        },
        "outputs": [],
        "context_truncated": truncated,
    }

    output_entries: list[tuple[dict[str, Any], Sequence[Any], list[str]]] = []
    for output in outputs[:_MAX_OUTPUTS]:
        if not isinstance(output, Mapping):
            continue
        table = output.get("table")
        if not isinstance(table, Mapping):
            continue
        raw_columns = table.get("columns")
        columns = raw_columns if isinstance(raw_columns, list) else []
        selected_columns = [
            _bounded_text(item.get("name"), 200)
            for item in columns[:_MAX_COLUMNS]
            if isinstance(item, Mapping) and _bounded_text(item.get("name"), 200)
        ]
        raw_rows = table.get("rows")
        rows = raw_rows if isinstance(raw_rows, list) else []
        chart = output.get("chart")
        chart_spec = chart.get("spec") if isinstance(chart, Mapping) else None
        raw_encodings = (
            chart_spec.get("encodings")
            if isinstance(chart_spec, Mapping)
            else None
        )
        chart_encodings = (
            raw_encodings if isinstance(raw_encodings, Mapping) else {}
        )
        entry = {
            "kind": _bounded_text(output.get("kind"), 40),
            "title": _bounded_text(output.get("title"), 240),
            "description": _bounded_text(
                output.get("display_instruction") or output.get("subtitle"),
                500,
            ),
            "chart": (
                {
                    "type": _bounded_text(chart_spec.get("chart_type"), 100),
                    "encodings": {
                        _bounded_text(key, 100): _bounded_text(value, 200)
                        for key, value in chart_encodings.items()
                        if isinstance(key, str) and isinstance(value, str)
                    },
                }
                if isinstance(chart_spec, Mapping)
                else None
            ),
            "table": {
                "name": _bounded_text(table.get("name"), 240),
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count"),
                "columns": selected_columns,
                "rows": [],
                "sample_truncated": (
                    len(rows) > _MAX_ROWS_PER_OUTPUT
                    or len(columns) > _MAX_COLUMNS
                ),
            },
        }
        payload["outputs"].append(entry)
        output_entries.append((entry, rows, selected_columns))

    for entry, rows, selected_columns in output_entries:
        for raw_row in rows[:_MAX_ROWS_PER_OUTPUT]:
            if not isinstance(raw_row, Mapping):
                continue
            row = {
                name: _bounded_value(raw_row.get(name))
                for name in selected_columns
            }
            entry["table"]["rows"].append(row)
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded) > _MAX_CONTEXT_BYTES:
                entry["table"]["rows"].pop()
                entry["table"]["sample_truncated"] = True
                payload["context_truncated"] = True
                break

    encoded_context = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(encoded_context.encode("utf-8")) > _MAX_CONTEXT_BYTES:
        raise AutomationReportAnalysisError("Run context exceeds the safe limit")
    return encoded_context


def analyze_automation_report(
    client: Client,
    *,
    report: Mapping[str, Any],
    outputs: Sequence[Mapping[str, Any]],
    parameter_values: Mapping[str, Any],
    language_code: str = "en",
    timeout_seconds: int | float = 120,
) -> AutomationReportAnalysis:
    """Interpret one verified result after an explicit user action."""
    context = _report_context(
        report=report,
        outputs=outputs,
        parameter_values=parameter_values,
    )
    response = client.get_completion(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"UI language code: {language_code or 'en'}\n"
                    "Verified Automation Run context:\n"
                    f"{context}"
                ),
            },
        ],
        reasoning_effort=reasoning_effort_for("workflow_distill", client.model),
        timeout=timeout_seconds,
    )
    try:
        content = response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError) as exc:
        raise AutomationReportAnalysisError(
            "Model returned no report analysis"
        ) from exc
    return _parse_analysis(content)

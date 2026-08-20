from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from data_formulator.recipes.compiler import RecipeParameterCandidate
from data_formulator.recipes.parameter_suggestions import (
    RecipeParameterSuggestionError,
    suggest_recipe_parameter_configurations,
)
from data_formulator.recipes.spec import BindingTarget, ParameterBinding, ParameterType


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
        content = json.dumps(self.payload, ensure_ascii=False)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


def _candidates() -> tuple[RecipeParameterCandidate, ...]:
    return (
        RecipeParameterCandidate(
            candidate_id="cand_111111111111",
            parameter_id="region",
            kind="filter",
            name="region",
            value_type=ParameterType.STRING,
            default_value="west",
            binding=ParameterBinding(
                parameter_id="region",
                step_id="step_" + "a" * 64,
                target=BindingTarget.LOAD_FILTER_VALUE,
                filter_index=0,
            ),
        ),
        RecipeParameterCandidate(
            candidate_id="cand_222222222222",
            parameter_id="row_limit",
            kind="limit",
            name="Row limit",
            value_type=ParameterType.INTEGER,
            default_value=100,
            binding=ParameterBinding(
                parameter_id="row_limit",
                step_id="step_" + "a" * 64,
                target=BindingTarget.LOAD_LIMIT,
            ),
        ),
    )


def test_parameter_suggestions_reuse_workflow_context_and_only_return_known_slots() -> None:
    client = _Client({
        "suggestions": [
            {
                "candidate_id": "cand_111111111111",
                "name": "销售区域",
                "description": "本次运行包含的区域。",
                "mode": "ask",
            },
            {
                "candidate_id": "cand_999999999999",
                "name": "虚构参数",
                "description": "不应进入结果。",
                "mode": "keep",
            },
            {
                "candidate_id": "cand_111111111111",
                "name": "重复区域",
                "description": "重复建议应被忽略。",
                "mode": "keep",
            },
        ],
        "unmatched": ["Top N", "Top N", ""],
    })

    suggestions = suggest_recipe_parameter_configurations(
        client,
        _candidates(),
        workflow_context={
            "threads": [{
                "thread_id": "thread-1",
                "events": [{
                    "type": "message",
                    "from": "user",
                    "to": "data-agent",
                    "role": "user",
                    "content": "比较不同区域的销售额",
                }],
            }],
        },
        recipe_name="区域销售额",
        language_code="zh",
        timeout_seconds=45,
    )

    assert suggestions.to_dict() == {
        "suggestions": [{
            "candidate_id": "cand_111111111111",
            "name": "销售区域",
            "description": "本次运行包含的区域。",
            "mode": "ask",
        }],
        "unmatched": ["Top N"],
    }
    assert client.reasoning_effort in {"minimal", "low", "none"}
    assert client.timeout == 45
    prompt = client.messages[1]["content"]
    assert "比较不同区域的销售额" in prompt
    assert "cand_111111111111" in prompt
    assert prompt.index("Relevant analysis workflow context") < prompt.index(
        "Available typed binding candidates"
    )


def test_parameter_suggestions_allow_no_match_and_normalize_noncritical_metadata() -> None:
    result = suggest_recipe_parameter_configurations(
        _Client({
            "suggestions": [{
                "candidate_id": "cand_111111111111",
                "name": "",
                "description": 42,
                "mode": "sometimes",
            }],
            "unmatched": [],
        }),
        _candidates(),
    )

    assert result.to_dict() == {
        "suggestions": [{
            "candidate_id": "cand_111111111111",
            "name": "region",
            "description": "",
            "mode": "keep",
        }],
        "unmatched": [],
    }
    assert suggest_recipe_parameter_configurations(
        _Client({"suggestions": [], "unmatched": []}),
        _candidates(),
    ).to_dict() == {"suggestions": [], "unmatched": []}


def test_parameter_suggestions_can_explain_a_meaningful_choice_without_candidates() -> None:
    client = _Client({"suggestions": [], "unmatched": ["Top 10 movies"]})

    result = suggest_recipe_parameter_configurations(
        client,
        (),
        workflow_context={
            "threads": [{
                "thread_id": "movies",
                "events": [{
                    "type": "message",
                    "from": "user",
                    "to": "data-agent",
                    "role": "user",
                    "content": "Show the top 10 movies by profit.",
                }],
            }],
        },
    )

    assert result.to_dict() == {
        "suggestions": [],
        "unmatched": ["Top 10 movies"],
    }
    assert "Available typed binding candidates" in client.messages[1]["content"]


def test_parameter_suggestions_reject_only_a_malformed_top_level_response() -> None:
    with pytest.raises(RecipeParameterSuggestionError):
        suggest_recipe_parameter_configurations(
            _Client({"not_suggestions": []}),
            _candidates(),
        )

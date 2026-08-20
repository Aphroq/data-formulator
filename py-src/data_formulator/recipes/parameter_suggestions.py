# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Semantic, authoring-time recommendations for compiler-owned Recipe slots.

This module never creates bindings and is never used by Recipe execution. The
workflow context decides which choices matter; the compiler remains the source
of truth for candidate ids, types and targets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import re
from typing import Any

from data_formulator.agent_config import reasoning_effort_for
from data_formulator.agents.agent_utils import extract_json_objects
from data_formulator.agents.agent_workflow_distill import WorkflowDistillAgent
from data_formulator.agents.client_utils import Client
from data_formulator.recipes.compiler import RecipeParameterCandidate


_MAX_RECOMMENDATIONS = 4


_SYSTEM_PROMPT = """\
You help a user turn a finished analysis into a deterministic Recipe.

First read the analysis workflow and identify the FEW choices that materially
change the result and that a user may want to revisit on later manual or
scheduled runs. Usually there are 0-4. A period, category filter, threshold,
or top-N may matter; a technical row cap usually does not. It is better to
recommend nothing than to expose a value with no clear user value.

Then use the typed binding candidates only as an availability map:
- Put a meaningful choice in "suggestions" only when one supplied candidate
  represents it. Use that candidate_id verbatim.
- Put a short user-facing name in "unmatched" when the choice matters but no
  supplied candidate represents it. Do not invent a candidate or binding.
- Do not return an entry for every candidate. Return at most four choices in
  total across "suggestions" and "unmatched".

For each matched suggestion provide a short label, one sentence explaining
its effect, and mode "ask" when the user should normally choose it per run or
"keep" when the current value is a useful default.

Return JSON only, with this exact shape:
{"suggestions":[{"candidate_id":"cand_...","name":"...","description":"...","mode":"ask"}],"unmatched":["..."]}
"""


class RecipeParameterSuggestionError(ValueError):
    """The model response could not be reduced to safe candidate metadata."""


@dataclass(frozen=True, slots=True)
class RecipeParameterSuggestion:
    candidate_id: str
    name: str
    description: str
    mode: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.candidate_id, str)
            or not re.fullmatch(r"cand_[0-9a-f]{12}", self.candidate_id)
        ):
            raise RecipeParameterSuggestionError("Invalid candidate id")
        if not isinstance(self.name, str) or not self.name.strip():
            raise RecipeParameterSuggestionError("Invalid candidate name")
        name = self.name.strip()
        if len(name) > 200:
            raise RecipeParameterSuggestionError("Candidate name is too long")
        if not isinstance(self.description, str):
            raise RecipeParameterSuggestionError("Invalid candidate description")
        description = self.description.strip()
        if len(description) > 500:
            raise RecipeParameterSuggestionError("Candidate description is too long")
        if not isinstance(self.mode, str) or self.mode not in {"ask", "keep"}:
            raise RecipeParameterSuggestionError("Invalid candidate mode")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class RecipeParameterSuggestionResult:
    suggestions: tuple[RecipeParameterSuggestion, ...]
    unmatched: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestions": [item.to_dict() for item in self.suggestions],
            "unmatched": list(self.unmatched),
        }


def _text_or_default(value: Any, default: str, limit: int) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return (text or default.strip())[:limit].strip()


def _parse_suggestions(
    content: str,
    candidates: Sequence[RecipeParameterCandidate],
) -> RecipeParameterSuggestionResult:
    objects = extract_json_objects(content + "\n")
    payload = next(
        (
            item for item in objects
            if isinstance(item, Mapping) and "suggestions" in item
        ),
        None,
    )
    if payload is None:
        raise RecipeParameterSuggestionError("Missing parameter suggestions")
    raw_suggestions = payload.get("suggestions")
    if not isinstance(raw_suggestions, list):
        raise RecipeParameterSuggestionError("Invalid parameter suggestions")

    candidates_by_id = {item.candidate_id: item for item in candidates}
    parsed: list[RecipeParameterSuggestion] = []
    seen_ids: set[str] = set()
    for raw in raw_suggestions:
        if len(parsed) >= _MAX_RECOMMENDATIONS or not isinstance(raw, Mapping):
            continue
        candidate_id = raw.get("candidate_id")
        if (
            not isinstance(candidate_id, str)
            or candidate_id in seen_ids
            or candidate_id not in candidates_by_id
        ):
            continue
        candidate = candidates_by_id[candidate_id]
        mode = raw.get("mode")
        parsed.append(RecipeParameterSuggestion(
            candidate_id=candidate_id,
            name=_text_or_default(raw.get("name"), candidate.name, 200),
            description=_text_or_default(
                raw.get("description"), candidate.description, 500
            ),
            mode=mode if mode in {"ask", "keep"} else "keep",
        ))
        seen_ids.add(candidate_id)

    unmatched: list[str] = []
    seen_unmatched: set[str] = set()
    raw_unmatched = payload.get("unmatched", [])
    if isinstance(raw_unmatched, list):
        for raw in raw_unmatched:
            if len(parsed) + len(unmatched) >= _MAX_RECOMMENDATIONS:
                break
            label = _text_or_default(raw, "", 200)
            folded = label.casefold()
            if not label or folded in seen_unmatched:
                continue
            unmatched.append(label)
            seen_unmatched.add(folded)

    return RecipeParameterSuggestionResult(
        suggestions=tuple(parsed),
        unmatched=tuple(unmatched),
    )


def suggest_recipe_parameter_configurations(
    client: Client,
    candidates: Sequence[RecipeParameterCandidate],
    *,
    workflow_context: Mapping[str, Any] | None = None,
    recipe_name: str = "",
    description: str = "",
    language_code: str = "en",
    timeout_seconds: int | float = 120,
) -> RecipeParameterSuggestionResult:
    """Recommend meaningful workflow choices and map them to known candidates."""
    candidate_tuple = tuple(candidates)

    context = dict(workflow_context) if workflow_context is not None else {}
    context_summary = WorkflowDistillAgent._extract_context_summary(context)
    candidate_payload = [item.to_dict() for item in candidate_tuple]
    user_prompt = (
        f"UI language code: {language_code or 'en'}\n"
        f"Recipe name: {recipe_name.strip()}\n"
        f"Recipe description: {description.strip()}\n\n"
        "Relevant analysis workflow context (judge meaning from this first):\n"
        f"{context_summary[:60_000]}\n\n"
        "Available typed binding candidates (use only to map those choices):\n"
        f"{json.dumps(candidate_payload, ensure_ascii=False, separators=(',', ':'))}"
    )
    response = client.get_completion(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        reasoning_effort=reasoning_effort_for("workflow_distill", client.model),
        timeout=timeout_seconds,
    )
    try:
        content = response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError) as exc:
        raise RecipeParameterSuggestionError(
            "Model returned no parameter suggestions"
        ) from exc
    return _parse_suggestions(content, candidate_tuple)

from __future__ import annotations

import pytest

from data_formulator.recipes.transform_parameters import (
    normalize_transform_parameter_slots,
    validate_parameterized_transform_code,
)


pytestmark = [pytest.mark.backend]


def _slot(
    slot_id: str,
    *,
    value_type: str = "string",
    default="value",
):
    return normalize_transform_parameter_slots([{
        "id": slot_id,
        "name": slot_id.replace("_", " ").title(),
        "description": "A meaningful deterministic analysis setting.",
        "type": value_type,
        "default": default,
    }])


@pytest.mark.parametrize(
    ("code", "slots"),
    [
        (
            "result_df = orders.loc[orders['amount'] >= "
            "params['minimum_amount']].copy()",
            _slot("minimum_amount", value_type="number", default=10),
        ),
        (
            "result_df = summary.head(params['top_n'])",
            _slot("top_n", value_type="integer", default=5),
        ),
        (
            "result_df = orders.assign("
            "moving=orders['amount'].rolling(params['window']).mean())",
            _slot("window", value_type="integer", default=7),
        ),
        (
            "result_df = orders.loc[orders['region'] == params['region']]",
            _slot("region", default="west"),
        ),
        (
            "result_df = orders.loc[orders['date'] >= "
            "pd.Timestamp(params['start_date'])]",
            _slot("start_date", value_type="date", default="2026-01-01"),
        ),
    ],
    ids=("threshold", "top-n", "window", "category", "date"),
)
def test_useful_scalar_transform_contexts_are_allowed(code, slots) -> None:
    validate_parameterized_transform_code(code, slots)


@pytest.mark.parametrize(
    ("code", "slots"),
    [
        (
            "result_df = pd.read_csv(params['filename'])",
            _slot("filename", default="orders.csv"),
        ),
        (
            "result_df = pd.read_sql_query(params['query'], connection)",
            _slot("query", default="select * from orders"),
        ),
        (
            "result_df = orders.sort_values(params['column_name'])",
            _slot("column_name", default="amount"),
        ),
        (
            "result_df = params['callable_name']()",
            _slot("callable_name", default="head"),
        ),
        (
            "filename = params['filename']\n"
            "result_df = pd.read_csv(filename)",
            _slot("filename", default="orders.csv"),
        ),
        (
            "def choose(params):\n"
            "    return orders.head(params['top_n'])\n"
            "result_df = choose({'top_n': 1})",
            _slot("top_n", value_type="integer", default=5),
        ),
        (
            "def head(value):\n"
            "    return pd.read_csv(value)\n"
            "result_df = head(params['filename'])",
            _slot("filename", default="orders.csv"),
        ),
    ],
    ids=(
        "file",
        "sql",
        "column",
        "callable",
        "aliased-file",
        "shadowed-params",
        "local-callable",
    ),
)
def test_structural_or_executable_transform_contexts_are_rejected(
    code,
    slots,
) -> None:
    with pytest.raises(ValueError, match="Transform parameters"):
        validate_parameterized_transform_code(code, slots)

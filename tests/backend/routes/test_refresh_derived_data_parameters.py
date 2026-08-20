from __future__ import annotations

from unittest.mock import patch

import flask
import pandas as pd
import pytest

from data_formulator.error_handler import register_error_handlers
from data_formulator.errors import ErrorCode
from data_formulator.routes.agents import agent_bp
from data_formulator.security.code_signing import sign_code


pytestmark = [pytest.mark.backend]


class _Sandbox:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_python_code(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "ok",
            "content": pd.DataFrame({"value": [1, 2, 3]}),
        }


@pytest.fixture()
def app():
    test_app = flask.Flask(__name__)
    test_app.config.update(
        TESTING=True,
        CLI_ARGS={"sandbox": "local", "max_display_rows": 5000},
    )
    test_app.register_blueprint(agent_bp)
    register_error_handlers(test_app)
    return test_app


def _body(code: str, slots: list[dict]) -> dict:
    return {
        "input_tables": [{"name": "orders", "rows": [{"value": 1}]}],
        "code": code,
        "code_signature": sign_code(code),
        "output_variable": "result_df",
        "parameter_slots": slots,
        "virtual": False,
    }


def test_refresh_injects_declared_defaults_separately_from_signed_code(app) -> None:
    sandbox = _Sandbox()
    code = "result_df = orders.head(params['top_n'])"
    slots = [{
        "id": "top_n",
        "name": "Top rows",
        "description": "Number of rows kept in the refreshed result.",
        "type": "integer",
        "default": 3,
    }]

    with (
        patch("data_formulator.routes.agents.get_identity_id", return_value="user:1"),
        patch("data_formulator.routes.agents.get_workspace", return_value=object()),
        patch("data_formulator.sandbox.create_sandbox", return_value=sandbox),
        app.test_client() as client,
    ):
        response = client.post(
            "/api/agent/refresh-derived-data",
            json=_body(code, slots),
        )

    assert response.status_code == 200
    assert response.get_json()["data"]["row_count"] == 3
    assert len(sandbox.calls) == 1
    assert sandbox.calls[0]["code"] == code
    assert sandbox.calls[0]["parameters"] == {"top_n": 3}


def test_refresh_rejects_parameter_driven_dynamic_column_selection(app) -> None:
    sandbox = _Sandbox()
    code = "result_df = orders[[params['column_name']]]"
    slots = [{
        "id": "column_name",
        "name": "Column",
        "description": "Attempted dynamic column selection.",
        "type": "string",
        "default": "value",
    }]

    with (
        patch("data_formulator.sandbox.create_sandbox", return_value=sandbox),
        app.test_client() as client,
    ):
        response = client.post(
            "/api/agent/refresh-derived-data",
            json=_body(code, slots),
        )

    # The agent blueprint keeps the legacy HTTP-200 error envelope.
    assert response.status_code == 200
    assert response.get_json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert sandbox.calls == []

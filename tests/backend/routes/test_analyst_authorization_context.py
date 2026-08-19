# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import flask
import pytest


pytestmark = [pytest.mark.backend]


@pytest.fixture()
def agents_client():
    from data_formulator.routes.agents import agent_bp

    app = flask.Flask(__name__)
    app.config["TESTING"] = True
    app.config["CLI_ARGS"] = {}
    app.register_blueprint(agent_bp)
    return app.test_client()


def test_analyst_uses_backend_authorized_workspace_not_request_payload(
    agents_client,
) -> None:
    workspace = SimpleNamespace(user_home=None)

    with (
        patch(
            "data_formulator.routes.agents.get_identity_id",
            return_value="user:42",
        ),
        patch(
            "data_formulator.routes.agents.get_workspace",
            return_value=workspace,
        ),
        patch(
            "data_formulator.routes.agents.get_client",
            return_value=object(),
        ),
        patch("data_formulator.routes.agents.AnalystAgent") as analyst_agent,
    ):
        analyst_agent.return_value.run.return_value = iter([{
            "type": "completion",
            "message": "done",
        }])
        response = agents_client.post(
            "/api/agent/analyst-streaming",
            headers={"X-Workspace-Id": "workspace-authorized"},
            json={
                "model": {},
                "input_tables": [],
                "user_question": "question",
                "workspace_id": "workspace-attacker",
                "identity_id": "identity-attacker",
            },
        )

    assert response.status_code == 200
    assert json.loads(response.data.decode("utf-8").strip())["type"] == "completion"
    constructor_kwargs = analyst_agent.call_args.kwargs
    assert constructor_kwargs["identity_id"] == "user:42"
    assert constructor_kwargs["workspace_id"] == "workspace-authorized"

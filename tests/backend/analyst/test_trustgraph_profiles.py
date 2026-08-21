from __future__ import annotations

import json

import pytest

from data_formulator.analyst.business_context import trustgraph_profiles


pytestmark = [pytest.mark.backend]


def _allow_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", "https://trustgraph.example/*")


def test_workspace_profile_round_trips_without_a_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _allow_target(monkeypatch)
    monkeypatch.setattr(trustgraph_profiles, "get_user_home", lambda _: tmp_path)

    saved = trustgraph_profiles.save_workspace_profile(
        "user:one",
        "workspace-one",
        api_base="https://trustgraph.example/",
        trustgraph_workspace="manufacturing",
        flow_id="analysis",
        tool_group="ontology-readonly",
    )
    loaded = trustgraph_profiles.load_workspace_profile("user:one", "workspace-one")

    assert loaded == saved
    assert loaded is not None
    assert loaded.credential_ref.startswith("trustgraph:workspace:")
    persisted = (tmp_path / "trustgraph_profiles.json").read_text(encoding="utf-8")
    assert "bearer_token" not in persisted
    assert "reader-secret" not in persisted


def test_profile_is_scoped_by_identity_and_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _allow_target(monkeypatch)
    monkeypatch.setattr(
        trustgraph_profiles,
        "get_user_home",
        lambda identity: tmp_path / identity.replace(":", "-"),
    )
    trustgraph_profiles.save_workspace_profile(
        "user:one",
        "workspace-one",
        api_base="https://trustgraph.example",
        trustgraph_workspace="default",
    )

    assert trustgraph_profiles.load_workspace_profile("user:one", "workspace-two") is None
    assert trustgraph_profiles.load_workspace_profile("user:two", "workspace-one") is None


def test_invalid_persisted_profile_is_not_exposed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _allow_target(monkeypatch)
    monkeypatch.setattr(trustgraph_profiles, "get_user_home", lambda _: tmp_path)
    (tmp_path / "trustgraph_profiles.json").write_text(
        json.dumps({"workspace-one": {"api_base": "http://unsafe.example"}}),
        encoding="utf-8",
    )

    assert trustgraph_profiles.load_workspace_profile("user:one", "workspace-one") is None


def test_delete_removes_only_requested_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _allow_target(monkeypatch)
    monkeypatch.setattr(trustgraph_profiles, "get_user_home", lambda _: tmp_path)
    for workspace in ("one", "two"):
        trustgraph_profiles.save_workspace_profile(
            "user:one",
            workspace,
            api_base="https://trustgraph.example",
            trustgraph_workspace="default",
        )

    assert trustgraph_profiles.delete_workspace_profile("user:one", "one") is True
    assert trustgraph_profiles.load_workspace_profile("user:one", "one") is None
    assert trustgraph_profiles.load_workspace_profile("user:one", "two") is not None

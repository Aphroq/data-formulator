from __future__ import annotations

from unittest.mock import patch

import pyarrow as pa
import pytest
from cryptography.fernet import Fernet

from data_formulator.auth.vault.local_vault import LocalCredentialVault
from data_formulator.data_connector import (
    DATA_CONNECTORS,
    DataConnector,
    SourceSpec,
    _ADMIN_CONNECTOR_IDS,
    _LOADED_USER_IDENTITIES,
    _user_connector_key,
    initialize_data_connectors,
)
from data_formulator.data_loader.external_data_loader import ExternalDataLoader
from data_formulator.datalake.workspace import sanitize_identity_dirname
from data_formulator.datalake.workspace_manager import WorkspaceManager
from data_formulator.recipes.openers import (
    ConnectorOpenError,
    ExplicitConnectorOpener,
    LocalWorkspaceOpener,
    WorkspaceOpenError,
)


pytestmark = [pytest.mark.backend]


class _CredentialLoader(ExternalDataLoader):
    def __init__(self, params):
        self.params = params

    @staticmethod
    def list_params():
        return [{
            "name": "password",
            "type": "password",
            "tier": "auth",
            "required": True,
            "sensitive": True,
        }]

    def test_connection(self):
        return self.params.get("password") == "secret"

    def list_tables(self, table_filter=None):
        return []

    def fetch_data_as_arrow(self, source_table, import_options=None):
        return pa.table({"value": [1]})


@pytest.fixture(autouse=True)
def isolated_connector_registry():
    old_connectors = dict(DATA_CONNECTORS)
    old_admin = set(_ADMIN_CONNECTOR_IDS)
    old_loaded = set(_LOADED_USER_IDENTITIES)
    DATA_CONNECTORS.clear()
    _ADMIN_CONNECTOR_IDS.clear()
    _LOADED_USER_IDENTITIES.clear()
    yield
    DATA_CONNECTORS.clear()
    DATA_CONNECTORS.update(old_connectors)
    _ADMIN_CONNECTOR_IDS.clear()
    _ADMIN_CONNECTOR_IDS.update(old_admin)
    _LOADED_USER_IDENTITIES.clear()
    _LOADED_USER_IDENTITIES.update(old_loaded)


def test_local_workspace_opener_uses_explicit_scope_without_lazy_create(
    tmp_path,
) -> None:
    data_home = tmp_path / "home"
    identity_id = "user:alice"
    manager = WorkspaceManager(
        data_home
        / "users"
        / sanitize_identity_dirname(identity_id)
        / "workspaces"
    )
    manager.create_workspace("ws-1")
    opener = LocalWorkspaceOpener(data_home)

    workspace = opener.open(identity_id, "ws-1")

    assert workspace.identity_id == identity_id
    assert workspace.workspace_id == "ws-1"
    assert workspace.storage_capabilities.durable is True
    with pytest.raises(WorkspaceOpenError, match="does not exist"):
        opener.open(identity_id, "missing")
    assert manager.workspace_exists("missing") is False
    with pytest.raises(WorkspaceOpenError, match="workspace_id"):
        opener.open(identity_id, "../ws-1")
    with pytest.raises(WorkspaceOpenError, match="workspace_id"):
        opener.open(identity_id, "")
    with pytest.raises(WorkspaceOpenError, match="workspace_id"):
        opener.open(identity_id, str((tmp_path / "absolute").resolve()))


def test_local_workspace_opener_rejects_symlink_escape(tmp_path) -> None:
    data_home = tmp_path / "home"
    identity_id = "user:alice"
    workspaces_root = (
        data_home
        / "users"
        / sanitize_identity_dirname(identity_id)
        / "workspaces"
    )
    workspaces_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspaces_root / "ws-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(WorkspaceOpenError, match="does not exist"):
        LocalWorkspaceOpener(data_home).open(identity_id, "ws-link")


def test_workspace_opener_fails_closed_for_non_local_backend(tmp_path) -> None:
    with pytest.raises(WorkspaceOpenError, match="local"):
        LocalWorkspaceOpener(tmp_path, storage_backend="ephemeral")


def test_connector_registry_can_initialize_without_flask_context() -> None:
    spec = SourceSpec(
        source_id="warehouse",
        loader_type="credential_test",
        display_name="Warehouse",
        default_params={"password": "secret"},
    )

    with (
        patch(
            "data_formulator.data_connector._load_admin_specs",
            return_value=[spec],
        ),
        patch(
            "data_formulator.data_loader.DATA_LOADERS",
            {"credential_test": _CredentialLoader},
        ),
        patch("data_formulator.data_loader.DISABLED_LOADERS", {}),
    ):
        initialize_data_connectors()

    assert DATA_CONNECTORS["warehouse"]._source_id == "warehouse"
    assert "warehouse" in _ADMIN_CONNECTOR_IDS


def test_connector_opener_restores_vault_loader_without_request_identity(
    tmp_path,
) -> None:
    identity_id = "user:alice"
    source_id = "warehouse"
    connector = DataConnector.from_loader(_CredentialLoader, source_id)
    DATA_CONNECTORS[_user_connector_key(identity_id, source_id)] = connector
    _LOADED_USER_IDENTITIES.add(identity_id)
    vault = LocalCredentialVault(
        tmp_path / "credentials.db",
        Fernet.generate_key().decode(),
    )
    vault.store(identity_id, source_id, {
        "user_params": {"password": "secret"},
        "source_id": source_id,
    })
    opener = ExplicitConnectorOpener(initialize_registry=False)

    with (
        patch.object(DataConnector, "_get_vault", return_value=vault),
        patch.object(
            DataConnector,
            "_get_identity",
            side_effect=AssertionError("request identity must not be read"),
        ),
    ):
        loader = opener.open(identity_id, source_id)

    assert isinstance(loader, _CredentialLoader)
    assert loader.params["password"] == "secret"
    with pytest.raises(ConnectorOpenError, match="not available"):
        opener.open("user:bob", source_id)


def test_background_connector_probe_does_not_delete_stale_vault_credentials(
    tmp_path,
) -> None:
    identity_id = "user:alice"
    source_id = "warehouse"
    connector = DataConnector.from_loader(_CredentialLoader, source_id)
    DATA_CONNECTORS[_user_connector_key(identity_id, source_id)] = connector
    _LOADED_USER_IDENTITIES.add(identity_id)
    vault = LocalCredentialVault(
        tmp_path / "credentials.db",
        Fernet.generate_key().decode(),
    )
    vault.store(identity_id, source_id, {
        "user_params": {"password": "wrong"},
        "source_id": source_id,
    })
    opener = ExplicitConnectorOpener(initialize_registry=False)

    with patch.object(DataConnector, "_get_vault", return_value=vault):
        with pytest.raises(ConnectorOpenError, match="not connected"):
            opener.open(identity_id, source_id)

    assert vault.retrieve(identity_id, source_id) is not None


def test_connector_opener_rejects_session_only_in_memory_loader() -> None:
    identity_id = "user:alice"
    source_id = "warehouse"
    connector = DataConnector.from_loader(_CredentialLoader, source_id)
    connector._loaders[identity_id] = _CredentialLoader({"password": "secret"})
    DATA_CONNECTORS[_user_connector_key(identity_id, source_id)] = connector
    _LOADED_USER_IDENTITIES.add(identity_id)
    opener = ExplicitConnectorOpener(initialize_registry=False)

    with patch.object(DataConnector, "_get_vault", return_value=None):
        with pytest.raises(ConnectorOpenError, match="recoverable"):
            opener.open(identity_id, source_id)

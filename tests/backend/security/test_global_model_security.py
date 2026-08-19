"""Tests for global model security: credential resolution and error sanitization.

These verify two critical security properties:
1. get_client() resolves real credentials from the registry for global models.
2. test_model error messages never leak API keys for global models.
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from data_formulator.errors import AppError, ErrorCode
from data_formulator.model_registry import ModelRegistry

pytestmark = [pytest.mark.backend]


SAMPLE_ENV = {
    # Several tests intentionally clear the environment.  Keep route-module
    # imports independent of the host's USERPROFILE/HOME discovery.
    "DATA_FORMULATOR_HOME": os.path.join(
        os.environ.get("TEMP", os.getcwd()),
        "data-formulator-test",
    ),
    "OPENAI_ENABLED": "true",
    "OPENAI_API_KEY": "sk-secret-key-12345",
    "OPENAI_MODELS": "gpt-4o",
}


# ---------------------------------------------------------------------------
# get_client: global model credential resolution
# ---------------------------------------------------------------------------

class TestGetClientGlobalResolution:
    """get_client() must resolve real credentials from model_registry
    when the model config has is_global=True."""

    @patch.dict(os.environ, SAMPLE_ENV, clear=True)
    def test_global_model_gets_real_api_key(self):
        """A global model config (no api_key from frontend) should be
        resolved to the full config with the real api_key."""
        registry = ModelRegistry()

        with patch("data_formulator.routes.agents.model_registry", registry):
            from data_formulator.routes.agents import get_client

            client = get_client({
                "id": "global-openai-gpt-4o",
                "endpoint": "openai",
                "model": "gpt-4o",
                "is_global": True,
            })

            assert client.params.get("api_key") == "sk-secret-key-12345"

    @patch.dict(os.environ, SAMPLE_ENV, clear=True)
    def test_user_model_keeps_own_credentials(self):
        """A non-global (user-added) model should use its own api_key,
        not touch the registry."""
        registry = ModelRegistry()

        with patch("data_formulator.routes.agents.model_registry", registry):
            from data_formulator.routes.agents import get_client

            client = get_client({
                "id": "user-custom-model",
                "endpoint": "openai",
                "model": "gpt-4o",
                "api_key": "sk-user-own-key",
                "api_base": "",
                "api_version": "",
            })

            assert client.params.get("api_key") == "sk-user-own-key"

    @patch.dict(os.environ, SAMPLE_ENV, clear=True)
    def test_global_claim_for_unregistered_id_is_rejected(self):
        """An is_global claim naming an id the registry does not know must be
        rejected outright.

        Falling through to the caller's own config would grant it the trust it
        just failed to prove -- in particular the allowlist exemption below,
        which turned api_base into an SSRF sink that the server signs with its
        own credentials.
        """
        registry = ModelRegistry()

        with patch("data_formulator.routes.agents.model_registry", registry):
            from data_formulator.routes.agents import get_client

            with pytest.raises(AppError, match="Unknown global model") as exc:
                get_client({
                    "id": "global-nonexistent-model",
                    "endpoint": "openai",
                    "model": "nonexistent",
                    "api_key": "sk-fallback",
                    "api_base": "",
                    "api_version": "",
                    "is_global": True,
                })

            assert exc.value.code == ErrorCode.ACCESS_DENIED
            assert exc.value.get_http_status() == 403

    @patch.dict(
        os.environ,
        {**SAMPLE_ENV, "DF_ALLOWED_API_BASES": "https://api.openai.com/*"},
        clear=True,
    )
    def test_global_claim_cannot_bypass_the_api_base_allowlist(self):
        """The reported vulnerability: is_global + an unregistered id skipped
        validate_api_base entirely, so an attacker-controlled api_base was
        accepted even with the allowlist enforced."""
        registry = ModelRegistry()

        with patch("data_formulator.routes.agents.model_registry", registry):
            from data_formulator.routes.agents import get_client

            with pytest.raises(AppError) as exc:
                get_client({
                    "id": "nonexistent-xyz",
                    "endpoint": "azure",
                    "model": "gpt-4",
                    "api_key": "",
                    "api_base": "https://attacker-listener.example/",
                    "is_global": True,
                })

            assert exc.value.code == ErrorCode.ACCESS_DENIED

    @patch.dict(
        os.environ,
        {**SAMPLE_ENV, "DF_ALLOWED_API_BASES": "https://api.openai.com/*"},
        clear=True,
    )
    def test_user_model_api_base_is_still_validated(self):
        """Without the is_global claim the allowlist applies as before."""
        registry = ModelRegistry()

        with patch("data_formulator.routes.agents.model_registry", registry):
            from data_formulator.routes.agents import get_client

            with pytest.raises(AppError, match="allowlist") as exc:
                get_client({
                    "id": "user-custom-model",
                    "endpoint": "azure",
                    "model": "gpt-4",
                    "api_key": "",
                    "api_base": "https://attacker-listener.example/",
                })

            assert exc.value.get_http_status() == 403

    @patch.dict(os.environ, SAMPLE_ENV, clear=True)
    def test_resolving_a_global_model_does_not_mutate_the_registry(self):
        """get_client normalises strings in place; it must copy first so the
        process-wide registry config is not edited by a request."""
        registry = ModelRegistry()
        stored = registry.get_config("global-openai-gpt-4o")
        before = dict(stored)

        with patch("data_formulator.routes.agents.model_registry", registry):
            from data_formulator.routes.agents import get_client

            get_client({
                "id": "global-openai-gpt-4o",
                "endpoint": "openai",
                "model": "gpt-4o",
                "is_global": True,
            })

        assert registry.get_config("global-openai-gpt-4o") == before

    @patch.dict(os.environ, {
        "GITHUB_COPILOT_ENABLED": "true",
        "GITHUB_COPILOT_MODELS": "gpt-4.1",
    }, clear=True)
    def test_copilot_global_model_uses_identity_vault_token_only_after_probe(self):
        registry = ModelRegistry()
        service = MagicMock()
        service.retrieve_access_token.return_value = "identity-a-long-token"
        capability_store = MagicMock()
        capability_store.get_qualified.return_value = MagicMock(qualified=True)

        with (
            patch("data_formulator.routes.agents.model_registry", registry),
            patch(
                "data_formulator.routes.agents.get_copilot_device_flow_service",
                return_value=service,
                create=True,
            ),
            patch(
                "data_formulator.routes.agents.copilot_capability_store",
                capability_store,
                create=True,
            ),
        ):
            from data_formulator.routes.agents import get_client

            client = get_client(
                {
                    "id": "global-github_copilot-gpt-4.1",
                    "endpoint": "github_copilot",
                    "model": "gpt-4.1",
                    "is_global": True,
                },
                identity_id="browser:identity-a",
            )

        assert client.endpoint == "github_copilot"
        assert client.model == "github_copilot/gpt-4.1"
        assert "api_key" not in client.params
        assert client._copilot_token_manager.get_access_token() == "identity-a-long-token"
        capability_store.get_qualified.assert_called_once_with(
            "browser:identity-a",
            "global-github_copilot-gpt-4.1",
        )
        service.retrieve_access_token.assert_called_once_with("browser:identity-a")

    @patch.dict(os.environ, {
        "GITHUB_COPILOT_ENABLED": "true",
        "GITHUB_COPILOT_MODELS": "gpt-4.1",
    }, clear=True)
    def test_unqualified_copilot_model_fails_before_vault_access(self):
        registry = ModelRegistry()
        service = MagicMock()
        capability_store = MagicMock()
        capability_store.get_qualified.return_value = None

        with (
            patch("data_formulator.routes.agents.model_registry", registry),
            patch(
                "data_formulator.routes.agents.get_copilot_device_flow_service",
                return_value=service,
                create=True,
            ),
            patch(
                "data_formulator.routes.agents.copilot_capability_store",
                capability_store,
                create=True,
            ),
        ):
            from data_formulator.routes.agents import get_client

            with pytest.raises(AppError, match="capability checks") as exc:
                get_client(
                    {
                        "id": "global-github_copilot-gpt-4.1",
                        "endpoint": "github_copilot",
                        "model": "gpt-4.1",
                        "is_global": True,
                    },
                    identity_id="browser:identity-a",
                )

        assert exc.value.code == ErrorCode.SERVICE_UNAVAILABLE
        service.retrieve_access_token.assert_not_called()

    @patch.dict(os.environ, {"GITHUB_COPILOT_ENABLED": "true"}, clear=True)
    def test_caller_controlled_copilot_config_is_rejected(self):
        from data_formulator.routes.agents import get_client

        with pytest.raises(AppError) as exc:
            get_client({
                "id": "user-copilot",
                "endpoint": "github_copilot",
                "model": "gpt-4.1",
            })

        assert exc.value.code == ErrorCode.ACCESS_DENIED



# ---------------------------------------------------------------------------
# Error sanitization (shared sanitize module)
# ---------------------------------------------------------------------------

class TestSharedErrorSanitization:
    """The shared sanitize_error_message function must strip sensitive data."""

    def test_sanitize_redacts_api_key_patterns(self):
        from data_formulator.security.sanitize import sanitize_error_message

        raw = "Connection failed: api_key=sk-secret-key-12345 is invalid"
        sanitized = sanitize_error_message(raw)

        assert "sk-secret-key-12345" not in sanitized
        assert "<redacted>" in sanitized

    def test_sanitize_truncates_long_messages(self):
        from data_formulator.security.sanitize import sanitize_error_message

        raw = "x" * 1000
        sanitized = sanitize_error_message(raw)

        assert len(sanitized) <= 503  # 500 + "..."
        assert sanitized.endswith("...")

    def test_sanitize_escapes_html(self):
        from data_formulator.security.sanitize import sanitize_error_message

        raw = '<script>alert("xss")</script>'
        sanitized = sanitize_error_message(raw)

        assert "<script>" not in sanitized
        assert "&lt;script&gt;" in sanitized


# ---------------------------------------------------------------------------
# classify_llm_error: pattern-based safe message classification
# ---------------------------------------------------------------------------

class TestClassifyLlmError:
    """classify_llm_error returns pre-defined safe messages based on error patterns."""

    def test_auth_error_401(self):
        from data_formulator.security.sanitize import classify_llm_error

        msg = classify_llm_error(RuntimeError("Error code: 401 - Unauthorized"))
        assert "Authentication failed" in msg
        assert "401" not in msg

    def test_auth_error_invalid_key(self):
        from data_formulator.security.sanitize import classify_llm_error

        msg = classify_llm_error(RuntimeError("Invalid API key provided: sk-secret..."))
        assert "Authentication failed" in msg
        assert "sk-secret" not in msg

    def test_rate_limit_429(self):
        from data_formulator.security.sanitize import classify_llm_error

        msg = classify_llm_error(RuntimeError("Error code: 429 - Rate limit exceeded"))
        assert "Rate limit" in msg

    def test_context_length(self):
        from data_formulator.security.sanitize import classify_llm_error

        msg = classify_llm_error(RuntimeError("maximum context length is 8192 tokens"))
        assert "too long" in msg.lower() or "reduce" in msg.lower()

    def test_model_not_found(self):
        from data_formulator.security.sanitize import classify_llm_error

        msg = classify_llm_error(RuntimeError("The model 'gpt-5' does not exist"))
        assert "Model not found" in msg

    def test_timeout(self):
        from data_formulator.security.sanitize import classify_llm_error

        msg = classify_llm_error(RuntimeError("Connection timed out"))
        assert "timed out" in msg.lower() or "timeout" in msg.lower()

    def test_unknown_error_generic_fallback(self):
        from data_formulator.security.sanitize import classify_llm_error

        msg = classify_llm_error(RuntimeError("some completely unknown error xyz"))
        assert msg == "Model request failed"
        assert "unknown error xyz" not in msg

    def test_never_includes_raw_exception_text(self):
        from data_formulator.security.sanitize import classify_llm_error

        secret = "my-super-secret-api-key-12345"
        msg = classify_llm_error(RuntimeError(f"Failed with api_key={secret}"))
        assert secret not in msg

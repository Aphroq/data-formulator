# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""HMAC-based code signing for transformation code.

When the agent generates Python transformation code and the server
executes it successfully, the server signs the code with a secret key.
The signature is returned to the frontend alongside the code.

When the frontend later sends the code back for re-execution (e.g.
during data refresh), the server verifies the signature before running
the code.  This prevents a tampered or injected script from being
executed by the sandbox.

Secret lifecycle
~~~~~~~~~~~~~~~~
- **Stable application key**: derives from ``FLASK_SECRET_KEY`` so Recipe
  lifecycle actions and request-independent workers resolve the same signing
  material.
- **Dev mode** (``--dev``): uses a fixed, deterministic key only while a
  Flask development app context is active.  This is not secure for production.
- **Interactive Web fallback**: when no stable key is configured, an active
  Flask app may use its current process-local ``app.secret_key``.  This keeps
  legacy interactive analysis working but is never accepted by Recipe or
  background execution boundaries.
- **Explicit override**: set ``DF_CODE_SIGNING_SECRET`` env-var — this
  takes priority over everything (useful for multi-instance deploys
  behind a load balancer).
"""

import hashlib
import hmac
import os

# ---------------------------------------------------------------------------
# Server-side secret
# ---------------------------------------------------------------------------

# Fixed key used in dev mode so reloader restarts don't invalidate
# existing signatures.  NOT suitable for production.
_DEV_SECRET = b"data-formulator-dev-signing-key"


class CodeSigningConfigurationError(RuntimeError):
    """No stable code-signing key is available outside explicit dev mode."""


def _derive_flask_secret(secret: object) -> bytes:
    """Derive a purpose-specific HMAC key from Flask's shared secret."""
    return hmac.new(
        b"df-code-signing",
        str(secret).encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _stable_configured_secret() -> bytes | None:
    """Resolve process-independent signing material from environment config."""
    explicit = os.environ.get("DF_CODE_SIGNING_SECRET")
    if explicit:
        return explicit.encode("utf-8")
    flask_secret = os.environ.get("FLASK_SECRET_KEY")
    if flask_secret:
        return _derive_flask_secret(flask_secret)
    return None


def _is_dev_mode() -> bool:
    """Return True if the server was started with ``--dev``."""
    try:
        from flask import current_app
        return current_app.config.get("CLI_ARGS", {}).get("dev", False)
    except (ImportError, RuntimeError):
        return False


def _active_flask_secret() -> bytes | None:
    """Resolve the current process-local Flask secret when an app is active."""
    try:
        from flask import current_app
        secret = current_app.secret_key
    except (ImportError, RuntimeError):
        return None
    if not secret:
        return None
    return _derive_flask_secret(secret)


def _configuration_error() -> CodeSigningConfigurationError:
    return CodeSigningConfigurationError(
        "A stable code-signing secret is required; set "
        "DF_CODE_SIGNING_SECRET or FLASK_SECRET_KEY."
    )


def _get_secret(*, require_stable: bool = False) -> bytes:
    """Return the signing secret.

    Priority:
    1. Stable env config (``DF_CODE_SIGNING_SECRET`` / ``FLASK_SECRET_KEY``)
    2. Explicit dev mode → fixed deterministic key (survives reloader restarts)
    3. Active Flask app → current process-local application secret
    4. Every other caller without stable config fails closed

    ``require_stable=True`` stops after step 1.  Recipe lifecycle actions and
    request-independent workers use that mode so process-local or development
    material can never make a persisted Recipe appear portable.
    """
    configured = _stable_configured_secret()
    if configured is not None:
        return configured

    if require_stable:
        raise _configuration_error()

    # In dev mode use a fixed key so the reloader doesn't break sigs.
    if _is_dev_mode():
        return _DEV_SECRET

    flask_secret = _active_flask_secret()
    if flask_secret is not None:
        return flask_secret

    raise _configuration_error()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Maximum code size we are willing to sign / verify (256 KB).
MAX_CODE_SIZE = 256 * 1024


def require_stable_code_signing() -> None:
    """Fail unless process-independent signing material is configured."""
    _get_secret(require_stable=True)


def sign_code(code: str, *, require_stable: bool = False) -> str:
    """Compute an HMAC-SHA256 signature over *code*.

    Returns the hex-encoded signature string.  The signature covers
    the raw UTF-8 bytes of *code* — whitespace and encoding matter.
    """
    if not code:
        return ""
    return hmac.new(
        _get_secret(require_stable=require_stable),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_code(
    code: str,
    signature: str,
    *,
    require_stable: bool = False,
) -> bool:
    """Return ``True`` if *signature* is a valid HMAC for *code*.

    Uses constant-time comparison to prevent timing attacks.
    """
    if not code or not signature:
        return False
    expected = sign_code(code, require_stable=require_stable)
    return hmac.compare_digest(expected, signature)


def sign_result(result: dict) -> dict:
    """Add ``code_signature`` to an agent result dict (in-place).

    If the result contains a non-empty ``code`` key, a signature is
    computed and stored under ``code_signature``.  The result dict is
    returned for convenience.
    """
    code = result.get("code", "")
    if code:
        result["code_signature"] = sign_code(code)
    return result

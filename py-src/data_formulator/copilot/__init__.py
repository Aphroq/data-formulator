"""Application-owned GitHub Copilot authentication support.

The interactive device flow lives here instead of LiteLLM's filesystem-based
``Authenticator`` so credentials remain scoped to the authenticated Data
Formulator identity.  Model-request adaptation is added separately in A5.
"""

from .device_flow import (
    COPILOT_CREDENTIAL_SOURCE,
    CopilotDeviceFlowService,
    is_github_copilot_enabled,
)

__all__ = [
    "COPILOT_CREDENTIAL_SOURCE",
    "CopilotDeviceFlowService",
    "is_github_copilot_enabled",
]

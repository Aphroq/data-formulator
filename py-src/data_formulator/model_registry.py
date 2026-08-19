# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import os
from typing import Optional, Dict, List

BUILTIN_PROVIDERS = {'openai', 'azure', 'anthropic', 'gemini', 'ollama'}
COPILOT_PROVIDER = "github_copilot"
_TRUE_VALUES = {"1", "true", "yes", "on"}


class ModelRegistry:
    """
    Load global model configurations from environment variables.

    Supports both built-in providers (openai / azure / anthropic / gemini /
    ollama) and arbitrary custom providers (e.g. DEEPSEEK, QWEN).

    For a custom provider, set:
        {PROVIDER}_ENABLED=true
        {PROVIDER}_ENDPOINT=openai        # actual call type; defaults to openai
        {PROVIDER}_API_KEY=<key>
        {PROVIDER}_API_BASE=<url>
        {PROVIDER}_API_VERSION=<ver>      # optional
        {PROVIDER}_MODELS=model-a,model-b

    API keys and credentials live server-side only; the public information
    returned to the frontend contains no sensitive fields.
    """

    def __init__(self) -> None:
        self._models: Dict[str, dict] = {}
        self._reload()

    @staticmethod
    def make_id(provider: str, model: str) -> str:
        return f"global-{provider}-{model}"

    def _discover_providers(self) -> List[str]:
        """
        Return the lowercase names of all enabled providers by scanning
        every environment variable that ends with _ENABLED=true.
        """
        providers: List[str] = []
        for key, val in os.environ.items():
            if key.upper().endswith("_ENABLED") and val.strip().lower() == "true":
                prefix = key[: -len("_ENABLED")].lower()
                providers.append(prefix)
        return providers

    def _reload(self) -> None:
        self._models = {}
        self._load_copilot_candidates()
        for provider in self._discover_providers():
            # GitHub Copilot is an application-owned OAuth provider.  It must
            # never fall through to the generic API-key/base configuration.
            if provider == COPILOT_PROVIDER:
                continue
            env = provider.upper()

            api_key = os.getenv(f"{env}_API_KEY", "").strip()
            api_base = os.getenv(f"{env}_API_BASE", "").strip()
            api_version = os.getenv(f"{env}_API_VERSION", "").strip()
            models_str = os.getenv(f"{env}_MODELS", "").strip()

            if not (api_key or api_base) or not models_str:
                continue

            if provider in BUILTIN_PROVIDERS:
                endpoint = provider
            else:
                endpoint = os.getenv(f"{env}_ENDPOINT", "openai").strip().lower()

            for model_name in models_str.split(","):
                model_name = model_name.strip()
                if not model_name:
                    continue

                model_id = self.make_id(provider, model_name)
                self._models[model_id] = {
                    "id": model_id,
                    "endpoint": endpoint,
                    "model": model_name,
                    "api_key": api_key,
                    "api_base": api_base,
                    "api_version": api_version,
                    "provider_display": provider,
                }

    def _load_copilot_candidates(self) -> None:
        """Load explicit Copilot candidates without treating OAuth as a key."""

        enabled = os.getenv("GITHUB_COPILOT_ENABLED", "").strip().lower()
        if enabled not in _TRUE_VALUES:
            return
        models_str = os.getenv("GITHUB_COPILOT_MODELS", "").strip()
        if not models_str:
            return

        seen: set[str] = set()
        for raw_name in models_str.split(","):
            model_name = raw_name.strip()
            if model_name.lower().startswith(f"{COPILOT_PROVIDER}/"):
                model_name = model_name[len(COPILOT_PROVIDER) + 1 :].strip()
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            model_id = self.make_id(COPILOT_PROVIDER, model_name)
            self._models[model_id] = {
                "id": model_id,
                "endpoint": COPILOT_PROVIDER,
                "model": model_name,
                "api_key": "",
                "api_base": "",
                "api_version": "",
                "provider_display": COPILOT_PROVIDER,
            }

    def get_config(self, model_id: str) -> Optional[dict]:
        """Return the full config (including credentials) for a global model."""
        return self._models.get(model_id)

    def list_public(self) -> list:
        """
        Return public info for all globally configured models.
        Sensitive fields (api_key) are intentionally excluded.
        """
        return [
            {
                "id": m["id"],
                "endpoint": m["endpoint"],
                "model": m["model"],
                "api_base": m["api_base"],
                "api_version": m["api_version"],
                "auth_mode": (
                    "oauth_device"
                    if m["endpoint"] == COPILOT_PROVIDER
                    else (
                        "azure_identity"
                        if m["endpoint"] == "azure" and not m["api_key"]
                        else "key"
                    )
                ),
                "is_global": True,
            }
            for m in self._models.values()
        ]

    def is_global(self, model_id: str) -> bool:
        return model_id in self._models


model_registry = ModelRegistry()

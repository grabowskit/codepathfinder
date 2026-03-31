"""
Parse librechat.yaml to build a shared model list for the embedded chat panel.

Models defined in librechat.yaml are available in both LibreChat and the side panel,
so LLM configuration only needs to happen in one place.
"""
import logging
import os
from functools import lru_cache
from typing import Any, Optional

import yaml
from django.conf import settings

logger = logging.getLogger(__name__)

# SDK provider identifiers
PROVIDER_ANTHROPIC = "anthropic"       # Direct Anthropic API
PROVIDER_BEDROCK = "bedrock"           # AWS Bedrock
PROVIDER_OPENAI = "openai"             # OpenAI


def _yaml_path() -> str:
    return getattr(settings, "LIBRECHAT_YAML_PATH", "/app/librechat.yaml")


@lru_cache(maxsize=1)
def load_models() -> list[dict[str, Any]]:
    """
    Load and parse librechat.yaml, returning a flat list of model configs.

    Each model dict has:
        id          — unique slug (matches librechat modelSpec name)
        label       — display name
        description — tooltip text
        provider    — PROVIDER_* constant
        model_id    — SDK-level model identifier
        context_k   — context window in thousands of tokens (int)
        is_default  — bool, first default=true in yaml
    """
    path = _yaml_path()
    if not os.path.exists(path):
        logger.warning("librechat.yaml not found at %s — no models available", path)
        return _fallback_models()

    try:
        with open(path) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error("Failed to parse librechat.yaml: %s", e)
        return _fallback_models()

    models = []
    specs = (config.get("modelSpecs") or {}).get("list") or []

    for spec in specs:
        preset = spec.get("preset") or {}
        endpoint = (preset.get("endpoint") or "").lower()
        model_id = preset.get("model") or ""

        provider = _endpoint_to_provider(endpoint)
        if not provider:
            logger.debug("Skipping model %s — unknown endpoint %s", spec.get("name"), endpoint)
            continue

        models.append({
            "id": spec.get("name") or model_id,
            "label": spec.get("label") or spec.get("name") or model_id,
            "description": spec.get("description") or "",
            "provider": provider,
            "model_id": model_id,
            "context_k": _context_for_model(model_id),
            "is_default": bool(spec.get("default")),
        })

    if not models:
        return _fallback_models()

    return models


def _endpoint_to_provider(endpoint: str) -> Optional[str]:
    if endpoint == "bedrock":
        return PROVIDER_BEDROCK
    if endpoint in ("openai", "openai (custom)"):
        return PROVIDER_OPENAI
    if endpoint == "anthropic":
        return PROVIDER_ANTHROPIC
    return None


def _context_for_model(model_id: str) -> int:
    """Return context window in K tokens based on model ID prefix."""
    m = model_id.lower()
    if "opus-4" in m or "sonnet-4" in m:
        return 200
    if "haiku-4" in m:
        return 200
    if "gpt-5" in m:
        return 128
    if "claude-3" in m:
        return 200
    return 128


def _fallback_models() -> list[dict[str, Any]]:
    """Minimal fallback if yaml is missing — just Claude Sonnet via direct API if key exists."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return []
    return [{
        "id": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6",
        "description": "Anthropic Claude Sonnet 4.6",
        "provider": PROVIDER_ANTHROPIC,
        "model_id": "claude-sonnet-4-6",
        "context_k": 200,
        "is_default": True,
    }]


def get_default_model() -> Optional[dict[str, Any]]:
    models = load_models()
    for m in models:
        if m["is_default"]:
            return m
    return models[0] if models else None


def get_model_by_id(model_id: str) -> Optional[dict[str, Any]]:
    for m in load_models():
        if m["id"] == model_id:
            return m
    return None


def models_for_api() -> list[dict[str, Any]]:
    """Return model list in the format the chat JS model selector expects."""
    result = []
    for m in load_models():
        result.append({
            "id": m["id"],
            "name": m["label"],
            "modelId": m["model_id"],
            "providerName": m["provider"].title(),
            "contextK": m["context_k"],
            "isDefault": m["is_default"],
        })
    return result

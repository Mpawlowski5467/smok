"""Streaming adapters. No terminal or UI dependencies belong here."""

from smok.models.anthropic import AnthropicAdapter
from smok.models.base import ModelAdapter
from smok.models.openai_compat import OpenAICompatibleAdapter
from smok.models.profiles import ModelConfig


def create_adapter(config: ModelConfig) -> ModelAdapter:
    if config.adapter == "anthropic":
        return AnthropicAdapter(config)
    return OpenAICompatibleAdapter(config)

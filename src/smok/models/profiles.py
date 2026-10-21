import math
import os
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

import yaml

from smok.tuning import EDIT_FORMATS, PROMPT_STYLES, TOOL_SETS

REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


@dataclass(frozen=True)
class ModelConfig:
    name: str
    model: str
    adapter: str
    base_url: str
    api_key_env: str
    key_required: bool = False
    token_parameter: str = "max_tokens"
    max_output_tokens: int = 4096
    timeout_seconds: float = 180.0
    context_window: int = 32768
    compact_at: float = 0.8
    keep_recent: int = 4
    chars_per_token: float = 3.0
    repo_map_tokens: int = 1500
    prompt_cache: bool = False
    count_tokens: bool = False
    local: bool = False
    vision: bool = False
    prompt_style: str = "full"
    tool_set: str = "full"
    edit_format: str = "both"
    reasoning_effort: str | None = None
    prices: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if self.reasoning_effort is not None and (
            not isinstance(self.reasoning_effort, str)
            or self.reasoning_effort not in REASONING_EFFORTS
            or self.adapter != "openai_compat"
        ):
            raise ValueError(
                "reasoning_effort requires an OpenAI-compatible adapter and a supported "
                "effort name, or null for the provider default. Model support varies."
            )
        for name, choices in (
            ("prompt_style", PROMPT_STYLES),
            ("tool_set", TOOL_SETS),
            ("edit_format", EDIT_FORMATS),
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or value not in choices:
                raise ValueError(f"{name} must be one of: {', '.join(choices)}.")
        for name in ("max_output_tokens", "context_window", "keep_recent", "repo_map_tokens"):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < (0 if name == "repo_map_tokens" else 1)
            ):
                raise ValueError(f"{name} must be a valid integer limit.")
        if self.context_window <= self.max_output_tokens + 512:
            raise ValueError("context_window must leave space beyond the output allowance.")
        for key in ("compact_at", "chars_per_token", "timeout_seconds"):
            value = getattr(self, key)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError(f"{key} must be a finite number.")
        if not 0.5 <= self.compact_at <= 0.95 or not 0.5 <= self.chars_per_token <= 8:
            raise ValueError("Invalid compaction threshold or token estimate ratio.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Invalid request timeout.")
        if any(
            not isinstance(getattr(self, key), bool)
            for key in ("prompt_cache", "count_tokens", "local", "vision")
        ):
            raise ValueError("prompt_cache, count_tokens, and local must be booleans.")
        if not isinstance(self.prices, dict) or set(self.prices) - {
            "input",
            "output",
            "cache_read",
            "cache_write",
        }:
            raise ValueError(
                "Prices use input, output, cache_read, and cache_write per million tokens."
            )
        for price in self.prices.values():
            if (
                not isinstance(price, (int, float))
                or isinstance(price, bool)
                or not math.isfinite(price)
                or price < 0
            ):
                raise ValueError("Prices must be finite nonnegative numbers.")

    def api_key(self) -> str | None:
        key = os.getenv(self.api_key_env)
        if self.key_required and not key:
            raise ValueError(f"Set {self.api_key_env} in your shell before using {self.name}.")
        return key


def resolve_model(
    selector: str | None = None,
    *,
    config_path: Path | None = None,
    base_url: str | None = None,
    overrides: dict | None = None,
) -> ModelConfig:
    data = yaml.safe_load(files("smok.models").joinpath("profiles.yaml").read_text())
    for custom in ([yaml.safe_load(config_path.read_text()) or {}] if config_path else []) + (
        [overrides] if overrides is not None else []
    ):
        if not isinstance(custom, dict):
            raise ValueError("Model configuration must be a YAML mapping.")
        for section in ("providers", "models"):
            overrides = custom.get(section, {})
            if not isinstance(overrides, dict):
                raise ValueError(f"{section} must be a YAML mapping.")
            for key, value in overrides.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    raise ValueError(f"Each {section} entry needs a string name and a mapping.")
                data[section][key] = {**data[section].get(key, {}), **value}
        if "default_model" in custom:
            data["default_model"] = custom["default_model"]
    name = selector or os.getenv("SMOK_MODEL") or data["default_model"]
    if not isinstance(name, str):
        raise ValueError("The model name must be a provider/model string.")
    provider, sep, model = name.partition("/")
    if not sep or not model or provider not in data["providers"]:
        raise ValueError(
            "Use provider/model, for example ollama/qwen3.6:27b. Providers: "
            + ", ".join(data["providers"])
        )
    profile = {**data["providers"][provider], **data["models"].get(name, {})}
    if not isinstance(profile.get("base_url", ""), str) or not profile.get("base_url"):
        raise ValueError("Each provider must define a base_url.")
    if not isinstance(profile.get("base_url_env", ""), str):
        raise ValueError("base_url_env must name an environment variable.")
    if not isinstance(profile.get("api_key_env", "SMOK_API_KEY"), str):
        raise ValueError("api_key_env must name an environment variable.")
    url = base_url or os.getenv(profile.get("base_url_env", "")) or profile["base_url"]
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("The base URL must be an HTTP(S) endpoint without embedded credentials.")
    adapter = profile.get("adapter")
    if adapter not in {"anthropic", "openai_compat"}:
        raise ValueError(f"Unknown adapter: {adapter}")
    tokens = profile.get("max_output_tokens", 4096)
    timeout = profile.get("timeout_seconds", 180)
    parameter = profile.get("token_parameter", "max_tokens")
    if not isinstance(parameter, str) or parameter not in {"max_tokens", "max_completion_tokens"}:
        raise ValueError("Invalid token parameter.")
    return ModelConfig(
        name=name,
        model=model,
        adapter=adapter,
        base_url=url.rstrip("/"),
        api_key_env=profile.get("api_key_env", "SMOK_API_KEY"),
        key_required=bool(profile.get("key_required", False)),
        token_parameter=parameter,
        max_output_tokens=tokens,
        timeout_seconds=timeout,
        **{
            key: profile[key]
            for key in (
                "context_window",
                "compact_at",
                "keep_recent",
                "chars_per_token",
                "repo_map_tokens",
                "prompt_cache",
                "count_tokens",
                "local",
                "vision",
                "prompt_style",
                "tool_set",
                "edit_format",
                "reasoning_effort",
                "prices",
            )
            if key in profile
        },
    )

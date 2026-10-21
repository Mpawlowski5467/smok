"""Form-backed configuration; secret values are never returned to the browser."""

import hashlib
import json
import os
import re
from dataclasses import asdict, fields
from importlib.resources import files

import yaml

from smok.extensions.mcp import configurations
from smok.models.profiles import ModelConfig, resolve_model
from smok.settings import ProjectSettings
from smok.state import state_path, write_json


class Configuration:
    def __init__(self, root, *, model=None, config_path=None, base_url=None, load_keys=True):
        self.root, self.initial_model = root, model
        self.config_path, self.base_url = config_path, base_url
        self.path = state_path(root, "gui.json")
        self.key_path = state_path(root, "gui-keys.json")
        self.data = self.read(self.path)
        self.original_keys = {}
        if load_keys:
            self.apply_keys(self.read(self.key_path))

    @staticmethod
    def read(path):
        if not path.exists():
            return {}
        if path.stat().st_size > 128_000:
            raise ValueError("GUI configuration exceeds 128 KB.")
        value = yaml.safe_load(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("GUI configuration must be an object.")
        return value

    def resolve(self, name=None, *, base_url=None):
        return resolve_model(
            name or self.initial_model or self.data.get("default_model"),
            config_path=self.config_path,
            base_url=base_url or self.base_url,
            overrides={"models": self.data.get("profiles", {})},
        )

    def profiles(self):
        base = yaml.safe_load(files("smok.models").joinpath("profiles.yaml").read_text())
        custom = self.read(self.config_path) if self.config_path else {}
        names = set(base.get("models", {})) | set(custom.get("models", {}))
        names |= set(self.data.get("profiles", {})) | {self.resolve().name}
        return [self.resolve(n) for n in sorted(names)]

    @staticmethod
    def validate_keys(keys):
        if len(keys) > 30 or not all(
            isinstance(k, str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]{1,70}_(KEY|TOKEN)", k)
            and isinstance(v, str)
            and 0 < len(v) <= 4096
            and "\0" not in v
            for k, v in keys.items()
        ):
            raise ValueError(
                "Secret names must end in _KEY or _TOKEN; values allow at most 4096 characters."
            )

    def apply_keys(self, keys):
        self.validate_keys(keys)
        for key in self.original_keys.keys() | keys.keys():
            if key not in self.original_keys:
                self.original_keys[key] = os.environ.get(key)
            value = keys.get(key, self.original_keys[key])
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def revision(self):
        values = [self.read(self.path), self.read(self.key_path), ProjectSettings(self.root).data]
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def view(self):
        self.data = self.read(self.path)
        settings = ProjectSettings(self.root)
        stored = self.read(self.key_path)
        self.apply_keys(stored)
        models = self.profiles()
        names = set(stored) | {m.api_key_env for m in models}
        names |= {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"}
        return {
            "revision": self.revision(),
            "permissions": settings.permission_mode,
            "allow_rules": settings.rules,
            "sandbox": asdict(settings.sandbox),
            "mcp_servers": configurations(settings.data),
            "models": [asdict(m) for m in models],
            "default_model": self.resolve().name,
            "secrets": [
                {"name": n, "configured": bool(os.getenv(n)), "saved": n in stored}
                for n in sorted(names)
            ],
        }

    def update(self, value):
        if value.get("revision") is not None and value["revision"] != self.revision():
            raise ValueError(
                "Settings changed in another client. Close and reopen Settings, then retry."
            )
        if set(value) - {
            "revision",
            "permissions",
            "allow_rules",
            "sandbox",
            "mcp_servers",
            "profiles",
            "default_model",
            "secrets",
        }:
            raise ValueError("Unknown settings field.")
        self.data = self.read(self.path)
        settings = ProjectSettings(self.root)
        candidate = {
            **settings.data,
            **{
                k: value[k]
                for k in ("permissions", "allow_rules", "sandbox", "mcp_servers")
                if k in value
            },
        }
        ProjectSettings(self.root, data=candidate)
        configurations(candidate)
        new = {**self.data, **{k: value[k] for k in ("profiles", "default_model") if k in value}}
        profiles = new.get("profiles", {})
        allowed = {f.name for f in fields(ModelConfig)} - {"name", "model"}
        if not isinstance(profiles, dict) or len(profiles) > 50:
            raise ValueError("Use at most 50 model profiles.")
        for name, profile in profiles.items():
            if not isinstance(profile, dict) or set(profile) - allowed:
                raise ValueError("Invalid model profile fields.")
            resolve_model(name, config_path=self.config_path, overrides={"models": profiles})
        resolve_model(
            new.get("default_model") or self.initial_model,
            config_path=self.config_path,
            overrides={"models": profiles},
        )
        keys = self.read(self.key_path)
        edits = value.get("secrets", {})
        if not isinstance(edits, dict):
            raise ValueError("Invalid secret changes.")
        for name, secret in edits.items():
            if secret is None:
                keys.pop(name, None)
            else:
                keys[name] = secret
        # Validate all sections before the first write or environment change.
        if len(str(new)) + len(str(candidate)) > 100_000:
            raise ValueError("Settings exceed 100 KB.")
        self.apply_keys(keys)
        write_json(self.key_path, keys)
        write_json(self.path, new)
        write_json(state_path(self.root, "settings.json"), candidate)
        self.data = new
        if "default_model" in value:
            self.initial_model = None
        return self.view()

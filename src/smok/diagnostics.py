"""Read-only setup checks. Model discovery is explicit and never generates tokens."""

import asyncio
import json
import os
import re
import shutil
import sys
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import yaml

from smok import __version__
from smok.gui.config import Configuration
from smok.settings import ProjectSettings
from smok.state import state_path

PROBE_SECONDS = 5
MAX_DISCOVERY_BYTES = 256_000


def item(identifier, label, status, detail, remedy=""):
    return dict(id=identifier, label=label, status=status, detail=detail, remedy=remedy)


def frontend_check():
    try:
        root = files("smok.gui").joinpath("static")
        html = root.joinpath("index.html").read_text()
        assets = re.findall(r'(?:src|href)="(/assets/[^"?#]+)"', html)
        if not any(path.endswith(".js") for path in assets) or any(
            ".." in Path(path).parts or not root.joinpath(path.lstrip("/")).is_file()
            for path in assets
        ):
            raise ValueError("Missing compiled assets")
        return item(
            "frontend", "Desktop and browser interface", "ok", "Compiled assets are present."
        )
    except (OSError, ValueError):
        return item(
            "frontend",
            "Desktop and browser interface",
            "warning",
            "Compiled assets are missing.",
            "Reinstall the wheel or run npm --prefix web run build from a source checkout. "
            "CLI use is unaffected.",
        )


def local_checks(root, *, model=None, config_path=None, base_url=None):
    """Return public checks plus private probe inputs; do not create metadata or load keys."""
    root = Path(root).resolve()
    checks = [
        item(
            "python",
            "Python runtime",
            "ok" if sys.version_info >= (3, 12) else "error",
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "Use Python 3.12 or later." if sys.version_info < (3, 12) else "",
        )
    ]
    for name, label in (("git", "Git"), ("rg", "Ripgrep")):
        present = bool(shutil.which(name))
        checks.append(
            item(
                name,
                label,
                "ok" if present else "error",
                "Executable is on PATH." if present else "Executable is missing from PATH.",
                "Install " + label + " and restart Smok." if not present else "",
            )
        )
    checks.append(frontend_check())
    config, key = None, None
    if not root.is_dir():
        checks.append(
            item(
                "workspace",
                "Workspace",
                "error",
                "The workspace is not a directory.",
                "Choose an existing project folder with -C or the native workspace picker.",
            )
        )
        return checks, config, key
    try:
        metadata = state_path(root)
        if metadata.exists() and not metadata.is_dir():
            raise ValueError("Metadata is not a directory")
        target = metadata if metadata.exists() else root
        writable = os.access(target, os.W_OK | os.X_OK)
        checks.append(
            item(
                "workspace",
                "Workspace",
                "ok" if writable else "error",
                "Permissions allow project metadata; no write was attempted."
                if writable
                else "Project metadata is not writable by this process.",
                "Choose a writable folder or correct its permissions." if not writable else "",
            )
        )
        # Bound settings reads before using the ordinary settings validator.
        settings_path = state_path(root, "settings.json")
        if settings_path.exists() and settings_path.stat().st_size > 128_000:
            raise ValueError("Settings exceed 128 KB")
        settings = ProjectSettings(root)
        checks.append(
            item(
                "settings",
                "Project settings",
                "ok",
                f"Permissions: {settings.permission_mode}. "
                f"Shell backend: {settings.sandbox.backend}.",
            )
        )
        if settings.sandbox.backend == "docker":
            checks.append(
                item(
                    "docker",
                    "Docker shell",
                    "warning" if shutil.which("docker") else "error",
                    "Daemon and image availability have not been checked.",
                    "Start Docker and ensure the configured image is installed before shell use.",
                )
            )
    except (OSError, ValueError):
        checks.append(
            item(
                "settings",
                "Project settings",
                "error",
                "Could not read safe, valid project settings.",
                "Check .smok/settings.json and ensure .smok and its files are not symlinks.",
            )
        )
        return checks, config, key
    try:
        configuration = Configuration(
            root, model=model, config_path=config_path, base_url=base_url, load_keys=False
        )
        config = configuration.resolve()
        keys = configuration.read(configuration.key_path)
        configuration.validate_keys(keys)
        key = keys.get(config.api_key_env, os.getenv(config.api_key_env))
        checks.append(item("model", "Model profile", "ok", config.name))
        missing = config.key_required and not key
        checks.append(
            item(
                "credentials",
                "API credentials",
                "error" if missing else "ok",
                "The selected profile requires a key that is not configured."
                if missing
                else "A key is configured."
                if key
                else "This profile does not require a key.",
                "Add the key in Settings → API keys or set the profile's key environment variable."
                if missing
                else "",
            )
        )
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        # Parser/HTTP exception text can include user secrets. Do not reflect it.
        config, key = None, None
        checks.append(
            item(
                "model",
                "Model profile",
                "error",
                "Could not read a valid model profile or key file.",
                "Check --model, --config, endpoint settings, and .smok/gui.json / gui-keys.json.",
            )
        )
    return checks, config, key


async def probe_model(config, key, *, transport=None):
    if config.adapter != "openai_compat":
        return item(
            "connection",
            "Model connection",
            "warning",
            "Model discovery is unavailable for this adapter; no request was sent.",
            "Use an explicit small task to verify this provider. Generation can incur API charges.",
        )
    if config.key_required and not key:
        return item(
            "connection",
            "Model connection",
            "skipped",
            "Configure the required key before checking the connection.",
        )
    parsed = urlsplit(config.base_url)
    endpoint = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/models", parsed.query, "")
    )
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with asyncio.timeout(PROBE_SECONDS):
            async with httpx.AsyncClient(
                timeout=PROBE_SECONDS, follow_redirects=False, trust_env=False, transport=transport
            ) as client:
                async with client.stream("GET", endpoint, headers=headers) as response:
                    if response.status_code in {404, 405, 501}:
                        return item(
                            "connection",
                            "Model connection",
                            "warning",
                            "This endpoint does not offer model discovery; "
                            "generation remains unverified.",
                            "Check the endpoint URL in Settings and verify it with a task.",
                        )
                    if response.status_code != 200:
                        return item(
                            "connection",
                            "Model connection",
                            "error",
                            f"Model discovery returned HTTP {response.status_code}; "
                            "redirects are not followed.",
                            "Check the endpoint and API credentials in Settings.",
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_DISCOVERY_BYTES:
                            raise ValueError("Discovery response too large")
                    data = json.loads(raw)
        models = data.get("data") if isinstance(data, dict) else None
        if not isinstance(models, list) or not all(
            isinstance(m, dict) and isinstance(m.get("id"), str) for m in models
        ):
            raise ValueError("Invalid discovery response")
        if config.model not in {m["id"] for m in models}:
            return item(
                "connection",
                "Model connection",
                "error" if config.local else "warning",
                "The endpoint responded, but the selected model was not listed.",
                "Choose an available model in Settings. Hosted catalogs may be incomplete.",
            )
        return item(
            "connection",
            "Model connection",
            "ok",
            "The endpoint lists the selected model. "
            "Generation and tool support have not been tested.",
        )
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError):
        return item(
            "connection",
            "Model connection",
            "error",
            "Could not obtain a valid model list within the bounded connection check.",
            "Start the model server and check its endpoint. No model was downloaded or prompted.",
        )


async def diagnose(
    root, *, model=None, config_path=None, base_url=None, probe=False, transport=None
):
    root = await asyncio.to_thread(Path(root).resolve)
    checks, config, key = await asyncio.to_thread(
        local_checks,
        root,
        model=model,
        config_path=config_path,
        base_url=base_url,
    )
    connection = (
        (await probe_model(config, key, transport=transport))
        if probe and config
        else item(
            "connection",
            "Model connection",
            "skipped",
            "Connection was not checked. No network request was sent.",
            "Use Check model connection or --doctor --probe-model to request a model list.",
        )
    )
    checks.append(connection)
    return {
        "schema_version": 1,
        "smok_version": __version__,
        "workspace": str(root),
        "model": config.name if config else None,
        "ok": not any(c["status"] == "error" for c in checks),
        "probe_requested": probe,
        "generation_requests": 0,
        "checks": checks,
    }

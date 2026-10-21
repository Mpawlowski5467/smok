"""Deterministic, disposable server for browser integration tests. Never uses a provider."""

import tempfile
from pathlib import Path

import uvicorn
from test_gui import Model

from smok.gui.server import create_app
from smok.gui.service import Service

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="smok-browser-") as directory:
        root = Path(directory).resolve()
        (root / "hello.py").write_text("before\n")
        service = Service(root, factory=Model, model="local/gui-test")
        app = create_app(
            root, service=service, token="browser-test", origin="http://127.0.0.1:38765"
        )
        uvicorn.run(app, host="127.0.0.1", port=38765, log_level="warning", access_log=False)

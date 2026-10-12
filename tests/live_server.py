"""A running server for integration and browser tests.

If BASE_URL is set (CI sets it to `pywrangler dev`), tests use that. Otherwise a dev
server (devserver/server.py) is started on a free port for the test session.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_healthy(url: str, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError(f"server at {url} did not become healthy")
        time.sleep(0.2)


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    configured = os.environ.get("BASE_URL")
    if configured:
        url = configured.rstrip("/")
        _wait_healthy(url, timeout_s=120)
        yield url
        return
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}",
        "APP_ENV": "development",
        "PUBLIC_URL": f"http://localhost:{port}",
    }
    log_path = Path(tempfile.gettempdir()) / f"labscloud-devserver-{port}.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "devserver.server", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        url = f"http://localhost:{port}"
        try:
            _wait_healthy(url)
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

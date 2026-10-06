"""Test-wide guards: the suite must run offline (NFR-006) and never use a real API key.

Any real socket connection fails the test. A developer's `.env` (with a real GEMINI_API_KEY / ANTHROPIC_API_KEY) is
ignored via PROFILER_NO_DOTENV, which subprocesses spawned by tests inherit (BUG-002)."""

import socket

import pytest


class NetworkAccessError(RuntimeError):
    pass


LLM_ENV_VARS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GEMINI_MODEL", "GEMINI_FALLBACK_MODELS")


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch):
    monkeypatch.setenv("PROFILER_NO_DOTENV", "1")
    for name in LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def guard(*args, **kwargs):
        raise NetworkAccessError("tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)

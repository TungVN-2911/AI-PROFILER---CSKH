"""Test-wide guard: the suite must run offline (NFR-006). Any real socket connection fails the test."""

import socket

import pytest


class NetworkAccessError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def guard(*args, **kwargs):
        raise NetworkAccessError("tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)

"""Shared pytest fixtures for all tests."""

import pytest

from hopper import config


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Isolate all tests from the real config directory.

    Redirects hopper_dir() to a temporary directory so all file paths
    (sessions, backlog, config, socket) resolve there automatically.
    """
    monkeypatch.setattr(config, "hopper_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def temp_config(isolate_config):
    """Alias for isolate_config for tests that need the path.

    Tests can request this fixture to get the temporary config directory path.
    The isolation is already applied by the autouse isolate_config fixture.
    """
    return isolate_config

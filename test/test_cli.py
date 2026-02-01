"""Tests for the hopper CLI."""

import sys
from unittest.mock import patch

from hopper.cli import main


def test_main_is_callable():
    assert callable(main)


def test_unknown_command():
    """Unknown command returns 1."""
    with patch.object(sys, "argv", ["hopper", "unknown"]):
        result = main()
    assert result == 1


def test_ping_command_no_server():
    """Ping command returns 1 when server not running."""
    with patch.object(sys, "argv", ["hopper", "ping"]):
        with patch("hopper.cli.SOCKET_PATH", "/tmp/nonexistent.sock"):
            result = main()
    assert result == 1

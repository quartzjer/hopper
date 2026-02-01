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


def test_up_command_requires_tmux(capsys):
    """Up command returns 1 when not inside tmux."""
    with patch.object(sys, "argv", ["hopper", "up"]):
        with patch("hopper.tmux.is_inside_tmux", return_value=False):
            with patch("hopper.tmux.get_tmux_sessions", return_value=[]):
                result = main()
    assert result == 1
    captured = capsys.readouterr()
    assert "hopper up must run inside tmux" in captured.out
    assert "tmux new 'hopper up'" in captured.out


def test_up_command_shows_existing_sessions(capsys):
    """Up command shows existing sessions when tmux is running."""
    with patch.object(sys, "argv", ["hopper", "up"]):
        with patch("hopper.tmux.is_inside_tmux", return_value=False):
            with patch("hopper.tmux.get_tmux_sessions", return_value=["main", "dev"]):
                result = main()
    assert result == 1
    captured = capsys.readouterr()
    assert "tmux attach -t main" in captured.out
    assert "tmux attach -t dev" in captured.out

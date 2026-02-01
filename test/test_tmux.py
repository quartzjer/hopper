"""Tests for tmux interaction utilities."""

from unittest.mock import patch

from hopper.tmux import get_tmux_sessions, is_inside_tmux, is_tmux_server_running


class TestIsInsideTmux:
    def test_returns_true_when_tmux_env_set(self):
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            assert is_inside_tmux() is True

    def test_returns_false_when_tmux_env_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            assert is_inside_tmux() is False


class TestIsTmuxServerRunning:
    def test_returns_true_when_sessions_exist(self):
        with patch("hopper.tmux.get_tmux_sessions", return_value=["main"]):
            assert is_tmux_server_running() is True

    def test_returns_false_when_no_sessions(self):
        with patch("hopper.tmux.get_tmux_sessions", return_value=[]):
            assert is_tmux_server_running() is False


class TestGetTmuxSessions:
    def test_returns_session_names(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "main\ndev\nhopper\n"
            sessions = get_tmux_sessions()
            assert sessions == ["main", "dev", "hopper"]
            mock_run.assert_called_once_with(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
            )

    def test_returns_empty_list_when_no_sessions(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            assert get_tmux_sessions() == []

    def test_returns_empty_list_when_tmux_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert get_tmux_sessions() == []

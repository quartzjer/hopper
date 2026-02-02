"""Tests for the ore runner module."""

from pathlib import Path
from unittest.mock import patch

from hopper.ore import OreRunner, run_ore


class TestOreRunner:
    def test_run_notifies_active_then_inactive(self):
        """Runner notifies server of state changes."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        notifications = []

        def mock_set_state(socket_path, session_id, state, timeout=2.0):
            notifications.append((session_id, state))
            return True

        with (
            patch("hopper.ore.set_session_state", side_effect=mock_set_state),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            exit_code = runner.run()

        assert exit_code == 0
        # Should notify running, then idle (exit code 0)
        assert ("test-session", "running") in notifications
        assert ("test-session", "idle") in notifications

    def test_run_sets_error_state_on_nonzero_exit(self):
        """Runner sets error state when Claude exits with non-zero."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        notifications = []

        def mock_set_state(socket_path, session_id, state, timeout=2.0):
            notifications.append((session_id, state))
            return True

        with (
            patch("hopper.ore.set_session_state", side_effect=mock_set_state),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            exit_code = runner.run()

        assert exit_code == 1
        assert ("test-session", "running") in notifications
        assert ("test-session", "error") in notifications

    def test_run_claude_command(self):
        """Runner invokes claude with correct arguments."""
        runner = OreRunner("my-session-id", Path("/tmp/test.sock"))

        with (
            patch("hopper.ore.set_session_state", return_value=True),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            runner.run()

        # Check the command
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["claude", "--resume", "my-session-id"]

        # Check environment includes HOPPER_SID
        env = call_args[1]["env"]
        assert env["HOPPER_SID"] == "my-session-id"

    def test_run_handles_missing_claude(self):
        """Runner returns 127 if claude command not found."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        with (
            patch("hopper.ore.set_session_state", return_value=True),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            exit_code = runner.run()

        assert exit_code == 127

    def test_server_disconnect_tracked(self):
        """Runner tracks server connection state."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        with (
            patch("hopper.ore.set_session_state", return_value=False),
            patch("hopper.ore.ping", return_value=False),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            runner.run()

        # Should have marked as disconnected
        assert runner.server_connected is False


class TestRunOre:
    def test_run_ore_creates_runner(self):
        """run_ore entry point creates and runs OreRunner."""
        with (
            patch("hopper.ore.set_session_state", return_value=True),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            exit_code = run_ore("test-id", Path("/tmp/test.sock"))

        assert exit_code == 0
        mock_run.assert_called_once()

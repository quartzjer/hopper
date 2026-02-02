"""Tests for the ore runner module."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from hopper.ore import OreRunner, _extract_error_message, run_ore


class TestExtractErrorMessage:
    def test_empty_bytes_returns_none(self):
        """Empty stderr returns None."""
        assert _extract_error_message(b"") is None

    def test_single_line(self):
        """Single line is returned as-is."""
        assert _extract_error_message(b"Error: something broke\n") == "Error: something broke"

    def test_multiple_lines_under_limit(self):
        """Lines under the limit are all returned."""
        stderr = b"line1\nline2\nline3\n"
        result = _extract_error_message(stderr)
        assert result == "line1\nline2\nline3"

    def test_multiple_lines_over_limit(self):
        """Only last 5 lines are returned when over limit."""
        stderr = b"line1\nline2\nline3\nline4\nline5\nline6\nline7\n"
        result = _extract_error_message(stderr)
        assert result == "line3\nline4\nline5\nline6\nline7"

    def test_preserves_newlines(self):
        """Newlines are preserved in output."""
        stderr = b"error on\nmultiple lines\n"
        result = _extract_error_message(stderr)
        assert "\n" in result

    def test_handles_unicode(self):
        """Unicode characters are handled correctly."""
        stderr = "Error: café ☕\n".encode("utf-8")
        result = _extract_error_message(stderr)
        assert result == "Error: café ☕"

    def test_handles_invalid_utf8(self):
        """Invalid UTF-8 is replaced rather than raising."""
        stderr = b"Error: \xff\xfe invalid\n"
        result = _extract_error_message(stderr)
        assert "Error:" in result
        assert "invalid" in result


class TestOreRunner:
    def test_run_notifies_active_then_inactive(self):
        """Runner notifies server of state changes with messages."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        notifications = []

        def mock_set_state(socket_path, session_id, state, message, timeout=2.0):
            notifications.append((session_id, state, message))
            return True

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.ore.get_session_state", return_value="idle"),
            patch("hopper.ore.set_session_state", side_effect=mock_set_state),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            exit_code = runner.run()

        assert exit_code == 0
        # Should notify running, then idle (exit code 0)
        assert ("test-session", "running", "Claude running") in notifications
        assert ("test-session", "idle", "Completed successfully") in notifications

    def test_run_sets_error_state_on_nonzero_exit(self):
        """Runner sets error state when Claude exits with non-zero, no stderr."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        notifications = []

        def mock_set_state(socket_path, session_id, state, message, timeout=2.0):
            notifications.append((session_id, state, message))
            return True

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = io.BytesIO(b"")  # Empty stderr

        with (
            patch("hopper.ore.get_session_state", return_value="idle"),
            patch("hopper.ore.set_session_state", side_effect=mock_set_state),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            exit_code = runner.run()

        assert exit_code == 1
        assert ("test-session", "running", "Claude running") in notifications
        assert ("test-session", "error", "Exited with code 1") in notifications

    def test_run_captures_stderr_on_error(self):
        """Runner captures stderr and uses last 5 lines as error message."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        notifications = []

        def mock_set_state(socket_path, session_id, state, message, timeout=2.0):
            notifications.append((session_id, state, message))
            return True

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = io.BytesIO(b"Error: something went wrong\nDetails here\n")

        with (
            patch("hopper.ore.get_session_state", return_value="idle"),
            patch("hopper.ore.set_session_state", side_effect=mock_set_state),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            exit_code = runner.run()

        assert exit_code == 1
        # Should use stderr content, not generic message
        error_notification = [n for n in notifications if n[1] == "error"][0]
        assert "something went wrong" in error_notification[2]
        assert "Details here" in error_notification[2]
        # Newlines preserved in stored message
        assert "\n" in error_notification[2]

    def test_run_claude_with_resume_for_existing_session(self):
        """Runner invokes claude with --resume for existing (non-new) sessions."""
        runner = OreRunner("my-session-id", Path("/tmp/test.sock"))

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.ore.get_session_state", return_value="idle"),
            patch("hopper.ore.set_session_state", return_value=True),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            runner.run()

        # Check the command uses --resume for existing session
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert call_args[0][0] == ["claude", "--resume", "my-session-id"]

        # Check environment includes HOPPER_SID
        env = call_args[1]["env"]
        assert env["HOPPER_SID"] == "my-session-id"

    def test_run_claude_with_prompt_for_new_session(self):
        """Runner invokes claude with --session-id and prompt for new sessions."""
        runner = OreRunner("my-session-id", Path("/tmp/test.sock"))

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.ore.get_session_state", return_value="new"),
            patch("hopper.ore.set_session_state", return_value=True),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            runner.run()

        # Check the command uses --session-id and prompt for new session
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "claude"
        assert cmd[1:3] == ["--session-id", "my-session-id"]
        assert "--resume" not in cmd
        assert len(cmd) == 4  # ["claude", "--session-id", "<id>", "<prompt>"]

    def test_run_fails_if_prompt_missing_for_new_session(self):
        """Runner raises FileNotFoundError if shovel prompt is missing for new session."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        with (
            patch("hopper.ore.get_session_state", return_value="new"),
            patch(
                "hopper.ore.prompt.load",
                side_effect=FileNotFoundError("Prompt not found: shovel.md"),
            ),
        ):
            import pytest

            with pytest.raises(FileNotFoundError, match="Prompt not found"):
                runner.run()

    def test_run_handles_missing_claude(self):
        """Runner returns 127 if claude command not found."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        notifications = []

        def mock_set_state(socket_path, session_id, state, message, timeout=2.0):
            notifications.append((session_id, state, message))
            return True

        with (
            patch("hopper.ore.get_session_state", return_value="idle"),
            patch("hopper.ore.set_session_state", side_effect=mock_set_state),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.Popen", side_effect=FileNotFoundError),
        ):
            exit_code = runner.run()

        assert exit_code == 127
        assert ("test-session", "error", "claude command not found") in notifications

    def test_server_disconnect_tracked(self):
        """Runner tracks server connection state."""
        runner = OreRunner("test-session", Path("/tmp/test.sock"))

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.ore.get_session_state", return_value=None),
            patch("hopper.ore.set_session_state", return_value=False),
            patch("hopper.ore.ping", return_value=False),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            runner.run()

        # Should have marked as disconnected
        assert runner.server_connected is False


class TestRunOre:
    def test_run_ore_creates_runner(self):
        """run_ore entry point creates and runs OreRunner."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.ore.get_session_state", return_value="idle"),
            patch("hopper.ore.set_session_state", return_value=True),
            patch("hopper.ore.ping", return_value=True),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            exit_code = run_ore("test-id", Path("/tmp/test.sock"))

        assert exit_code == 0
        mock_popen.assert_called_once()

"""Tests for the task runner module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from hopper.task import run_task


def _mock_response(stage="processing", project="my-project", scope="build widget"):
    return {
        "type": "connected",
        "tmux": None,
        "session": {"stage": stage, "project": project, "scope": scope},
        "session_found": True,
    }


class TestRunTask:
    def test_session_not_found(self, capsys):
        """Returns 1 when session doesn't exist."""
        with patch("hopper.task.connect", return_value={"session": None}):
            exit_code = run_task("sid", Path("/tmp/test.sock"), "audit")

        assert exit_code == 1
        assert "not found" in capsys.readouterr().out

    def test_not_processing_stage(self, capsys):
        """Returns 1 when session is not in processing stage."""
        with patch("hopper.task.connect", return_value=_mock_response(stage="ore")):
            exit_code = run_task("test-1234", Path("/tmp/test.sock"), "audit")

        assert exit_code == 1
        assert "not in processing stage" in capsys.readouterr().out

    def test_wrong_cwd(self, tmp_path, monkeypatch, capsys):
        """Returns 1 when cwd doesn't match worktree."""
        monkeypatch.chdir(tmp_path)

        session_dir = tmp_path / "sessions" / "test-sid"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)

        with (
            patch("hopper.task.connect", return_value=_mock_response()),
            patch("hopper.task.find_project", return_value=None),
            patch("hopper.task.get_session_dir", return_value=session_dir),
        ):
            exit_code = run_task("test-sid", Path("/tmp/test.sock"), "audit")

        assert exit_code == 1
        assert "worktree" in capsys.readouterr().out

    def test_prompt_not_found(self, tmp_path, monkeypatch, capsys):
        """Returns 1 when task prompt doesn't exist."""
        session_dir = tmp_path / "sessions" / "test-sid"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)
        monkeypatch.chdir(worktree)

        with (
            patch("hopper.task.connect", return_value=_mock_response()),
            patch("hopper.task.find_project", return_value=None),
            patch("hopper.task.get_session_dir", return_value=session_dir),
            patch("hopper.task.prompt.load", side_effect=FileNotFoundError("nope")),
        ):
            exit_code = run_task("test-sid", Path("/tmp/test.sock"), "nonexistent")

        assert exit_code == 1
        assert "not found" in capsys.readouterr().out

    def test_runs_codex_and_saves_output(self, tmp_path, monkeypatch, capsys):
        """Runs codex, saves output, prints it, and manages state."""
        session_dir = tmp_path / "sessions" / "test-sid"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)
        monkeypatch.chdir(worktree)

        state_calls = []

        def mock_set_state(sock, sid, state, status):
            state_calls.append((state, status))
            return True

        def mock_run_codex(prompt, cwd, output_file):
            Path(output_file).write_text("# Audit Result\nAll good.")
            return 0

        mock_project = MagicMock()
        mock_project.path = str(tmp_path / "project")

        with (
            patch("hopper.task.prompt.load", return_value="prompt text"),
            patch("hopper.task.connect", return_value=_mock_response()),
            patch("hopper.task.find_project", return_value=mock_project),
            patch("hopper.task.get_session_dir", return_value=session_dir),
            patch("hopper.task.set_session_state", side_effect=mock_set_state),
            patch("hopper.task.run_codex", side_effect=mock_run_codex),
        ):
            exit_code = run_task("test-sid", Path("/tmp/test.sock"), "audit")

        assert exit_code == 0
        assert state_calls[0] == ("audit", "Running audit")
        assert state_calls[1] == ("running", "Processing")

        output = capsys.readouterr().out
        assert "Audit Result" in output
        assert "All good" in output
        assert (session_dir / "audit.md").exists()

    def test_restores_state_on_failure(self, tmp_path, monkeypatch):
        """Restores state to running/Processing even when codex fails."""
        session_dir = tmp_path / "sessions" / "test-sid"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)
        monkeypatch.chdir(worktree)

        state_calls = []

        def mock_set_state(sock, sid, state, status):
            state_calls.append((state, status))
            return True

        with (
            patch("hopper.task.prompt.load", return_value="prompt text"),
            patch("hopper.task.connect", return_value=_mock_response()),
            patch("hopper.task.find_project", return_value=None),
            patch("hopper.task.get_session_dir", return_value=session_dir),
            patch("hopper.task.set_session_state", side_effect=mock_set_state),
            patch("hopper.task.run_codex", return_value=1),
        ):
            exit_code = run_task("test-sid", Path("/tmp/test.sock"), "audit")

        assert exit_code == 1
        assert state_calls[-1] == ("running", "Processing")

    def test_server_unreachable(self, capsys):
        """Returns 1 when server connection fails."""
        with patch("hopper.task.connect", return_value=None):
            exit_code = run_task("sid", Path("/tmp/test.sock"), "audit")

        assert exit_code == 1
        assert "Failed to connect" in capsys.readouterr().out

    def test_loads_prompt_with_context(self, tmp_path, monkeypatch):
        """Loads prompt with project context."""
        session_dir = tmp_path / "sessions" / "test-sid"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)
        monkeypatch.chdir(worktree)

        load_calls = []

        def mock_load(name, context=None):
            load_calls.append((name, context))
            return "prompt text"

        mock_project = MagicMock()
        mock_project.path = "/path/to/project"

        with (
            patch("hopper.task.prompt.load", side_effect=mock_load),
            patch("hopper.task.connect", return_value=_mock_response()),
            patch("hopper.task.find_project", return_value=mock_project),
            patch("hopper.task.get_session_dir", return_value=session_dir),
            patch("hopper.task.set_session_state", return_value=True),
            patch("hopper.task.run_codex", return_value=0),
        ):
            run_task("test-sid", Path("/tmp/test.sock"), "audit")

        # Single load with context
        assert len(load_calls) == 1
        assert load_calls[0][0] == "audit"
        assert load_calls[0][1]["project"] == "my-project"
        assert load_calls[0][1]["dir"] == "/path/to/project"
        assert load_calls[0][1]["scope"] == "build widget"

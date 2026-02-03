"""Tests for the refine runner module."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from hopper.refine import RefineRunner, run_refine


class TestRefineRunner:
    def _make_runner(self, session_id="test-session-id"):
        return RefineRunner(session_id, Path("/tmp/test.sock"))

    def _mock_response(self, state="ready", active=False, project="my-project"):
        return {
            "type": "connected",
            "tmux": None,
            "session": {"state": state, "active": active, "project": project},
            "session_found": True,
        }

    def _mock_conn(self, emitted=None):
        mock = MagicMock()
        if emitted is not None:
            mock.emit = lambda msg_type, **kw: emitted.append((msg_type, kw)) or True
        else:
            mock.emit = MagicMock(return_value=True)
        return mock

    def test_first_run_creates_worktree_and_uses_prompt(self, tmp_path):
        """First run (state=ready) creates worktree and passes refine prompt."""
        runner = self._make_runner()

        # Set up project dir
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        # Set up session dir with shovel.md
        session_dir = tmp_path / "sessions" / "test-session-id"
        session_dir.mkdir(parents=True)
        (session_dir / "shovel.md").write_text("Build the widget")

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.refine.connect", return_value=self._mock_response()),
            patch("hopper.refine.HopperConnection", return_value=self._mock_conn()),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("hopper.refine.create_worktree", return_value=True) as mock_wt,
            patch("hopper.refine.prompt.load", return_value="loaded prompt") as mock_load,
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("hopper.refine.get_current_window_id", return_value=None),
        ):
            exit_code = runner.run()

        assert exit_code == 0

        # Worktree created with correct branch name
        mock_wt.assert_called_once_with(
            str(project_dir),
            session_dir / "worktree",
            "hopper-test-ses",
        )

        # Prompt loaded with shovel content
        mock_load.assert_called_once()
        call_kwargs = mock_load.call_args
        assert call_kwargs[0][0] == "refine"
        assert call_kwargs[1]["context"]["shovel"] == "Build the widget"

        # Claude invoked with --session-id and prompt, cwd=worktree
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["claude", "--session-id", "test-session-id", "loaded prompt"]
        assert mock_popen.call_args[1]["cwd"] == str(session_dir / "worktree")

    def test_resume_uses_existing_worktree(self, tmp_path):
        """Resume (state!=ready) uses --resume and existing worktree."""
        runner = self._make_runner()

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-session-id"
        session_dir.mkdir(parents=True)
        worktree = session_dir / "worktree"
        worktree.mkdir()

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.refine.connect", return_value=self._mock_response(state="running")),
            patch("hopper.refine.HopperConnection", return_value=self._mock_conn()),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("hopper.refine.create_worktree") as mock_wt,
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("hopper.refine.get_current_window_id", return_value=None),
        ):
            exit_code = runner.run()

        assert exit_code == 0

        # Worktree NOT created (already exists)
        mock_wt.assert_not_called()

        # Claude invoked with --resume, cwd=worktree
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["claude", "--resume", "test-session-id"]
        assert mock_popen.call_args[1]["cwd"] == str(worktree)

    def test_bails_if_session_already_active(self):
        """Runner exits with code 1 if session is already active."""
        runner = self._make_runner()

        with patch("hopper.refine.connect", return_value=self._mock_response(active=True)):
            exit_code = runner.run()

        assert exit_code == 1

    def test_fails_if_no_project_dir(self):
        """Runner exits with code 1 if no project directory found."""
        runner = self._make_runner()

        response = self._mock_response(project="")
        with patch("hopper.refine.connect", return_value=response):
            exit_code = runner.run()

        assert exit_code == 1

    def test_fails_if_project_dir_missing(self, tmp_path):
        """Runner exits with code 1 if project directory doesn't exist."""
        runner = self._make_runner()

        mock_project = MagicMock()
        mock_project.path = str(tmp_path / "does-not-exist")

        with (
            patch("hopper.refine.connect", return_value=self._mock_response()),
            patch("hopper.refine.find_project", return_value=mock_project),
        ):
            exit_code = runner.run()

        assert exit_code == 1

    def test_fails_if_worktree_creation_fails(self, tmp_path):
        """Runner exits with code 1 if git worktree add fails."""
        runner = self._make_runner()

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-session-id"
        session_dir.mkdir(parents=True)

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        with (
            patch("hopper.refine.connect", return_value=self._mock_response()),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("hopper.refine.create_worktree", return_value=False),
        ):
            exit_code = runner.run()

        assert exit_code == 1

    def test_fails_if_shovel_missing_on_first_run(self, tmp_path):
        """Runner exits with code 1 if shovel.md missing on first run."""
        runner = self._make_runner()

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-session-id"
        session_dir.mkdir(parents=True)

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        with (
            patch("hopper.refine.connect", return_value=self._mock_response()),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("hopper.refine.create_worktree", return_value=True),
        ):
            exit_code = runner.run()

        assert exit_code == 1

    def test_emits_error_on_nonzero_exit(self, tmp_path):
        """Runner emits error state when Claude exits non-zero."""
        runner = self._make_runner()
        emitted = []

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-session-id"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = io.BytesIO(b"Something broke\n")

        with (
            patch("hopper.refine.connect", return_value=self._mock_response(state="running")),
            patch("hopper.refine.HopperConnection", return_value=self._mock_conn(emitted)),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("hopper.refine.get_current_window_id", return_value=None),
        ):
            exit_code = runner.run()

        assert exit_code == 1
        error_emissions = [
            e for e in emitted if e[0] == "session_set_state" and e[1]["state"] == "error"
        ]
        assert len(error_emissions) == 1
        assert "Something broke" in error_emissions[0][1]["status"]

    def test_emits_running_state(self, tmp_path):
        """Runner emits running state when Claude starts."""
        runner = self._make_runner()
        emitted = []

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-session-id"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.refine.connect", return_value=self._mock_response(state="running")),
            patch("hopper.refine.HopperConnection", return_value=self._mock_conn(emitted)),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("hopper.refine.get_current_window_id", return_value=None),
        ):
            exit_code = runner.run()

        assert exit_code == 0
        assert any(e[0] == "session_set_state" and e[1]["state"] == "running" for e in emitted)

    def test_handles_missing_claude(self, tmp_path):
        """Runner returns 127 if claude command not found."""
        runner = self._make_runner()
        emitted = []

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-session-id"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        with (
            patch("hopper.refine.connect", return_value=self._mock_response(state="running")),
            patch("hopper.refine.HopperConnection", return_value=self._mock_conn(emitted)),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("subprocess.Popen", side_effect=FileNotFoundError),
            patch("hopper.refine.get_current_window_id", return_value=None),
        ):
            exit_code = runner.run()

        assert exit_code == 127
        assert any(
            e[0] == "session_set_state" and e[1]["status"] == "claude command not found"
            for e in emitted
        )

    def test_connection_stopped_on_exit(self, tmp_path):
        """Runner stops HopperConnection on exit."""
        runner = self._make_runner()
        mock_conn = self._mock_conn()

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-session-id"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.refine.connect", return_value=self._mock_response(state="running")),
            patch("hopper.refine.HopperConnection", return_value=mock_conn),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("hopper.refine.get_current_window_id", return_value=None),
        ):
            runner.run()

        mock_conn.start.assert_called_once()
        mock_conn.stop.assert_called_once()

    def test_sets_hopper_sid_env(self, tmp_path):
        """Runner sets HOPPER_SID environment variable."""
        runner = self._make_runner()

        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-session-id"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        with (
            patch("hopper.refine.connect", return_value=self._mock_response(state="running")),
            patch("hopper.refine.HopperConnection", return_value=self._mock_conn()),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("hopper.refine.get_current_window_id", return_value=None),
        ):
            runner.run()

        env = mock_popen.call_args[1]["env"]
        assert env["HOPPER_SID"] == "test-session-id"


class TestRunRefine:
    def test_entry_point(self, tmp_path):
        """run_refine creates and runs RefineRunner."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_dir = tmp_path / "sessions" / "test-id"
        worktree = session_dir / "worktree"
        worktree.mkdir(parents=True)

        mock_project = MagicMock()
        mock_project.path = str(project_dir)

        mock_conn = MagicMock()
        mock_conn.emit = MagicMock(return_value=True)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = None

        mock_response = {
            "type": "connected",
            "tmux": None,
            "session": {"state": "running", "project": "my-project"},
            "session_found": True,
        }

        with (
            patch("hopper.refine.connect", return_value=mock_response),
            patch("hopper.refine.HopperConnection", return_value=mock_conn),
            patch("hopper.refine.find_project", return_value=mock_project),
            patch("hopper.refine.get_session_dir", return_value=session_dir),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("hopper.refine.get_current_window_id", return_value=None),
        ):
            exit_code = run_refine("test-id", Path("/tmp/test.sock"))

        assert exit_code == 0


class TestActivityMonitor:
    def test_check_activity_detects_stuck(self):
        """Monitor detects stuck state when pane content doesn't change."""
        runner = RefineRunner("test-session", Path("/tmp/test.sock"))
        runner._window_id = "@1"

        emitted = []
        mock_conn = MagicMock()
        mock_conn.emit = lambda msg_type, **kw: emitted.append((msg_type, kw)) or True
        runner.connection = mock_conn

        runner._last_snapshot = "Hello World"

        with patch("hopper.refine.capture_pane", return_value="Hello World"):
            runner._check_activity()

        assert runner._stuck_since is not None
        stuck_emissions = [
            e for e in emitted if e[0] == "session_set_state" and e[1]["state"] == "stuck"
        ]
        assert len(stuck_emissions) == 1

    def test_check_activity_recovers_from_stuck(self):
        """Monitor emits running when recovering from stuck state."""
        runner = RefineRunner("test-session", Path("/tmp/test.sock"))
        runner._window_id = "@1"

        emitted = []
        mock_conn = MagicMock()
        mock_conn.emit = lambda msg_type, **kw: emitted.append((msg_type, kw)) or True
        runner.connection = mock_conn

        runner._last_snapshot = "Hello World"
        runner._stuck_since = 1000

        with patch("hopper.refine.capture_pane", return_value="New content"):
            runner._check_activity()

        assert runner._stuck_since is None
        assert any(e[0] == "session_set_state" and e[1]["state"] == "running" for e in emitted)

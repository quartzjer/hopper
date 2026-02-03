"""Refine runner - wraps Claude execution for processing stage sessions."""

import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from hopper import prompt
from hopper.client import HopperConnection, connect
from hopper.git import create_worktree
from hopper.projects import find_project
from hopper.sessions import SHORT_ID_LEN, current_time_ms, get_session_dir
from hopper.tmux import capture_pane, get_current_window_id

logger = logging.getLogger(__name__)

ERROR_LINES = 5
MONITOR_INTERVAL = 5.0
MONITOR_INTERVAL_MS = int(MONITOR_INTERVAL * 1000)


def _extract_error_message(stderr_bytes: bytes) -> str | None:
    """Extract last N lines from stderr as error message."""
    if not stderr_bytes:
        return None
    text = stderr_bytes.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()
    if not lines:
        return None
    tail = lines[-ERROR_LINES:]
    return "\n".join(tail)


class RefineRunner:
    """Runs Claude for a processing-stage session with git worktree."""

    def __init__(self, session_id: str, socket_path: Path):
        self.session_id = session_id
        self.socket_path = socket_path
        self.connection: HopperConnection | None = None
        self.is_first_run = False
        self.project_name: str = ""
        self.project_dir: str = ""
        # Activity monitor state
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop = threading.Event()
        self._last_snapshot: str | None = None
        self._stuck_since: int | None = None
        self._window_id: str | None = None

    def run(self) -> int:
        """Run Claude for this session. Returns exit code."""
        original_sigint = signal.signal(signal.SIGINT, self._handle_signal)
        original_sigterm = signal.signal(signal.SIGTERM, self._handle_signal)

        try:
            # Query server for session state and project info
            response = connect(self.socket_path, session_id=self.session_id)
            if response:
                session_data = response.get("session")
                if session_data:
                    if session_data.get("active", False):
                        sid = self.session_id[:SHORT_ID_LEN]
                        logger.error(f"Session {sid} already has an active connection")
                        print(f"Session {sid} is already active")
                        return 1

                    state = session_data.get("state")
                    self.is_first_run = state == "ready"

                    project_name = session_data.get("project", "")
                    if project_name:
                        self.project_name = project_name
                        project = find_project(project_name)
                        if project:
                            self.project_dir = project.path

            # Validate project directory
            if not self.project_dir:
                print("No project directory found for session.")
                return 1
            if not Path(self.project_dir).is_dir():
                print(f"Project directory not found: {self.project_dir}")
                return 1

            # Ensure worktree exists
            worktree_path = get_session_dir(self.session_id) / "worktree"
            if not worktree_path.is_dir():
                branch_name = f"hopper-{self.session_id[:SHORT_ID_LEN]}"
                if not create_worktree(self.project_dir, worktree_path, branch_name):
                    print("Failed to create git worktree.")
                    return 1

            # Load shovel doc for first run
            shovel_content: str | None = None
            if self.is_first_run:
                shovel_path = get_session_dir(self.session_id) / "shovel.md"
                if not shovel_path.exists():
                    print(f"Shovel document not found: {shovel_path}")
                    return 1
                shovel_content = shovel_path.read_text()

            # Start persistent connection and register
            self.connection = HopperConnection(self.socket_path)
            self.connection.start()
            self.connection.emit("session_register", session_id=self.session_id)

            # Run Claude
            exit_code, error_msg = self._run_claude(worktree_path, shovel_content)

            if exit_code == 127:
                self._emit_state("error", error_msg or "Command not found")
            elif exit_code != 0 and exit_code != 130:
                msg = error_msg or f"Exited with code {exit_code}"
                self._emit_state("error", msg)

            return exit_code

        finally:
            self._stop_monitor()
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            if self.connection:
                self.connection.stop()

    def _handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        logger.debug(f"Received signal {signum}")
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        sys.exit(128 + signum)

    def _emit_state(self, state: str, status: str) -> None:
        """Emit state change to server."""
        if self.connection:
            self.connection.emit(
                "session_set_state",
                session_id=self.session_id,
                state=state,
                status=status,
            )
            logger.debug(f"Emitted state: {state}, status: {status}")

    def _run_claude(
        self, worktree_path: Path, shovel_content: str | None
    ) -> tuple[int, str | None]:
        """Run Claude with the session ID. Returns (exit_code, error_message)."""
        env = os.environ.copy()
        env["HOPPER_SID"] = self.session_id

        if self.is_first_run and shovel_content is not None:
            context: dict[str, str] = {"shovel": shovel_content}
            if self.project_name:
                context["project"] = self.project_name
            if self.project_dir:
                context["dir"] = self.project_dir
            initial_prompt = prompt.load("refine", context=context)
            cmd = ["claude", "--session-id", self.session_id, initial_prompt]
        else:
            cmd = ["claude", "--resume", self.session_id]

        logger.debug(f"Running: {' '.join(cmd[:3])}...")

        try:
            proc = subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE, cwd=str(worktree_path))

            self._emit_state("running", "Claude running")
            self._start_monitor()

            proc.wait()

            if proc.returncode != 0 and proc.stderr:
                stderr_bytes = proc.stderr.read()
                error_msg = _extract_error_message(stderr_bytes)
                return proc.returncode, error_msg

            return proc.returncode, None
        except FileNotFoundError:
            logger.error("claude command not found")
            return 127, "claude command not found"
        except KeyboardInterrupt:
            return 130, None

    def _start_monitor(self) -> None:
        """Start the activity monitor thread."""
        self._window_id = get_current_window_id()
        if not self._window_id:
            logger.debug("Not in tmux, skipping activity monitor")
            return

        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name="activity-monitor", daemon=True
        )
        self._monitor_thread.start()
        logger.debug(f"Started activity monitor for window {self._window_id}")

    def _stop_monitor(self) -> None:
        """Stop the activity monitor thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_stop.set()
            self._monitor_thread.join(timeout=1.0)
            logger.debug("Stopped activity monitor")

    def _monitor_loop(self) -> None:
        """Monitor loop that checks for activity."""
        while not self._monitor_stop.wait(MONITOR_INTERVAL):
            self._check_activity()

    def _check_activity(self) -> None:
        """Check tmux pane for activity and update state."""
        if not self._window_id:
            return

        snapshot = capture_pane(self._window_id)
        if snapshot is None:
            logger.debug("Failed to capture pane, stopping monitor")
            self._monitor_stop.set()
            return

        if snapshot == self._last_snapshot:
            now = current_time_ms()
            if self._stuck_since is None:
                self._stuck_since = now - MONITOR_INTERVAL_MS
            duration_sec = (now - self._stuck_since) // 1000
            self._emit_state("stuck", f"No output for {duration_sec}s")
        else:
            if self._stuck_since is not None:
                self._emit_state("running", "Claude running")
            self._stuck_since = None
            self._last_snapshot = snapshot


def run_refine(session_id: str, socket_path: Path) -> int:
    """Entry point for refine command."""
    runner = RefineRunner(session_id, socket_path)
    return runner.run()

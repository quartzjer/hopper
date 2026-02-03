"""Refine runner - wraps Claude execution for processing stage sessions."""

import logging
import os
import signal
import subprocess
import threading
from pathlib import Path

from hopper import prompt
from hopper.client import HopperConnection, connect
from hopper.git import create_worktree
from hopper.projects import find_project
from hopper.runner import BaseRunner, extract_error_message
from hopper.sessions import SHORT_ID_LEN, get_session_dir

logger = logging.getLogger(__name__)


class RefineRunner(BaseRunner):
    """Runs Claude for a processing-stage session with git worktree."""

    _done_label = "Refine done"

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
            self.connection.start(callback=self._on_server_message)
            self.connection.emit("session_register", session_id=self.session_id)

            # Run Claude
            exit_code, error_msg = self._run_claude(worktree_path, shovel_content)

            if exit_code == 127:
                self._emit_state("error", error_msg or "Command not found")
            elif exit_code != 0 and exit_code != 130:
                msg = error_msg or f"Exited with code {exit_code}"
                self._emit_state("error", msg)
            elif exit_code == 0 and self._done.is_set():
                self._emit_state("ready", "Refine complete")
                self._emit_stage("ship")

            return exit_code

        finally:
            self._stop_monitor()
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            if self.connection:
                self.connection.stop()

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
            proc = subprocess.Popen(
                cmd,
                env=env,
                stderr=subprocess.PIPE,
                cwd=str(worktree_path),
            )

            self._emit_state("running", "Claude running")
            self._start_monitor()

            # Start dismiss thread to auto-exit after refine completes
            if self._window_id:
                threading.Thread(
                    target=self._wait_and_dismiss_claude,
                    name="refine-dismiss",
                    daemon=True,
                ).start()

            proc.wait()

            if proc.returncode != 0 and proc.stderr:
                stderr_bytes = proc.stderr.read()
                error_msg = extract_error_message(stderr_bytes)
                return proc.returncode, error_msg

            return proc.returncode, None
        except FileNotFoundError:
            logger.error("claude command not found")
            return 127, "claude command not found"
        except KeyboardInterrupt:
            return 130, None


def run_refine(session_id: str, socket_path: Path) -> int:
    """Entry point for refine command."""
    runner = RefineRunner(session_id, socket_path)
    return runner.run()

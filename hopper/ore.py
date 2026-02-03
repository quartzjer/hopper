"""Ore runner - wraps Claude execution with session lifecycle management."""

import logging
import os
import signal
import subprocess
import threading
from pathlib import Path

from hopper import prompt
from hopper.client import HopperConnection, connect
from hopper.projects import find_project
from hopper.runner import BaseRunner, extract_error_message
from hopper.sessions import SHORT_ID_LEN

logger = logging.getLogger(__name__)


class OreRunner(BaseRunner):
    """Runs Claude for an ore-stage session, managing active/inactive state."""

    _done_label = "Shovel done"

    def __init__(self, session_id: str, socket_path: Path):
        super().__init__(session_id, socket_path)
        self.scope: str = ""

    def run(self) -> int:
        """Run Claude for this session. Returns exit code."""
        original_sigint = signal.signal(signal.SIGINT, self._handle_signal)
        original_sigterm = signal.signal(signal.SIGTERM, self._handle_signal)

        try:
            # Query server for session to get state and project info (one-shot)
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
                    self.is_first_run = state == "new"

                    project_name = session_data.get("project", "")
                    if project_name:
                        self.project_name = project_name
                        project = find_project(project_name)
                        if project:
                            self.project_dir = project.path

                    self.scope = session_data.get("scope", "")

            # Start persistent connection and register ownership (sets active=True)
            self.connection = HopperConnection(self.socket_path)
            self.connection.start(callback=self._on_server_message)
            self.connection.emit("session_register", session_id=self.session_id)

            # Run Claude (blocking)
            exit_code, error_msg = self._run_claude()

            if exit_code == 127:
                self._emit_state("error", error_msg or "Command not found")
            elif exit_code != 0 and exit_code != 130:
                msg = error_msg or f"Exited with code {exit_code}"
                self._emit_state("error", msg)
            elif exit_code == 0 and self._done.is_set():
                self._emit_state("ready", "Shovel-ready prompt saved")
                self._emit_stage("processing")

            return exit_code

        finally:
            self._stop_monitor()
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            if self.connection:
                self.connection.stop()

    def _run_claude(self) -> tuple[int, str | None]:
        """Run Claude with the session ID. Returns (exit_code, error_message)."""
        cwd: str | None = None
        if self.project_dir:
            if not Path(self.project_dir).is_dir():
                return 1, f"Project directory not found: {self.project_dir}"
            cwd = self.project_dir

        env = os.environ.copy()
        env["HOPPER_SID"] = self.session_id

        if self.is_first_run:
            context = {}
            if self.project_name:
                context["project"] = self.project_name
            if self.project_dir:
                context["dir"] = self.project_dir
            if self.scope:
                context["scope"] = self.scope
            initial_prompt = prompt.load("shovel", context=context if context else None)
            cmd = ["claude", "--session-id", self.session_id, initial_prompt]
        else:
            cmd = ["claude", "--resume", self.session_id]

        logger.debug(f"Running: {' '.join(cmd)}")

        try:
            proc = subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE, cwd=cwd)

            self._emit_state("running", "Claude running")
            self._start_monitor()

            # For new sessions, start dismiss thread to auto-exit after shovel
            if self.is_first_run and self._window_id:
                threading.Thread(
                    target=self._wait_and_dismiss_claude,
                    name="shovel-dismiss",
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


def run_ore(session_id: str, socket_path: Path) -> int:
    """Entry point for ore command."""
    runner = OreRunner(session_id, socket_path)
    return runner.run()

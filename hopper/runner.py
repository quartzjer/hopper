"""Base runner - shared logic for ore and refine runners."""

import logging
import signal
import sys
import threading
from pathlib import Path

from hopper.client import HopperConnection
from hopper.sessions import current_time_ms
from hopper.tmux import capture_pane, get_current_window_id, send_keys

logger = logging.getLogger(__name__)

ERROR_LINES = 5  # Number of stderr lines to capture on error
MONITOR_INTERVAL = 5.0  # Seconds between activity checks
MONITOR_INTERVAL_MS = int(MONITOR_INTERVAL * 1000)


def extract_error_message(stderr_bytes: bytes) -> str | None:
    """Extract last N lines from stderr as error message.

    Args:
        stderr_bytes: Raw stderr output from subprocess

    Returns:
        Last ERROR_LINES lines joined with newlines, or None if empty
    """
    if not stderr_bytes:
        return None

    text = stderr_bytes.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()
    if not lines:
        return None

    tail = lines[-ERROR_LINES:]
    return "\n".join(tail)


class BaseRunner:
    """Base class for session runners (ore, refine).

    Provides shared infrastructure: signal handling, server communication,
    activity monitoring, completion detection, and auto-dismiss.

    Subclasses must implement run() and _run_claude().
    """

    # Subclasses set these to customize completion behavior
    _done_label: str = "done"

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
        # Completion tracking
        self._done = threading.Event()

    def run(self) -> int:
        """Run Claude for this session. Returns exit code.

        Subclasses must implement this.
        """
        raise NotImplementedError

    def _handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        logger.debug(f"Received signal {signum}")
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        sys.exit(128 + signum)

    def _emit_state(self, state: str, status: str) -> None:
        """Emit state change to server via persistent connection."""
        if self.connection:
            self.connection.emit(
                "session_set_state",
                session_id=self.session_id,
                state=state,
                status=status,
            )
            logger.debug(f"Emitted state: {state}, status: {status}")

    def _emit_stage(self, stage: str) -> None:
        """Emit stage change to server via persistent connection."""
        if self.connection:
            self.connection.emit(
                "session_update",
                session_id=self.session_id,
                stage=stage,
            )
            logger.debug(f"Emitted stage: {stage}")

    def _on_server_message(self, message: dict) -> None:
        """Handle incoming server broadcast messages."""
        if message.get("type") != "session_state_changed":
            return
        session = message.get("session", {})
        if session.get("id") != self.session_id:
            return
        if session.get("state") == "completed":
            self._done.set()
            logger.debug(f"{self._done_label} signal received")

    def _wait_and_dismiss_claude(self) -> None:
        """Wait for completion, screen stability, then send Ctrl-D to exit Claude."""
        while not self._done.wait(timeout=1.0):
            if self._monitor_stop.is_set():
                return

        if not self._window_id:
            return

        logger.debug(f"{self._done_label}, waiting for screen to stabilize")

        last_snapshot = None
        while not self._monitor_stop.is_set():
            self._monitor_stop.wait(MONITOR_INTERVAL)
            snapshot = capture_pane(self._window_id)
            if snapshot is None:
                return
            if snapshot == last_snapshot:
                break
            last_snapshot = snapshot

        if self._monitor_stop.is_set():
            return

        logger.debug("Screen stable, sending Ctrl-D")
        send_keys(self._window_id, "C-d")
        send_keys(self._window_id, "C-d")

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
        """Monitor loop that checks for activity every MONITOR_INTERVAL seconds."""
        while not self._monitor_stop.wait(MONITOR_INTERVAL):
            self._check_activity()

    def _check_activity(self) -> None:
        """Check tmux pane for activity and update state accordingly."""
        if not self._window_id:
            return

        # Skip stuck detection once done — dismiss thread handles exit
        if self._done.is_set():
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

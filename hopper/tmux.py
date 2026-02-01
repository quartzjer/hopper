"""tmux interaction utilities."""

import os
import subprocess


def is_inside_tmux() -> bool:
    """Check if currently running inside a tmux session."""
    return "TMUX" in os.environ


def is_tmux_server_running() -> bool:
    """Check if a tmux server is running with active sessions."""
    return len(get_tmux_sessions()) > 0


def get_tmux_sessions() -> list[str]:
    """Get list of active tmux session names."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return [s.strip() for s in result.stdout.strip().split("\n") if s.strip()]
    except FileNotFoundError:
        return []

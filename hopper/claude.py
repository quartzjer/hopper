"""Claude Code wrapper for hopper."""

from hopper.tmux import new_window, select_window


def spawn_claude(session_id: str, resume: bool = False) -> str | None:
    """Spawn Claude Code in a new tmux window.

    Args:
        session_id: The hopper session ID.
        resume: If True, resume an existing Claude session instead of starting fresh.

    Returns:
        The tmux window ID on success, None on failure.
    """
    env = {"HOPPER_SID": session_id}

    if resume:
        command = f"claude --resume {session_id}"
    else:
        command = f"claude --session-id {session_id}"

    return new_window(command, env)


def switch_to_window(window_id: str) -> bool:
    """Switch to an existing tmux window.

    Args:
        window_id: The tmux window ID to switch to.

    Returns:
        True if successfully switched, False otherwise (window doesn't exist or other error).
    """
    return select_window(window_id)

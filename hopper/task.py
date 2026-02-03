"""Task runner - runs a prompt via Codex in one-shot mode."""

import logging
from pathlib import Path

from hopper import prompt
from hopper.client import connect, set_session_state
from hopper.codex import run_codex
from hopper.projects import find_project
from hopper.sessions import get_session_dir

logger = logging.getLogger(__name__)


def run_task(session_id: str, socket_path: Path, task_name: str) -> int:
    """Run a task prompt via Codex for a processing-stage session.

    Validates the prompt exists, session is in processing stage, and cwd
    matches the session worktree. Runs Codex one-shot, saves output to
    the session directory, and prints it to stdout.

    Args:
        session_id: The hopper session ID.
        socket_path: Path to the server Unix socket.
        task_name: Name of the prompt file (without .md extension).

    Returns:
        Exit code (0 on success).
    """
    # Query server for session data
    response = connect(socket_path, session_id=session_id)
    if not response:
        print("Failed to connect to server.")
        return 1

    session_data = response.get("session")
    if not session_data:
        print(f"Session {session_id} not found.")
        return 1

    # Validate session is in processing stage
    if session_data.get("stage") != "processing":
        print(f"Session {session_id[:8]} is not in processing stage.")
        return 1

    # Validate cwd is the session worktree
    worktree_path = get_session_dir(session_id) / "worktree"
    cwd = Path.cwd()
    try:
        if cwd.resolve() != worktree_path.resolve():
            print(f"Must run from session worktree: {worktree_path}")
            return 1
    except OSError:
        print(f"Must run from session worktree: {worktree_path}")
        return 1

    # Build context for prompt template
    context: dict[str, str] = {}
    project_name = session_data.get("project", "")
    if project_name:
        context["project"] = project_name
        project = find_project(project_name)
        if project:
            context["dir"] = project.path
    scope = session_data.get("scope", "")
    if scope:
        context["scope"] = scope

    # Load prompt with context
    try:
        prompt_text = prompt.load(task_name, context=context if context else None)
    except FileNotFoundError:
        print(f"Task prompt not found: prompts/{task_name}.md")
        return 1

    # Set state to task name while running
    set_session_state(socket_path, session_id, task_name, f"Running {task_name}")

    # Run codex
    output_path = get_session_dir(session_id) / f"{task_name}.md"
    exit_code = run_codex(prompt_text, str(cwd), str(output_path))

    # Restore state to running/processing regardless of outcome
    set_session_state(socket_path, session_id, "running", "Processing")

    # Print output if it was written
    if output_path.exists():
        content = output_path.read_text()
        if content:
            print(content)

    return exit_code

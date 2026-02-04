"""Code runner - runs a prompt via Codex, resuming the session's Codex thread."""

import json
import logging
import os
from pathlib import Path

from hopper import prompt
from hopper.client import connect, set_session_state
from hopper.codex import run_codex
from hopper.projects import find_project
from hopper.sessions import current_time_ms, format_duration_ms, get_session_dir

logger = logging.getLogger(__name__)


def run_code(session_id: str, socket_path: Path, stage_name: str, request: str) -> int:
    """Run a stage prompt via Codex for a processing-stage session.

    Resumes the session's Codex thread so that context accumulates across
    stages. Validates the prompt exists, session is in processing stage,
    cwd matches the session worktree, and a Codex thread ID is present.
    Saves artifacts (<stage>.in.md, <stage>.out.md, <stage>.json) to the
    session directory and prints the output to stdout.

    Args:
        session_id: The hopper session ID.
        socket_path: Path to the server Unix socket.
        stage_name: Name of the prompt file (without .md extension).
        request: The user's directions/request text from stdin.

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

    # Validate Codex thread ID exists
    codex_thread_id = session_data.get("codex_thread_id")
    if not codex_thread_id:
        print(f"Session {session_id[:8]} has no Codex thread ID.")
        print("The Codex session is bootstrapped during 'hop refine' first run.")
        print("Re-run 'hop refine' to bootstrap the Codex session.")
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
    context: dict[str, str] = {"request": request}
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
        prompt_text = prompt.load(stage_name, context=context if context else None)
    except FileNotFoundError:
        print(f"Prompt not found: prompts/{stage_name}.md")
        return 1

    # Save input prompt
    session_dir = get_session_dir(session_id)
    input_path = session_dir / f"{stage_name}.in.md"
    _atomic_write(input_path, prompt_text)

    # Set state to stage name while running
    set_session_state(socket_path, session_id, stage_name, f"Running {stage_name}")

    # Run codex (resume existing thread)
    output_path = session_dir / f"{stage_name}.out.md"
    started_at = current_time_ms()
    exit_code, cmd = run_codex(prompt_text, str(cwd), str(output_path), codex_thread_id)
    finished_at = current_time_ms()

    # Save run metadata
    metadata = {
        "stage": stage_name,
        "session_id": session_id,
        "codex_thread_id": codex_thread_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": finished_at - started_at,
        "exit_code": exit_code,
        "cmd": cmd,
    }
    meta_path = session_dir / f"{stage_name}.json"
    _atomic_write(meta_path, json.dumps(metadata, indent=2) + "\n")

    # Update status with stage result and duration
    duration = format_duration_ms(finished_at - started_at)
    if exit_code == 0:
        status = f"{stage_name} ran for {duration}"
    else:
        status = f"{stage_name} failed after {duration}"
    set_session_state(socket_path, session_id, "running", status)

    # Print output if it was written
    if output_path.exists():
        content = output_path.read_text()
        if content:
            print(content)

    return exit_code


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically via tmp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)

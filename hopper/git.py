"""Git utilities for hopper."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def create_worktree(repo_dir: str, worktree_path: Path, branch_name: str) -> bool:
    """Create a git worktree with a new branch.

    Args:
        repo_dir: Path to the main git repository.
        worktree_path: Where to place the worktree.
        branch_name: Name for the new branch.

    Returns:
        True on success, False on failure.
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"git worktree add failed: {result.stderr.strip()}")
            return False
        return True
    except FileNotFoundError:
        logger.error("git command not found")
        return False

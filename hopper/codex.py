"""Codex CLI wrapper for hopper."""

import logging
import subprocess

logger = logging.getLogger(__name__)


def run_codex(prompt: str, cwd: str, output_file: str) -> int:
    """Run Codex in one-shot mode with full permissions.

    Args:
        prompt: The prompt text to send to Codex.
        cwd: Working directory for Codex.
        output_file: Path to write the final agent message.

    Returns:
        Exit code from Codex (127 if codex not found).
    """
    cmd = [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-o",
        output_file,
        prompt,
    ]

    logger.debug(f"Running: codex exec in {cwd}")

    try:
        result = subprocess.run(cmd, cwd=cwd)
        return result.returncode
    except FileNotFoundError:
        logger.error("codex command not found")
        return 127
    except KeyboardInterrupt:
        return 130

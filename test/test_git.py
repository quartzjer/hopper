"""Tests for the git utilities module."""

from unittest.mock import MagicMock, patch

from hopper.git import create_worktree


class TestCreateWorktree:
    def test_success(self, tmp_path):
        """Creates worktree with correct git command."""
        worktree_path = tmp_path / "worktree"
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = create_worktree("/repo", worktree_path, "hopper-abc12345")

        assert result is True
        mock_run.assert_called_once_with(
            ["git", "worktree", "add", str(worktree_path), "-b", "hopper-abc12345"],
            cwd="/repo",
            capture_output=True,
            text=True,
        )

    def test_failure_returns_false(self, tmp_path):
        """Returns False when git command fails."""
        worktree_path = tmp_path / "worktree"
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "fatal: already exists"

        with patch("subprocess.run", return_value=mock_result):
            result = create_worktree("/repo", worktree_path, "hopper-abc12345")

        assert result is False

    def test_git_not_found(self, tmp_path):
        """Returns False when git is not installed."""
        worktree_path = tmp_path / "worktree"

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = create_worktree("/repo", worktree_path, "hopper-abc12345")

        assert result is False

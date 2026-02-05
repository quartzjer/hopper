.PHONY: install test ci clean

install:
	@if [ -z "$$VIRTUAL_ENV" ] && \
	   git rev-parse --is-inside-work-tree >/dev/null 2>&1 && \
	   [ "$$(git rev-parse --git-common-dir 2>/dev/null)" != "$$(git rev-parse --git-dir 2>/dev/null)" ]; then \
		echo "Error: Installing in a git worktree without an active venv."; \
		echo "This would overwrite the global 'hop' command."; \
		echo ""; \
		echo "Activate the worktree's venv first:"; \
		echo "  source .venv/bin/activate"; \
		exit 1; \
	fi
	pip install -e ".[dev]"

test:
	pytest

ci:
	ruff format .
	ruff check --fix .

clean:
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +

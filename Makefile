.PHONY: install test ci clean

install:
	pip install -e ".[dev]"

test:
	pytest

ci:
	ruff format .
	ruff check --fix .

clean:
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hopper is a TUI (text user interface) for managing coding agents, built with Python and the `blessed` library.

## Commands

```bash
make install    # Install package in editable mode with dev dependencies
make test       # Run all tests with pytest
make ci         # Auto-format and lint with ruff
pytest test/test_file.py::test_name  # Run a single test
```

## Architecture

- `hopper/cli.py` - Main entry point (`main()` function), uses blessed for terminal UI
- `hopper/__main__.py` - Enables `python -m hopper` execution
- `test/` - Test files, discovered by pytest

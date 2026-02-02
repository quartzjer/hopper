"""Shared configuration for hopper."""

from pathlib import Path

from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("hopper"))
SOCKET_PATH = DATA_DIR / "server.sock"
SESSIONS_FILE = DATA_DIR / "sessions.jsonl"
ARCHIVED_FILE = DATA_DIR / "archived.jsonl"
SESSIONS_DIR = DATA_DIR / "sessions"

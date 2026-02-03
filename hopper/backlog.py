"""Backlog management for hopper."""

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from hopper.config import BACKLOG_FILE
from hopper.sessions import SHORT_ID_LEN, current_time_ms


def _check_test_isolation() -> None:
    """Raise an error if running under pytest without path isolation."""
    if "pytest" not in sys.modules:
        return

    from platformdirs import user_data_dir

    real_data_dir = Path(user_data_dir("hopper"))
    if BACKLOG_FILE.is_relative_to(real_data_dir):
        raise RuntimeError(
            "Test isolation failure: backlog.py is trying to write to the real "
            f"config directory ({real_data_dir}). Ensure the isolate_config fixture "
            "from conftest.py is active."
        )


@dataclass
class BacklogItem:
    """A backlog item."""

    id: str
    project: str
    description: str
    created_at: int  # milliseconds since epoch
    session_id: str | None = None  # session that added it

    @property
    def short_id(self) -> str:
        """Return the 8-character short ID."""
        return self.id[:SHORT_ID_LEN]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "description": self.description,
            "created_at": self.created_at,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BacklogItem":
        return cls(
            id=data["id"],
            project=data["project"],
            description=data["description"],
            created_at=data["created_at"],
            session_id=data.get("session_id"),
        )


def load_backlog() -> list[BacklogItem]:
    """Load backlog items from JSONL file."""
    if not BACKLOG_FILE.exists():
        return []

    items = []
    with open(BACKLOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                items.append(BacklogItem.from_dict(data))
    return items


def save_backlog(items: list[BacklogItem]) -> None:
    """Atomically save backlog items to JSONL file."""
    _check_test_isolation()
    BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = BACKLOG_FILE.with_suffix(".jsonl.tmp")
    with open(tmp_path, "w") as f:
        for item in items:
            f.write(json.dumps(item.to_dict()) + "\n")

    os.replace(tmp_path, BACKLOG_FILE)


def add_backlog_item(
    items: list[BacklogItem],
    project: str,
    description: str,
    session_id: str | None = None,
) -> BacklogItem:
    """Create a new backlog item, add to list, and persist."""
    item = BacklogItem(
        id=str(uuid.uuid4()),
        project=project,
        description=description,
        created_at=current_time_ms(),
        session_id=session_id,
    )
    items.append(item)
    save_backlog(items)
    return item


def remove_backlog_item(items: list[BacklogItem], item_id: str) -> BacklogItem | None:
    """Remove a backlog item by ID. Returns the removed item or None."""
    for i, item in enumerate(items):
        if item.id == item_id:
            removed = items.pop(i)
            save_backlog(items)
            return removed
    return None


def find_by_short_id(items: list[BacklogItem], prefix: str) -> BacklogItem | None:
    """Find a backlog item by ID prefix. Returns None if not found or ambiguous."""
    matches = [item for item in items if item.id.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    return None

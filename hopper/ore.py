"""Ore runner - wraps Claude execution with lode lifecycle management."""

from pathlib import Path

from hopper import prompt
from hopper.runner import BaseRunner


class OreRunner(BaseRunner):
    """Runs Claude for an ore-stage lode, managing active/inactive state."""

    _done_label = "Shovel done"
    _first_run_state = "new"
    _done_status = "Shovel-ready prompt saved"
    _next_stage = "processing"

    def __init__(self, lode_id: str, socket_path: Path):
        super().__init__(lode_id, socket_path)
        self.scope: str = ""

    def _load_lode_data(self, lode_data: dict) -> None:
        self.scope = lode_data.get("scope", "")

    def _setup(self) -> int | None:
        # Validate project directory if set
        if self.project_dir and not Path(self.project_dir).is_dir():
            print(f"Project directory not found: {self.project_dir}")
            return 1
        return None

    def _build_command(self) -> tuple[list[str], str | None]:
        cwd = self.project_dir if self.project_dir else None

        skip = "--dangerously-skip-permissions"

        if self.is_first_run:
            context = {}
            if self.project_name:
                context["project"] = self.project_name
            if self.project_dir:
                context["dir"] = self.project_dir
            if self.scope:
                context["scope"] = self.scope
            initial_prompt = prompt.load("shovel", context=context if context else None)
            # Note: --session-id is Claude's flag, not ours
            cmd = ["claude", skip, "--session-id", self.lode_id, initial_prompt]
        else:
            # Note: --resume is Claude's flag, not ours
            cmd = ["claude", skip, "--resume", self.lode_id]

        return cmd, cwd


def run_ore(lode_id: str, socket_path: Path) -> int:
    """Entry point for ore command."""
    runner = OreRunner(lode_id, socket_path)
    return runner.run()
